from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row as dict_row_factory

from focus_agent.storage.postgres import PostgresConnectionProvider


class PostgresMixin:
    database_uri: str
    connection_provider: PostgresConnectionProvider | None

    @contextmanager
    def _connection(self, *, dict_row: bool = False) -> Iterator[object]:
        row_factory = dict_row_factory if dict_row else None
        provider = getattr(self, "connection_provider", None)
        if provider is not None:
            with provider.connect(row_factory=row_factory) as conn:
                yield conn
            return

        kwargs: dict[str, Any] = {}
        if row_factory is not None:
            kwargs["row_factory"] = row_factory
        module = sys.modules.get(type(self).__module__)
        psycopg_module = getattr(module, "psycopg", psycopg)
        with psycopg_module.connect(self.database_uri, **kwargs) as conn:
            yield conn

    @contextmanager
    def _cursor(self, *, dict_row: bool = False) -> Iterator[object]:
        with self._connection(dict_row=dict_row) as conn:
            with conn.cursor() as cur:
                yield cur

    def _connect(self) -> object:
        return self._connection(dict_row=True)


__all__ = ["PostgresMixin", "dict_row_factory", "psycopg"]
