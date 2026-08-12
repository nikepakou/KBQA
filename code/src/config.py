"""配置模块

加载环境变量并提供全局配置常量，包括 MySQL 数据库连接、Ollama 模型以及查询安全限制等。
"""

import os

from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# ==================== MySQL 数据库配置 ====================
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "")

# ==================== 模型提供商配置 ====================
# LLM 提供商: "ollama" | "longcat"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
# Embedding 提供商: "ollama" | "longcat"（可独立于 LLM 配置）
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "ollama")

# 向后兼容：如果设置了 MODEL_PROVIDER，则同时应用于 LLM 和 Embedding
_model_provider = os.getenv("MODEL_PROVIDER")
if _model_provider:
    LLM_PROVIDER = _model_provider
    EMBEDDING_PROVIDER = _model_provider

# ==================== Ollama 模型配置 ====================
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen3:4b")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "qwen3-embedding:0.6b")

# ==================== 美团 LongCat-2.0 模型配置 ====================
LONGCAT_BASE_URL = os.getenv("LONGCAT_BASE_URL", "https://api.longcat.chat/openai")
LONGCAT_API_KEY = os.getenv("LONGCAT_API_KEY", "")
LONGCAT_LLM_MODEL = os.getenv("LONGCAT_LLM_MODEL", "LongCat-2.0-Chat")
LONGCAT_EMBEDDING_MODEL = os.getenv("LONGCAT_EMBEDDING_MODEL", "LongCat-Embedding")

# ==================== 查询安全限制 ====================
# 返回的最大行数，防止一次性拉取过多数据
MAX_QUERY_ROWS = 1000
# 单次 SQL 查询超时时间（秒）
QUERY_TIMEOUT_SECONDS = 30
