# Qdrant 向量数据库 — 快速指南

## 部署信息

| 项目 | 值 |
|------|-----|
| 版本 | v1.19.0 |
| REST API | http://localhost:6333 |
| gRPC | localhost:6334 |
| Web UI | http://localhost:6333/dashboard |
| 数据持久化 | Docker volume `qdrant_qdrant_data` |
| 配置文件 | `docker-compose.yml` |

## 常用管理命令

```bash
# 启动
cd qdrant && docker compose up -d

# 停止
cd qdrant && docker compose down

# 查看日志
docker logs qdrant --tail 30

# 查看状态
docker ps --filter name=qdrant
```

## REST API 速查

```bash
# 创建 Collection（1024维 Cosine，适配 bge-m3 等 Embedding 模型）
curl -X PUT http://localhost:6333/collections/my_collection \
  -H 'Content-Type: application/json' \
  -d '{"vectors": {"size": 1024, "distance": "Cosine"}}'

# 插入向量（Python 示例见 test_qdrant.py）
# 搜索向量（Python 示例见 test_qdrant.py）

# 查看所有 Collections
curl http://localhost:6333/collections

# 删除 Collection
curl -X DELETE http://localhost:6333/collections/my_collection
```

## Python SDK 用法

```python
# pip install qdrant-client
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

client = QdrantClient(host="localhost", port=6333)

# 创建 Collection
client.create_collection("knowledge_base", vectors=VectorParams(size=1024, distance=Distance.COSINE))

# 插入
client.upsert("knowledge_base", points=[
    PointStruct(id=1, vector=[...], payload={"content": "文档内容", "source": "file.md"})
])

# 搜索
results = client.search("knowledge_base", query_vector=[...], limit=5)
for hit in results:
    print(hit.score, hit.payload["content"])
```

## 常见 Embedding 模型维度参考

| 模型 | 维度 | 适用场景 |
|------|------|---------|
| BGE-m3 | 1024 | 多语言、中文知识库（推荐） |
| text-embedding-3-large | 3072 | OpenAI 最新模型 |
| text-embedding-ada-002 | 1536 | OpenAI 经典模型 |
| bge-large-zh-v1.5 | 1024 | 中文专用 |
| jina-embeddings-v3 | 1024 | 多语言 |

## 用于 Agent 知识库问答的架构

```
用户提问 → Embedding 模型 → 向量 → Qdrant 搜索 → Top-K 文档 → LLM → 回答
```

Qdrant 存储文档的向量化表示和原文 payload，Agent 检索时传入问题向量，
Qdrant 返回最相似的文档片段，再交给 LLM 生成回答。
