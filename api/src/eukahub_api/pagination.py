"""Keyset (cursor) pagination for the list endpoints.

A page is sorted by a list of keys that ends in a unique one, so the rows form a
total order. A cursor holds the key values of the row a page starts after (or,
going back, before), and the next query filters on them instead of skipping
``offset`` rows, so a deep page costs the same as the first. Cursors are opaque to
clients: base64url JSON naming the ordering they belong to.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

# Python types a cursor value may have, by the SQL type of its key.
_VALUE_TYPES: dict[str, tuple[type, ...]] = {
    "bigint": (int,),
    "integer": (int,),
    "real": (float, int),
    "text": (str,),
    "date": (str,),
    "boolean": (bool,),
}
_MAX_INT = 2**63
_MAX_TEXT = 500


@dataclass(frozen=True, slots=True)
class Key:
    """One sort key: a trusted SQL expression (never request input), the SQL type
    of its values, and its direction."""

    sql: str
    type: str
    descending: bool = False


@dataclass(frozen=True, slots=True)
class Cursor:
    values: list[object]
    backward: bool  # the page ends before ``values`` rather than starting after them


class InvalidCursor(ValueError):
    """A cursor this API did not issue for this ordering."""


def encode(values: Sequence[object], *, ordering: str, backward: bool) -> str:
    payload = {
        "o": ordering,
        "b": backward,
        "v": [v.isoformat() if isinstance(v, date) else v for v in values],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(token: str, *, ordering: str, keys: Sequence[Key]) -> Cursor:
    """The cursor in ``token``, checked against ``ordering`` and the keys' types,
    or ``InvalidCursor``."""
    try:
        payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except (binascii.Error, ValueError) as e:
        raise InvalidCursor("this cursor was not issued by this API") from e
    if not isinstance(payload, dict) or payload.get("o") != ordering:
        raise InvalidCursor("this cursor belongs to another sort order; start without it")
    values, backward = payload.get("v"), payload.get("b")
    if not isinstance(values, list) or len(values) != len(keys) or not isinstance(backward, bool):
        raise InvalidCursor("this cursor was not issued by this API")
    for key, value in zip(keys, values, strict=True):
        if value is not None and not _valid(key.type, value):
            raise InvalidCursor("this cursor was not issued by this API")
    return Cursor(values, backward)


def _valid(sql_type: str, value: object) -> bool:
    if isinstance(value, bool) != (sql_type == "boolean"):
        return False
    if not isinstance(value, _VALUE_TYPES[sql_type]):
        return False
    if isinstance(value, int) and not isinstance(value, bool):
        return -_MAX_INT <= value < _MAX_INT
    if sql_type == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
    return not isinstance(value, str) or len(value) <= _MAX_TEXT


def key_columns(keys: Sequence[Key]) -> str:
    """The keys as SELECT items named ``k0``, ``k1``, ...; the other helpers refer
    to them by these names."""
    return ", ".join(f"{k.sql} AS k{i}" for i, k in enumerate(keys))


def order_by(keys: Sequence[Key], *, backward: bool = False, table: str = "") -> str:
    prefix = f"{table}." if table else ""
    return ", ".join(
        f"{prefix}k{i} {'DESC' if k.descending != backward else 'ASC'}" for i, k in enumerate(keys)
    )


def beyond(keys: Sequence[Key], cursor: Cursor) -> tuple[str, list[object]]:
    """A condition over ``k0``, ``k1``, ... keeping the rows after the cursor in the
    keys' order, or before it for a backward cursor, with its parameters. Equality
    is ``IS NOT DISTINCT FROM`` so that a null key value compares as a value."""
    clauses: list[str] = []
    params: list[object] = []
    for i, key in enumerate(keys):
        terms = []
        for j in range(i):
            terms.append(f"k{j} IS NOT DISTINCT FROM %s::{keys[j].type}")
            params.append(cursor.values[j])
        op = ">" if key.descending == cursor.backward else "<"
        terms.append(f"k{i} {op} %s::{key.type}")
        params.append(cursor.values[i])
        clauses.append(f"({' AND '.join(terms)})")
    return f"({' OR '.join(clauses)})", params


@dataclass(frozen=True, slots=True)
class Page[T]:
    rows: list[T]
    next: str | None
    previous: str | None


def page[T](
    rows: list[T],
    keys_of: Sequence[Sequence[object]],
    *,
    limit: int,
    cursor: Cursor | None,
    ordering: str,
) -> Page[T]:
    """A page from up to ``limit + 1`` rows fetched in cursor order (the extra row
    only says that more follow), with ``keys_of`` the key values of each row."""
    more = len(rows) > limit
    rows, keys_of = rows[:limit], list(keys_of[:limit])
    backward = cursor is not None and cursor.backward
    if backward:
        rows.reverse()
        keys_of.reverse()
    has_previous = more if backward else cursor is not None
    has_next = True if backward else more
    if not rows:
        return Page(rows, None, None)
    return Page(
        rows,
        next=encode(keys_of[-1], ordering=ordering, backward=False) if has_next else None,
        previous=encode(keys_of[0], ordering=ordering, backward=True) if has_previous else None,
    )
