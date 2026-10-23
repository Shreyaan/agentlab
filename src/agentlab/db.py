"""Postgres connection pool shared by the results store and the sandbox environments."""

import os

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

type Pool = ConnectionPool[Connection[DictRow]]

DATABASE_URL_ENV = "AGENTLAB_DATABASE_URL"


def database_url(explicit: str | None = None) -> str:
    url = explicit or os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise ValueError(f"no database configured: pass --database-url or set {DATABASE_URL_ENV}")
    return url


def open_pool(url: str, max_size: int = 20) -> Pool:
    pool: Pool = ConnectionPool(
        url,
        connection_class=Connection[DictRow],
        kwargs={"row_factory": dict_row},
        min_size=1,
        max_size=max_size,
        open=True,
    )
    pool.wait(timeout=15)
    return pool


def pool_conninfo(pool: Pool) -> str:
    """The pool's connection string (psycopg_pool also accepts a callable that produces one)."""
    info = pool.conninfo
    return info if isinstance(info, str) else info()
