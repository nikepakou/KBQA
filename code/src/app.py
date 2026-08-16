"""
知识库问答 Web 应用
基于 FastAPI + LangChain + Ollama 的 RAG 知识库问答系统
"""

import os
import uuid
import logging
from contextlib import asynccontextmanager

# ---------------------------------------------------------------------------
# SSL 环境变量防御：
# Windows 版 conda 的 openssl activate 钩子（旧版生成的 openssl_activate.sh）
# 会把 SSL_CERT_FILE 指向不存在的路径（ssl/cacert.pem，实际在 Library/ssl/），
# 导致 httpx/requests 初始化 SSL 上下文时 FileNotFoundError 崩溃。
# 启动时检测这类"指向不存在文件"的证书变量并清除。
# ---------------------------------------------------------------------------
for _SSL_ENV in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
    _SSL_PATH = os.environ.get(_SSL_ENV)
    if _SSL_PATH and not os.path.exists(_SSL_PATH):
        logging.warning(
            "[启动防御] 环境变量 %s 指向不存在的文件: %s，已清除以避免 SSL 初始化失败",
            _SSL_ENV, _SSL_PATH,
        )
        del os.environ[_SSL_ENV]

import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from knowledge_base import KnowledgeBase
from rag_chain import RAGChain
from config import (
    ENVIRONMENT,
    LLM_PROVIDER,
    EMBEDDING_PROVIDER,
    VECTOR_STORE_PROVIDER,
)
from database_factory import DatabaseFactory
from db_manager import DBManager
from data_analyzer import DataAnalyzer
from llm_factory import LLMFactory
from agent_state import SQLiteStateStore, state_summary
from agent_plan import SQLitePlanStore
from agent_tools import build_default_tools
from agent_planner import TaskPlanner
from agent_harness import AgentHarness
from agent_trace import TraceCollector, get_collector, set_collector

