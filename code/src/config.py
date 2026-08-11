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

# ==================== Ollama 模型配置 ====================
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen3:4b")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "qwen3-embedding:0.6b")

# ==================== 查询安全限制 ====================
# 返回的最大行数，防止一次性拉取过多数据
MAX_QUERY_ROWS = 1000
# 单次 SQL 查询超时时间（秒）
QUERY_TIMEOUT_SECONDS = 30
