"""
Agent 状态与持久化模块
参考 Agent Harness 设计（断点续跑 + 工具调用幂等）实现。

核心约束：
1. 结构化 State 是唯一可信源，文本日志不参与流程恢复
2. StateStore 为持久化介质抽象，可替换 Redis/Postgres
   - MemoryStateStore: 内存实现（测试用）
   - SQLiteStateStore: SQLite 实现（单机生产可用，替换文档中的内存方案）
"""

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentState:
    """结构化 Agent 状态（必须持久化），断点续跑的唯一可信源。

    属性说明：
    - task_id: 全局唯一任务ID，主键
    - status: running / completed / failed
    - iteration: 当前第几轮工具循环（护栏计数）
    - max_iteration: 最大允许循环次数（安全护栏，Harness 强制管控）
    - messages: 标准消息序列（System/User/Assistant/Tool）
    - tool_records: 所有已执行工具记录（幂等校验 + 审计依据）
    - biz_context: 业务自定义上下文（如自省建议）
    - pending_tool_call: 正在执行中的工具占位记录，解决「执行中崩溃」黑洞
    """

    task_id: str
    status: str  # running / completed / failed
    iteration: int = 0
    max_iteration: int = 10
    messages: List[Dict[str, Any]] = field(default_factory=list)
    tool_records: List[Dict[str, Any]] = field(default_factory=list)
    biz_context: Dict[str, Any] = field(default_factory=dict)
    pending_tool_call: Optional[Dict[str, Any]] = None
    # 记录当前正在执行哪个子任务id（规划驱动模式下的断点恢复定位用）
    current_subtask_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    final_result: Optional[str] = None

    # tool_records 单条样例：
    # {
    #     "call_id": "uuid-xxxx",        # 单次工具调用唯一ID（幂等标识）
    #     "tool_name": "kb_search",
    #     "args": {...},
    #     "result": "...",
    #     "success": True,
    #     "call_start_ts": 1752000000,
    #     "call_end_ts": 1752000010,
    # }

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, default=str)

    @staticmethod
    def from_json(raw: str) -> "AgentState":
        data = json.loads(raw)
        return AgentState(**data)


class StateStore:
    """持久化存储抽象层。

    生产环境可替换为 RedisStateStore / PostgresStateStore，
    接口保持不变（对应 LangGraph 的 Checkpointer 概念）。
    """

    def save(self, state: AgentState) -> None:
        """持久化完整状态"""
        raise NotImplementedError

    def load(self, task_id: str) -> Optional[AgentState]:
        """根据 task_id 加载状态，不存在返回 None"""
        raise NotImplementedError

    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出所有任务的概要信息"""
        raise NotImplementedError


class MemoryStateStore(StateStore):
    """内存实现（测试用，生产替换 SQLite/Redis）"""

    def __init__(self):
        self.cache: Dict[str, str] = {}

    def save(self, state: AgentState) -> None:
        state.updated_at = time.time()
        self.cache[state.task_id] = state.to_json()

    def load(self, task_id: str) -> Optional[AgentState]:
        raw = self.cache.get(task_id)
        return AgentState.from_json(raw) if raw else None

    def list_tasks(self) -> List[Dict[str, Any]]:
        result = []
        for raw in self.cache.values():
            state = AgentState.from_json(raw)
            result.append(state_summary(state))
        return result


class SQLiteStateStore(StateStore):
    """SQLite 持久化实现（单机生产可用）。

    进程崩溃后状态不丢失，支持断点续跑；
    SQLite 自身的写锁天然提供单机串行化，多实例部署时请替换为 Redis + 分布式锁。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    max_iteration INTEGER NOT NULL,
                    final_result TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    state_json TEXT NOT NULL
                )
                """
            )

    def save(self, state: AgentState) -> None:
        state.updated_at = time.time()
        with self._lock, self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_tasks
                    (task_id, status, iteration, max_iteration, final_result,
                     created_at, updated_at, state_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status = excluded.status,
                    iteration = excluded.iteration,
                    max_iteration = excluded.max_iteration,
                    final_result = excluded.final_result,
                    updated_at = excluded.updated_at,
                    state_json = excluded.state_json
                """,
                (
                    state.task_id,
                    state.status,
                    state.iteration,
                    state.max_iteration,
                    state.final_result,
                    state.created_at,
                    state.updated_at,
                    state.to_json(),
                ),
            )

    def load(self, task_id: str) -> Optional[AgentState]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT state_json FROM agent_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return AgentState.from_json(row["state_json"]) if row else None

    def list_tasks(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT task_id, status, iteration, max_iteration,
                       final_result, created_at, updated_at
                FROM agent_tasks ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]


def new_call_id() -> str:
    """生成本次工具调用唯一 ID（幂等主键 / Idempotency Key）"""
    return str(uuid.uuid4())


def state_summary(state: AgentState) -> Dict[str, Any]:
    """生成任务概要（不含完整 messages，避免响应过大）"""
    return {
        "task_id": state.task_id,
        "status": state.status,
        "iteration": state.iteration,
        "max_iteration": state.max_iteration,
        "tool_count": len(state.tool_records),
        "pending_tool_call": state.pending_tool_call,
        "current_subtask_id": state.current_subtask_id,
        "final_result": state.final_result,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }
