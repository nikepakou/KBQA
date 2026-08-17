"""
Agent Harness 核心运行引擎
参考《01-Agent Harness（断点续跑 + 工具调用幂等）》与
《02-任务规划与Harness主分支结合方案》两篇文档实现。

分层架构：
    用户请求 → 【Planner 任务规划器】输出结构化 ExecutionPlan（独立持久化）
            → 【Harness 主循环（ReAct执行引擎）】逐条执行计划，可动态调整
            → 【Tool 执行层】

核心设计（与文档一一对应）：
1. 结构化 AgentState 是唯一可信源；Plan 是独立结构化清单（what to do），
   两者通过 root_task_id 绑定，断点续跑时双向恢复
2. Planner 属于上层模块，不侵入主循环核心：只产出/修改清单，
   循环调度、断点、幂等、护栏全部由 Harness 主循环负责
3. 规划驱动（DAG 依赖调度）+ 无 Plan 任务回退纯 ReAct（向后兼容）
4. 动态规划：子任务失败时触发 revise_plan（防过度规划：仅失败时 + 次数上限）
5. 工具调用幂等三层防护（预占位 / 重复预检查 / check_executed 恢复）完整保留

提示词模板（Jinja2 分离，位于 src/prompt/）：
- system/harness_decision.j2：规划模式决策系统提示词
- system/harness_react.j2：纯 ReAct 模式决策系统提示词
- system/harness_task_init.j2：任务初始化系统消息
- user/harness_subtask_inject.j2：子任务上下文注入用户消息
- user/harness_reflect_on_failure.j2：失败自省用户消息
"""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from agent.state import AgentState, StateStore, new_call_id
from agent.plan import ExecutionPlan, PlanStore, SubTask
from agent.tools import BaseTool
from llm_factory import LLMFactory
from agent_trace import (TraceCollector, get_collector,
                         set_current_trace)
from prompt.loader import render_system, render_user

logger = logging.getLogger(__name__)

# 决策系统提示词模板名（位于 src/prompt/system/）
DECISION_SYSTEM_PROMPT = "harness_decision"
REACT_SYSTEM_PROMPT = "harness_react"


