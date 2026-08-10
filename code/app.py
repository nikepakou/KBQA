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

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 全局对象
knowledge_base: KnowledgeBase = None
rag_chain: RAGChain = None

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化全局对象"""
    global knowledge_base, rag_chain

    # 确保上传目录存在
    os.makedirs("./data/uploads", exist_ok=True)
    os.makedirs("./data/chroma_db", exist_ok=True)

    # 初始化知识库
    knowledge_base = KnowledgeBase(
        persist_directory="./data/chroma_db",
        model_name="qwen3:4b",
        base_url="http://localhost:11434",
    )
    logger.info("知识库初始化完成")

    # 初始化 RAG 问答链
    rag_chain = RAGChain(
        knowledge_base=knowledge_base,
        model_name="qwen3:4b",
        base_url="http://localhost:11434",
    )
    logger.info("RAG 问答链初始化完成")

    yield

    # 清理资源（如有需要）
    logger.info("应用关闭")


# 创建 FastAPI 应用实例
app = FastAPI(
    title="知识库问答系统",
    description="基于 RAG 的知识库问答 Web 应用",
    version="1.0.0",
    lifespan=lifespan,
)

# 配置模板和静态文件目录
templates = Jinja2Templates(directory="./templates")
app.mount("/static", StaticFiles(directory="./static"), name="static")


# 请求模型
class AskRequest(BaseModel):
    question: str


# ==================== API 路由 ====================


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """返回主页 HTML"""
    return templates.TemplateResponse("index.html", {"request": request})


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
    file_path = os.path.join("./data/uploads", file.filename)
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
        raise HTTPException(
            status_code=503,
            detail="Ollama 服务不可用，请确保 Ollama 服务已启动",
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
    os.makedirs("./data/uploads", exist_ok=True)
    os.makedirs("./data/chroma_db", exist_ok=True)
    os.makedirs("./templates", exist_ok=True)
    os.makedirs("./static", exist_ok=True)

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
