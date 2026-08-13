"""
知识库问答 Web 应用
基于 FastAPI + LangChain + Ollama 的 RAG 知识库问答系统
"""

import os
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from knowledge_base import KnowledgeBase
from rag_chain import RAGChain
from config import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, LLM_PROVIDER, EMBEDDING_PROVIDER
from db_manager import DBManager
from data_analyzer import DataAnalyzer
from llm_factory import LLMFactory

# 基于当前文件位置定位目录，避免工作目录不同导致路径错误
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")

# Milvus 配置
MILVUS_URI = "http://localhost:19530"
MILVUS_COLLECTION = "knowledge_base"

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ==================== 模型配置 ====================
# LLM_PROVIDER: LLM 提供商（ollama 或 longcat）
# EMBEDDING_PROVIDER: Embedding 提供商（可独立于 LLM 配置）
# 注意：模型具体配置已移至 config.py，通过 LLMFactory 统一管理

# 全局对象
knowledge_base: KnowledgeBase = None
rag_chain: RAGChain = None
db_manager: DBManager = None
data_analyzer: DataAnalyzer = None

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化全局对象"""
    global knowledge_base, rag_chain, db_manager, data_analyzer

    # 确保上传目录存在
    os.makedirs(UPLOADS_DIR, exist_ok=True)

    # 初始化知识库（使用 Milvus 向量数据库）
    knowledge_base = KnowledgeBase(
        milvus_uri=MILVUS_URI,
        collection_name=MILVUS_COLLECTION,
        provider=EMBEDDING_PROVIDER,
    )
    logger.info("知识库初始化完成，Embedding 提供商: %s，嵌入模型: %s", EMBEDDING_PROVIDER, LLMFactory.get_embedding_model_name())

    # 初始化 RAG 问答链（使用 LLM 提供商配置）
    rag_chain = RAGChain(
        knowledge_base=knowledge_base,
        provider=LLM_PROVIDER,
    )
    logger.info("RAG 问答链初始化完成，LLM 提供商: %s，LLM 模型: %s", LLM_PROVIDER, LLMFactory.get_llm_model_name())

    # 初始化数据分析模块（MySQL 连接失败不阻断启动）
    try:
        db_manager = DBManager(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
        )
        if db_manager.connect():
            data_analyzer = DataAnalyzer(
                db_manager=db_manager,
                provider=LLM_PROVIDER,
            )
            logger.info("数据分析模块初始化完成")
        else:
            logger.warning("MySQL 连接失败，数据分析功能不可用")
    except Exception as e:
        logger.warning("数据分析模块初始化失败: %s，数据分析功能不可用", str(e))

    yield

    # 清理资源
    if db_manager:
        db_manager.close()
    logger.info("应用关闭")


# 创建 FastAPI 应用实例
app = FastAPI(
    title="知识库问答系统",
    description="基于 RAG 的知识库问答 Web 应用",
    version="1.0.0",
    lifespan=lifespan,
)

# 配置模板和静态文件目录
templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# 请求模型
class AskRequest(BaseModel):
    question: str


class AnalyzeRequest(BaseModel):
    question: str


# ==================== API 路由 ====================


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """返回主页 HTML"""
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """
    上传文档到知识库

    - 接收文件上传
    - 保存到 ./data/uploads 目录
    - 添加到知识库
    """
    # 检查文件扩展名
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_extension}。支持的文件类型: {', '.join(SUPPORTED_EXTENSIONS)}",
        )

    # 保存文件到上传目录
    file_path = os.path.join(UPLOADS_DIR, file.filename)
    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        logger.info("文件已保存: %s", file_path)
    except Exception as e:
        logger.error("保存文件失败: %s", str(e))
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")
    finally:
        await file.close()

    # 添加到知识库
    try:
        doc_id = knowledge_base.add_document(file_path=file_path, file_name=file.filename)
        return {
            "success": True,
            "doc_id": doc_id,
            "file_name": file.filename,
        }
    except ValueError as e:
        # 文件格式不支持
        # 删除已保存的文件
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # 删除已保存的文件
        if os.path.exists(file_path):
            os.remove(file_path)
        logger.error("添加文档到知识库失败: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"添加文档到知识库失败: {str(e)}",
        )


@app.post("/api/ask")
async def ask_question(request: AskRequest):
    """
    问答接口

    - 接收问题
    - 使用 RAG 链获取答案
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    try:
        result = rag_chain.ask(request.question)
        return {
            "answer": result["answer"],
            "sources": result["sources"],
        }
    except ConnectionError:
        provider = LLMFactory.get_current_provider()
        model_name = LLMFactory.get_llm_model_name()
        raise HTTPException(
            status_code=503,
            detail=f"模型服务不可用（提供商: {provider}，模型: {model_name}），请检查配置",
        )
    except Exception as e:
        logger.error("问答处理失败: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"处理问题时发生错误: {str(e)}",
        )


@app.get("/api/documents")
async def list_documents():
    """获取知识库中的文档列表"""
    try:
        documents = knowledge_base.list_documents()
        return {"documents": documents}
    except Exception as e:
        logger.error("获取文档列表失败: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"获取文档列表失败: {str(e)}",
        )


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    """删除知识库中的文档"""
    try:
        success = knowledge_base.delete_document(doc_id)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"未找到文档: {doc_id}",
            )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除文档失败: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"删除文档失败: {str(e)}",
        )


@app.get("/api/db/tables")
async def get_db_tables():
    """获取数据库表结构"""
    if not db_manager or not data_analyzer:
        raise HTTPException(
            status_code=503,
            detail="数据分析功能未就绪，请检查 MySQL 连接配置",
        )
    try:
        schema = db_manager.get_schema()
        return {"tables": schema}
    except Exception as e:
        logger.error("获取表结构失败: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"获取表结构失败: {str(e)}",
        )


@app.post("/api/analyze")
async def analyze_data(request: AnalyzeRequest):
    """
    数据分析接口

    - 接收自然语言问题
    - 生成 SQL 查询
    - 执行查询并推荐图表
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    if not data_analyzer:
        raise HTTPException(
            status_code=503,
            detail="数据分析功能未就绪，请检查 MySQL 连接配置",
        )

    try:
        result = data_analyzer.analyze(request.question.strip())
        return result
    except Exception as e:
        logger.error("数据分析失败: %s", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"数据分析失败: {str(e)}",
        )


# ==================== 全局异常处理 ====================


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """统一处理 HTTP 异常"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """统一处理未捕获的异常"""
    logger.error("未捕获的异常: %s", str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "服务器内部错误"},
    )


# ==================== 启动配置 ====================

if __name__ == "__main__":
    # 确保必要的目录存在
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    os.makedirs(STATIC_DIR, exist_ok=True)

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
    )