class AgentHarness:
    """Agent 核心运行器：Planner 规划驱动 + ReAct 工具循环 + 幂等 + 断点续跑"""

    # 防过度规划：单任务允许的最大重规划次数（框架侧强制管控）
    MAX_PLAN_REVISE = 3

    def __init__(self, state_store: StateStore, tools: List[BaseTool],
                 provider: Optional[str] = None,
                 plan_store: Optional[PlanStore] = None,
                 planner: Any = None,
                 collector: Optional[TraceCollector] = None,
                 event_callback: Optional[Any] = None):
        """
        Args:
            state_store: Agent 状态持久化
            tools: 工具列表
            provider: 主循环 LLM 提供商
            plan_store: Plan 持久化（与 StateStore 分离）；None 时禁用规划
            planner: TaskPlanner 实例；None 时退化为纯 ReAct 模式（向后兼容）
            collector: Trace 收集器；None 时回退全局收集器（未启用则零开销）
            event_callback: 事件回调函数，签名 callback(event_type: str, data: dict)，用于 SSE 流式推送
        """
        self.state_store = state_store
        self.plan_store = plan_store
        self.planner = planner
        self.tool_map: Dict[str, BaseTool] = {t.name: t for t in tools}
        self.provider = provider
        self.collector = collector or get_collector()
        self.llm = LLMFactory.create_llm(provider=provider)
        # 单机并发锁（生产多实例部署替换为 Redis 分布式锁）
        self._tool_lock = threading.Lock()
        self._event_callback = event_callback

    def _emit(self, task_id: str, operation: str, status: str = "ok",
              duration_ms: float = 0.0, **attrs: Any) -> None:
        """Trace 埋点（collector 未启用时零开销）"""
        if self.collector is not None:
            try:
                self.collector.event(task_id, operation, duration_ms=duration_ms,
                                     status=status, **attrs)
            except Exception:  # noqa: BLE001
                logger.debug("Trace 上报失败（不影响主流程）", exc_info=True)

    def _fire_event(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """通过回调发送事件（用于 SSE 流式推送）"""
        if self._event_callback is not None:
            try:
                self._event_callback(event_type, data or {})
            except Exception:
                pass

    # ==================== LLM 决策 ====================

    def llm_infer(self, state: AgentState, system_prompt: str) -> Dict[str, Any]:
        """调用 LLM 进行单次决策。

        Args:
            state: 当前 Agent 状态
            system_prompt: 系统提示词模板名（位于 src/prompt/system/<name>.j2），
                           例如 "harness_decision" 或 "harness_react"

        返回格式：
        {"type": "tool_call", "tool_name": "xxx", "args": {...}}
        或 {"type": "finish", "content": "任务完成结论"}
        """
        tools_desc = "\n".join(
            f"- {t.name} ({t.risk_level}): {t.description}"
            for t in self.tool_map.values()
        )
        prompt = render_system(system_prompt, tools_desc=tools_desc)

        # 组装消息：tool 角色消息转为 user 文本（兼容所有 Chat 模型）
        llm_messages: List[Dict[str, str]] = [
            {"role": "system", "content": prompt}
        ] + [self._convert_message(m) for m in state.messages]

        self._fire_event("thinking", {"message": "LLM 正在思考...", "iteration": state.iteration})
        response = self.llm.invoke(llm_messages)
        content = getattr(response, "content", str(response))
        logger.info("LLM 原始返回: %s", content[:500])
        decision = self._parse_decision(content)

        self._fire_event("llm_response", {
            "raw_content": content[:300],
            "decision_type": decision.get("type"),
            "iteration": state.iteration,
        })

        # 决策兜底：解析失败或未知工具名 → 视为 finish，避免死循环
        if decision.get("type") == "tool_call" and decision.get("tool_name") not in self.tool_map:
            logger.warning("LLM 返回未知工具名: %s，强制结束", decision.get("tool_name"))
            self._fire_event("warning", {"message": f"未知工具: {decision.get('tool_name')}，强制结束"})
            return {"type": "finish",
                    "content": f"无法处理该请求（未知工具 {decision.get('tool_name')}）"}
        return decision

    @staticmethod
    def _convert_message(msg: Dict[str, Any]) -> Dict[str, str]:
        """将标准消息序列转换为通用 Chat 格式（tool 角色转 user 文本）"""
        role = msg.get("role", "user")
        if role == "tool":
            name = msg.get("name", "tool")
            return {"role": "user", "content": f"[工具 {name} 返回]\n{msg.get('content', '')}"}
        if role == "assistant" and "tool_calls" in msg:
            calls = msg["tool_calls"]
            text = "\n".join(
                f"[调用工具 {c.get('name')}] 参数: {json.dumps(c.get('arguments', {}), ensure_ascii=False)}"
                for c in calls
            )
            return {"role": "assistant", "content": text or "(空决策)"}
        return {"role": role, "content": msg.get("content", "")}

    @staticmethod
    def _parse_decision(text: str) -> Dict[str, Any]:
        """从 LLM 输出稳健解析决策 JSON（处理 markdown 代码块/多余文字）"""
        if not text:
            return {"type": "finish", "content": "模型未返回有效决策"}
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        start = text.find("{")
        if start == -1:
            return {"type": "finish", "content": text}
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        return {"type": "finish", "content": text}
        return {"type": "finish", "content": text}

    # ==================== 任务入口 ====================

    def start_task(self, task_id: str, user_query: str, max_iter: int = 10) -> Dict[str, Any]:
        """新建任务：先规划（Planner 输出结构化 Plan 并持久化），再执行主循环"""
        if self.state_store.load(task_id) is not None:
            raise ValueError(f"任务已存在: {task_id}，如需继续请调用 resume")
        init_state = AgentState(
            task_id=task_id,
            status="running",
            iteration=0,
            max_iteration=max_iter,
            messages=[
                {"role": "system", "content": render_system("harness_task_init")},
                {"role": "user", "content": user_query},
            ],
            current_subtask_id=None,
        )
        self.state_store.save(init_state)

        # ========== Planner 初始规划：生成 Plan 并独立持久化 ==========
        set_current_trace(task_id)  # 绑定 trace 上下文：后续 LLM 调用自动归属本任务
        if self.planner is not None and self.plan_store is not None:
            plan_start = time.time()
            try:
                plan = self.planner.create_initial_plan(task_id, user_query)
                logger.info("Agent 任务启动: %s（规划 %d 个子任务，plan v%d）",
                            task_id, len(plan.subtasks), plan.plan_version)
                self._emit(task_id, "plan_create", duration_ms=(time.time() - plan_start) * 1000,
                           subtask_count=len(plan.subtasks), plan_version=plan.plan_version)
            except Exception as e:  # noqa: BLE001
                logger.warning("初始规划失败，回退纯 ReAct 模式: %s", e)
                self._emit(task_id, "plan_create", status="error",
                           duration_ms=(time.time() - plan_start) * 1000,
                           error=str(e)[:300], fallback="react")
        else:
            logger.info("Agent 任务启动: %s（无规划器，纯 ReAct 模式）", task_id)
            self._emit(task_id, "plan_create", mode="react")
        return self.run_loop(task_id)

    def resume_task(self, task_id: str) -> Dict[str, Any]:
        """【断点续跑入口】自动加载 AgentState + ExecutionPlan 双向恢复。

        - Plan 与 State 缺一不可：只有状态没有计划，无法知道下一步目标
        - 中断时 running 状态的子任务回退为 pending，由调度器重新选中
        - 未闭环工具调用（pending_tool_call）依据幂等策略处理（同 01 文档）
        """
        state = self.state_store.load(task_id)
        if not state:
            raise ValueError(f"任务不存在: {task_id}")
        if state.status != "running":
            return {"task_id": task_id, "status": state.status,
                    "result": state.final_result, "resumed": False,
                    "message": "任务已结束，无需续跑"}

        plan = self.plan_store.load_plan(task_id) if self.plan_store else None
        if plan is not None:
            # 定位中断时正在执行的子任务：running → pending（幂等由工具层保证，
            # 已执行过的工具调用会被 tool_records 预检查拦截并注入历史结果）
            for st in plan.subtasks:
                if st.task_id == state.current_subtask_id and st.status == "running":
                    st.status = "pending"
                    logger.info("续跑定位：子任务 %s 回退为 pending 重新调度", st.task_id)
            self.plan_store.save_plan(task_id, plan)

        # ========= 幂等恢复核心逻辑（未闭环工具调用，同 01 文档）=========
        pending = state.pending_tool_call
        if pending is not None:
            call_id = pending["call_id"]
            tool_name = pending["tool_name"]
            tool_args = pending.get("args", {})
            logger.info("检测到未闭环工具调用 %s(%s)，进入恢复流程", tool_name, call_id)

            target_tool = self.tool_map.get(tool_name)
            # 策略A（高危写操作）：查询业务系统确认是否已生效
            executed = False
            if target_tool is not None and hasattr(target_tool, "check_executed"):
                executed = bool(target_tool.check_executed(tool_args))

            if executed:
                state.tool_records.append({
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "args": tool_args,
                    "result": "【恢复检测】上次调用已生效，跳过重复执行",
                    "success": True,
                    "recovered": True,
                })
                state.messages.append({
                    "role": "tool", "name": tool_name,
                    "content": "系统检测：上次调用已完成，跳过重复执行",
                })
                state.pending_tool_call = None
                self.state_store.save(state)
            else:
                state.pending_tool_call = None
                self.state_store.save(state)
        # ==================================

        logger.info("Agent 任务续跑: %s（第 %d/%d 轮）", task_id, state.iteration, state.max_iteration)
        self._emit(task_id, "resume", iteration=state.iteration,
                   max_iteration=state.max_iteration,
                   pending_tool_call=pending.get("tool_name") if pending else None,
                   pending_already_executed=bool(pending and executed) if pending else False)
        set_current_trace(task_id)
        result = self.run_loop(task_id)
        result["resumed"] = True
        return result

    # ==================== 计划调度 ====================

    @staticmethod
    def _get_next_executable_subtask(plan: ExecutionPlan) -> Optional[SubTask]:
        """核心调度函数：按依赖关系（简单DAG）找出下一个可执行的 pending 子任务。

        completed/skipped/failed 均视为不再执行；依赖未全部 completed 则阻塞。
        """
        for st in plan.subtasks:
            if st.status != "pending":
                continue
            all_dep_finished = all(
                any(s.task_id == dep_id and s.status == "completed"
                    for s in plan.subtasks)
                for dep_id in st.depend_on
            )
            if all_dep_finished:
                return st
        return None

    def _summarize_plan_result(self, plan: ExecutionPlan) -> str:
        """计划完成后汇总各子任务结果摘要（Plan 压缩策略：只取摘要）"""
        parts = []
        for st in plan.subtasks:
            if st.status == "completed":
                parts.append(f"✓ {st.title}: {st.result_summary or '完成'}")
            elif st.status == "failed":
                parts.append(f"✗ {st.title}: 未完成")
        return "\n".join(parts) or "所有子任务执行完毕"

    # ==================== 主循环 ====================

    def run_loop(self, task_id: str) -> Dict[str, Any]:
        """主循环：规划驱动执行（无 Plan 时回退纯 ReAct）。

        - 规划模式：外层按 DAG 逐个子任务 → 内层 ReAct 工具循环
        - 全局 iteration/max_iteration 护栏由框架强制管控
        - 工具失败 → 可选触发动态重规划（revise_plan）
        """
        state = self.state_store.load(task_id)
        plan = self.plan_store.load_plan(task_id) if self.plan_store else None
        set_current_trace(task_id)  # 主循环内所有 LLM 调用归属本任务 trace

        # ---------- 无 Plan：回退纯 ReAct 模式（向后兼容）----------
        if plan is None:
            return self._run_react_loop(task_id, state)

        # ---------- 有 Plan：规划驱动模式 ----------
        while True:
            # 安全护栏校验（Harness 强制管控，不依赖 LLM）
            if state.iteration >= state.max_iteration:
                state.status = "failed"
                state.final_result = "超出最大工具调用轮次，任务终止"
                plan.plan_status = "abandoned"
                self.state_store.save(state)
                self.plan_store.save_plan(task_id, plan)
                self._emit(task_id, "task_end", status="error",
                           task_status="failed", iteration=state.iteration,
                           reason="max_iteration_exceeded")
                self._fire_event("task_end", {"status": "failed", "result": state.final_result})
                return {"task_id": task_id, "status": "failed",
                        "result": state.final_result}

            # 规划驱动：获取下一个待执行子任务
            next_subtask = self._get_next_executable_subtask(plan)
            if next_subtask is None:
                # 没有可执行子任务 → 计划全部完成
                plan.plan_status = "finished"
                state.status = "completed"
                state.current_subtask_id = None
                state.final_result = self._summarize_plan_result(plan)
                self.state_store.save(state)
                self.plan_store.save_plan(task_id, plan)
                logger.info("Agent 任务完成（计划内全部子任务）: %s", task_id)
                self._emit(task_id, "task_end", task_status="completed",
                           iteration=state.iteration,
                           plan_version=plan.plan_version)
                self._fire_event("task_end", {"status": "completed", "result": state.final_result})
                return {"task_id": task_id, "status": "completed",
                        "result": state.final_result}

            # 标记当前子任务 running，写入状态（断点恢复定位用）
            state.current_subtask_id = next_subtask.task_id
            next_subtask.status = "running"
            self.plan_store.save_plan(task_id, plan)
            self.state_store.save(state)
            self._emit(task_id, "subtask_schedule",
                       subtask_id=next_subtask.task_id,
                       title=next_subtask.title[:100],
                       depend_on=next_subtask.depend_on,
                       plan_version=plan.plan_version)

            # 给 LLM 注入当前子任务上下文，引导决策（模板：user/harness_subtask_inject.j2）
            inject = render_user(
                "harness_subtask_inject",
                overall_goal=plan.overall_goal,
                subtask_title=next_subtask.title,
                subtask_description=next_subtask.description,
                required_tools=", ".join(next_subtask.required_tools) if next_subtask.required_tools else "",
            )
            state.messages.append({"role": "user", "content": inject})
            self.state_store.save(state)

            # ===== 内层循环：当前子任务内的 ReAct 工具执行（幂等逻辑复用）=====
            subtask_failed = False
            while True:
                if state.iteration >= state.max_iteration:
                    break  # 由外层护栏统一判定失败

                try:
                    decision = self.llm_infer(state, DECISION_SYSTEM_PROMPT)
                except Exception as e:  # noqa: BLE001
                    logger.error("LLM 决策失败: %s", e)
                    state.biz_context["last_error"] = str(e)
                    self.state_store.save(state)
                    return {"task_id": task_id, "status": "running",
                            "error": f"模型决策失败: {e}", "resumable": True}

                # 分支1：LLM 判定当前子任务完成
                if decision.get("type") == "finish":
                    next_subtask.status = "completed"
                    next_subtask.result_summary = decision.get("content", "")
                    state.current_subtask_id = None
                    state.messages.append({
                        "role": "assistant",
                        "content": f"[子任务完成] {next_subtask.title}: {next_subtask.result_summary}",
                    })
                    self.plan_store.save_plan(task_id, plan)
                    self.state_store.save(state)
                    break  # 回到外层取下一个子任务

                # 分支2：工具调用（幂等、预占位、持久化逻辑完全复用）
                success = self._execute_tool_call(task_id, state, decision)
                if not success:
                    # 【动态规划触发点】子任务执行失败，调用 Planner 修正计划
                    # 防过度规划：次数上限由 Harness 框架侧强制管控（不依赖 Planner 实现）
                    revise_count = state.biz_context.get("plan_revise_count", 0)
                    if self.planner is not None and revise_count < self.MAX_PLAN_REVISE:
                        failure = state.biz_context.get("last_tool_error", "未知错误")
                        revise_start = time.time()
                        revised = self.planner.revise_plan(task_id, state, failure)
                        if revised is not None:
                            plan = revised
                            state.biz_context["plan_revise_count"] = revise_count + 1
                            self._emit(task_id, "plan_revise",
                                       duration_ms=(time.time() - revise_start) * 1000,
                                       new_version=plan.plan_version,
                                       subtask_count=len(plan.subtasks),
                                       failure=failure[:300])
                            state.messages.append({
                                "role": "user",
                                "content": "[系统提示] 计划已动态修正（v%d），按新计划继续" % plan.plan_version,
                            })
                            self.state_store.save(state)
                            # 当前子任务在新计划中已被替换/移除
                            subtask_failed = True
                            break
                    # 未重规划或修正失败：标记当前子任务 failed，调度下一个
                    subtask_failed = True
                    break

            if subtask_failed:
                if next_subtask.status == "running":  # 未经重规划替换时标记失败
                    next_subtask.status = "failed"
                state.current_subtask_id = None
                self.plan_store.save_plan(task_id, plan)
                self.state_store.save(state)

    def _run_react_loop(self, task_id: str, state: AgentState) -> Dict[str, Any]:
        """纯 ReAct 模式（无计划，与 01 文档版行为一致）"""
        set_current_trace(task_id)
        while True:
            if state.iteration >= state.max_iteration:
                state.status = "failed"
                state.final_result = "超出最大工具调用轮次，任务终止"
                self.state_store.save(state)
                self._emit(task_id, "task_end", status="error",
                           task_status="failed", iteration=state.iteration,
                           reason="max_iteration_exceeded", mode="react")
                self._fire_event("task_end", {"status": "failed", "result": state.final_result})
                return {"task_id": task_id, "status": "failed",
                        "result": state.final_result}

            try:
                decision = self.llm_infer(state, REACT_SYSTEM_PROMPT)
            except Exception as e:  # noqa: BLE001
                logger.error("LLM 决策失败: %s", e)
                state.biz_context["last_error"] = str(e)
                self.state_store.save(state)
                self._fire_event("error", {"message": str(e)})
                return {"task_id": task_id, "status": "running",
                        "error": f"模型决策失败: {e}", "resumable": True}

            if decision.get("type") == "finish":
                state.status = "completed"
                state.final_result = decision.get("content", "")
                self.state_store.save(state)
                self._emit(task_id, "task_end", task_status="completed",
                           iteration=state.iteration, mode="react")
                self._fire_event("task_end", {"status": "completed", "result": state.final_result})
                return {"task_id": task_id, "status": "completed",
                        "result": state.final_result}

            self._execute_tool_call(task_id, state, decision)

    # ==================== 幂等工具调用（01 文档核心逻辑，两种模式复用）====================

    def _execute_tool_call(self, task_id: str, state: AgentState,
                           decision: Dict[str, Any]) -> bool:
        """执行一次工具调用：重复预检查 → 预占位 → 加锁执行 → 状态落盘。

        Returns:
            True 表示工具执行成功或被幂等拦截；False 表示执行失败
        """
        tool_name = decision.get("tool_name", "")
        tool_args = decision.get("args") or {}
        if not isinstance(tool_args, dict):
            tool_args = {"value": str(tool_args)}
        tool = self.tool_map.get(tool_name)
        if tool is None:
            state.messages.append({
                "role": "tool", "name": tool_name,
                "content": f"【系统提示】工具 {tool_name} 不存在，可用工具: {list(self.tool_map.keys())}",
            })
            self.state_store.save(state)
            self._fire_event("tool_result", {
                "tool_name": tool_name,
                "success": False,
                "result": f"工具不存在，可用工具: {list(self.tool_map.keys())}",
            })
            return True  # 非执行失败，交由下轮决策

        call_id = new_call_id()

        # 预检查：查询历史 tool_records，防止重复调用（幂等拦截）
        history = next(
            (r for r in state.tool_records
             if r["tool_name"] == tool_name and r.get("args") == tool_args),
            None,
        )
        if history is not None:
            state.messages.append({
                "role": "tool", "name": tool_name,
                "content": f"【系统提示】该工具已执行完成，无需重复调用。历史结果：\n{history.get('result', '')}",
            })
            self.state_store.save(state)
            # Trace：幂等拦截审计事件
            self._emit(task_id, "idempotent_block", tool_name=tool_name,
                       blocked_call_id=call_id,
                       history_call_id=history.get("call_id"))
            return True  # 拦截不算失败

        # 【关键】预占位：执行工具之前先写入 pending_tool_call，立刻持久化
        state.pending_tool_call = {
            "call_id": call_id,
            "tool_name": tool_name,
            "args": tool_args,
            "start_ts": time.time(),
        }
        self.state_store.save(state)

        self._fire_event("tool_call", {
            "tool_name": tool_name,
            "args": tool_args,
            "call_id": call_id,
        })

        # 加锁执行（单机锁；生产多实例替换 Redis 分布式锁）
        with self._tool_lock:
            try:
                tool_result = tool.run(tool_args)
                success = True
            except Exception as e:  # noqa: BLE001
                tool_result = str(e)
                success = False

        # 更新结构化状态（每一轮执行完成立刻持久化！）
        state.iteration += 1
        state.messages.append({
            "role": "assistant",
            "tool_calls": [{"name": tool_name, "arguments": tool_args}],
        })
        result_text = json.dumps(tool_result, ensure_ascii=False, default=str) \
            if not isinstance(tool_result, str) else tool_result
        state.messages.append({
            "role": "tool", "name": tool_name, "content": result_text,
        })
        state.tool_records.append({
            "call_id": call_id,
            "tool_name": tool_name,
            "args": tool_args,
            "result": result_text,
            "success": success,
            "call_start_ts": state.pending_tool_call["start_ts"],
            "call_end_ts": time.time(),
        })
        state.pending_tool_call = None

        self._fire_event("tool_result", {
            "tool_name": tool_name,
            "call_id": call_id,
            "success": success,
            "result": result_text[:500] if result_text else "",
        })

        if not success:
            state.biz_context["last_tool_error"] = result_text
            # 可选增强分支：失败自省（不影响主流程）
            try:
                self._reflect_on_failure(state, tool_name, tool_args, result_text)
            except Exception as e:  # noqa: BLE001
                logger.warning("自省分支执行失败（不影响主流程）: %s", e)

        # 立刻落地存储，保证崩溃不丢失本轮进度
        self.state_store.save(state)
        logger.info("任务 %s 第 %d 轮工具 %s 执行完成 success=%s",
                    task_id, state.iteration, tool_name, success)
        # Trace：工具调用 span（耗时由预占位时间戳精确计算）
        call_duration = (state.tool_records[-1]["call_end_ts"]
                         - state.tool_records[-1]["call_start_ts"]) * 1000
        self._emit(task_id, "tool_call", status="ok" if success else "error",
                   duration_ms=call_duration, tool_name=tool_name,
                   call_id=call_id, iteration=state.iteration,
                   risk_level=getattr(tool, "risk_level", "unknown"))
        return success

    def _reflect_on_failure(self, state: AgentState, tool_name: str,
                            tool_args: Dict[str, Any], error: str) -> None:
        """失败自省（可选增强分支）：让 LLM 分析失败原因并给出调整建议

        提示词模板位于 src/prompt/user/harness_reflect_on_failure.j2
        """
        history_brief = [
            {"tool": r["tool_name"], "success": r["success"]}
            for r in state.tool_records[-5:]
        ]
        prompt = render_user(
            "harness_reflect_on_failure",
            history_json=json.dumps(history_brief, ensure_ascii=False),
            tool_name=tool_name,
            error=error,
            args_json=json.dumps(tool_args, ensure_ascii=False),
        )
        response = self.llm.invoke(prompt)
        suggestion = getattr(response, "content", str(response))
        state.biz_context["reflect_suggest"] = suggestion
        state.messages.append({
            "role": "user",
            "content": f"[系统自省] 上次工具失败，分析建议：{suggestion}",
        })
        logger.info("失败自省完成: %s -> %s", tool_name, suggestion[:100])
