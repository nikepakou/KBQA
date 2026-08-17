"""
Agent 任务规划模块
参考文档《02-任务规划与Harness主分支结合方案》实现。

核心设计原则（与文档一一对应）：
1. Plan 是独立结构化数据，不用自然语言文本充当计划
2. Plan 独立持久化（PlanStore，与 StateStore 分离），通过 root_task_id
   与 AgentState 一对一绑定，断点续跑时双向恢复（State + Plan 缺一不可）
3. Plan：目标拆解后的任务清单（what to do）；AgentState：实时执行上下文（running context）
4. 支持动态规划：plan_version 版本号自增，防止并发覆盖
5. 子任务支持简单 DAG 依赖（depend_on），由 Harness 主循环调度，
   Planner 只产出/修改清单，不控制执行流
"""

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SubTask:
    """单条子任务（计划内最小单元）"""

    task_id: str                      # 子任务唯一id
    title: str                        # 任务名称（自然语言）
    description: str = ""             # 任务目标
    status: str = "pending"           # pending / running / completed / skipped / failed
    depend_on: List[str] = field(default_factory=list)   # 依赖的前置子任务ID，支持简单DAG
    required_tools: List[str] = field(default_factory=list)  # 预估需要使用的工具
    result_summary: Optional[str] = None  # 子任务执行结果摘要


@dataclass
class ExecutionPlan:
    """整体任务规划（独立持久化对象）"""

    plan_id: str
    root_task_id: str                 # 关联顶层 Agent 任务ID（与 AgentState.task_id 一一绑定）
    overall_goal: str                 # 用户原始总目标
    subtasks: List[SubTask] = field(default_factory=list)
    plan_status: str = "active"       # active / finished / abandoned
    plan_version: int = 1             # 动态修改计划时版本号+1，防止并发覆盖
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        # dataclasses.asdict 递归展开内层 SubTask，保证可 JSON 序列化
        from dataclasses import asdict
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @staticmethod
    def from_json(raw: str) -> "ExecutionPlan":
        data = json.loads(raw)
        # 反序列化内层 SubTask
        data["subtasks"] = [SubTask(**s) for s in data.get("subtasks", [])]
        return ExecutionPlan(**data)

    def to_brief(self) -> Dict[str, Any]:
        """生成计划概要（列表展示用）"""
        return {
            "plan_id": self.plan_id,
            "root_task_id": self.root_task_id,
            "overall_goal": self.overall_goal,
            "plan_status": self.plan_status,
            "plan_version": self.plan_version,
            "subtasks": [
                {
                    "task_id": st.task_id,
                    "title": st.title,
                    "status": st.status,
                    "depend_on": st.depend_on,
                    "result_summary": st.result_summary,
                }
                for st in self.subtasks
            ],
        }


class PlanStore:
    """Plan 持久化抽象层（与 StateStore 分离；生产可替换 Redis/PG）"""

    def save_plan(self, root_task_id: str, plan: ExecutionPlan) -> None:
        raise NotImplementedError

    def load_plan(self, root_task_id: str) -> Optional[ExecutionPlan]:
        raise NotImplementedError


class MemoryPlanStore(PlanStore):
    """内存实现（测试用）"""

    def __init__(self):
        self.cache: Dict[str, str] = {}

    def save_plan(self, root_task_id: str, plan: ExecutionPlan) -> None:
        plan.updated_at = time.time()
        self.cache[root_task_id] = plan.to_json()

    def load_plan(self, root_task_id: str) -> Optional[ExecutionPlan]:
        raw = self.cache.get(root_task_id)
        return ExecutionPlan.from_json(raw) if raw else None


class SQLitePlanStore(PlanStore):
    """SQLite 持久化实现。

    物理上与任务状态同库（data/agent_tasks.db）、逻辑上独立成表 agent_plans，
    接口与 StateStore 分离；换库只需替换本类。
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
                CREATE TABLE IF NOT EXISTS agent_plans (
                    root_task_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    plan_status TEXT NOT NULL,
                    plan_version INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    plan_json TEXT NOT NULL
                )
                """
            )

    def save_plan(self, root_task_id: str, plan: ExecutionPlan) -> None:
        plan.updated_at = time.time()
        with self._lock, self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO agent_plans
                    (root_task_id, plan_id, plan_status, plan_version, updated_at, plan_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_task_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    plan_status = excluded.plan_status,
                    plan_version = excluded.plan_version,
                    updated_at = excluded.updated_at,
                    plan_json = excluded.plan_json
                """,
                (
                    root_task_id,
                    plan.plan_id,
                    plan.plan_status,
                    plan.plan_version,
                    plan.updated_at,
                    plan.to_json(),
                ),
            )

    def load_plan(self, root_task_id: str) -> Optional[ExecutionPlan]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT plan_json FROM agent_plans WHERE root_task_id = ?",
                (root_task_id,),
            ).fetchone()
        return ExecutionPlan.from_json(row["plan_json"]) if row else None


def new_subtask_id(seq: int) -> str:
    """生成有序子任务ID：st_001 / st_002 ..."""
    return f"st_{seq:03d}"


def new_plan_id() -> str:
    return str(uuid.uuid4())
