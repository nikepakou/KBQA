# Tasks

- [x] Task 1: 创建数据库连接配置模块
  - [x] SubTask 1.1: 新建 `code/src/config.py`，包含 MySQL 连接配置（host/port/user/password/database）和 Ollama 配置，从环境变量读取
  - [x] SubTask 1.2: 在 `code/` 下创建 `.env.example` 模板文件
  - [x] SubTask 1.3: 更新 `requirements.txt`，添加 `pymysql`、`sqlparse`、`python-dotenv`

- [x] Task 2: 实现 MySQL 数据源管理模块
  - [x] SubTask 2.1: 新建 `code/src/db_manager.py`，实现 `DBManager` 类
  - [x] SubTask 2.2: 实现 `connect()` 方法，使用 pymysql 连接 MySQL，连接失败时抛出带提示的异常
  - [x] SubTask 2.3: 实现 `get_schema()` 方法，查询 `information_schema` 获取所有表名、字段名、字段类型、注释，缓存结果
  - [x] SubTask 2.4: 实现 `execute_query(sql, limit, timeout)` 方法，执行只读查询并返回 `{"columns": [...], "rows": [...]}`

- [x] Task 3: 实现 NL2SQL + 图表推荐核心模块
  - [x] SubTask 3.1: 新建 `code/src/data_analyzer.py`，实现 `DataAnalyzer` 类
  - [x] SubTask 3.2: 实现 `_build_nl2sql_prompt(question, schema)` 方法，组装表结构 + 用户问题的 prompt
  - [x] SubTask 3.3: 实现 `generate_sql(question)` 方法，调用 ChatOllama 生成 SQL，提取纯 SQL 语句
  - [x] SubTask 3.4: 实现 `_validate_sql(sql)` 方法，使用 sqlparse 解析，仅允许 SELECT 语句
  - [x] SubTask 3.5: 实现 `_build_chart_prompt(question, sql, columns, sample_rows)` 方法，组装图表推荐 prompt
  - [x] SubTask 3.6: 实现 `recommend_chart(question, sql, query_result)` 方法，调用 LLM 返回 `{"chart_type": "...", "option": {...}}` 或 `{"chart_type": "none"}`
  - [x] SubTask 3.7: 实现 `analyze(question)` 主方法，串联：生成 SQL → 校验 → 执行 → 推荐图表 → 返回完整结果

- [x] Task 4: 集成到 FastAPI 应用
  - [x] SubTask 4.1: 在 `app.py` 中导入 DBManager 和 DataAnalyzer，在 lifespan 中初始化（MySQL 连接失败不阻断启动）
  - [x] SubTask 4.2: 新增 `GET /api/db/tables` 端点，返回数据库表结构
  - [x] SubTask 4.3: 新增 `POST /api/analyze` 端点，接收 `{"question": "..."}`，返回 SQL + 图表配置 + 数据
  - [x] SubTask 4.4: 在 `/api/analyze` 中处理 DBManager 未就绪、SQL 校验失败、查询超时等异常

- [x] Task 5: 前端数据分析界面
  - [x] SubTask 5.1: 在 `index.html` 中添加 Tab 切换（知识库问答 / 数据分析）
  - [x] SubTask 5.2: 实现数据分析页布局：表结构面板、输入框、分析按钮、图表区、数据表格区
  - [x] SubTask 5.3: 引入 ECharts CDN，实现 `renderChart(option)` 函数渲染图表
  - [x] SubTask 5.4: 实现调用 `/api/analyze` 的 JS 逻辑，展示 SQL、图表、表格
  - [x] SubTask 5.5: 在 `style.css` 中添加数据分析页样式

# Task Dependencies

- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 2]
- [Task 4] depends on [Task 3]
- [Task 5] depends on [Task 4]
