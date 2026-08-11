# Checklist

- [x] `config.py` 存在且包含 MySQL 连接配置，支持从环境变量读取
- [x] `requirements.txt` 已添加 `pymysql`、`sqlparse`、`python-dotenv`
- [x] `db_manager.py` 的 `get_schema()` 能正确返回表名、字段名、字段类型、注释
- [x] `db_manager.py` 的 `execute_query()` 仅执行 SELECT 查询，限制返回行数（≤1000）和超时（30s）
- [x] `data_analyzer.py` 的 `generate_sql()` 能将自然语言转换为有效 SQL
- [x] `data_analyzer.py` 的 `_validate_sql()` 能阻止 INSERT/UPDATE/DELETE/DROP 等写操作
- [x] `data_analyzer.py` 的 `recommend_chart()` 能根据查询结果返回 ECharts option 配置
- [x] `data_analyzer.py` 的 `analyze()` 能串联完整流程：NL→SQL→校验→执行→图表推荐
- [x] `app.py` 新增 `GET /api/db/tables` 端点，返回数据库表结构
- [x] `app.py` 新增 `POST /api/analyze` 端点，返回 SQL + 图表配置 + 数据
- [x] MySQL 连接失败时不阻断应用启动，知识库问答功能正常可用
- [x] 前端新增数据分析 Tab 页，可切换知识库问答和数据分析
- [x] 前端表结构面板能展示数据库表和字段信息
- [x] 前端 ECharts 图表能正确渲染柱状图、折线图、饼图等
- [x] 前端展示生成的 SQL（可折叠）、图表、数据表格
- [x] 非法 SQL 操作返回友好错误提示，不执行危险操作
