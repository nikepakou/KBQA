"""数据分析模块

基于 LangChain 与 Ollama 实现自然语言转 SQL（NL2SQL）与数据可视化推荐，
集成 DBManager 完成端到端的数据分析流程：自然语言问题 → SQL → 查询 → 图表推荐。
"""

import json
import re
import logging
from typing import Optional

import sqlparse
from langchain_ollama import ChatOllama
from db_manager import DBManager
from config import OLLAMA_BASE_URL, LLM_MODEL_NAME, MAX_QUERY_ROWS


class DataAnalyzer:
    """数据分析器，提供自然语言转 SQL、查询执行与图表推荐能力。"""

    def __init__(self, db_manager: DBManager, llm_model: str = LLM_MODEL_NAME, base_url: str = OLLAMA_BASE_URL):
        """初始化数据分析器。

        Args:
            db_manager: 数据库管理器实例，提供 schema 获取与查询执行能力
            llm_model: Ollama 模型名称，默认使用配置中的 LLM_MODEL_NAME
            base_url: Ollama 服务地址，默认使用配置中的 OLLAMA_BASE_URL
        """
        self.db_manager = db_manager
        self.llm = ChatOllama(
            model=llm_model,
            base_url=base_url,
            temperature=0.1,
        )
        self._schema_text = None
        logger.info("DataAnalyzer 初始化完成，模型: %s，地址: %s", llm_model, base_url)

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

    def _build_nl2sql_prompt(self, question: str) -> str:
        """构建自然语言转 SQL 的提示词。

        Args:
            question: 用户的自然语言问题

        Returns:
            完整的提示词字符串
        """
        schema_text = self._get_schema_text()

        prompt = f"""你是一个 MySQL SQL 专家。请根据以下数据库表结构，将用户的自然语言问题转换为 SQL 查询语句。

规则：
1. 只生成 SELECT 查询语句，禁止 INSERT/UPDATE/DELETE/DROP 等写操作
2. 只返回纯 SQL 语句，不要加任何解释说明
3. 不要使用 markdown 代码块标记
4. 表名和字段名使用反引号包裹
5. 如果问题不明确，返回最合理的查询

数据库表结构：
{schema_text}
用户问题：{question}

SQL："""
        return prompt

    def _strip_markdown_code_blocks(self, text: str) -> str:
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

    def generate_sql(self, question: str) -> str:
        """根据自然语言问题生成 SQL 查询语句。

        Args:
            question: 用户的自然语言问题

        Returns:
            纯 SQL 语句字符串

        Raises:
            Exception: 生成过程中发生任何错误时抛出
        """
        try:
            self._get_schema_text()
            prompt = self._build_nl2sql_prompt(question)
            response = self.llm.invoke(prompt)
            # ChatOllama 返回 AIMessage，通过 .content 获取文本内容
            content = response.content
            sql = self._strip_markdown_code_blocks(content)
            # 处理 LLM 可能在 SQL 前后附加说明文字的情况
            sql = self._extract_sql_from_text(sql)
            logger.info("生成 SQL 成功: %s", sql)
            return sql
        except Exception as e:
            logger.error("生成 SQL 失败: %s", e)
            raise

    @staticmethod
    def _extract_sql_from_text(text: str) -> str:
        """从 LLM 输出中提取纯 SQL，处理可能夹杂的说明文字。

        尝试匹配以 SELECT/WITH 开头到分号结束的 SQL 语句；
        若未匹配成功则返回原文去引号去空白后的结果。
        """
        if not text:
            return ""
        # 去除首尾空白与多余引号
        text = text.strip().strip('"').strip("'")
        # 尝试提取 SELECT/WITH 开头的 SQL 语句（到分号或文本结尾）
        match = re.search(r"((?:SELECT|WITH)\b.*?)(?:;|\Z)", text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return text

    def _validate_sql(self, sql: str) -> bool:
        """校验 SQL 是否为只读 SELECT 查询且不包含危险关键字。

        Args:
            sql: 待校验的 SQL 语句

        Returns:
            全部校验通过返回 True，否则返回 False
        """
        try:
            parsed = sqlparse.parse(sql)
            if not parsed:
                return False

            # 危险关键字（按整词匹配，不区分大小写）
            dangerous_pattern = re.compile(
                r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
                re.IGNORECASE,
            )

            for stmt in parsed:
                stmt_type = stmt.get_type()
                # 校验语句类型必须为 SELECT 或 None（WITH 等子查询解析可能返回 None）
                if stmt_type is not None and stmt_type != "SELECT":
                    return False
                # 校验不包含危险关键字
                if dangerous_pattern.search(stmt.value):
                    return False
            return True
        except Exception as e:
            logger.error("SQL 校验失败: %s", e)
            return False

    def _build_chart_prompt(self, question: str, sql: str, columns: list, rows: list) -> str:
        """构建图表推荐的提示词。

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

        prompt = f"""你是一个数据可视化专家。请根据以下信息推荐最合适的 ECharts 图表并生成完整配置。

规则：
1. 根据数据特征选择图表类型：
   - 类别 + 数值 → 柱状图 (bar)
   - 时间 + 数值 → 折线图 (line)
   - 占比/比例 → 饼图 (pie)
   - 不适合可视化 → chart_type 设为 "none"
2. 返回严格的 JSON 格式，不要加 markdown 标记
3. option 必须是完整的 ECharts 配置

用户问题：{question}
执行的 SQL：{sql}
查询结果列名：{columns_json}
查询结果数据（前5行）：{sample_rows_json}

请返回如下 JSON 格式：
{{"chart_type": "bar", "option": {{"title": {{"text": "..."}}, ...}}}}"""
        return prompt

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
        """执行完整的数据分析流程：生成 SQL → 校验 → 查询 → 图表推荐。

        Args:
            question: 用户的自然语言问题

        Returns:
            包含问题、SQL、数据与图表配置的字典；出错时返回包含 error 的字典
        """
        sql = ""
        try:
            sql = self.generate_sql(question)

            # 校验 SQL，仅允许只读 SELECT 查询
            if not self._validate_sql(sql):
                logger.warning("SQL 校验未通过，拒绝执行: %s", sql)
                return {"error": "仅支持查询操作，请重新描述问题", "sql": sql}

            query_result = self.db_manager.execute_query(sql)
            chart = self.recommend_chart(question, sql, query_result)

            logger.info("数据分析完成，问题: %s", question)
            return {
                "question": question,
                "sql": sql,
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
