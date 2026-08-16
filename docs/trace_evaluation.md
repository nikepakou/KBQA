# KBQA 项目 Trace 方案评估

> 依据：Obsidian《20260815_技术_Trace模块引入与行业实践》（2026-08-16）
> 评估对象：KBQA 当前架构（自研 Agent Harness + Planner + 多提供商 LLM）

## 一、项目关键特征（选型约束）

| 特征 | 现状 | 对选型的影响 |
|------|------|-------------|
| Agent 主循环 | **自研 Harness**（agent_harness.py），非 LangGraph/AgentExecutor | 框架自动埋点（方式二）覆盖不到关键决策节点 |
| LLM 接入 | LLMFactory 统一封装 ollama / longcat / deepseek | 存在**统一出口**，代理层（方式三）可行且有价值 |
| 已有可观测基础 | AgentState.messages + tool_records（含入参出参/recovered 标记）+ biz_context | 结构化数据已存在，是 Trace 雏形，增量成本低 |
| 部署形态 | 单机、SQLite 状态库、本地 Milvus/MySQL、本地 ollama 为主 | 排除 SaaS 方案（数据出境 + 网络依赖） |
| 数据敏感度 | 知识库文档 + 业务库 SQL 数据 | Trace 数据（含 prompt/结果）不宜出本机 |
| 规模 | 低 QPS、个人/小团队项目 | 不需要 ClickHouse/Kafka 级存储；全量上报即可 |
| 任务标识 | task_id 已是全链路唯一键（断点续跑/幂等审计均依赖） | **task_id = trace_id**，天然与可观测打通 |

## 二、行业方案逐一评估

### 1. LangSmith ❌ 不推荐

- SaaS 为主（自托管为企业付费版），**数据出境**与本项目数据敏感约束冲突
- 主循环自研：LangChain 自动 Trace 只能捕获底层 `llm.invoke`，**Harness 的决策/规划/幂等拦截等关键节点全部不可见**——恰好是本项目最需要观测的部分
- 国内网络访问不稳定

### 2. Langfuse ⚠️ 二期候选

- 开源可自托管，数据可控，能力最全（Prompt 版本管理、评估、成本统计）
- 但自托管需部署 Postgres + ClickHouse + Server（Docker Compose），对单机个人项目**运维偏重**
- 适合：项目走向多用户/团队协作、需要可视化面板与评估工作流时引入

### 3. Arize Phoenix ⚠️ 二期候选（轻于 Langfuse）

- 开源，支持本地 Python 进程内启动（`pip install arize-phoenix` 即可用，无需重型服务端）
- OpenInference 语义标准，搜索/过滤强，带幻觉等质量评估
- 适合：需要**深度质量评估**（检索命中率、幻觉检测）时引入

### 4. W&B ❌ 不推荐

- 定位 ML 实验追踪，本项目无超参实验需求；云端服务同样有数据出境问题

### 5. 自建轻量 Trace ✅ 一期推荐

- 项目已具备全部基础设施：SQLite StateStore、结构化 tool_records、task_id 全链路键
- 按文档第五节"行业共识数据结构"（trace_id/span_id/parent_span_id/operation_name/attributes/resource/status）扩展即可
- **零新增部署、数据不出机、与断点续跑/幂等审计天然关联**——商业方案给不了 task_id ↔ tool_records ↔ pending_tool_call 这层业务关联

## 三、结论：分阶段组合方案

### 一期（现在做）：SDK 嵌入 + 代理层组合，自建轻量 Trace 落 SQLite

文档三种引入方式的适配结论：

| 方式 | 是否采用 | 理由 |
|------|---------|------|
| 方式一 SDK 嵌入 | ✅ 主力 | 主循环是自己的，在 Harness 关键节点埋点最准确、最完整 |
| 方式二 框架集成 | ❌ | 自研循环，框架自动埋点覆盖不到决策/规划/恢复节点 |
| 方式三 代理层 | ✅ 补充 | LLMFactory 是统一出口，包一层 TraceProxy 可无侵入捕获**所有** LLM 调用（含 RAG 链、数据分析等非 Agent 路径）的 token/耗时/模型 |

具体埋点清单：

```
trace 根节点（task_id = trace_id）
├── plan_create / plan_revise          # Planner 规划与重规划（版本、子任务数）
├── subtask_schedule                    # DAG 调度（subtask_id、依赖状态）
├── llm_call                            # 经 LLMProxy 自动记录（模型、token、耗时、finish_reason）
├── tool_call                           # 复用并扩展现有 tool_records（duration、status、recovered）
├── idempotent_block                    # 重复调用拦截事件（命中历史结果）
└── state_change / resume               # 断点续跑、崩溃恢复事件（recovered 标记）
```

数据结构遵循文档第五节共识字段（trace_id/span_id/parent_span_id/operation_name/duration_ms/attributes/resource/status），**为二期迁移商业平台预留 OTLP 兼容性**。

一期遵循的最佳实践（文档第六节）：

- 异步写入：trace 写入走后台线程队列，不阻塞主循环
- 采样：低 QPS 场景全量上报，不做采样
- 业务关联：resource 段固定携带 task_id、LLM_PROVIDER、ENVIRONMENT、app 版本
- 成本观测：ollama 本地零成本；longcat/deepseek 路径记录 token 估算成本，单任务 token 超阈值告警日志

### 二期（触发条件明确后再做）：Langfuse 或 Phoenix 自托管

- 触发条件（满足任一）：
  1. 需要可视化调用链面板/团队共享观测数据
  2. 需要检索质量评估、幻觉检测等深度分析
  3. 项目走向多实例部署（Trace 存储随之升级）
- 迁移成本低：一期自建数据结构按 OpenTelemetry/OpenInference 语义设计，二期只需把 Collector 的存储后端从 SQLite 换成 OTLP 上报

## 四、为什么不"直接上 Langfuse/Phoenix"

按文档最佳实践第 1 条"从一开始就加"——Trace 该立刻加，但**加的应该是与架构耦合的埋点，而非重型平台**。本项目当前瓶颈是"看不见 Harness 在干什么"，一期轻量自建即可 100% 解决；平台化（面板、评估）是规模化之后的需求，提前引入只会增加部署负担且数据结构被平台绑架（文档方式二的缺点）。
