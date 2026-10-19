"""Query parameters shared by several resources."""

from typing import Annotated

import psycopg
from fastapi import Query, Request
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError

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


def only_known_parameters(request: Request) -> None:
    """Refuse query parameters the endpoint doesn't take: a typo such as ``rnak``
    would otherwise return an unfiltered list."""
    known = _query_parameters(request.scope["route"].dependant)
    unknown = [name for name in dict.fromkeys(request.query_params) if name not in known]
    if not unknown:
        return
    expected = (
        f"expected one of: {', '.join(sorted(known))}" if known else "this endpoint takes none"
    )
    raise RequestValidationError(
        [
            {
                "type": "extra_forbidden",
                "loc": ("query", name),
                "msg": f"Unknown parameter ({expected})",
                "input": request.query_params[name],
            }
            for name in unknown
        ]
    )


def _query_parameters(dependant: Dependant) -> set[str]:
    names = {param.alias for param in dependant.query_params}
    for sub in dependant.dependencies:
        names |= _query_parameters(sub)
    return names
