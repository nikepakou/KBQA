"""
Agent 工具模块
将 KBQA 现有能力封装为 Harness 可调度的工具，遵循文档的风险分层幂等策略：

- 只读工具（kb_search / sql_query / db_schema）：无需严格幂等，重复调用无害
- 高危写工具（add_document）：工具侧天然幂等优先——以 file_name 为唯一标识，
  重复入库直接返回已有 doc_id，无副作用
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseTool:
    """工具抽象基类：Harness 通过 name 调度，通过 description 注入 LLM 提示词"""

    name: str = ""
    description: str = ""
    # 风险等级：readonly（只读，可安全重试）/ write（写操作，幂等保护）
    risk_level: str = "readonly"

    def run(self, args: Dict[str, Any]) -> Any:
        raise NotImplementedError

    def spec(self) -> Dict[str, str]:
        """返回注入 LLM 决策提示词的工具说明"""
        return {"name": self.name, "description": self.description}


class KBSearchTool(BaseTool):
    """知识库检索工具（只读）：基于 Milvus 向量检索"""

    name = "kb_search"
    risk_level = "readonly"
    description = (
        "在知识库中进行语义检索。参数: {\"query\": \"检索的问题或关键词\", \"top_k\": 3(可选)}。"
        "返回最相关的文档片段列表（含文件名与内容）。适合回答文档/资料类问题。"
    )

    def __init__(self, knowledge_base: Any, default_top_k: int = 3):
        self.knowledge_base = knowledge_base
        self.default_top_k = default_top_k

    def run(self, args: Dict[str, Any]) -> Any:
        query = args.get("query")
        if not query or not str(query).strip():
            raise ValueError("kb_search 缺少必填参数 query")
        top_k = int(args.get("top_k") or self.default_top_k)

        retriever = self.knowledge_base.get_retriever(search_kwargs={"k": top_k})
        docs = retriever.invoke(str(query).strip())

        results = []
        for doc in docs:
            results.append({
                "file_name": doc.metadata.get("file_name", "未知文档"),
                "content": doc.page_content,
            })
        return results


class SQLQueryTool(BaseTool):
    """NL2SQL 数据查询工具（只读）：自然语言 → SQL → 校验 → 执行"""

    name = "sql_query"
    risk_level = "readonly"
    description = (
        "对业务数据库执行自然语言查询（自动生成 SQL，仅限只读 SELECT）。"
        "参数: {\"question\": \"自然语言查询问题，如：统计每个部门的员工数量\"}。"
        "返回查询结果列名与数据行。适合数据统计/分析类问题。"
    )

    def __init__(self, data_analyzer: Any):
        self.data_analyzer = data_analyzer

    def run(self, args: Dict[str, Any]) -> Any:
        question = args.get("question")
        if not question or not str(question).strip():
            raise ValueError("sql_query 缺少必填参数 question")

        analyzer = self.data_analyzer
        sql = analyzer.generate_sql(str(question).strip())
        # 只读校验：仅允许 SELECT（拒绝 INSERT/UPDATE/DELETE/DROP 等）
        if not analyzer._validate_sql(sql):
            raise ValueError(f"生成的 SQL 未通过只读校验，拒绝执行: {sql}")
        query_result = analyzer.db_manager.execute_query(sql)
        return {
            "sql": sql,
            "columns": query_result.get("columns", []),
            "rows": query_result.get("rows", [])[:20],  # 控制注入 LLM 的上下文长度
        }


class AddDocumentTool(BaseTool):
    """文档入库工具（高危写操作）：将 uploads 目录中已上传的文件加入知识库。

    幂等设计（工具侧天然幂等）：
    - 以 file_name 为唯一业务标识，若同名文档已入库则直接返回已有 doc_id，
      重复调用无副作用，配合 Harness 层预占位 + call_id 实现双重幂等保护
    """

    name = "add_document"
    risk_level = "write"
    description = (
        "将 data/uploads 目录下已上传的文件添加到知识库（解析+分块+向量化入库）。"
        "参数: {\"file_name\": \"上传目录中的文件名，如 report.pdf\"}。"
        "返回入库结果。注意：同名文件重复入库无副作用（幂等）。"
    )

    def __init__(self, knowledge_base: Any, uploads_dir: str):
        self.knowledge_base = knowledge_base
        self.uploads_dir = uploads_dir

    def check_executed(self, args: Dict[str, Any]) -> bool:
        """幂等恢复检查（Harness 策略A）：崩溃恢复时确认该写操作是否已生效。

        由 AgentHarness.resume_task 调用：若同名文档已入库，视为上次调用已生效，
        补全记录并跳过重复执行，绝不盲目重试。
        """
        file_name = args.get("file_name")
        if not file_name:
            return False
        existing = {
            d.get("file_name") for d in self.knowledge_base.list_documents()
        }
        return file_name in existing

    def run(self, args: Dict[str, Any]) -> Any:
        existing = {
            d.get("file_name") for d in self.knowledge_base.list_documents()
        }
        if file_name in existing:
            return {
                "skipped": True,
                "message": f"文档 {file_name} 已存在于知识库，跳过重复入库（幂等保护）",
            }

        file_path = os.path.join(self.uploads_dir, file_name)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在于上传目录: {file_path}")

        doc_id = self.knowledge_base.add_document(
            file_path=file_path, file_name=file_name
        )
        return {"skipped": False, "doc_id": doc_id, "file_name": file_name}


def build_default_tools(knowledge_base: Any, data_analyzer: Any,
                        uploads_dir: str) -> List[BaseTool]:
    """构建默认工具集。data_analyzer 为 None 时跳过 SQL 工具（数据库未就绪）。"""
    tools: List[BaseTool] = [KBSearchTool(knowledge_base)]
    if data_analyzer is not None:
        tools.append(SQLQueryTool(data_analyzer))
    tools.append(AddDocumentTool(knowledge_base, uploads_dir))
    return tools
