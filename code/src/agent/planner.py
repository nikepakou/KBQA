"""
Agent 任务规划器模块
参考文档《02-任务规划与Harness主分支结合方案》第2节实现。

职责边界（文档明确）：
- Planner 只负责产出 / 修改结构化任务清单（SubTask 列表）
- 循环调度、断点、幂等、护栏全部由 Harness 主循环负责，规划器不控制执行流

防非结构化输出（文档"常见落地优化点"）：
- 强制 JSON 协议提示词 + 稳健解析 + 结构校验 + 兜底单任务计划
- 防过度规划：revise_plan 仅由 Harness 在子任务失败时触发，且带次数上限

提示词模板（Jinja2 分离）：
- system/planner_initial.j2：初始规划系统提示词
- system/planner_revise.j2：动态修正系统提示词
- user/planner_initial_user.j2：初始规划用户消息
- user/planner_revise_user.j2：动态修正用户消息
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from agent.plan import ExecutionPlan, SubTask, new_plan_id, new_subtask_id
from llm_factory import LLMFactory
from prompt.loader import render_system, render_user

logger = logging.getLogger(__name__)


class TaskPlanner:
    """任务规划器：初始规划 + 动态修正（上层模块，不侵入主循环核心）"""

    # 防过度规划：单个任务允许的最大重规划次数
    MAX_REVISE_PER_TASK = 3

    def __init__(self, plan_store, tools: List[Any], provider: Optional[str] = None):
        """
        Args:
            plan_store: PlanStore 实例
            tools: 可用工具列表（用于注入提示词，帮助 LLM 选择 required_tools）
            provider: LLM 提供商（Planner LLM，负责高层目标拆解，可与主循环 LLM 不同）
        """
        self.plan_store = plan_store
        self.tool_names = [t.name for t in tools]
        self.provider = provider
        self.llm = LLMFactory.create_llm(temperature=0.0, provider=provider)

    # ==================== 初始规划 ====================

    def create_initial_plan(self, root_task_id: str, user_goal: str) -> ExecutionPlan:
        """初始规划：调用 LLM 将总目标拆解为 SubTask 清单，立刻持久化。

        LLM 输出非法/解析失败时，兜底为单任务计划（目标本身作为唯一子任务），
        保证任务始终可执行——规划失败不阻塞执行。
        """
        prompt = render_system("planner_initial", tools=", ".join(self.tool_names))
        user_msg = render_user("planner_initial_user", user_goal=user_goal)
        subtasks: Optional[List[SubTask]] = None
        try:
            response = self.llm.invoke([
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_msg},
            ])
            content = getattr(response, "content", str(response))
            subtasks = self._parse_subtasks(content)
        except Exception as e:  # noqa: BLE001
            logger.warning("Planner 初始规划 LLM 调用失败，使用兜底单任务计划: %s", e)

        if not subtasks:
            # 兜底：目标整体作为单个子任务（纯 ReAct 语义）
            subtasks = [SubTask(
                task_id=new_subtask_id(1),
                title="完成用户目标",
                description=user_goal,
                depend_on=[],
                required_tools=[],
            )]
            logger.info("使用兜底单任务计划（规划解析失败或目标过于简单）")
        else:
            logger.info("初始规划完成，共 %d 个子任务", len(subtasks))

        plan = ExecutionPlan(
            plan_id=new_plan_id(),
            root_task_id=root_task_id,
            created_at=time.time(),
            updated_at=time.time(),
            overall_goal=user_goal,
            subtasks=subtasks,
            plan_status="active",
        )
        self.plan_store.save_plan(root_task_id, plan)
        return plan

    # ==================== 动态修正 ====================

    def revise_plan(self, root_task_id: str, state: Any, failure_info: str) -> Optional[ExecutionPlan]:
        """动态规划：执行失败时自省修正计划（增删子任务、调整依赖）。

        返回新版本 Plan（版本号+1，持久化覆盖）；修正失败返回 None，
        由主循环按原计划继续（重规划是增强分支，不是主干）。
        防过度规划：超过 MAX_REVISE_PER_TASK 次不再修正。
        """
        plan = self.plan_store.load_plan(root_task_id)
        if plan is None:
            return None
        revise_count = state.biz_context.get("plan_revise_count", 0) if state else 0
        if revise_count >= self.MAX_REVISE_PER_TASK:
            logger.info("已达最大重规划次数 %d，停止修正", self.MAX_REVISE_PER_TASK)
            return None

        progress = [
            {"title": st.title, "status": st.status, "result": st.result_summary}
            for st in plan.subtasks
        ]
        prompt = render_system("planner_revise", tools=", ".join(self.tool_names))
        user_msg = render_user(
            "planner_revise_user",
            overall_goal=plan.overall_goal,
            progress_json=json.dumps(progress, ensure_ascii=False, default=str),
            failure_info=failure_info,
        )
        try:
            response = self.llm.invoke([
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_msg},
            ])
            content = getattr(response, "content", str(response))
            new_subtasks = self._parse_subtasks(content)
            if not new_subtasks:
                return None

            plan.subtasks = new_subtasks
            plan.plan_version += 1
            plan.updated_at = time.time()
            self.plan_store.save_plan(root_task_id, plan)
            logger.info("计划已动态修正至 v%d，新子任务数 %d", plan.plan_version, len(new_subtasks))
            return plan
        except Exception as e:  # noqa: BLE001
            logger.warning("动态重规划失败（沿用原计划继续）: %s", e)
            return None

    # ==================== 解析与校验 ====================

    def _parse_subtasks(self, text: str) -> Optional[List[SubTask]]:
        """从 LLM 输出稳健解析子任务清单，强制结构合法。

        处理：markdown 代码块、多余文字、字段缺失/类型错误、
        depend_on 序号引用（转为已生成的 task_id）。
        解析结果为空或全部非法时返回 None。
        """
        data = self._parse_json_object(text)
        if data is None:
            return None
        raw_list = data.get("subtasks") if isinstance(data, dict) else data
        if not isinstance(raw_list, list) or not raw_list:
            return None

        subtasks: List[SubTask] = []
        for idx, item in enumerate(raw_list, start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            if not title:
                continue
            depend_idx = item.get("depend_on") or []
            if not isinstance(depend_idx, list):
                depend_idx = []
            # 序号引用 → task_id 引用（仅允许引用已生成的前置任务，防循环依赖）
            depend_ids = []
            for d in depend_idx:
                try:
                    seq = int(str(d).replace("st_", ""))
                    if 1 <= seq < idx:
                        depend_ids.append(new_subtask_id(seq))
                except (ValueError, TypeError):
                    continue
            tools = item.get("required_tools") or []
            if not isinstance(tools, list):
                tools = []
            subtasks.append(SubTask(
                task_id=new_subtask_id(idx),
                title=title,
                description=str(item.get("description") or "").strip(),
                status="pending",
                depend_on=depend_ids,
                required_tools=[str(t) for t in tools if t in self.tool_names],
            ))
        return subtasks if subtasks else None

    @staticmethod
    def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
        """提取并解析第一个 JSON 对象（容忍代码块与前后杂文）"""
        if not text:
            return None
        text = text.strip()
        # 去除 markdown 代码块
        if "```" in text:
            start = text.find("```")
            nl = text.find("\n", start)
            end = text.rfind("```")
            if nl != -1 and end > nl:
                text = text[nl + 1:end].strip()
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, (dict, list)) else None
        except json.JSONDecodeError:
            pass
        # 提取第一个 { ... } 块
        brace = text.find("{")
        if brace == -1:
            return None
        depth = 0
        for i in range(brace, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[brace:i + 1])
                        return parsed if isinstance(parsed, (dict, list)) else None
                    except json.JSONDecodeError:
                        return None
        return None
