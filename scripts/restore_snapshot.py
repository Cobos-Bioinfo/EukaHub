"""Install a dataset snapshot (``pg_dump -Fc``) as the live serving database.

Restores into ``<db>_next`` while the live database keeps serving, verifies it with
the pipeline's ``check_invariants``, then swaps by renaming databases and keeps the
old one as ``<db>_prev`` for ``--rollback``. Any failure before the swap leaves the
live database untouched. Databases are renamed rather than schemas because the
``ltree``/``pg_trgm`` extensions live in ``public``; the swap terminates open
sessions on the renamed databases.

    uv run python scripts/restore_snapshot.py --dump snap.dump [--dry-run]
    uv run python scripts/restore_snapshot.py --url https://.../eukahub-dataset.dump
    uv run python scripts/restore_snapshot.py --rollback

``DATABASE_URL`` names the live database; its role must be able to create and
rename databases.
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


class RestoreError(RuntimeError):
    """A restore step failed; the live database was left untouched."""


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
        raise RestoreError("DATABASE_URL does not name a database")
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
    """Close other sessions on ``name`` so it can be renamed or dropped."""
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


def download(url: str, dest: Path) -> Path:
    """Fetch a snapshot over HTTP(S) to ``dest``."""
    log.info("downloading %s", url)
    with urllib.request.urlopen(url, timeout=600) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)
    log.info("downloaded %.1f MB to %s", dest.stat().st_size / 1_048_576, dest)
    return dest


def _pg_restore(url: str, dbname: str, dump: Path) -> None:
    """Load the custom-format dump into an existing empty database.

    ``--no-owner``/``--no-privileges`` keep the restore working when the
    serving role differs from whichever role produced the dump in CI. Runs as a
    single job on purpose: the target host has one CPU core, where parallel
    jobs only compete with the site that is still serving meanwhile.
    """
    if shutil.which("pg_restore") is None:
        raise RestoreError(
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
        str(dump),
    ]
    log.info("restoring into %s", dbname)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        log.error("pg_restore failed:\n%s", result.stderr.strip()[:4000])
        raise RestoreError(f"pg_restore exited {result.returncode}")
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
            raise RestoreError(f"no {previous} database to roll back to")
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

    if not args.rollback and not args.dump and not args.url:
        parser.error("one of --dump, --url or --rollback is required")
    try:
        if args.rollback:
            rollback(url)
            return
        with tempfile.TemporaryDirectory() as tmp:
            dump = args.dump if args.dump else download(args.url, Path(tmp) / "snapshot.dump")
            if not dump.exists():
                raise RestoreError(f"{dump} does not exist")
            restore(url, dump, dry_run=args.dry_run)
    except (RestoreError, DataValidationError) as exc:
        raise SystemExit(f"restore failed: {exc}") from exc


if __name__ == "__main__":
    main()
