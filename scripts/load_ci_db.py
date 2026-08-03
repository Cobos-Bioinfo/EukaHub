"""Apply the schema + CI seed to a target Postgres.

Used by the CI workflow to seed a throwaway ``postgres`` service so the
DB-backed API tests can run (they otherwise skip when no DB is reachable — see
``api/tests/conftest.py``). Also handy locally to point a scratch DB at the
committed seed.

Reads ``DATABASE_URL`` (default: the docker-compose dev DB), applies every
``infra/postgres/init/*.sql`` (idempotent ``CREATE ... IF NOT EXISTS``), then
``api/tests/seed.sql`` (which TRUNCATEs and reloads the slice). The target DB
must already exist; in CI the service container creates it.

    DATABASE_URL=postgresql://... uv run python scripts/load_ci_db.py
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"


def main() -> None:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    with psycopg.connect(url) as conn:
        for sql_file in sorted((ROOT / "infra" / "postgres" / "init").glob("*.sql")):
            conn.execute(sql_file.read_text())
            print("applied", sql_file.name)
        conn.execute((ROOT / "api" / "tests" / "seed.sql").read_text())
        print("applied seed.sql")
        conn.commit()
        counts = {}
        for table in ("taxon", "clade_features", "assembly", "annotation"):
            counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"{table}: {counts[table]}")
        # Stamp dataset_meta so the /meta endpoint (and its test) exercises the
        # populated path in CI too, just like a real build's final step.
        conn.execute("TRUNCATE dataset_meta")
        conn.execute(
            "INSERT INTO dataset_meta "
            "(built_at, taxon_count, assembly_count, annotation_count, clade_count) "
            "VALUES (now(), %s, %s, %s, %s)",
            (counts["taxon"], counts["assembly"], counts["annotation"], counts["clade_features"]),
        )
        conn.commit()
        print("stamped dataset_meta")


if __name__ == "__main__":
    main()
