"""
轻量级 Trace 模块（一期方案：自建 Trace 落 SQLite，OTel 语义）

参考《20260815_技术_Trace模块引入与行业实践》落地：
- TraceEvent: 行业共识数据结构（trace_id / span_id / parent_span_id /
  operation_name / duration_ms / attributes / resource / status）
- TraceCollector: 后台 daemon 线程异步批量写入，不阻塞主流程（最佳实践#2）
- 全局 collector 注入（set_collector / get_collector）：
  LLMFactory 回调等横切面无需依赖注入即可上报
- ContextVar 绑定当前 trace_id：Harness 在 run_loop 入口绑定 task_id=trace_id，
  任意深处的 LLM 调用都能正确归属（最佳实践#4 关联业务上下文）
- LLM 调用采用"代理层"思路的等价实现：LangChain callbacks 钩子，
  零侵入捕获所有 LLM 调用（含 RAG 链 / 数据分析等非 Agent 路径）

二期迁移说明：数据结构遵循 OpenTelemetry 语义，迁移 Langfuse/Phoenix 时
只需将 TraceCollector 的存储后端替换为 OTLP 上报。
"""

import contextlib
import json
import logging
import queue
import sqlite3
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 当前请求绑定的 trace_id（Harness 主循环入口设置；非 Agent 路径为 "adhoc"）
_current_trace: ContextVar[Optional[str]] = ContextVar("kbqa_current_trace", default=None)

# 全局 Trace 收集器（app.py lifespan 启动时注入；None 表示 Trace 关闭）
_global_collector: Optional["TraceCollector"] = None
_global_lock = threading.Lock()


def set_current_trace(trace_id: Optional[str]) -> None:
    """绑定当前执行流的 trace_id（Agent 任务即 task_id）"""
    _current_trace.set(trace_id)


def get_current_trace() -> Optional[str]:
    return _current_trace.get()


def set_collector(collector: Optional["TraceCollector"]) -> None:
    """注入全局 Trace 收集器（None 可关闭）"""
    global _global_collector
    with _global_lock:
        _global_collector = collector


def get_collector() -> Optional["TraceCollector"]:
    return _global_collector


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


@dataclass
class TraceEvent:
    """一条 Trace 记录（对应 OTel 语义的一个 Span/Event）"""
    trace_id: str
    span_id: str = field(default_factory=new_span_id)
    parent_span_id: Optional[str] = None
    operation_name: str = ""
    start_time: int = 0                      # epoch 毫秒
    duration_ms: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)
    resource: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"                       # "ok" | "error"

    def to_row(self) -> tuple:
        return (
            self.trace_id, self.span_id, self.parent_span_id,
            self.operation_name, self.start_time, self.duration_ms,
            json.dumps(self.attributes, ensure_ascii=False, default=str),
            json.dumps(self.resource, ensure_ascii=False, default=str),
            self.status,
        )


