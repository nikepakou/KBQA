# 智能数据分析功能 Spec

## Why

当前知识库问答系统仅支持文档 RAG 问答，用户无法直接对 MySQL 数据库中的业务数据进行自然语言分析。需要扩展系统，让用户用自然语言提问，由大模型生成 SQL 查询并执行，结果以 ECharts 图表可视化展示，实现"对话式数据分析"。

## What Changes

- 新增 MySQL 数据源连接管理（读取数据库元数据/表结构）
- 新增 NL2SQL 模块：基于大模型将自然语言转换为 SQL 查询
- 新增 SQL 安全执行器：白名单校验 + 只读限制 + 超时控制
- 新增图表推荐模块：由大模型根据查询结果推荐 ECharts 图表类型和配置
- 新增数据分析 API 端点（`/api/analyze`）
- 新增前端数据分析页面（Tab 切换：知识库问答 / 数据分析）
- 集成 ECharts CDN 渲染图表

## Impact

- Affected specs: `knowledge-base-qa`（前端新增 Tab 页，后端新增模块）
- Affected code:
  - `code/src/app.py` — 新增数据分析 API 路由
  - `code/src/data_analyzer.py` — **新建**，NL2SQL + SQL 执行 + 图表推荐核心逻辑
  - `code/src/db_manager.py` — **新建**，MySQL 连接与元数据管理
  - `code/src/templates/index.html` — 新增数据分析 Tab 和 ECharts 容器
  - `code/src/static/style.css` — 新增分析页样式
  - `code/requirements.txt` — 新增 `pymysql`、`sqlparse` 依赖
  - `code/src/config.py` — **新建**，数据库连接配置

## ADDED Requirements

### Requirement: MySQL 数据源管理

系统应能连接到 MySQL 数据库并读取表结构元数据，供大模型理解数据库 schema。

#### Scenario: 成功连接数据库并获取元数据

- **WHEN** 系统启动且 MySQL 连接配置有效
- **THEN** 系统自动连接 MySQL，缓存所有表名、字段名、字段类型和注释，供 NL2SQL 使用

#### Scenario: 数据库连接失败

- **WHEN** MySQL 不可达或凭证错误
- **THEN** 系统返回友好错误提示，数据分析功能标记为不可用，知识库问答不受影响

### Requirement: 自然语言转 SQL（NL2SQL）

系统应基于数据库 schema 元数据和用户自然语言问题，通过大模型生成可执行的 SQL 查询语句。

#### Scenario: 生成有效查询 SQL

- **WHEN** 用户输入"统计每个部门的员工数量"
- **THEN** 系统将表结构、用户问题组装为 prompt，调用 qwen3:4b 生成 `SELECT department, COUNT(*) FROM employees GROUP BY department` 形式的 SQL

#### Scenario: 模型生成非法 SQL

- **WHEN** 大模型生成的 SQL 包含 INSERT/UPDATE/DELETE/DROP 等写操作
- **THEN** 系统拒绝执行，返回"仅支持查询操作"的错误提示

### Requirement: SQL 安全执行

系统应在受限环境中执行大模型生成的 SQL，确保数据安全。

#### Scenario: 执行 SELECT 查询

- **WHEN** SQL 通过白名单校验（仅允许 SELECT）
- **THEN** 系统在 MySQL 上执行查询，返回结果集（限制最多 1000 行），超时 30 秒自动终止

#### Scenario: 阻止危险操作

- **WHEN** SQL 包含 `DROP TABLE`、`DELETE FROM` 等写操作
- **THEN** 系统通过 `sqlparse` 解析语句类型，拒绝非 SELECT 语句，返回安全提示

### Requirement: 图表智能推荐与渲染

系统应根据查询结果的数据特征，由大模型推荐合适的 ECharts 图表类型并生成配置。

#### Scenario: 聚合查询推荐柱状图

- **WHEN** 查询结果为两列数据（类别 + 数值），如部门名称和员工数量
- **THEN** 大模型推荐柱状图（bar），生成 ECharts option 配置 JSON，前端渲染为柱状图

#### Scenario: 时间序列推荐折线图

- **WHEN** 查询结果包含日期列和数值列
- **THEN** 大模型推荐折线图（line），生成对应 ECharts option

#### Scenario: 不适合图表展示

- **WHEN** 查询结果不适合图表（如单行单列、非结构化数据）
- **THEN** 系统仅以表格形式展示数据，不渲染图表

### Requirement: 数据分析 Web 界面

系统应在现有 Web 界面中新增数据分析 Tab 页。

#### Scenario: 切换到数据分析页

- **WHEN** 用户点击"数据分析"Tab
- **THEN** 显示数据分析界面，包含：数据库表结构预览、自然语言输入框、分析按钮、图表展示区、数据表格区

#### Scenario: 查看表结构

- **WHEN** 用户点击"表结构"按钮
- **THEN** 展示数据库中所有表名及各表字段信息（字段名、类型、注释）

#### Scenario: 执行分析并查看结果

- **WHEN** 用户输入分析问题并点击"分析"
- **THEN** 界面展示生成的 SQL（可折叠）、ECharts 图表、原始数据表格，全程流式反馈进度

## MODIFIED Requirements

无（本 spec 为纯新增功能，不修改现有知识库问答逻辑）

## REMOVED Requirements

无
