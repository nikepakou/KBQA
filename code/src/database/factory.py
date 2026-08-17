"""数据库工厂模块

根据运行环境创建相应的数据库管理器：
- local: 使用 SQLite 内存数据库（本地开发测试）
- production: 使用 MySQL 数据库（服务器部署）
"""

import logging

from config import ENVIRONMENT, MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
from database.db_manager import DBManager
from database.sqlite_manager import SQLiteDatabaseManager

logger = logging.getLogger(__name__)


class DatabaseFactory:
    """数据库管理器工厂类，根据环境创建相应的数据库管理器。"""

    @staticmethod
    def create_database_manager():
        """根据 ENVIRONMENT 配置创建数据库管理器。

        Returns:
            DBManager 或 SQLiteDatabaseManager 实例

        Raises:
            ValueError: 当 ENVIRONMENT 配置无效时
        """
        if ENVIRONMENT == "local":
            logger.info("使用 SQLite 内存数据库（本地开发环境）")
            return SQLiteDatabaseManager()
        elif ENVIRONMENT == "production":
            logger.info("使用 MySQL 数据库（服务器部署环境）")
            return DBManager(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DATABASE,
            )
        else:
            raise ValueError(f"无效的 ENVIRONMENT 配置: {ENVIRONMENT}，仅支持 'local' 或 'production'")

    @staticmethod
    def get_environment_info():
        """获取当前环境信息。

        Returns:
            dict: 包含环境名称和数据库类型
        """
        info = {
            "environment": ENVIRONMENT,
            "database_type": "SQLite (内存数据库)" if ENVIRONMENT == "local" else "MySQL",
        }
        logger.debug("当前环境信息: %s", info)
        return info
