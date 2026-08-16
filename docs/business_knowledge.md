# 业务知识库

本文档记录项目开发过程中的业务需求、实现方案和关键决策。

---

## 2026-08-16: 支持两套执行环境

### 业务需求描述

项目需要支持两套执行环境：
1. **本地开发测试环境**：不依赖数据库，使用内存数据库
2. **服务器部署环境**：依赖 MySQL 数据库

### 实现方案

#### 1. 环境配置
- 通过 `ENVIRONMENT` 环境变量区分环境
- 支持两个值：
  - `local`：本地开发环境，使用 SQLite 内存数据库
  - `production`：服务器部署环境，使用 MySQL 数据库
- 默认值为 `local`

#### 2. 数据库管理
- **SQLite 内存数据库**：
  - 使用 Python 标准库 `sqlite3`
  - 数据库连接字符串：`:memory:`
  - 自动创建示例表和数据（users、orders）
  - 无需安装和配置外部数据库

- **MySQL 数据库**：
  - 继续使用现有配置
  - 通过环境变量配置连接参数

#### 3. 代码架构
- 创建 `SQLiteDatabaseManager` 类，实现与 `DBManager` 相同的接口
- 创建 `DatabaseFactory` 工厂类，根据环境创建相应的数据库管理器
- 更新 `app.py` 使用工厂类创建数据库管理器
- 保持向后兼容，不影响现有功能

### 关键决策点

1. **为什么选择 SQLite 内存数据库？**
   - Python 标准库自带，无需额外安装
   - 内存数据库速度快，适合开发测试
   - 无需配置，开箱即用
   - 与 MySQL 接口兼容，便于切换

2. **为什么使用工厂模式？**
   - 统一创建逻辑，便于维护
   - 支持未来扩展其他数据库类型
   - 集中管理环境配置

3. **为什么自动创建示例表？**
   - 方便开发测试，无需手动准备数据
   - 提供真实的数据分析场景
   - 新开发者可以快速上手

### 遇到的问题及解决方案

**问题**：如何确保两套环境的代码兼容性？

**解决方案**：
- 定义统一的数据库管理器接口
- 两个管理器类实现相同的方法签名
- 使用工厂类统一创建实例

### 文件变更清单