class TraceCollector:
    """Trace 收集器：内存队列 + 后台线程异步批量写 SQLite。

    - emit() 非阻塞（队列满则丢弃并告警，绝不影响主流程）
    - flush() 供测试与查询前强制落盘
    - resource 段全局携带服务元数据（service.name / environment / llm_provider）
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS agent_traces (
        trace_id       TEXT NOT NULL,
        span_id        TEXT PRIMARY KEY,
        parent_span_id TEXT,
        operation_name TEXT NOT NULL,
        start_time     INTEGER NOT NULL,
        duration_ms    REAL NOT NULL DEFAULT 0,
        attributes     TEXT NOT NULL DEFAULT '{}',
        resource       TEXT NOT NULL DEFAULT '{}',
        status         TEXT NOT NULL DEFAULT 'ok'
    );
    CREATE INDEX IF NOT EXISTS idx_agent_traces_trace
        ON agent_traces (trace_id, start_time);
    """

    def __init__(self, db_path: str, resource: Optional[Dict[str, Any]] = None,
                 queue_size: int = 10000, flush_interval: float = 0.5):
        self.db_path = db_path
        self.resource = resource or {}
        self._queue: "queue.Queue[TraceEvent]" = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._flush_interval = flush_interval
        self._init_db()
        self._worker = threading.Thread(target=self._write_loop,
                                        name="trace-collector", daemon=True)
        self._worker.start()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(self._SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # ---------- 对外接口 ----------

    def emit(self, event: TraceEvent) -> None:
        """非阻塞上报：合并全局 resource 后入队"""
        if not event.resource:
            event.resource = dict(self.resource)
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("Trace 队列已满，丢弃事件: %s", event.operation_name)

    def event(self, trace_id: str, operation_name: str,
              duration_ms: float = 0.0, status: str = "ok",
              parent_span_id: Optional[str] = None,
              **attributes: Any) -> None:
        """便捷方法：上报一个瞬时事件"""
        self.emit(TraceEvent(
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            start_time=int(time.time() * 1000),
            duration_ms=round(duration_ms, 1),
            attributes=attributes,
            status=status,
        ))

    def flush(self, timeout: float = 2.0) -> bool:
        """等待队列中事件全部落盘（测试/查询前使用）"""
        deadline = time.time() + timeout
        while not self._queue.empty() and time.time() < deadline:
            time.sleep(0.02)
        return self._queue.empty()

    def close(self, timeout: float = 2.0) -> None:
        """停机：flush 后退出后台线程（app.py lifespan 清理时调用）"""
        self.flush(timeout)
        self._stop.set()
        self._worker.join(timeout=timeout)

    def query(self, trace_id: str) -> List[Dict[str, Any]]:
        """按 trace_id 查询完整调用链（按开始时间排序）"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT trace_id, span_id, parent_span_id, operation_name,"
                " start_time, duration_ms, attributes, resource, status"
                " FROM agent_traces WHERE trace_id = ? ORDER BY start_time ASC",
                (trace_id,),
            ).fetchall()
        finally:
            conn.close()
        result = []
        for r in rows:
            result.append({
                "trace_id": r[0], "span_id": r[1], "parent_span_id": r[2],
                "operation_name": r[3], "start_time": r[4],
                "duration_ms": r[5],
                "attributes": json.loads(r[6]),
                "resource": json.loads(r[7]),
                "status": r[8],
            })
        return result

    # ---------- 后台写入 ----------

    def _write_loop(self) -> None:
        while not self._stop.is_set():
            batch: List[TraceEvent] = []
            try:
                item = self._queue.get(timeout=self._flush_interval)
                batch.append(item)
                while len(batch) < 200 and not self._queue.empty():
                    batch.append(self._queue.get_nowait())
            except queue.Empty:
                continue
            except Exception:  # noqa: BLE001
                continue
            try:
                self._write_batch(batch)
            except Exception as e:  # noqa: BLE001
                logger.warning("Trace 批量写入失败（丢弃 %d 条）: %s", len(batch), e)
            finally:
                for _ in batch:
                    self._queue.task_done()

    def _write_batch(self, batch: List[TraceEvent]) -> None:
        conn = self._connect()
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO agent_traces"
                " (trace_id, span_id, parent_span_id, operation_name,"
                "  start_time, duration_ms, attributes, resource, status)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                [e.to_row() for e in batch],
            )
            conn.commit()
        finally:
            conn.close()


@contextlib.contextmanager
def trace_span(operation_name: str, trace_id: Optional[str] = None,
               parent_span_id: Optional[str] = None,
               **attributes: Any):
    """上下文管理器用法：自动计时，异常时 status=error 并抛出。

    collector 未启用时为零开销空操作。
    """
    collector = get_collector()
    if collector is None:
        yield None
        return
    tid = trace_id or get_current_trace() or "adhoc"
    span_id = new_span_id()
    start = time.time()
    try:
        yield span_id
    except Exception as e:  # noqa: BLE001
        collector.event(tid, operation_name,
                        duration_ms=(time.time() - start) * 1000,
                        status="error", parent_span_id=span_id,
                        error=str(e)[:500], **attributes)
        raise
    else:
        collector.event(tid, operation_name,
                        duration_ms=(time.time() - start) * 1000,
                        parent_span_id=parent_span_id,
                        span_id=span_id, **attributes)


# ==================== LLM 调用代理层（LangChain callbacks 钩子）====================

def build_llm_trace_handler(provider: str) -> Optional[Any]:
    """构建 LLM 调用 Trace 回调处理器（代理层模式的等价实现）。

    - 拦截所有经过 LangChain Runnable 的 LLM 调用，自动记录：
      模型、token 用量、耗时、prompt/完成长度、trace_id 归属
    - 覆盖 RAG 链 / 数据分析等非 Agent 路径（trace_id=adhoc 也能定位）
    - Trace 未启用（全局 collector 为空）或 langchain 不可用时返回 None
    """
    collector = get_collector()
    if collector is None:
        return None
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:  # 测试环境无 langchain
        return None

    class _LLMTraceHandler(BaseCallbackHandler):
        """无侵入 LLM 调用追踪：并发安全（按 run_id 记录起点）"""

        def __init__(self):
            self._starts: Dict[Any, tuple] = {}
            self._lock = threading.Lock()

        def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
            prompt_chars = sum(len(p) for p in prompts) if prompts else 0
            model = None
            if isinstance(serialized, dict):
                model = serialized.get("name") or serialized.get("id", [None])[-1]
            with self._lock:
                self._starts[run_id] = (time.time(), prompt_chars, model)

        def on_llm_end(self, response, *, run_id, **kwargs):
            with self._lock:
                record = self._starts.pop(run_id, None)
            if record is None:
                record = (time.time(), 0, None)
            start_ts, prompt_chars, model = record
            attrs: Dict[str, Any] = {
                "provider": provider,
                "model": model,
                "prompt_chars": prompt_chars,
            }
            # token 统计（兼容 ChatOllama / ChatOpenAI 的 usage_metadata）
            try:
                gen = response.generations[0][0]
                msg = getattr(gen, "message", None)
                usage = getattr(msg, "usage_metadata", None) or {}
                if usage:
                    attrs["input_tokens"] = usage.get("input_tokens")
                    attrs["output_tokens"] = usage.get("output_tokens")
                    attrs["total_tokens"] = usage.get("total_tokens")
                resp_meta = getattr(msg, "response_metadata", None) or {}
                attrs["model"] = resp_meta.get("model_name") or model or provider
                attrs["completion_chars"] = len(getattr(gen, "text", "") or "")
            except Exception:  # noqa: BLE001
                pass
            collector.event(
                trace_id=get_current_trace() or "adhoc",
                operation_name="llm_call",
                duration_ms=(time.time() - start_ts) * 1000,
                **attrs,
            )

        def on_llm_error(self, error, *, run_id, **kwargs):
            with self._lock:
                record = self._starts.pop(run_id, None)
            start_ts = record[0] if record else time.time()
            collector.event(
                trace_id=get_current_trace() or "adhoc",
                operation_name="llm_call",
                duration_ms=(time.time() - start_ts) * 1000,
                status="error",
                provider=provider,
                error=str(error)[:500],
            )

    return _LLMTraceHandler()
