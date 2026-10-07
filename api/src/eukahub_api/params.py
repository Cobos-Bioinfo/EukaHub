"""Query parameters shared by several resources."""

from typing import Annotated

import psycopg
from fastapi import Query

from eukahub_api.queries import fetch_root

Within = Annotated[
    int | None,
    Query(description="Only rows on this taxon or below it (e.g. 40674 for mammals)."),
]
Cursor = Annotated[
    str | None,
    Query(
        max_length=1000,
        description="``next`` or ``previous`` from a page with the same sort, for the "
        "page after or before it.",
    ),
]


def within_path(conn: psycopg.Connection, taxid: int | None) -> str | None:
    """The path of the ``within`` taxon; an unknown taxon is a 404 (see ``errors``)."""
    return None if taxid is None else fetch_root(conn, taxid)[2]
