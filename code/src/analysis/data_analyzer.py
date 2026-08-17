"""数据分析模块

基于 LangChain 与 Ollama 实现自然语言转 SQL（NL2SQL）与数据可视化推荐，
集成 DBManager 完成端到端的数据分析流程：自然语言问题 → 结构化查询计划 → 安全 SQL → 查询 → 图表推荐。
"""

import json
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel, Field

from database.db_manager import DBManager
from config import MAX_QUERY_ROWS
from llm_factory import LLMFactory
from prompt.loader import render_system, render_fewshot

logger = logging.getLogger(__name__)

# --- 结构化查询计划定义 ---

class QueryField(BaseModel):
    """查询字段定义"""
    name: str                          # 字段名
    alias: Optional[str] = None        # 字段别名 (AS xxx)
    function: Optional[str] = None     # 聚合函数: COUNT, SUM, AVG, MIN, MAX

class QueryFilter(BaseModel):
    """WHERE 过滤条件"""
    field: str                         # 字段名
    operator: str                      # 操作符: =, !=, >, <, >=, <=, LIKE, IN, BETWEEN
    value: Any = None                  # 过滤值

class QueryOrderBy(BaseModel):
    """排序条件"""
    field: str                         # 字段名
    direction: str = "ASC"             # ASC 或 DESC

class QueryPlan(BaseModel):
    """结构化查询计划"""
    table: str                         # 主表名
    fields: List[QueryField]           # 查询字段列表
    filters: List[QueryFilter] = Field(default_factory=list)   # WHERE 条件列表
    group_by: List[str] = Field(default_factory=list)          # GROUP BY 字段列表
    order_by: List[QueryOrderBy] = Field(default_factory=list) # ORDER BY 列表
    limit: Optional[int] = None        # LIMIT 数量

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()

