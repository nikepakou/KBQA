# KBQA 模型与检索配置笔记

> 整理日期：2026-08-10
> 涉及文件：[app.py](../code/app.py)、[knowledge_base.py](../code/knowledge_base.py)、[rag_chain.py](../code/rag_chain.py)

---

## 一、qwen3:4b 是否包含 embedding 模型？

**结论：不包含。**

`qwen3:4b` 是一个**生成式大语言模型**，用于对话、问答、文本生成，输出文本。
在 Ollama 中，生成式模型与 embedding 模型是**两种分开的模型**：

| 模型类型 | 用途 | 示例 |
|---|---|---|
| 生成式模型（LLM） | 聊天、问答、文本补全 | `qwen3:4b` |
| Embedding 模型 | 文本向量化、语义检索 | `qwen3-embedding:0.6b`、`bge-m3`、`nomic-embed-text` |

### 错误做法
将同一个模型名 `qwen3:4b` 同时传给 `OllamaEmbeddings` 和 `ChatOllama`，会导致：
1. 向量质量差（不是为语义匹配训练的）
2. 速度慢、维度不匹配
3. 经常报错 `model not found`

### 正确做法
为 LLM 和 Embedding 分别指定不同的模型：

| 用途 | 推荐模型 |
|---|---|
| 聊天/问答 | `qwen3:4b` |
| 文本嵌入/向量检索 | `qwen3-embedding:0.6b` 或 `bge-m3` |

```powershell
ollama pull qwen3:4b
ollama pull qwen3-embedding:0.6b
```

---

## 二、将 LLM 和 Embedding 的模型配置分开

### 修改点 1：knowledge_base.py

将参数 `model_name` 重命名为 `embedding_model_name`，默认值改为专用嵌入模型：

```python
# 修改前
def __init__(self, model_name: str = "qwen3:4b", ...):
    self.embeddings = OllamaEmbeddings(model=self.model_name, ...)

# 修改后
def __init__(self, embedding_model_name: str = "qwen3-embedding:0.6b", ...):
    self.embeddings = OllamaEmbeddings(model=self.embedding_model_name, ...)
```

### 修改点 2：app.py

顶部新增配置常量区，集中管理模型配置：

```python
OLLAMA_BASE_URL = "http://localhost:11434"
LLM_MODEL_NAME = "qwen3:4b"                        # 生成式模型 → RAGChain
EMBEDDING_MODEL_NAME = "qwen3-embedding:0.6b"      # 嵌入模型 → KnowledgeBase
```

初始化时分别传参：

```python
knowledge_base = KnowledgeBase(
    embedding_model_name=EMBEDDING_MODEL_NAME,   # 嵌入模型
    base_url=OLLAMA_BASE_URL,
)

rag_chain = RAGChain(
    model_name=LLM_MODEL_NAME,                   # 生成式模型
    base_url=OLLAMA_BASE_URL,
)
```

### 注意事项
如果之前已经用 `qwen3:4b` 作为 embedding 创建了 chroma_db，由于向量维度和模型变更，**需要清空 `./data/chroma_db` 目录后重新上传文档**，否则检索会维度不匹配报错。

---

## 三、qwen3-embedding:0.6b 与 bge-m3 哪个更优？

**没有绝对的"更优"，取决于知识库场景。**

### 核心对比（同量级 0.6B）

| 维度 | qwen3-embedding:0.6b | bge-m3 |
|---|---|---|
| MTEB 总分 | 65.32 | **67.08** |
| 中文检索 CMTEB-R | 71.02 | **72.16** |
| 代码检索 MTEB-Code | **72.15** | 65.22 |
| 文本分类 | 63.89 | **66.44** |
| 文本聚类 | 59.27 | **61.85** |
| 多语言平均 | **66.14** | 65.82 |
| 上下文长度 | **32k tokens** | 通常 8k |
| 语言支持 | 100+ 种语言 | 多语言（中/英为主） |
| 指令感知 Instruction | 支持（可加前缀调整嵌入行为） | 不支持 |
| MRL 可变维度 | 支持（32~1024 维可调） | 固定 1024 维 |
| 社区成熟度 | 2025 年中发布，较新 | 老牌方案，生态完备 |

### 选型建议

| 场景 | 推荐 | 理由 |
|---|---|---|
| 纯中文通用知识库（PDF、Word、MD） | `bge-m3` | MTEB 总分、中文检索、分类、聚类全项小优，社区验证充分 |
| 技术文档 / 含代码注释 / 多语言混合 | `qwen3-embedding:0.6b` | 代码检索领先 10%+，32k 长上下文，指令感知可调整嵌入策略 |

---

## 四、检索算法分析

### 当前实现

```python
# knowledge_base.py - get_retriever()
return self.vectorstore.as_retriever(search_kwargs={"k": 4})
```

使用的是 **Chroma 默认的密集向量相似度检索（余弦相似度）**：

```
用户问题 → OllamaEmbeddings 生成查询向量
         → Chroma 在向量库中做余弦相似度比对
         → 返回 top-4 最相似的文本块
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `search_type` | `"similarity"` | 纯相似度检索（未显式传参，用默认值） |
| `search_kwargs={"k": 4}` | top-4 | 返回余弦相似度最高的 4 个文本块 |

### 不是什么
- 不是 BM25 / 关键词检索（稀疏检索，基于词频）
- 不是混合检索 Hybrid Search（向量 + 关键词融合）
- 不是重排序 Reranking（先粗排再精排）

### 潜在优化方向

1. **增加 k 值**（如 `{"k": 6}`）→ 召回更多候选，但增加 LLM 上下文长度
2. **改用 MMR 检索**（最大边际相关性）→ 去重，避免返回高度重复的文本块：
   ```python
   self.vectorstore.as_retriever(
       search_type="mmr",
       search_kwargs={"k": 4, "fetch_k": 20, "lambda_mult": 0.5}
   )
   ```
3. **加入重排序器**（如 `bge-reranker-v2-m3`）→ 先用向量检索 top-20，再用 reranker 精排取 top-4
