# Tasks

## 第一阶段：项目初始化

- [x] Task 1: 创建项目目录结构
  - [x] SubTask 1.1: 创建 `code/` 目录
  - [x] SubTask 1.2: 创建子目录 `templates/` 和 `static/`
  - [x] SubTask 1.3: 创建 `requirements.txt` 依赖文件

## 第二阶段：核心功能实现

- [x] Task 2: 实现知识库管理模块 (`knowledge_base.py`)
  - [x] SubTask 2.1: 实现文档解析功能（支持 PDF、TXT、Markdown、Word）
  - [x] SubTask 2.2: 实现文本分割功能
  - [x] SubTask 2.3: 实现 Chroma 向量数据库存储
  - [x] SubTask 2.4: 实现文档增删查接口

- [x] Task 3: 实现 RAG 问答链 (`rag_chain.py`)
  - [x] SubTask 3.1: 集成 Ollama qwen3:4b 模型
  - [x] SubTask 3.2: 构建 LangChain RAG 链（检索 + 生成）
  - [x] SubTask 3.3: 实现带引用来源的问答接口

## 第三阶段：Web 应用

- [x] Task 4: 实现 FastAPI 应用 (`app.py`)
  - [x] SubTask 4.1: 创建 API 路由（上传、问答、文档管理）
  - [x] SubTask 4.2: 配置文件上传接口

- [x] Task 5: 实现前端界面
  - [x] SubTask 5.1: 创建首页模板（`index.html`）
  - [x] SubTask 5.2: 实现文档上传 UI
  - [x] SubTask 5.3: 实现问答交互 UI
  - [x] SubTask 5.4: 实现文档列表展示

## 第四阶段：配置与文档

- [x] Task 6: 创建启动说明
  - [x] SubTask 6.1: 编写 README.md 说明文档
  - [x] SubTask 6.2: 说明 Ollama 环境配置要求

# Task Dependencies

- Task 2 依赖 Task 1
- Task 3 依赖 Task 2
- Task 4 依赖 Task 3
- Task 5 依赖 Task 4
- Task 6 依赖 Task 5
