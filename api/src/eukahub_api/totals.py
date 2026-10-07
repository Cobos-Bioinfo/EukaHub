"""Cached row counts for the list endpoints.

A list's ``total`` is a ``count(*)`` over every row its filters match. The data
only changes when a new dataset build is installed, so each count is kept per
build and per filter set in a small in-process LRU: a query is counted once per
dataset instead of on every page. The build's timestamp is part of the key, so a
newly installed dataset is counted afresh.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Sequence

import psycopg

# Each entry is a 16-byte key and an int: 10,000 of them take about 2 MB.
MAX_ENTRIES = 10_000


class CountCache:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._entries: OrderedDict[bytes, int] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def count(self, conn: psycopg.Connection, sql: str, params: Sequence[object]) -> int:
        """How many rows ``sql`` returns, counted the first time it is asked for
        under the installed dataset build."""
        (built_at,) = conn.execute("SELECT max(built_at) FROM dataset_meta").fetchone()
        key = hashlib.blake2b(repr((built_at, sql, list(params))).encode(), digest_size=16).digest()
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]
        (n,) = conn.execute(f"SELECT count(*) FROM ({sql}) matches", params).fetchone()
        with self._lock:
            self._entries[key] = n
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
        return n


counts = CountCache()
