"""
LLM 工厂模块

支持多模型提供商切换：Ollama（本地）和 美团 LongCat-2.0（云端 API）。
通过 MODEL_PROVIDER 环境变量控制使用的模型提供商。
"""

import logging
from typing import Optional

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from config import (
    LLM_PROVIDER,
    EMBEDDING_PROVIDER,
    OLLAMA_BASE_URL,
    LLM_MODEL_NAME,
    EMBEDDING_MODEL_NAME,
    LONGCAT_BASE_URL,
    LONGCAT_API_KEY,
    LONGCAT_LLM_MODEL,
    LONGCAT_EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)


class LLMFactory:
    """
    LLM 工厂类，根据配置创建对应的 LLM 或 Embedding 实例。

    支持的提供商：
    - ollama: 使用本地 Ollama 服务
    - longcat: 使用美团 LongCat-2.0 API（OpenAI 兼容格式）
    """

    @staticmethod
    def create_llm(
        model_name: Optional[str] = None,
        temperature: float = 0.1,
        provider: Optional[str] = None,
    ):
        """
        创建 LLM（大语言模型）实例。

        Args:
            model_name: 模型名称，为 None 时使用配置中的默认值
            temperature: 温度参数，控制生成随机性
            provider: 模型提供商，为 None 时使用配置中的默认值

        Returns:
            ChatOllama 或 ChatOpenAI 实例

        Raises:
            ValueError: 不支持的模型提供商
            RuntimeError: 创建实例失败
        """
        provider = provider or LLM_PROVIDER

        if provider == "ollama":
            return LLMFactory._create_ollama_llm(model_name, temperature)
        elif provider == "longcat":
            return LLMFactory._create_longcat_llm(model_name, temperature)
        else:
            raise ValueError(f"不支持的 LLM 提供商: {provider}，可选值: ollama, longcat")

    @staticmethod
    def create_embedding(
        model_name: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        """
        创建 Embedding（嵌入模型）实例。

        Args:
            model_name: 模型名称，为 None 时使用配置中的默认值
            provider: 模型提供商，为 None 时使用配置中的默认值。
                     注意：如果不指定，使用 EMBEDDING_PROVIDER（可与 LLM 提供商不同）

        Returns:
            OllamaEmbeddings 或 OpenAIEmbeddings 实例

        Raises:
            ValueError: 不支持的模型提供商
            RuntimeError: 创建实例失败
        """
        provider = provider or EMBEDDING_PROVIDER

        if provider == "ollama":
            return LLMFactory._create_ollama_embedding(model_name)
        elif provider == "longcat":
            return LLMFactory._create_longcat_embedding(model_name)
        else:
            raise ValueError(f"不支持的 Embedding 提供商: {provider}，可选值: ollama, longcat")

    @staticmethod
    def _create_ollama_llm(model_name: Optional[str], temperature: float) -> ChatOllama:
        """创建 Ollama LLM 实例"""
        model = model_name or LLM_MODEL_NAME
        try:
            llm = ChatOllama(
                model=model,
                base_url=OLLAMA_BASE_URL,
                temperature=temperature,
            )
            logger.info("Ollama LLM 创建成功，模型: %s，地址: %s", model, OLLAMA_BASE_URL)
            return llm
        except Exception as e:
            logger.error("创建 Ollama LLM 失败: %s", str(e))
            raise RuntimeError(f"创建 Ollama LLM 失败: {str(e)}") from e

    @staticmethod
    def _create_longcat_llm(model_name: Optional[str], temperature: float) -> ChatOpenAI:
        """创建 LongCat-2.0 LLM 实例（OpenAI 兼容格式）"""
        if not LONGCAT_API_KEY:
            raise RuntimeError(
                "LongCat-2.0 API Key 未配置，请设置环境变量 LONGCAT_API_KEY"
            )

        model = model_name or LONGCAT_LLM_MODEL
        try:
            llm = ChatOpenAI(
                model=model,
                base_url=LONGCAT_BASE_URL,
                api_key=LONGCAT_API_KEY,
                temperature=temperature,
            )
            logger.info(
                "LongCat-2.0 LLM 创建成功，模型: %s，地址: %s",
                model,
                LONGCAT_BASE_URL,
            )
            return llm
        except Exception as e:
            logger.error("创建 LongCat-2.0 LLM 失败: %s", str(e))
            raise RuntimeError(f"创建 LongCat-2.0 LLM 失败: {str(e)}") from e

    @staticmethod
    def _create_ollama_embedding(model_name: Optional[str]) -> OllamaEmbeddings:
        """创建 Ollama Embedding 实例"""
        model = model_name or EMBEDDING_MODEL_NAME
        try:
            embedding = OllamaEmbeddings(
                model=model,
                base_url=OLLAMA_BASE_URL,
            )
            logger.info(
                "Ollama Embedding 创建成功，模型: %s，地址: %s",
                model,
                OLLAMA_BASE_URL,
            )
            return embedding
        except Exception as e:
            logger.error("创建 Ollama Embedding 失败: %s", str(e))
            raise RuntimeError(f"创建 Ollama Embedding 失败: {str(e)}") from e

    @staticmethod
    def _create_longcat_embedding(model_name: Optional[str]) -> OpenAIEmbeddings:
        """创建 LongCat-2.0 Embedding 实例（OpenAI 兼容格式）"""
        if not LONGCAT_API_KEY:
            raise RuntimeError(
                "LongCat-2.0 API Key 未配置，请设置环境变量 LONGCAT_API_KEY"
            )

        model = model_name or LONGCAT_EMBEDDING_MODEL
        try:
            embedding = OpenAIEmbeddings(
                model=model,
                base_url=LONGCAT_BASE_URL,
                api_key=LONGCAT_API_KEY,
            )
            logger.info(
                "LongCat-2.0 Embedding 创建成功，模型: %s，地址: %s",
                model,
                LONGCAT_BASE_URL,
            )
            return embedding
        except Exception as e:
            logger.error("创建 LongCat-2.0 Embedding 失败: %s", str(e))
            raise RuntimeError(f"创建 LongCat-2.0 Embedding 失败: {str(e)}") from e

    @staticmethod
    def get_current_llm_provider() -> str:
        """获取当前使用的 LLM 提供商"""
        return LLM_PROVIDER

    @staticmethod
    def get_current_embedding_provider() -> str:
        """获取当前使用的 Embedding 提供商"""
        return EMBEDDING_PROVIDER

    @staticmethod
    def get_current_provider() -> str:
        """获取当前使用的模型提供商（向后兼容，返回 LLM 提供商）"""
        return LLM_PROVIDER

    @staticmethod
    def get_llm_model_name() -> str:
        """获取当前 LLM 模型名称"""
        if LLM_PROVIDER == "ollama":
            return LLM_MODEL_NAME
        elif LLM_PROVIDER == "longcat":
            return LONGCAT_LLM_MODEL
        return LLM_MODEL_NAME

    @staticmethod
    def get_embedding_model_name() -> str:
        """获取当前 Embedding 模型名称"""
        if EMBEDDING_PROVIDER == "ollama":
            return EMBEDDING_MODEL_NAME
        elif EMBEDDING_PROVIDER == "longcat":
            return LONGCAT_EMBEDDING_MODEL
        return EMBEDDING_MODEL_NAME