# 基于当前文件位置定位目录，避免工作目录不同导致路径错误
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")

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
agent_harness: AgentHarness = None
trace_collector: TraceCollector = None

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化全局对象"""
    global knowledge_base, rag_chain, db_manager, data_analyzer

    # 确保上传目录存在
    os.makedirs(UPLOADS_DIR, exist_ok=True)

    # 初始化 Trace 收集器（最优先：后续所有 LLM 创建时自动挂载追踪回调）
    # 一期方案：自建轻量 Trace 落 SQLite（data/agent_traces.db），异步写入
    global trace_collector
    trace_collector = TraceCollector(
        os.path.join(DATA_DIR, "agent_traces.db"),
        resource={
            "service.name": "kbqa",
            "service.version": "1.0.0",
            "environment": ENVIRONMENT,
            "llm_provider": LLM_PROVIDER,
        },
    )
    set_collector(trace_collector)
    logger.info("Trace 收集器初始化完成: %s", os.path.join(DATA_DIR, "agent_traces.db"))

    # 初始化知识库（向量数据库由配置决定）
    knowledge_base = KnowledgeBase(
        vector_store_provider=VECTOR_STORE_PROVIDER,
        provider=EMBEDDING_PROVIDER,
    )
    logger.info("知识库初始化完成，向量数据库: %s，Embedding 提供商: %s，嵌入模型: %s", VECTOR_STORE_PROVIDER, EMBEDDING_PROVIDER, LLMFactory.get_embedding_model_name())

    # 初始化 RAG 问答链（使用 LLM 提供商配置）
    rag_chain = RAGChain(
        knowledge_base=knowledge_base,
        provider=LLM_PROVIDER,
    )
    logger.info("RAG 问答链初始化完成，LLM 提供商: %s，LLM 模型: %s", LLM_PROVIDER, LLMFactory.get_llm_model_name())

    # 初始化数据分析模块（根据环境选择数据库）
    try:
        # 使用工厂类创建数据库管理器
        db_manager = DatabaseFactory.create_database_manager()
        
        # 连接数据库
        if db_manager.connect():
            # 如果是本地环境（SQLite），创建示例表
            if ENVIRONMENT == "local":
                from sqlite_db_manager import SQLiteDatabaseManager
                if isinstance(db_manager, SQLiteDatabaseManager):
                    db_manager.create_sample_tables()
                    logger.info("已创建 SQLite 示例表和数据")
            
            data_analyzer = DataAnalyzer(
                db_manager=db_manager,
                provider=LLM_PROVIDER,
            )
            env_info = DatabaseFactory.get_environment_info()
            logger.info("数据分析模块初始化完成，环境: %s，数据库: %s", 
                       env_info["environment"], env_info["database_type"])
        else:
            logger.warning("数据库连接失败，数据分析功能不可用")
    except Exception as e:
        logger.warning("数据分析模块初始化失败: %s，数据分析功能不可用", str(e))

    # 初始化 Agent Harness（断点续跑 + 工具调用幂等）
    try:
        global agent_harness
        agent_harness = init_agent_harness()
        logger.info("Agent Harness 初始化完成，已注册工具: %s", list(agent_harness.tool_map.keys()))
    except Exception as e:
        logger.warning("Agent Harness 初始化失败: %s，Agent 功能不可用", str(e))

    yield

    # 清理资源
    if db_manager:
        db_manager.close()
    # Trace 收集器停机：flush 后退出后台线程
    if trace_collector:
        trace_collector.close()
    logger.info("应用关闭")


# ==================== Agent Harness 初始化 ====================

def init_agent_harness() -> AgentHarness:
    """初始化 Agent Harness（Planner 规划 + 断点续跑 + 工具调用幂等）。

    - Agent 状态持久化到 data/agent_tasks.db（SQLite）
    - ExecutionPlan 独立持久化（同库 agent_plans 表，PlanStore 与 StateStore 分离）
    - 进程重启后任务状态不丢失，可通过 /api/agent/resume/{task_id} 断点续跑
    """
    agent_db_path = os.path.join(DATA_DIR, "agent_tasks.db")
    state_store = SQLiteStateStore(agent_db_path)
    plan_store = SQLitePlanStore(agent_db_path)
    tools = build_default_tools(knowledge_base, data_analyzer, UPLOADS_DIR)
    planner = TaskPlanner(plan_store=plan_store, tools=tools, provider=LLM_PROVIDER)
    harness = AgentHarness(
        state_store=state_store,
        tools=tools,
        provider=LLM_PROVIDER,
        plan_store=plan_store,
        planner=planner,
        collector=get_collector(),  # Trace 埋点（未启用时零开销）
    )
    # 服务启动时自动恢复所有 running 状态的任务（进程崩溃场景）
    _recover_running_tasks(harness)
    return harness


def _recover_running_tasks(harness: AgentHarness) -> None:
    """服务重启后扫描未完成任务并自动断点续跑。

    此前进程若在工具执行中崩溃，pending_tool_call 仍在状态里；
    resume_task 会依据幂等策略决定跳过或重发该调用。
    """
    try:
        running = [t for t in harness.state_store.list_tasks() if t["status"] == "running"]
        if not running:
            return
        logger.info("检测到 %d 个未完成 Agent 任务，开始自动续跑", len(running))
        import threading

        def _resume(t):
            try:
                harness.resume_task(t["task_id"])
            except Exception as e:  # noqa: BLE001
                logger.error("自动续跑任务 %s 失败: %s", t["task_id"], e)

        # 后台线程续跑，不阻塞服务启动
        threading.Thread(target=lambda: [_resume(t) for t in running], daemon=True).start()
    except Exception as e:  # noqa: BLE001
        logger.warning("扫描未完成任务失败: %s", e)


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


class AgentStartRequest(BaseModel):
    question: str
    task_id: str = None  # 可选，不传则自动生成
    max_iteration: int = 10


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


# ==================== Agent Harness API（断点续跑 + 工具调用幂等）====================


@app.post("/api/agent/start")
async def agent_start(request: AgentStartRequest):
    """启动 Agent 任务：LLM 多轮决策 + 工具循环（含幂等保护与状态持久化）"""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")
    if not agent_harness:
        raise HTTPException(status_code=503, detail="Agent 功能未就绪，请检查初始化日志")

    task_id = (request.task_id or f"task_{uuid.uuid4().hex[:12]}").strip()
    logger.info("收到 Agent 任务请求: task_id=%s, question=%s", task_id, request.question)
    try:
        result = agent_harness.start_task(
            task_id=task_id,
            user_query=request.question.strip(),
            max_iter=max(1, min(request.max_iteration, 30)),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("Agent 任务执行失败: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Agent 任务执行失败: {str(e)}")


@app.post("/api/agent/resume/{task_id}")
async def agent_resume(task_id: str):
    """断点续跑：进程崩溃/中断后恢复任务。

    - 未闭环的工具调用（pending_tool_call）依据幂等策略处理：
      写工具先查业务状态确认是否已生效，绝不盲目重试
    - 已执行过的工具调用直接复用历史结果
    """
    logger.info("收到 Agent 任务续跑请求: %s", task_id)
    if not agent_harness:
        raise HTTPException(status_code=503, detail="Agent 功能未就绪")
    try:
        return agent_harness.resume_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Agent 任务续跑失败: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Agent 任务续跑失败: {str(e)}")


@app.get("/api/agent/tasks")
async def agent_tasks():
    """获取所有 Agent 任务列表（概要，不含完整消息）"""
    if not agent_harness:
        raise HTTPException(status_code=503, detail="Agent 功能未就绪")
    return {"tasks": agent_harness.state_store.list_tasks()}


@app.get("/api/agent/tasks/{task_id}")
async def agent_task_detail(task_id: str):
    """获取单个 Agent 任务详情：状态、消息序列、工具调用履历、未闭环调用"""
    if not agent_harness:
        raise HTTPException(status_code=503, detail="Agent 功能未就绪")
    state = agent_harness.state_store.load(task_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    plan = agent_harness.plan_store.load_plan(task_id) if agent_harness.plan_store else None
    return {
        "summary": state_summary(state),
        "messages": state.messages,
        "tool_records": state.tool_records,
        "biz_context": state.biz_context,
        "pending_tool_call": state.pending_tool_call,
        "plan": plan.to_brief() if plan else None,
    }


@app.get("/api/agent/tasks/{task_id}/plan")
async def agent_task_plan(task_id: str):
    """获取 Agent 任务的执行计划（结构化子任务清单 + DAG 依赖 + 版本）"""
    if not agent_harness:
        raise HTTPException(status_code=503, detail="Agent 功能未就绪")
    state = agent_harness.state_store.load(task_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    plan = agent_harness.plan_store.load_plan(task_id) if agent_harness.plan_store else None
    if not plan:
        return {"plan": None, "message": "该任务无执行计划（纯 ReAct 模式）"}
    return {"plan": plan.to_brief()}


@app.get("/api/agent/tasks/{task_id}/trace")
async def agent_task_trace(task_id: str):
    """获取 Agent 任务的调用链 Trace（按时间排序的 span 列表）。

    - task_id 即 trace_id，与断点续跑/幂等审计共用同一业务键
    - 查询前 flush，保证刚产生的事件（异步写入）可见
    """
    if not agent_harness:
        raise HTTPException(status_code=503, detail="Agent 功能未就绪")
    state = agent_harness.state_store.load(task_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    if trace_collector is None:
        return {"trace_id": task_id, "spans": [], "message": "Trace 未启用"}
    trace_collector.flush(timeout=1.0)
    spans = trace_collector.query(task_id)
    total_ms = sum(s["duration_ms"] for s in spans)
    return {
        "trace_id": task_id,
        "span_count": len(spans),
        "total_duration_ms": round(total_ms, 1),
        "spans": spans,
    }


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
