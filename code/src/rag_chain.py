"""
RAG 问答链模块
基于 LangChain 和 Ollama 实现检索增强生成（RAG）问答功能
"""

import logging
from typing import Any

from langchain_ollama import ChatOllama
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# 默认提示词模板
DEFAULT_PROMPT_TEMPLATE = """你是一个知识库问答助手。请基于以下上下文回答用户的问题。
如果上下文中没有相关信息，请明确告知用户无法从知识库中找到答案。

上下文：
{context}

问题：{question}

请用中文回答："""


class RAGChain:
    """
    RAG 问答链类，集成 Ollama 模型和知识库检索器，
    提供基于文档检索的问答功能。
    """

    def __init__(
        self,
        knowledge_base: Any,
        model_name: str = "qwen3:4b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        prompt_template: str = DEFAULT_PROMPT_TEMPLATE,
    ):
        """
        初始化 RAG 问答链

        Args:
            knowledge_base: KnowledgeBase 实例，提供 get_retriever() 方法
            model_name: Ollama 模型名称，默认为 qwen3:4b
            base_url: Ollama 服务地址，默认为 http://localhost:11434
            temperature: 模型温度参数，控制生成随机性
            prompt_template: 自定义提示词模板，需包含 {context} 和 {question} 占位符
        """
        self.knowledge_base = knowledge_base
        self.model_name = model_name
        self.base_url = base_url

        # 初始化 LLM
        self.llm = ChatOllama(
            model=self.model_name,
            base_url=self.base_url,
            temperature=temperature,
        )

        # 初始化提示词模板
        self.prompt = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"],
        )

        # 构建 RAG 链
        self._chain = self._build_chain()

        logger.info("RAG 问答链初始化完成，模型: %s", self.model_name)

    def _build_chain(self):
        """
        构建完整的 RAG 链（检索 → 生成）

        Returns:
            可执行的 LangChain 链对象
        """
        # 获取检索器
        retriever = self.knowledge_base.get_retriever()

        # 文档格式化函数：将检索到的文档列表格式化为上下文文本
        def format_docs(docs: list[Document]) -> str:
            return "\n\n".join(doc.page_content for doc in docs)

        # 构建 RAG 链
        chain = (
            {
                "context": retriever | format_docs,
                "question": RunnablePassthrough(),
            }
            | self.prompt
            | self.llm
            | StrOutputParser()
        )

        return chain

    def _is_knowledge_base_empty(self) -> bool:
        """
        检查知识库是否为空

        Returns:
            True 表示知识库为空，False 表示有文档
        """
        try:
            documents = self.knowledge_base.list_documents()
            return len(documents) == 0
        except Exception as e:
            logger.warning("检查知识库状态时出错: %s", str(e))
            # 如果无法确定，假设不为空，让检索器自行处理
            return False

    def ask(self, question: str) -> dict:
        """
        执行 RAG 问答

        Args:
            question: 用户问题

        Returns:
            包含答案和来源文档的字典
            {
                "answer": "...",
                "sources": [{"file_name": "...", "content": "..."}]
            }
        """
        # 参数校验
        if not question or not question.strip():
            return {
                "answer": "请输入有效的问题。",
                "sources": [],
            }

        # 检查知识库是否为空
        if self._is_knowledge_base_empty():
            return {
                "answer": "知识库中还没有文档，请先上传文档后再进行问答。",
                "sources": [],
            }

        try:
            # 获取检索到的文档（用于返回来源信息）
            retriever = self.knowledge_base.get_retriever()
            source_docs = retriever.invoke(question)

            # 执行 RAG 链生成答案
            answer = self._chain.invoke(question)

            # 整理来源文档信息
            sources = []
            for doc in source_docs:
                source_info = {
                    "file_name": doc.metadata.get("file_name", "未知文档"),
                    "content": doc.page_content,
                }
                # 避免重复添加相同文档
                if source_info not in sources:
                    sources.append(source_info)

            logger.info("问答完成，问题: %s, 检索到 %d 个来源", question, len(sources))

            return {
                "answer": answer,
                "sources": sources,
            }

        except Exception as e:
            logger.error("问答过程中发生错误: %s", str(e))
            return {
                "answer": f"抱歉，处理问题时发生错误: {str(e)}",
                "sources": [],
            }
