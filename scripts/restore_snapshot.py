"""Restore a rebuilt dataset snapshot into the serving Postgres, safely.

The monthly ``rebuild.yml`` workflow produces a validated ``pg_dump`` snapshot
but stops there. This is the other half: it takes that snapshot and makes it
the live dataset, without a window where the site serves a half-loaded
database and without a failure mode that leaves no way back.

Why not just ``pg_restore --clean`` at the live DB: that drops the tables
first, so every request errors for the minutes the reload takes, and a restore
that dies halfway leaves neither the old nor the new dataset. Instead:

    1. restore the snapshot into a STAGING database (``<db>_next``), while the
       live database keeps serving untouched;
    2. verify the staging copy with the pipeline's own ``check_invariants``
       (non-empty tables, the species-universe rollup identity, coverage never
       exceeding species, the composition split reconciling);
    3. only then swap, by renaming databases;
    4. keep the previous dataset as ``<db>_prev`` so a rollback is one command.

If anything fails before step 3, the live database is never touched: the site
keeps serving the previous dataset and exits non-zero so the caller can alert.
A stale dataset is a much better failure than a broken one.

The swap renames databases rather than schemas because the ``ltree`` and
``pg_trgm`` extensions live in ``public``; renaming ``public`` out from under
them would break every LTREE column. Renaming requires no open connections, so
the live sessions are terminated first. The API's psycopg pool reconnects on
its own, making the visible interruption a second or two rather than minutes.

    # from a local file
    uv run python scripts/restore_snapshot.py --dump eukahub-dataset-20260901.dump

    # from a URL (GITHUB_TOKEN is sent as a bearer token when set)
    uv run python scripts/restore_snapshot.py --url https://.../eukahub-dataset.dump

    # restore and verify, but stop short of going live
    uv run python scripts/restore_snapshot.py --dump snap.dump --dry-run

    # put the previous dataset back
    uv run python scripts/restore_snapshot.py --rollback

``DATABASE_URL`` names the live database (default: the compose dev DB). The
connecting role must be allowed to CREATE DATABASE and to rename databases,
which the owning role already is.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import psycopg
from eukahub_pipeline.validate import DataValidationError, check_invariants
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

log = logging.getLogger("restore")

DEFAULT_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"
# Postgres caps identifiers at 63 bytes; the suffixed names must still fit.
STAGING_SUFFIX = "_next"
PREVIOUS_SUFFIX = "_prev"


def _admin_url(url: str, dbname: str = "postgres") -> str:
    """Same server and credentials, but pointed at a maintenance database.

    Renaming a database is impossible from a session connected to it, so every
    DDL step here runs against ``postgres`` instead.
    """
    params = conninfo_to_dict(url)
    params["dbname"] = dbname
    return make_conninfo(**params)


def _live_dbname(url: str) -> str:
    name = conninfo_to_dict(url).get("dbname")
    if not name:
        raise SystemExit("DATABASE_URL does not name a database")
    return str(name)


def _connect_admin(url: str) -> psycopg.Connection:
    """Autocommit connection for CREATE/DROP/ALTER DATABASE, which cannot run
    inside a transaction block."""
    return psycopg.connect(_admin_url(url), autocommit=True)


def _database_exists(conn: psycopg.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
    return row is not None


def _drop_database(conn: psycopg.Connection, name: str) -> None:
    if not _database_exists(conn, name):
        return
    _terminate_connections(conn, name)
    conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    log.info("dropped %s", name)


def _terminate_connections(conn: psycopg.Connection, name: str) -> None:
    """Close other sessions on ``name`` so it can be renamed or dropped.

    The API's pooled connections are the expected occupants; psycopg_pool
    transparently reconnects, so this costs a moment of reconnects rather than
    an outage.
    """
    conn.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (name,),
    )


def _rename_database(conn: psycopg.Connection, old: str, new: str) -> None:
    _terminate_connections(conn, old)
    conn.execute(
        sql.SQL("ALTER DATABASE {} RENAME TO {}").format(sql.Identifier(old), sql.Identifier(new))
    )
    log.info("renamed %s -> %s", old, new)


def _download(url: str, dest: Path) -> Path:
    """Fetch a snapshot over HTTP(S). Sends GITHUB_TOKEN as a bearer token when
    present, so a private-repo release or artifact URL works unchanged."""
    request = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    log.info("downloading %s", url)
    with urllib.request.urlopen(request, timeout=600) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)
    log.info("downloaded %.1f MB to %s", dest.stat().st_size / 1_048_576, dest)
    return dest


def _pg_restore(url: str, dbname: str, dump: Path) -> None:
    """Load the custom-format dump into an existing empty database.

    ``--no-owner``/``--no-privileges`` keep the restore working when the
    serving role differs from whichever role produced the dump in CI.
    """
    if shutil.which("pg_restore") is None:
        raise SystemExit(
            "pg_restore not found on PATH. Install the postgresql-client "
            "package matching the server major version."
        )
    cmd = [
        "pg_restore",
        "--dbname",
        _admin_url(url, dbname),
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        "--jobs",
        "4",
        str(dump),
    ]
    log.info("restoring into %s", dbname)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        log.error("pg_restore failed:\n%s", result.stderr.strip()[:4000])
        raise SystemExit(f"pg_restore exited {result.returncode}")
    log.info("restore complete")


def _verify(url: str, dbname: str) -> None:
    """Run the pipeline's invariant checks against the staged copy."""
    with psycopg.connect(_admin_url(url, dbname)) as conn:
        check_invariants(conn)
        row = conn.execute(
            "SELECT built_at, taxon_count, assembly_count, annotation_count, clade_count "
            "FROM dataset_meta"
        ).fetchone()
        if row is None:
            raise DataValidationError("dataset_meta is empty; snapshot is not a full build")
        log.info(
            "staged dataset built_at=%s taxon=%s assembly=%s annotation=%s clade=%s",
            *row,
        )


