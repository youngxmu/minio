import os
from typing import Any, Dict
from urllib.parse import parse_qs, unquote, urlparse


SUCAI_META_DATABASE = "sucai_meta"


def parse_mysql_dsn(dsn: str) -> Dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in ("mysql", "mysql+pymysql"):
        raise ValueError("metadata DSN must use mysql:// or mysql+pymysql://")

    database = parsed.path.lstrip("/")
    if database != SUCAI_META_DATABASE:
        raise ValueError("metadata DSN must point to database " + SUCAI_META_DATABASE)

    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": query.get("charset", ["utf8mb4"])[0],
    }


def connect_mysql(dsn: str):
    try:
        import pymysql
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyMySQL is required. Install requirements-cold-backup.txt before starting the API.") from exc

    config = parse_mysql_dsn(dsn)
    return pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        charset=config["charset"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def connect_from_env(env_name: str = "SUCAI_META_DSN"):
    dsn = os.environ.get(env_name)
    if not dsn:
        raise RuntimeError(env_name + " is required to connect to sucai_meta")
    return connect_mysql(dsn)