# --- 允许的操作符和聚合函数 ---
ALLOWED_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "LIKE", "IN", "BETWEEN", "NOT IN", "NOT LIKE"}
ALLOWED_FUNCTIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class DataAnalyzer:
    """数据分析器，提供自然语言转 SQL、查询执行与图表推荐能力。"""

    def __init__(self, db_manager: DBManager, llm_model: Optional[str] = None, base_url: Optional[str] = None, provider: Optional[str] = None):
        """初始化数据分析器。

        Args:
            db_manager: 数据库管理器实例，提供 schema 获取与查询执行能力
            llm_model: 模型名称，为 None 时使用配置中的默认值
            base_url: 模型服务地址（保留用于向后兼容，实际使用 LLMFactory 中的配置）
            provider: 模型提供商，为 None 时使用配置中的默认值
        """
        self.db_manager = db_manager
        self.llm = LLMFactory.create_llm(
            model_name=llm_model,
            temperature=0.1,
            provider=provider,
        )
        self._schema_text = None
        logger.info("DataAnalyzer 初始化完成，提供商: %s", provider or LLMFactory.get_current_provider())

    def _get_schema_text(self) -> str:
        """获取格式化的数据库表结构文本，带缓存。

        Returns:
            格式化的表结构描述字符串
        """
        if self._schema_text is not None:
            return self._schema_text

        schema = self.db_manager.get_schema()
        lines = []
        for table_name, columns in schema.items():
            lines.append(f"表名：{table_name}")
            lines.append("字段：")
            for col in columns:
                lines.append(f"  - {col['column']} ({col['type']}) - {col['comment']}")
            lines.append("")

        self._schema_text = "\n".join(lines)
        logger.info("已格式化数据库结构文本，共 %d 张表", len(schema))
        return self._schema_text

    @staticmethod
    def _strip_markdown_code_blocks(text: str) -> str:
        """去除 markdown 代码块标记，返回纯文本内容。

        支持 ```sql ... ```、```json ... ```、``` ... ``` 等格式。
        若未匹配到代码块，则返回去除首尾空白后的原文。
        """
        if not text:
            return ""
        match = re.search(r"```[a-zA-Z]*\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _build_query_plan_prompt(self, question: str) -> str:
        """构建结构化查询计划生成的提示词。

        要求 LLM 根据数据库表结构和用户问题，输出结构化的 JSON 查询计划，
        而不是直接生成 SQL 语句。代码侧负责校验和安全拼接。

        提示词由三部分组成（Jinja2 模板分离）：
        - system/data_analyzer_query_plan.j2：角色定义 + 规则 + 输出格式
        - fewshot/query_plan_example.j2：查询计划 JSON 示例
        - 运行时变量：schema_text、question

        Args:
            question: 用户的自然语言问题

        Returns:
            完整的提示词字符串
        """
        schema_text = self._get_schema_text()
        # few-shot 示例从模板加载（src/prompt/fewshot/query_plan_example.j2）
        plan_example = render_fewshot("query_plan_example")

        return render_system(
            "data_analyzer_query_plan",
            schema_text=schema_text,
            question=question,
            plan_example=plan_example,
        )

    def generate_query_plan(self, question: str) -> QueryPlan:
        """根据自然语言问题生成结构化查询计划。

        Args:
            question: 用户的自然语言问题

        Returns:
            QueryPlan 对象

        Raises:
            ValueError: LLM 输出无法解析为合法 JSON 或不符合 QueryPlan 结构
            Exception: 生成过程中发生其他错误
        """
        try:
            self._get_schema_text()
            prompt = self._build_query_plan_prompt(question)
            response = self.llm.invoke(prompt)
            content = self._strip_markdown_code_blocks(response.content)
            plan_dict = self._parse_json_from_text(content)

            if plan_dict is None:
                logger.error("LLM 输出无法解析为 JSON: %s", content[:200])
                raise ValueError("查询计划解析失败，模型输出不合法")

            logger.info("LLM 生成查询计划: %s", json.dumps(plan_dict, ensure_ascii=False))

            # 使用 Pydantic 校验并构造 QueryPlan
            plan = QueryPlan.model_validate(plan_dict)
            return plan

        except ValueError as e:
            logger.error("生成查询计划失败: %s", e)
            raise
        except Exception as e:
            logger.error("生成查询计划异常: %s", e)
            raise

    def _validate_query_plan(self, plan: QueryPlan) -> Tuple[bool, str]:
        """校验查询计划的合法性：表名/字段名白名单、操作符/聚合函数合法性。

        Args:
            plan: 待校验的结构化查询计划

        Returns:
            (是否通过, 失败原因) 元组
        """
        schema = self.db_manager.get_schema()
        if not schema:
            return False, "数据库表结构为空，无法校验查询计划"

        # 构建白名单
        allowed_tables = set(schema.keys())
        if plan.table not in allowed_tables:
            return False, f"表 '{plan.table}' 不在允许列表中，允许的表: {list(allowed_tables)}"

        allowed_columns = {col["column"] for col in schema[plan.table]}

        # 校验查询字段
        for field in plan.fields:
            if field.name not in allowed_columns:
                return False, f"字段 '{field.name}' 不在表 '{plan.table}' 中"
            if field.function is not None and field.function.upper() not in ALLOWED_FUNCTIONS:
                return False, f"聚合函数 '{field.function}' 不允许，允许的函数: {ALLOWED_FUNCTIONS}"

        # 校验 WHERE 条件
        for flt in plan.filters:
            if flt.field not in allowed_columns:
                return False, f"过滤字段 '{flt.field}' 不在表 '{plan.table}' 中"
            if flt.operator.upper() not in ALLOWED_OPERATORS:
                return False, f"操作符 '{flt.operator}' 不允许，允许的操作符: {ALLOWED_OPERATORS}"

        # 校验 GROUP BY
        for gb in plan.group_by:
            if gb not in allowed_columns:
                return False, f"GROUP BY 字段 '{gb}' 不在表 '{plan.table}' 中"

        # 校验 ORDER BY
        for ob in plan.order_by:
            if ob.field not in allowed_columns:
                return False, f"ORDER BY 字段 '{ob.field}' 不在表 '{plan.table}' 中"
            if ob.direction.upper() not in ("ASC", "DESC"):
                return False, f"排序方向 '{ob.direction}' 不允许"

        logger.debug("查询计划校验通过")
        return True, ""

    def _plan_to_sql(self, plan: QueryPlan) -> Tuple[str, tuple]:
        """将结构化查询计划安全拼接为 SQL 语句和参数元组。

        使用参数化查询：WHERE 条件的值通过占位符 %s 绑定，防止 SQL 注入。
        表名、字段名、聚合函数、操作符等从白名单中取，确保安全。

        Args:
            plan: 已通过校验的结构化查询计划

        Returns:
            (sql_string, params_tuple) 元组
        """
        # --- 构建 SELECT 子句 ---
        select_parts = []
        for field in plan.fields:
            if field.function:
                # 聚合函数 + 括号包裹字段
                expr = f"{field.function.upper()}(`{field.name}`)"
            else:
                expr = f"`{field.name}`"

            if field.alias:
                expr += f" AS `{field.alias}`"
            select_parts.append(expr)

        select_clause = ", ".join(select_parts)

        # --- 构建 FROM 子句 ---
        from_clause = f"`{plan.table}`"

        # --- 构建 WHERE 子句（参数化） ---
        where_parts = []
        params = []
        for flt in plan.filters:
            operator = flt.operator.upper()
            field_ref = f"`{flt.field}`"

            if operator == "IN" or operator == "NOT IN":
                # IN / NOT IN 子句：需要 (?, ?, ...) 形式
                if isinstance(flt.value, (list, tuple)):
                    # 空列表跳过该条件，避免生成无效 SQL (IN ())
                    if len(flt.value) == 0:
                        logger.warning("跳过空的 %s 过滤条件: %s", operator, flt.field)
                        continue
                    placeholders = ", ".join(["%s"] * len(flt.value))
                    where_parts.append(f"{field_ref} {operator} ({placeholders})")
                    params.extend(flt.value)
                else:
                    # 单值情况仍用 IN
                    where_parts.append(f"{field_ref} {operator} (%s)")
                    params.append(flt.value)

            elif operator == "BETWEEN":
                # BETWEEN ... AND ...
                if isinstance(flt.value, (list, tuple)) and len(flt.value) == 2:
                    where_parts.append(f"{field_ref} BETWEEN %s AND %s")
                    params.extend(flt.value)
                else:
                    where_parts.append(f"{field_ref} BETWEEN %s AND %s")
                    # 如果不是列表，将值拆分为两个相同的占位（兜底处理）
                    val = flt.value
                    params.extend([val, val])

            else:
                # 标准操作符: =, !=, >, <, >=, <=, LIKE, NOT LIKE
                where_parts.append(f"{field_ref} {operator} %s")
                params.append(flt.value)

        where_clause = ""
        if where_parts:
            where_clause = " WHERE " + " AND ".join(where_parts)

        # --- 构建 GROUP BY 子句 ---
        group_by_clause = ""
        if plan.group_by:
            group_fields = ", ".join(f"`{f}`" for f in plan.group_by)
            group_by_clause = f" GROUP BY {group_fields}"

        # --- 构建 ORDER BY 子句 ---
        order_by_clause = ""
        if plan.order_by:
            order_parts = []
            for ob in plan.order_by:
                direction = ob.direction.upper() if ob.direction else "ASC"
                order_parts.append(f"`{ob.field}` {direction}")
            order_by_clause = " ORDER BY " + ", ".join(order_parts)

        # --- 构建 LIMIT 子句 ---
        limit_clause = ""
        if plan.limit is not None and plan.limit > 0:
            limit_clause = f" LIMIT {int(plan.limit)}"

        # --- 组装完整 SQL ---
        sql = f"SELECT {select_clause} FROM {from_clause}{where_clause}{group_by_clause}{order_by_clause}{limit_clause}"

        logger.info("拼接 SQL: %s, params: %s", sql, params)
        return sql, tuple(params)

    def generate_sql(self, question: str) -> Tuple[str, tuple]:
        """根据自然语言问题生成安全的 SQL 查询语句与参数。

        内部流程：LLM 生成结构化查询计划 → 白名单校验 → 参数化安全拼接。

        Args:
            question: 用户的自然语言问题

        Returns:
            (sql_string, params_tuple) 元组，可直接传递给 execute_query

        Raises:
            ValueError: 查询计划校验失败
            Exception: 生成过程中发生任何错误时抛出
        """
        try:
            plan = self.generate_query_plan(question)

            # 校验查询计划
            valid, reason = self._validate_query_plan(plan)
            if not valid:
                logger.warning("查询计划校验失败: %s", reason)
                raise ValueError(f"查询计划校验失败: {reason}")

            # 安全拼接 SQL
            sql, params = self._plan_to_sql(plan)
            logger.info("生成 SQL 成功: %s, params: %s", sql, params)
            return sql, params
        except Exception as e:
            logger.error("生成 SQL 失败: %s", e)
            raise

    def _build_chart_prompt(self, question: str, sql: str, columns: list, rows: list) -> str:
        """构建图表推荐的提示词。

        提示词模板位于 src/prompt/system/data_analyzer_chart.j2，
        运行时注入：question、sql、columns_json、sample_rows_json。

        Args:
            question: 用户的自然语言问题
            sql: 实际执行的 SQL 语句
            columns: 查询结果列名列表
            rows: 查询结果行列表（取前 5 行作为样本）

        Returns:
            完整的图表推荐提示词字符串
        """
        sample_rows = rows[:5]
        columns_json = json.dumps(columns, ensure_ascii=False)
        # default=str 兼容 datetime、Decimal 等不可序列化类型
        sample_rows_json = json.dumps(sample_rows, ensure_ascii=False, default=str)

        return render_system(
            "data_analyzer_chart",
            question=question,
            sql=sql,
            columns_json=columns_json,
            sample_rows_json=sample_rows_json,
        )

    def recommend_chart(self, question: str, sql: str, query_result: dict) -> dict:
        """根据查询结果推荐 ECharts 图表配置。

        Args:
            question: 用户的自然语言问题
            sql: 实际执行的 SQL 语句
            query_result: 查询结果 {"columns": [...], "rows": [...]}

        Returns:
            {"chart_type": "...", "option": {...}}，解析失败返回默认空配置
        """
        columns = query_result.get("columns", [])
        rows = query_result.get("rows", [])

        # 无数据时不推荐图表
        if not rows:
            logger.info("查询结果为空，跳过图表推荐")
            return {"chart_type": "none", "option": {}}

        try:
            prompt = self._build_chart_prompt(question, sql, columns, rows)
            response = self.llm.invoke(prompt)
            content = self._strip_markdown_code_blocks(response.content)
            result = self._parse_json_from_text(content)

            if result is None:
                logger.warning("图表推荐 JSON 解析失败，返回默认配置")
                return {"chart_type": "none", "option": {}}

            chart_type = result.get("chart_type", "none")
            option = result.get("option", {})

            # 校验 chart_type 是否在允许范围内
            allowed_types = {"bar", "line", "pie", "none"}
            if chart_type not in allowed_types:
                logger.warning("图表类型 '%s' 不在允许范围内，回退为 none", chart_type)
                chart_type = "none"
                option = {}

            logger.info("图表推荐完成，类型: %s", chart_type)
            return {"chart_type": chart_type, "option": option}
        except Exception as e:
            logger.error("图表推荐失败: %s", e)
            return {"chart_type": "none", "option": {}}

    @staticmethod
    def _parse_json_from_text(text: str) -> Optional[dict]:
        """从文本中稳健地解析第一个 JSON 对象。

        处理 markdown 代码块、多个 JSON 对象、以及首尾多余文字等场景。
        """
        if not text:
            return None
        text = text.strip()
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试提取第一个 { ... } 块
        brace_start = text.find("{")
        if brace_start == -1:
            return None
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    def analyze(self, question: str) -> dict:
        """执行完整的数据分析流程：生成查询计划 → 校验 → 安全拼接 SQL → 查询 → 图表推荐。

        Args:
            question: 用户的自然语言问题

        Returns:
            包含问题、SQL、数据与图表配置的字典；出错时返回包含 error 的字典
        """
        logger.info("开始数据分析，问题: %s", question)
        sql = ""
        try:
            sql, params = self.generate_sql(question)

            # 结构化查询计划已通过白名单校验，无需再做 SQL 字符串级别的危险关键字检查
            query_result = self.db_manager.execute_query(sql, params)
            chart = self.recommend_chart(question, sql, query_result)

            logger.info("数据分析完成，问题: %s", question)
            return {
                "question": question,
                "sql": sql,
                "params": list(params) if params else [],
                "chart": chart,
                "data": {
                    "columns": query_result.get("columns", []),
                    "rows": query_result.get("rows", [])[:MAX_QUERY_ROWS],
                },
            }
        except ValueError as e:
            logger.error("数据分析过程发生值错误: %s", e)
            return {"error": str(e), "sql": sql}
        except TimeoutError as e:
            logger.error("查询超时: %s", e)
            return {"error": "查询超时，请尝试缩小查询范围", "sql": sql}
        except Exception as e:
            logger.error("数据分析过程发生错误: %s", e)
            return {"error": f"分析失败: {str(e)}", "sql": sql}