def restore(url: str, dump: Path, *, dry_run: bool = False) -> None:
    live = _live_dbname(url)
    staging = f"{live}{STAGING_SUFFIX}"
    previous = f"{live}{PREVIOUS_SUFFIX}"

    with _connect_admin(url) as admin:
        # A staging DB may survive an earlier interrupted run; start clean.
        _drop_database(admin, staging)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(staging)))
        log.info("created %s", staging)

    try:
        _pg_restore(url, staging, dump)
        _verify(url, staging)
    except BaseException:
        # Verification failed, or the restore died. The live dataset was never
        # touched, so the site keeps serving. Clear the staging DB and re-raise.
        log.error("staging failed; live database %s left untouched", live)
        with _connect_admin(url) as admin:
            _drop_database(admin, staging)
        raise

    if dry_run:
        log.info("dry run: %s verified but not promoted; dropping it", staging)
        with _connect_admin(url) as admin:
            _drop_database(admin, staging)
        return

    # Everything below is metadata-only and runs in well under a second.
    with _connect_admin(url) as admin:
        _drop_database(admin, previous)
        if _database_exists(admin, live):
            _rename_database(admin, live, previous)
        _rename_database(admin, staging, live)
    log.info("promoted: %s is now live, previous dataset kept as %s", live, previous)


def rollback(url: str) -> None:
    live = _live_dbname(url)
    previous = f"{live}{PREVIOUS_SUFFIX}"
    failed = f"{live}_failed"
    with _connect_admin(url) as admin:
        if not _database_exists(admin, previous):
            raise SystemExit(f"no {previous} database to roll back to")
        _drop_database(admin, failed)
        if _database_exists(admin, live):
            _rename_database(admin, live, failed)
        _rename_database(admin, previous, live)
    log.info("rolled back: %s restored, the promoted dataset kept as %s", live, failed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--dump", type=Path, help="path to a pg_dump custom-format snapshot")
    source.add_argument("--url", help="URL to download the snapshot from")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="restore and verify into staging, then discard without going live",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="put the previous dataset back and keep the current one aside",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)

    if args.rollback:
        rollback(url)
        return
    if not args.dump and not args.url:
        parser.error("one of --dump, --url or --rollback is required")

    with tempfile.TemporaryDirectory() as tmp:
        dump = args.dump if args.dump else _download(args.url, Path(tmp) / "snapshot.dump")
        if not dump.exists():
            raise SystemExit(f"{dump} does not exist")
        restore(url, dump, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