#### 新增文件
- [sqlite_db_manager.py](file:///d:/07-MM/KBQA/code/src/sqlite_db_manager.py) - SQLite 内存数据库管理器
- [database_factory.py](file:///d:/07-MM/KBQA/code/src/database_factory.py) - 数据库工厂类

#### 修改文件
- [config.py](file:///d:/07-MM/KBQA/code/src/config.py) - 添加 ENVIRONMENT 配置
- [app.py](file:///d:/07-MM/KBQA/code/src/app.py) - 使用工厂类创建数据库管理器
- [.env.example](file:///d:/07-MM/KBQA/code/.env.example) - 添加环境配置示例

### 使用说明

#### 本地开发环境
```bash
# .env 文件配置
ENVIRONMENT=local
```

启动应用后，系统会自动：
1. 创建 SQLite 内存数据库
2. 创建示例表（users、orders）
3. 插入测试数据

#### 服务器部署环境
```bash
# .env 文件配置
ENVIRONMENT=production
MYSQL_HOST=your_mysql_host
MYSQL_PORT=3306
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
```

### 后续待办事项

- [x] 添加环境切换的单元测试
- [ ] 优化 SQLite 示例数据，增加更多测试场景
- [ ] 考虑支持 PostgreSQL 作为第三种数据库选项
- [ ] 添加数据库迁移脚本支持

---

## 2026-08-16: 新增 DeepSeek 模型适配

### 业务需求描述

LongCat-2.0 token 余额用完，需要新增 DeepSeek 模型作为替代的在线模型提供商。

### 实现方案

#### 1. 配置扩展
- 在 `config.py` 中添加 DeepSeek 配置项：
  - `DEEPSEEK_BASE_URL`：API 地址（默认 `https://api.deepseek.com`）
  - `DEEPSEEK_API_KEY`：API 密钥
  - `DEEPSEEK_LLM_MODEL`：LLM 模型名（默认 `deepseek-chat`）

#### 2. 工厂类扩展
- 在 `LLMFactory` 中添加 DeepSeek LLM 支持：
  - `_create_deepseek_llm()`：创建 DeepSeek LLM 实例
  - 更新 `create_llm()` 方法支持 `deepseek` 提供商
  - 更新 `get_llm_model_name()` 方法
- **注意**：DeepSeek 不支持 Embedding 服务，`create_embedding()` 方法在遇到 `deepseek` 时会抛出明确的错误提示

#### 3. 技术实现
- DeepSeek API 兼容 OpenAI 格式，复用 `langchain_openai` 的 `ChatOpenAI`
- 使用延迟导入，按需加载模块
- 包含 SSL 证书和代理环境变量清理逻辑

### 关键决策点

1. **为什么选择 DeepSeek？**
   - 提供 OpenAI 兼容 API，易于集成
   - 支持中文场景，适合本项目
   - 成本较低，性价比高

2. **为什么复用 langchain_openai？**
   - DeepSeek API 兼容 OpenAI 格式
   - 减少依赖，代码复用
   - 统一在线提供商的实现方式

3. **为什么保留 LongCat 支持？**
   - 保持向后兼容
   - 未来 LongCat 充值后可继续使用
   - 支持多提供商灵活切换

### 文件变更清单

#### 修改文件
- [config.py](file:///d:/07-MM/KBQA/code/src/config.py) - 添加 DeepSeek 配置项
- [llm_factory.py](file:///d:/07-MM/KBQA/code/src/llm_factory.py) - 添加 DeepSeek 创建方法
- [.env.example](file:///d:/07-MM/KBQA/code/.env.example) - 添加 DeepSeek 配置示例

#### 新增文件
- [test/test_online_config.py](file:///d:/07-MM/KBQA/code/test/test_online_config.py) - 通用在线模型配置测试

#### 删除文件
- `test/test_longcat_config.py` - 替换为通用测试

### 使用说明

#### 推荐配置：DeepSeek LLM + Ollama Embedding（混合配置）
```bash
# .env 文件配置
LLM_PROVIDER=deepseek
EMBEDDING_PROVIDER=ollama
DEEPSEEK_API_KEY=your_deepseek_api_key
```

#### 全本地配置（Ollama）
```bash
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
```

#### 运行测试
```bash
python test/test_online_config.py
```

### 重要说明

**DeepSeek 不支持 Embedding 服务**：
- DeepSeek API 只提供 `/chat/completions` 端点
- 不提供 `/embeddings` 端点
- Embedding 必须使用其他提供商（Ollama 或 LongCat）
- 推荐使用混合配置：LLM 用 DeepSeek，Embedding 用 Ollama

### 支持的提供商汇总

| 提供商 | 类型 | LLM 支持 | Embedding 支持 | 说明 |
|--------|------|----------|----------------|------|
| ollama | 本地 | ✅ qwen3:4b | ✅ qwen3-embedding:0.6b | 无需 API Key |
| longcat | 在线 | ✅ LongCat-2.0-Chat | ✅ LongCat-Embedding | 需要 API Key |
| deepseek | 在线 | ✅ deepseek-chat | ❌ 不支持 | 仅 LLM，Embedding 需用其他提供商 |

---

## 2026-08-16: 修复数据分析接口 `row.forEach is not a function` 错误

### 业务需求描述

在本地环境（SQLite）中执行"统计用户数量"等查询时，前端报错：`请求失败: row.forEach is not a function`

### 根因分析

**双重问题导致：**

1. **后端问题**：`sqlite_db_manager.py` 中设置了 `self._connection.row_factory = sqlite3.Row`，
   `cursor.fetchall()` 返回的是 `sqlite3.Row` 对象列表而非 tuple 列表。
   `sqlite3.Row` 是类字典对象，JSON 序列化后前端拿到的是 `{column: value}` 对象而非数组。

2. **前端问题**：`renderTable()` 直接调用 `row.forEach(cell => ...)`，
   当 `row` 是对象而非数组时，对象没有 `forEach` 方法，直接抛出 TypeError。

### 修复方案

#### 1. 后端修复（[sqlite_db_manager.py](file:///d:/07-MM/KBQA/code/src/sqlite_db_manager.py#L136-L146)）

`execute_query` 返回时将 `sqlite3.Row` 归一化为 tuple：

```python
raw_rows = cursor.fetchall()
# 归一化：将 sqlite3.Row 转换为 tuple（保证 JSON 序列化后是数组）
rows = [tuple(r) for r in raw_rows]
```

#### 2. 前端修复（[index.html](file:///d:/07-MM/KBQA/code/src/templates/index.html#L542-L591)）

`renderTable()` 增加双重归一化兜底：

```javascript
// 1. 确保 columns 和 rawRows 是数组
const columns = Array.isArray(data.columns) ? data.columns : [];
const rawRows = Array.isArray(data.rows) ? data.rows : [];

// 2. 每行归一化：若 row 是对象则按列顺序提取值转换为数组
const rows = rawRows.map((row) => {
  if (Array.isArray(row)) return row;
  if (row && typeof row === "object") {
    return columns.map((col) => {
      const colName = typeof col === "object" ? col.name : col;
      return row[colName];
    });
  }
  return [];
});

// 3. 遍历前再次检查 Array.isArray
const cells = Array.isArray(row) ? row : [];
cells.forEach(...)
```

### 关键教训

1. **返回结构归一化原则**：后端接口返回的数据结构必须明确、统一。
   不同数据库/驱动（SQLite vs MySQL）返回的行对象不同，必须在后端抹平差异。

2. **前端消费接口必须兜底**：所有 `forEach`/`map` 调用前必须保证被遍历对象是数组类型。
   使用 `Array.isArray(x) ? x : []` 或归一化函数，杜绝运行时类型错误。

3. **双重保险策略**：后端保证结构正确 + 前端保证类型兜底，
   避免后端改一处前端就崩溃的耦合。

---

## 2026-08-16: 向量数据库配置统一管理，支持 Milvus/Chroma 双后端

### 业务需求描述

将 app.py 中硬编码的 Milvus 配置统一到 config.py 中，并通过 .env 控制向量数据库的选择，支持 Milvus（生产环境）和 Chroma（本地开发，内存模式）两种后端。

### 实现方案

#### 1. 配置统一管理
- 在 `config.py` 中添加向量数据库配置：
  - `VECTOR_STORE_PROVIDER`：向量数据库提供商（"milvus" | "chroma"）
  - `MILVUS_URI`、`MILVUS_COLLECTION`：Milvus 配置
  - `CHROMA_PERSIST_DIRECTORY`、`CHROMA_COLLECTION`：Chroma 配置

#### 2. 双后端支持
- 修改 `knowledge_base.py` 的 `KnowledgeBase` 类：
  - 添加 `vector_store_provider` 参数
  - 新增 `_create_vectorstore()` 方法，根据配置创建对应向量数据库实例
  - Milvus：使用 `langchain_milvus.Milvus`
  - Chroma：使用 `langchain_chroma.Chroma`，支持内存模式和持久化模式
  - 使用延迟导入，按需加载模块

#### 3. 应用集成
- 移除 `app.py` 中硬编码的 `MILVUS_URI` 和 `MILVUS_COLLECTION`
- 从 `config.py` 导入 `VECTOR_STORE_PROVIDER`
- `KnowledgeBase` 初始化时传入 `vector_store_provider`

### 关键决策点

1. **为什么选择 Chroma 作为本地开发选项？**
   - 轻量级，无需独立服务
   - 支持纯内存模式（重启后数据丢失，适合开发测试）
   - 支持本地持久化（可选配置 `CHROMA_PERSIST_DIRECTORY`）
   - 安装简单，`pip install langchain-chroma`

2. **为什么使用延迟导入？**
   - 只在需要时才导入对应的向量数据库模块
   - 避免安装了 Milvus 但使用 Chroma 时的依赖问题
   - 与 LLM 工厂类的延迟导入策略保持一致

3. **Chroma 内存模式 vs 持久化模式？**
   - 内存模式（`CHROMA_PERSIST_DIRECTORY` 留空）：数据存内存，重启丢失，适合开发测试
   - 持久化模式（设置目录路径）：数据存本地，重启不丢失，适合长期开发

### 文件变更清单

#### 修改文件
- [config.py](file:///d:/07-MM/KBQA/code/src/config.py) - 添加向量数据库配置项
- [knowledge_base.py](file:///d:/07-MM/KBQA/code/src/knowledge_base.py) - 支持 Milvus/Chroma 双后端
- [app.py](file:///d:/07-MM/KBQA/code/src/app.py) - 移除硬编码配置，使用 config.py
- [.env](file:///d:/07-MM/KBQA/code/.env) - 添加向量数据库配置
- [.env.example](file:///d:/07-MM/KBQA/code/.env.example) - 添加向量数据库配置示例

### 使用说明

#### 本地开发（Chroma 内存模式）
```bash
# .env 文件配置
VECTOR_STORE_PROVIDER=chroma
CHROMA_PERSIST_DIRECTORY=
```

#### 本地开发（Chroma 持久化模式）
```bash
# .env 文件配置
VECTOR_STORE_PROVIDER=chroma
CHROMA_PERSIST_DIRECTORY=./chroma_db
```

#### 生产环境（Milvus）
```bash
# .env 文件配置
VECTOR_STORE_PROVIDER=milvus
MILVUS_URI=http://your-milvus-host:19530
MILVUS_COLLECTION=knowledge_base
```

### 向量数据库对比

| 提供商 | 类型 | 适用场景 | 是否需要独立服务 | 持久化 |
|--------|------|----------|------------------|--------|
| milvus | 在线服务 | 生产环境 | 是 | 是 |
| chroma | 内存/本地 | 开发测试 | 否 | 可选 |

---

## 2026-08-16: 引入 Agent Harness（断点续跑 + 工具调用幂等）

### 业务需求描述

参考 Obsidian 文档《01-Agent Harness（断点续跑 + 工具调用幂等）》改造 KBQA 项目：
将原有"单次调用 RAG 链"的问答模式升级为 **Agent 多轮工具循环模式**，解决两个核心问题：
1. **进程崩溃导致任务丢失**：长任务（多轮检索+查询+入库）执行中崩溃后，重启需能从中断点续跑
2. **工具重复执行的副作用**：崩溃恢复/LLM 重复决策时，写操作（如文档入库）不能重复执行

### 实现方案

#### 新增文件

| 文件 | 职责 |
|------|------|
| `code/src/agent_state.py` | AgentState 结构化状态（唯一可信源）+ StateStore 抽象 + SQLiteStateStore 持久化实现（data/agent_tasks.db）+ MemoryStateStore（测试用） |
| `code/src/agent_tools.py` | BaseTool 工具抽象；KBSearchTool（知识库检索，只读）、SQLQueryTool（NL2SQL 只读查询）、AddDocumentTool（文档入库，写操作天然幂等 + check_executed 恢复检查） |
| `code/src/agent_harness.py` | AgentHarness 核心引擎：start_task / resume_task / run_loop |

#### 核心机制（与文档一一对应）

1. **结构化状态唯一可信源**：AgentState 含 task_id/status/iteration/max_iteration/messages/tool_records/pending_tool_call/biz_context，每轮执行完成立即持久化，断点续跑不依赖文本日志复盘
2. **框架控制循环指针**：LLM 只做单次决策（JSON 协议：`{"type":"tool_call",...}` 或 `{"type":"finish"}`），iteration/max_iteration 护栏由 Harness 强制管控（上限默认 10，API 层限 30）
3. **工具调用幂等三层防护**：
   - 工具侧天然幂等：add_document 同名文档直接跳过
   - Harness 层预占位：执行前写入 pending_tool_call 并立即持久化；重复调用预检查（同 tool_name + 同 args 拦截并注入历史结果）
   - 恢复策略A：写工具实现 check_executed，崩溃恢复时先查业务状态，已生效则补全记录跳过（recovered=True），绝不盲目重试
4. **可选自省分支**：工具失败后调 LLM 分析原因，建议存 biz_context 并注入上下文
5. **服务重启自动续跑**：app.py lifespan 启动时扫描 running 状态任务，后台线程自动 resume

#### API 变更（app.py）

- `POST /api/agent/start`：启动 Agent 任务（body: question / max_iteration / 可选 task_id）
- `POST /api/agent/resume/{task_id}`：断点续跑
- `GET /api/agent/tasks`：任务列表（概要）
- `GET /api/agent/tasks/{task_id}`：任务详情（messages / tool_records / pending_tool_call / biz_context）

#### 前端变更

- index.html 新增"Agent 任务"Tab：任务输入（含最大轮次设置）、结果展示、工具调用履历（含幂等审计标签"崩溃恢复·跳过重复执行"）、断点续跑按钮、历史任务列表（running 状态任务可一键续跑）
- style.css 新增 Agent 面板样式

### 关键决策点

1. **StateStore 选 SQLite 而非文档中的 MemoryStateStore**：内存版重启即失，违背断点续跑目标；SQLite 单文件零部署，接口抽象保留替换 Redis/Postgres 的能力（对应 LangGraph Checkpointer 概念）
2. **分布式锁降级为单机 threading.Lock**：当前为单实例部署；多实例时替换 Redis Lock（代码已留注释）
3. **LLM 决策用 JSON 输出解析而非原生 Function Calling**：兼容 ollama/longcat/deepseek 全部提供商；解析失败/未知工具名时强制 finish 兜底，避免死循环
4. **tool 角色消息转 user 文本送入 LLM**：部分 Chat 模型不支持 tool role，转换保证跨模型兼容
5. **保留原有 /api/ask 与 /api/analyze 接口不动**：Agent 模式为增量能力，不破坏既有功能

### 遇到的问题及解决方案

1. **问题**：LangChain Chat 模型对 OpenAI 风格 "tool" role 消息兼容性不一
   **解决**：`_convert_message()` 将 tool/assistant(tool_calls) 消息转为通用文本格式
2. **问题**：LLM 可能重复发起相同参数的工具调用造成浪费
   **解决**：run_loop 预检查 tool_records（tool_name + args 全等匹配），命中则注入历史结果并 continue，不消耗执行
3. **问题**：恢复时"执行中崩溃"的写操作无法判断远端是否已生效
   **解决**：写工具实现 check_executed（业务侧查询），Harness resume 按策略A处理；本项目场景（文档入库）可通过 list_documents 精确判断

### 验证结果

冒烟测试（Mock LLM + Mock 工具，6 场景全部通过）：
1. 正常流程：2 轮工具 + finish，状态 completed
2. 幂等预检查：重复调用被拦截，工具仅执行 1 次
3. 崩溃恢复（写已生效）：补全记录跳过重发，写工具执行 0 次，recovered=True
4. 崩溃恢复（写未生效）：占位清空，允许重新发起
5. 安全护栏：3 轮后强制 failed 终止
6. SQLite 任务列表读写正常

### 后续待办事项

- [ ] 多实例部署时：StateStore 替换 Redis + 分布式锁
- [ ] 超长 messages 上下文自动摘要压缩（文档"生产环境改造点"）
- [ ] 高危写工具增加 Human-in-the-loop 审批钩子
- [ ] Agent 任务异步执行 + SSE 进度推送（当前为同步阻塞 API）
- [ ] 增加 OpenTelemetry 链路埋点

---

## 2026-08-16: 引入任务规划器（Planner 与 Harness 主分支结合）

### 业务需求描述

参考 Obsidian 文档《02-任务规划与Harness主分支结合方案》继续完善 KBQA 项目：
在 01 文档的 Harness（断点续跑+幂等）之上增加 **Planner 规划层**，将"LLM 自由 ReAct"升级为
"结构化任务计划驱动"：用户目标先拆解为 SubTask 清单（简单 DAG），主循环按计划逐条执行，
失败时动态修正计划。

### 实现方案

#### 分层架构

```
用户请求 → Planner（输出结构化 ExecutionPlan，独立持久化）
        → Harness 主循环（ReAct 执行引擎，按 DAG 调度子任务，可动态调整）
        → Tool 执行层（幂等逻辑完全复用 01 版）
```

#### 新增文件

| 文件 | 职责 |
|------|------|
| `code/src/agent_plan.py` | SubTask（task_id/status/depend_on/required_tools/result_summary）+ ExecutionPlan（plan_version 防并发覆盖）+ PlanStore 抽象 + SQLitePlanStore（agent_plans 表，与 StateStore 分离） |
| `code/src/agent_planner.py` | TaskPlanner：create_initial_plan（LLM 目标拆解，强制 JSON + 稳健解析 + 兜底单任务计划）、revise_plan（失败动态修正，版本+1） |

#### 修改文件

- `agent_state.py`：AgentState 新增 `current_subtask_id`（断点恢复定位用）
- `agent_harness.py`：重构为双模式主循环
  - 规划驱动模式：外层 DAG 子任务调度（`_get_next_executable_subtask`）+ 内层子任务 ReAct 工具循环（幂等逻辑提取为 `_execute_tool_call` 复用）
  - 纯 ReAct 模式：无 Plan 任务自动回退（向后兼容 01 版任务）
  - 动态重规划：工具失败触发 `revise_plan`，次数上限由 Harness 框架侧强制管控（`MAX_PLAN_REVISE=3`）
  - 断点续跑升级：resume 同时加载 State + Plan 双向恢复；中断子任务 running→pending 重新调度（工具级幂等由 tool_records 预检查兜底）
- `app.py`：init 接线 plan_store/planner；新增 `GET /api/agent/tasks/{task_id}/plan`；任务详情 API 附带 plan 概要
- `index.html`/`style.css`：Agent 面板新增"执行计划（子任务 DAG）"展示（标题/状态/依赖/结果摘要/版本）

### 关键决策点

1. **Plan 独立持久化而非塞进 AgentState**：物理同库（agent_tasks.db）逻辑分离（agent_plans 表 + 独立 PlanStore 类），通过 root_task_id 一对一绑定；断点恢复 State+Plan 缺一不可
2. **Planner 不侵入主循环核心**：规划器只产出/修改清单，循环调度/断点/幂等/护栏全由 Harness 负责；规划 LLM 失败自动回退（初始规划失败→兜底单任务计划；重规划失败→沿用原计划）
3. **防过度规划双层保障**：Harness 侧 `MAX_PLAN_REVISE` 框架强制上限 + 仅在工具失败时触发（不每轮重规划）
4. **LLM 非结构化输出防护**：强制 JSON 协议提示词 + markdown/杂文容错解析 + 字段校验（depend_on 仅允许引用前置任务防循环依赖）+ 全部非法时兜底单任务计划
5. **中断子任务恢复策略**：running→pending 重新调度而非续跑半程——工具级幂等（同参数拦截+注入历史结果）保证重调度无重复副作用
6. **Planner LLM 与主循环 LLM 分层**：Planner temperature=0 负责目标拆解，主循环 LLM 负责子任务内工具选择

### 遇到的问题及解决方案

1. **问题**：ExecutionPlan.to_json 直接 json.dumps(dataclass) 时 SubTask 被 default=str 序列化为字符串，反序列化崩溃
   **解决**：改用 `dataclasses.asdict()` 递归展开
2. **问题**：重规划次数上限原放在 TaskPlanner 内部，替换 Planner 实现后上限失效（冒烟测试场景5暴露）
   **解决**：上限移至 Harness 框架侧（`MAX_PLAN_REVISE`），调用前强制检查，不依赖 Planner 实现

### 验证结果

冒烟测试（Mock LLM + Mock Planner，6 场景全部通过）：
1. DAG 调度：依赖顺序执行，计划 finished，结果按子任务汇总
2. 动态重规划：失败触发 revise，plan v2，修正后完成
3. 断点恢复：State+Plan 双向加载， running 子任务回退 pending 重调度
4. ReAct 回退：无 Plan 任务按 01 版模式执行
5. 防过度规划：达上限不再 revise，子任务标记 failed 并跳过
6. Planner 解析：正常 JSON / markdown 包裹 / 杂文 / 非法输出兜底单任务 / depend_on 序号重编号

### 后续待办事项

- [ ] Planner 重规划提示词按业务场景调优（当前为通用模板）
- [ ] Plan 压缩策略：长任务对已完成子任务做摘要再喂 Planner
- [ ] 前端计划 DAG 可视化（当前为列表展示，可升级依赖关系图）
- [ ] 子任务粒度策略：Planner 提示词中按工具能力约束拆解粒度

---

## 2026-08-16: 修复启动崩溃（SSL_CERT_FILE 指向不存在的证书文件）

### 问题现象

`python src/app.py` 启动即崩溃，lifespan 初始化 KnowledgeBase → OllamaEmbeddings → httpx 时：

```
FileNotFoundError: [Errno 2] No such file or directory
  File "...\httpx\_config.py", line 35, in create_ssl_context
    ctx = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
```

### 根因

**Windows 版 conda 环境的 openssl activate 钩子脚本路径错误**：
`<env>/etc/conda/activate.d/openssl_activate.sh`（旧版 conda 生成）激活环境时执行：

```bash
export SSL_CERT_FILE="${CONDA_PREFIX}/ssl/cacert.pem"   # 错误：小写 ssl
```

而 Windows 版 conda 环境证书实际位于 **`<env>/Library/ssl/cacert.pem`**（大写 Library）。
Git Bash 中 `conda activate kbqa` 时 shell 版钩子（.sh）生效，设置了指向不存在文件的坏变量；
httpx 的 `create_ssl_context(trust_env=True)` 读取该变量时文件不存在 → 崩溃。
（.bat/.ps1 钩子路径正确，故 CMD/PowerShell 启动不受影响。）

排查过程确认：注册表 HKCU/HKLM、~/.bashrc、~/.condarc 均无此变量，来源是 conda 激活钩子。

### 解决方案（双保险）

1. **修复钩子脚本**（kbqa + chaos_seg 两个环境均有问题）：
   `openssl_activate.sh` 改为 `${CONDA_PREFIX}/Library/ssl/cacert.pem`，并加 `-f` 存在性判断（文件不存在则完全不设置该变量，避免再次埋雷）
2. **app.py 启动防御**：模块顶部检测 `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE`，
   指向不存在文件则清除并告警（即使旧终端/其他环境带坏变量也能正常启动）

### 验证

- 模拟激活脚本：`SSL_CERT_FILE` 指向 Library/ssl/cacert.pem 且文件存在（FILE_OK）
- 预置坏变量 import app：防御清理生效，`langchain_ollama/OllamaEmbeddings` 导入成功（复现原崩溃路径不再报错）
- py_compile 通过

### 运维提示

用户侧修复后需**重新激活环境**（`conda deactivate && conda activate kbqa`）或新开终端，
使新钩子脚本生效（旧终端进程仍持有坏变量，但 app.py 防御可兜底）。

---

## 2026-08-16: Trace 方案评估（参考《20260815_技术_Trace模块引入与行业实践》）

### 业务需求描述

参考 Obsidian 文档评估 KBQA 项目应采用哪种 Trace（可观测性）方案，为后续接入做选型决策。

### 评估结论（详见 docs/trace_evaluation.md）

- **一期：SDK 嵌入 + 代理层组合，自建轻量 Trace 落 SQLite**（task_id = trace_id，扩展 tool_records + 新增 llm_call/plan/schedule/resume 等 span）
- **二期（触发式）：Langfuse 或 Phoenix 自托管**——需要可视化面板/深度质量评估/多实例部署时引入；一期数据结构按 OpenTelemetry 语义设计保证迁移成本低

### 关键决策点

1. **排除 LangSmith/W&B**：SaaS 数据出境与知识库数据敏感约束冲突；国内网络不稳
2. **框架集成方式（方式二）不可行**：Agent 主循环是自研 Harness，LangChain 自动埋点只能捕获底层 llm.invoke，决策/规划/幂等拦截等关键节点不可见
3. **自建优先的核心理由**：已有 SQLite StateStore + 结构化 tool_records + task_id 全链路键，增量成本最低；且 task_id ↔ tool_records ↔ pending_tool_call 的业务关联（断点续跑/幂等审计）是商业平台给不了的
4. **代理层作补充**：LLMFactory 是 LLM 唯一出口，包 TraceProxy 可无侵入覆盖非 Agent 路径（RAG 链、数据分析）的 token/耗时

### 后续待办事项

- [ ] 一期落地：TraceCollector（后台线程异步写 SQLite）+ LLMFactory TraceProxy + Harness 埋点（plan/subtask/llm_call/tool_call/idempotent_block/resume）
- [ ] 成本观测：longcat/deepseek 路径记录 token 成本，单任务超阈值告警
- [ ] 前端 Agent 面板增加调用链（Trace）时间线视图

---

## 2026-08-16: Trace 一期方案落地（自建轻量 Trace，SDK 埋点 + 回调代理层）

### 业务需求描述

按 `docs/trace_evaluation.md` 评估结论落地一期：自建轻量 Trace（OTel 语义数据结构，
SQLite 存储，异步写入），实现"调试靠看"——Agent 每一步的决策、工具调用、LLM 消耗、
耗时、状态变化全程可观测，并与断点续跑/幂等审计共用 task_id 业务键。

### 实现方案

#### 新增文件

| 文件 | 职责 |
|------|------|
| `code/src/agent_trace.py` | TraceEvent（trace_id/span_id/parent_span_id/operation_name/duration_ms/attributes/resource/status，OTel 语义）+ TraceCollector（后台 daemon 线程异步批量写 SQLite `data/agent_traces.db`，队列满丢弃不阻塞）+ trace_span 上下文管理器 + ContextVar 当前 trace 绑定 + build_llm_trace_handler（LangChain callbacks 钩子） |

#### 修改文件

- `llm_factory.py`：三个 LLM 构造方法统一挂 `_trace_callbacks(provider)` —— **代理层的等价实现**（callbacks 钩子而非对象包装，不破坏 LCEL 链），无侵入捕获所有 LLM 调用（模型、token 用量、耗时、prompt/完成长度）
- `agent_harness.py`：新增 collector 注入（未启用时零开销）+ 关键节点埋点：
  `plan_create`（含失败回退）/ `plan_revise` / `subtask_schedule` / `tool_call`（预占位时间戳精确计时）/ `idempotent_block`（幂等拦截审计）/ `resume`（含未闭环调用恢复结果）/ `task_end`；run_loop 入口 `set_current_trace(task_id)` 使任意深处的 LLM 调用自动归属
- `app.py`：lifespan 最先初始化 TraceCollector（保证 RAG 链 LLM 创建即挂回调）；停机 flush；新增 `GET /api/agent/tasks/{task_id}/trace`（查询前 flush，返回 span 列表 + 累计耗时）
- `index.html`/`style.css`：Agent 面板新增"调用链 Trace 时间线"（span 列表、偏移时间轴、成功/失败标记、tokens/模型/工具摘要）

### 关键决策点

1. **代理层用 LangChain callbacks 而非对象包装（LLMProxy）**：RAG 链使用 LCEL 管道，包装对象会破坏 Runnable 协议；callbacks 钩子同样实现"零侵入拦截所有 LLM 调用"
2. **ContextVar 而非参数透传 trace_id**：Harness 主循环入口绑定 task_id，深处 LLM 调用（含失败自省、Planner）自动归属；非 Agent 路径（RAG 问答/数据分析）归属 `adhoc` 也可追踪
3. **trace_id = task_id**：与断点续跑、幂等审计、任务详情 API 共用同一业务键，前端一个 ID 查全部
4. **Trace 独立库文件 `agent_traces.db`**：与 agent_tasks.db 物理分离，避免与 StateStore 并发写锁竞争（双方均设 busy_timeout）
5. **异步批量写入 + 队列满丢弃告警**：Trace 故障绝不影响主流程（最佳实践：异步上报）
6. **低 QPS 全量上报**：不做采样；错误事件天然 100% 可见

### 遇到的问题及解决方案

1. **问题**：冒烟测试环境（隔离 venv）无 langchain
   **解决**：agent_trace.py 核心纯标准库；callbacks 处理器懒导入 + ImportError 返回 None（Trace 优雅降级）
2. **问题**：venv 安装 langchain-core 走 pypi 超时
   **解决**：清华 TUNA 镜像安装成功

### 验证结果

冒烟测试 6 场景 23 项全部通过：
1. Collector 异步落库/按 trace_id 查询/resource 注入/时间排序
2. span 上下文管理器：正常记录、异常 status=error、错误信息捕获
3. LLM 回调：事件归属当前 trace、token 统计（total_tokens=150）、模型名、耗时、无上下文归 adhoc、错误路径
4. Trace 关闭时零开销（build 返回 None、span 空操作）
5. Harness 端到端：plan_create/tool_call/idempotent_block/失败 error/task_end/trace_id=task_id
6. 全局 collector 自动注入

### 后续待办事项

- [ ] 成本观测：longcat/deepseek 路径按 token 单价折算成本，单任务超阈值告警（一期已记录 token 数）
- [ ] Trace 清理策略：按保留天数定期清理 agent_traces.db
- [ ] 二期（触发式）：Langfuse/Phoenix 自托管，OTLP 上报替换 SQLite 后端
