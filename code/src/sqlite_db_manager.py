"""SQLite 内存数据库管理模块

封装 sqlite3 连接与查询操作，提供与 DBManager 相同的接口，用于本地开发测试。
使用内存数据库（:memory:），无需安装 MySQL。
"""

import re
import logging
import sqlite3

from config import MAX_QUERY_ROWS

logger = logging.getLogger(__name__)


class SQLiteDatabaseManager:
    """SQLite 内存数据库管理器，提供与 DBManager 相同的接口。"""

    def __init__(self):
        """初始化 SQLite 内存数据库连接。"""
        self._connection = None
        self._schema_cache = None

    def connect(self) -> bool:
        """建立 SQLite 内存数据库连接，成功返回 True。"""
        try:
            # 若已有连接则先关闭
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:
                    pass

            # 创建内存数据库连接
            self._connection = sqlite3.connect(":memory:", check_same_thread=False)
            self._connection.row_factory = sqlite3.Row

            logger.info("SQLite 内存数据库连接成功")
            return True
        except Exception as e:
            logger.error("SQLite 内存数据库连接失败: %s", e)
            self._connection = None
            return False

    def test_connection(self) -> bool:
        """测试数据库连接是否可用，执行 SELECT 1 验证。"""
        try:
            if not self.connect():
                return False
            cursor = self._connection.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                logger.info("SQLite 数据库连接测试成功")
                return True
            finally:
                cursor.close()
        except Exception as e:
            logger.error("SQLite 数据库连接测试失败: %s", e)
            return False

    def get_schema(self) -> dict:
        """获取当前数据库的表结构信息。

        返回格式: {table_name: [{"column": ..., "type": ..., "comment": ...}, ...]}
        连接失败时返回空 dict。

        注意：SQLite 内存数据库默认为空，需要手动创建表。
        """
        # 命中缓存直接返回
        if self._schema_cache is not None:
            return self._schema_cache

        schema = {}
        try:
            if self._connection is None and not self.connect():
                logger.error("获取数据库结构失败：无法建立数据库连接")
                return {}

            cursor = self._connection.cursor()
            try:
                # 查询所有表
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                tables = [row[0] for row in cursor.fetchall()]

                # 查询每个表的列信息
                for table_name in tables:
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns_info = cursor.fetchall()
                    schema[table_name] = [
                        {
                            "column": col[1],
                            "type": col[2],
                            "comment": "",  # SQLite 不支持列注释
                        }
                        for col in columns_info
                    ]
            finally:
                cursor.close()

            self._schema_cache = schema
            logger.info("成功获取 SQLite 数据库结构，共 %d 张表", len(schema))
        except Exception as e:
            logger.error("获取 SQLite 数据库结构失败: %s", e)
            return {}

        return schema

    def execute_query(self, sql: str) -> dict:
        """执行 SELECT 查询并返回列与行数据。

        - 校验是否为 SELECT 查询，否则抛出 ValueError
        - 若 SQL 未包含 LIMIT，自动追加 LIMIT {MAX_QUERY_ROWS}
        - 返回 {"columns": [...], "rows": [...]}，行以 tuple 形式返回
        - 出错时记录日志并重新抛出异常
        """
        # 校验查询类型
        if not self._is_select(sql):
            logger.warning("拒绝执行非 SELECT 查询: %s", sql)
            raise ValueError("仅支持 SELECT 查询")

        # 若 SQL 未包含 LIMIT，则自动追加行数限制
        final_sql = sql
        if not self._has_limit(sql):
            final_sql = f"{sql.rstrip(';')} LIMIT {MAX_QUERY_ROWS}"
            logger.info("已自动追加 LIMIT %d 限制查询行数", MAX_QUERY_ROWS)

        try:
            if self._connection is None and not self.connect():
                raise RuntimeError("无法建立数据库连接")

            cursor = self._connection.cursor()
            try:
                cursor.execute(final_sql)
                raw_rows = cursor.fetchall()
                # 从 cursor.description 提取列名
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                else:
                    columns = []
                # 归一化：将 sqlite3.Row 转换为 tuple（保证 JSON 序列化后是数组）
                rows = [tuple(r) for r in raw_rows]
                logger.info("查询执行成功，返回 %d 行 %d 列", len(rows), len(columns))
                return {"columns": columns, "rows": rows}
            finally:
                cursor.close()
        except Exception as e:
            logger.error("查询执行失败: SQL=%s，错误: %s", final_sql, e)
            raise

    def _is_select(self, sql: str) -> bool:
        """判断 SQL 是否为 SELECT 查询（不区分大小写）。"""
        if not sql or not sql.strip():
            return False
        stripped = sql.strip()
        upper = stripped.upper()
        return upper.startswith("SELECT")

    def _has_limit(self, sql: str) -> bool:
        """检查 SQL 是否已包含 LIMIT 子句（不区分大小写）。"""
        if not sql:
            return False
        # 使用单词边界匹配 LIMIT 关键字
        return re.search(r"\bLIMIT\b", sql, re.IGNORECASE) is not None

    def close(self):
        """关闭数据库连接（若已打开）。"""
        if self._connection is not None:
            try:
                self._connection.close()
                logger.info("SQLite 数据库连接已关闭")
            except Exception as e:
                logger.error("关闭 SQLite 数据库连接失败: %s", e)
            finally:
                self._connection = None

    def create_sample_tables(self):
        """创建示例表，用于本地开发测试。

        创建一些示例表和数据，方便测试数据分析功能。
        """
        try:
            if self._connection is None and not self.connect():
                logger.error("无法创建示例表：数据库连接失败")
                return

            cursor = self._connection.cursor()
            try:
                # 创建示例表：用户表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        age INTEGER,
                        city TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # 创建示例表：订单表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        product_name TEXT NOT NULL,
                        amount REAL,
                        order_date DATE,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                """)

                # 插入示例数据
                cursor.execute("INSERT INTO users (name, age, city) VALUES ('张三', 25, '北京')")
                cursor.execute("INSERT INTO users (name, age, city) VALUES ('李四', 30, '上海')")
                cursor.execute("INSERT INTO users (name, age, city) VALUES ('王五', 28, '广州')")
                cursor.execute("INSERT INTO users (name, age, city) VALUES ('赵六', 35, '深圳')")
                cursor.execute("INSERT INTO users (name, age, city) VALUES ('钱七', 22, '杭州')")

                cursor.execute(
                    "INSERT INTO orders (user_id, product_name, amount, order_date) VALUES (1, '笔记本电脑', 5999.00, '2024-01-15')"
                )
                cursor.execute(
                    "INSERT INTO orders (user_id, product_name, amount, order_date) VALUES (2, '手机', 2999.00, '2024-01-16')"
                )
                cursor.execute(
                    "INSERT INTO orders (user_id, product_name, amount, order_date) VALUES (3, '平板电脑', 3999.00, '2024-01-17')"
                )
                cursor.execute(
                    "INSERT INTO orders (user_id, product_name, amount, order_date) VALUES (1, '耳机', 299.00, '2024-01-18')"
                )
                cursor.execute(
                    "INSERT INTO orders (user_id, product_name, amount, order_date) VALUES (4, '键盘', 599.00, '2024-01-19')"
                )

                self._connection.commit()
                logger.info("示例表和数据创建成功")

                # 清空 schema 缓存
                self._schema_cache = None
            finally:
                cursor.close()
        except Exception as e:
            logger.error("创建示例表失败: %s", e)
