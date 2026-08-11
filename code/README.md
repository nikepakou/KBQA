# 知识库问答系统

基于 Python + LangChain + Ollama 的本地知识库问答系统。支持上传多种格式的文档（PDF、TXT、MD、DOCX），构建本地向量知识库，并通过 RAG（检索增强生成）技术实现智能问答。

## 技术栈

| 组件        | 说明                                |
| ----------- | ----------------------------------- |
| Python 3.8+ | 开发语言                            |
| LangChain   | LLM 应用开发框架                    |
| FastAPI     | Web 服务框架                        |
| Chroma      | 向量数据库                          |
| Ollama      | 本地大模型运行环境（qwen3:4b 模型） |

## 环境配置要求

### 安装 Ollama

1. 访问 [Ollama 官网](https://ollama.com) 下载并安装 Ollama。
2. 下载 `qwen3:4b` 模型：

```bash
ollama pull qwen3:4b
```

3. 确保 Ollama 服务运行在 `http://localhost:11434`（默认地址）。

### 安装依赖

```bash
cd code
pip install -r requirements.txt
```

## 启动应用

方式一：使用 Python 直接启动

```bash
python app.py
```

方式二：使用 Uvicorn 启动

```bash
uvicorn app:app --host 0.0.0.0 --port 8001 --reload
```

启动成功后，打开浏览器访问 [http://localhost:8000](http://localhost:8000) 即可使用。

## 使用说明

1. **上传文档**：在页面上传文档，支持 PDF、TXT、MD、DOCX 格式。
2. **智能问答**：在问答区域输入问题，系统将从知识库中检索相关内容并生成答案。
3. **查看来源**：查看答案对应的参考来源文档片段。
4. **文档管理**：浏览和删除已上传的文档。

## API 接口说明

| 方法     | 路径                      | 说明               |
| -------- | ------------------------- | ------------------ |
| `POST`   | `/api/upload`             | 上传文档到知识库   |
| `POST`   | `/api/ask`                | 提交问题获取答案   |
| `GET`    | `/api/documents`          | 获取知识库文档列表 |
| `DELETE` | `/api/documents/{doc_id}` | 删除指定文档       |

### 接口详情

#### POST /api/upload

上传文档到知识库。

- **请求参数**：`multipart/form-data`，字段名为 `file`
- **支持格式**：PDF、TXT、MD、DOCX
- **响应示例**：

```json
{
  "success": true,
  "doc_id": "doc_001",
  "file_name": "example.pdf"
}
```

#### POST /api/ask

提交问题，基于知识库内容生成答案。

- **请求体**：

```json
{
  "question": "什么是 RAG？"
}
```

- **响应示例**：

```json
{
  "answer": "RAG 是检索增强生成...",
  "sources": [
    {
      "content": "文档中的相关内容片段...",
      "source": "example.pdf"
    }
  ]
}
```

#### GET /api/documents

获取当前知识库中所有文档的列表。

- **响应示例**：

```json
{
  "documents": [
    {
      "doc_id": "doc_001",
      "file_name": "example.pdf",
      "created_at": "2026-08-10T10:00:00"
    }
  ]
}
```

#### DELETE /api/documents/{doc_id}

删除指定 ID 的文档及其向量数据。

- **响应示例**：

```json
{
  "success": true
}
```

## 项目结构

```
code/
├── app.py              # FastAPI 应用主入口
├── knowledge_base.py   # 知识库管理（向量存储）
├── rag_chain.py        # RAG 问答链
├── requirements.txt    # Python 依赖
├── templates/          # HTML 模板
│   └── index.html
└── static/             # 静态资源
    └── style.css
```

## 数据存储

- 上传的文档保存在 `./data/uploads/` 目录
- Chroma 向量数据库持久化在 `./data/chroma_db/` 目录
