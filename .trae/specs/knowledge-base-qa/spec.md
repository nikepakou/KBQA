# 知识库问答系统 Spec

## Why

构建一个基于本地大模型的知识库问答系统，允许用户上传文档到知识库，并通过自然语言提问获取基于文档内容的答案。使用本地 Ollama 部署的 qwen3:4b 模型，确保数据隐私和离线可用。

## What Changes

- 创建知识库管理功能（文档上传、存储、向量化）
- 实现文档解析支持（PDF、TXT、Markdown、Word）
- 集成 LangChain 框架构建 RAG 链
- 实现向量检索与语义问答接口
- 构建简单的 Web 交互界面

## Impact

- Affected specs: 新增功能
- Affected code: `code/` 目录下所有新建文件
  - `code/` - 项目主目录
  - `code/requirements.txt` - Python 依赖
  - `code/app.py` - FastAPI 应用入口
  - `code/knowledge_base.py` - 知识库管理核心
  - `code/rag_chain.py` - RAG 问答链
  - `code/templates/` - Web 前端模板
  - `code/static/` - 静态资源

## ADDED Requirements

### Requirement: 知识库文档管理

系统应支持用户上传文档到知识库，并进行向量化存储。

#### Scenario: 上传文档到知识库

- **WHEN** 用户上传一个 PDF 或 TXT 文档
- **THEN** 系统解析文档内容，分割为文本块，生成向量并存储到 Chroma 向量数据库

#### Scenario: 查看知识库文档列表

- **WHEN** 用户请求查看知识库中的文档
- **THEN** 系统返回所有已上传文档的名称和元数据

#### Scenario: 删除知识库文档

- **WHEN** 用户请求删除某个文档
- **THEN** 系统从知识库和向量数据库中移除该文档及其向量

### Requirement: RAG 问答功能

系统应支持用户基于知识库内容进行自然语言问答。

#### Scenario: 成功回答问题

- **WHEN** 用户提出一个与知识库内容相关的问题
- **THEN** 系统检索相关文档片段，结合 qwen3:4b 模型生成准确答案，并返回引用来源

#### Scenario: 问题超出知识库范围

- **WHEN** 用户提出与知识库内容无关的问题
- **THEN** 系统提示无法从知识库中找到相关信息

### Requirement: Web 交互界面

系统应提供简洁的 Web 界面供用户操作。

#### Scenario: 访问主页

- **WHEN** 用户访问系统首页
- **THEN** 显示知识库问答界面，包含文档上传区域和问答输入框

#### Scenario: 通过界面提问

- **WHEN** 用户在界面输入问题并提交
- **THEN** 系统显示生成的答案和参考文档片段

### Requirement: Ollama 模型集成

系统应集成本地 Ollama 服务调用 qwen3:4b 模型。

#### Scenario: 模型调用成功

- **WHEN** 系统需要调用大模型生成答案
- **THEN** 通过 Ollama API 成功调用 qwen3:4b 模型并获取响应

#### Scenario: 模型服务不可用

- **WHEN** Ollama 服务未启动或模型未下载
- **THEN** 系统返回友好的错误提示信息

## MODIFIED Requirements

无

## REMOVED Requirements

无
