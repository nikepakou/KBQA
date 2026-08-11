"""数据库管理模块

封装 pymysql 连接与查询操作，提供数据库连接测试、Schema 获取以及安全 SELECT 查询执行能力。
连接采用懒加载策略（首次使用时才建立），并对查询行数与类型进行安全限制。
"""

import re
import logging

import pymysql

from config import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DATABASE,
    MAX_QUERY_ROWS,
    QUERY_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class DBManager:
    """MySQL 数据库管理器，提供懒加载连接、Schema 缓存与安全 SELECT 查询。"""

    def __init__(self, host=None, port=None, user=None, password=None, database=None):
        # 使用 config 默认值，若参数未提供则回退到配置常量
        self._host = host if host is not None else MYSQL_HOST
        self._port = port if port is not None else MYSQL_PORT
        self._user = user if user is not None else MYSQL_USER
        self._password = password if password is not None else MYSQL_PASSWORD
        self._database = database if database is not None else MYSQL_DATABASE
        self._connection = None
        self._schema_cache = None

    def connect(self) -> bool:
        """建立 MySQL 连接，成功返回 True，失败记录日志并返回 False（不抛异常）。"""
        try:
            # 若已有连接则先关闭，避免重复连接
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:
                    pass
            self._connection = pymysql.connect(
                host=self._host,
                port=int(self._port),
                user=self._user,
                password=self._password,
                database=self._database,
                charset="utf8mb4",
                connect_timeout=QUERY_TIMEOUT_SECONDS,
            )
            logger.info("数据库连接成功: %s@%s:%s/%s", self._user, self._host, self._port, self._database)
            return True
        except Exception as e:
            logger.error("数据库连接失败: %s@%s:%s/%s，错误: %s",
                         self._user, self._host, self._port, self._database, e)
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
                logger.info("数据库连接测试成功")
                return True
            finally:
                cursor.close()
        except Exception as e:
            logger.error("数据库连接测试失败: %s", e)
            return False

    def get_schema(self) -> dict:
        """获取当前数据库的表结构信息，结果按表名分组并缓存。

        返回格式: {table_name: [{"column": ..., "type": ..., "comment": ...}, ...]}
        连接失败时返回空 dict。
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
                sql = (
                    "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s "
                    "ORDER BY TABLE_NAME, ORDINAL_POSITION"
                )
                cursor.execute(sql, (self._database,))
                for table_name, column_name, data_type, column_comment in cursor.fetchall():
                    schema.setdefault(table_name, []).append({
                        "column": column_name,
                        "type": data_type,
                        "comment": column_comment,
                    })
            finally:
                cursor.close()

            self._schema_cache = schema
            logger.info("成功获取数据库结构，共 %d 张表", len(schema))
        except Exception as e:
            logger.error("获取数据库结构失败: %s", e)
            return {}

        return schema

    def execute_query(self, sql: str) -> dict:
        """执行 SELECT 查询并返回列与行数据。

        - 校验是否为 SELECT/WITH 查询，否则抛出 ValueError
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

            # 使用普通 Cursor（非 DictCursor），保证行以 tuple 返回
            cursor = self._connection.cursor()
            try:
                cursor.execute(final_sql)
                rows = cursor.fetchall()
                # 从 cursor.description 提取列名
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                else:
                    columns = []
                logger.info("查询执行成功，返回 %d 行 %d 列", len(rows), len(columns))
                return {"columns": columns, "rows": rows}
            finally:
                cursor.close()
        except Exception as e:
            logger.error("查询执行失败: SQL=%s，错误: %s", final_sql, e)
            raise

    def _is_select(self, sql: str) -> bool:
        """判断 SQL 是否为 SELECT 或 WITH 开头的查询（不区分大小写）。"""
        if not sql or not sql.strip():
            return False
        stripped = sql.strip()
        upper = stripped.upper()
        return upper.startswith("SELECT") or upper.startswith("WITH")

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
                logger.info("数据库连接已关闭")
            except Exception as e:
                logger.error("关闭数据库连接失败: %s", e)
            finally:
                self._connection = None
