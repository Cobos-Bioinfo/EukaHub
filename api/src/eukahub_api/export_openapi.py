"""Dump the API's OpenAPI schema to a file (or stdout) without a server or DB.

    uv run --package eukahub-api python -m eukahub_api.export_openapi \
        web/src/api/openapi.json

Importing ``app`` builds the FastAPI object but does not start its lifespan,
so no database connection is opened — this is a pure route/schema
introspection. The web build consumes the dumped JSON to generate TypeScript
types (``npm run gen:api``), keeping the frontend types in lockstep with the
metric config that drives the API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from eukahub_api.main import app


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if argv:
        out = Path(argv[0])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
