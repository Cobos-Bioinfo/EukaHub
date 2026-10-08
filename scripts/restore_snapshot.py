"""Install a dataset snapshot (``pg_dump -Fc``) as the live serving database.

Restores into ``<db>_next`` while the live database keeps serving, collects planner
statistics, verifies it with the pipeline's ``check_invariants``, records which
Release it came from, then swaps by renaming databases and keeps the old one as
``<db>_prev`` for ``--rollback``. Any failure before the swap leaves the live
database untouched, and ``repair`` finishes a swap that was interrupted. Databases
are renamed rather than schemas because the ``ltree``/``pg_trgm`` extensions live
in ``public``; a rename refuses new sessions on the database, then closes the open
ones.

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
from typing import NamedTuple

import psycopg
from eukahub_pipeline.validate import DataValidationError, check_invariants
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

log = logging.getLogger("restore")

DEFAULT_URL = "postgresql://eukahub:eukahub@localhost:5432/eukahub"
# Postgres caps identifiers at 63 bytes; the suffixed names must still fit.
STAGING_SUFFIX = "_next"
PREVIOUS_SUFFIX = "_prev"
# The live database while a rollback swaps it with the previous one.
SWAP_SUFFIX = "_swap"
# Left by rollbacks of older versions of this script, which kept a third copy.
FAILED_SUFFIX = "_failed"

# Which Release a database was installed from, and the one a rollback left it
# for, which the refresher must not install again. Written by the installer into
# the database it installs; a dataset dump never carries a row.
_INSTALLED_TABLE = """
CREATE TABLE IF NOT EXISTS installed_release (
    id           BOOLEAN     PRIMARY KEY DEFAULT TRUE CHECK (id),
    tag          TEXT,
    sha256       TEXT,
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    skip_tag     TEXT,
    skip_sha256  TEXT
)
"""


class ReleaseId(NamedTuple):
    """A Release's tag and the SHA-256 of its dump, when GitHub published one."""

    tag: str
    sha256: str | None = None

    def same_as(self, other: ReleaseId | None) -> bool:
        """The same tag, and the same dump when both digests are known: a rebuild
        run twice on one day keeps its tag but replaces the dump."""
        return (
            other is not None
            and self.tag == other.tag
            and (self.sha256 is None or other.sha256 is None or self.sha256 == other.sha256)
        )


class Installed(NamedTuple):
    """What ``installed_release`` says about the live database."""

    release: ReleaseId | None
    skip: ReleaseId | None


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
    conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
    log.info("dropped %s", name)


def _allow_connections(conn: psycopg.Connection, name: str, allow: bool) -> None:
    conn.execute(
        sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS {}").format(
            sql.Identifier(name), sql.Literal(allow)
        )
    )


def _rename_database(conn: psycopg.Connection, old: str, new: str) -> None:
    """Rename ``old``: refuse new sessions first, so that a client reconnecting
    between closing the open ones and the rename cannot block it."""
    _allow_connections(conn, old, False)
    renamed = False
    try:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (old,),
        )
        conn.execute(
            sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
                sql.Identifier(old), sql.Identifier(new)
            )
        )
        renamed = True
    finally:
        _allow_connections(conn, new if renamed else old, True)
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


def _analyze(url: str, dbname: str) -> None:
    """Collect planner statistics, which a dump does not carry.

    Without them the first queries after the swap are planned blind, and the
    heaviest dashboard requests hit the API's statement timeout until
    autovacuum catches up."""
    with psycopg.connect(_admin_url(url, dbname), autocommit=True) as conn:
        conn.execute("ANALYZE")
    log.info("analyzed %s", dbname)


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


def _names(url: str) -> tuple[str, str, str, str]:
    """The live database's name, and those of its staging, previous and swap copies."""
    live = _live_dbname(url)
    return live, f"{live}{STAGING_SUFFIX}", f"{live}{PREVIOUS_SUFFIX}", f"{live}{SWAP_SUFFIX}"


def installed_release(url: str) -> Installed | None:
    """What the live database says it was installed from, or None when nothing is
    installed or recorded (no live database, or one installed before records were
    kept). Any other error is raised: a database that can't be read is not a reason
    to install again."""
    live = _live_dbname(url)
    with _connect_admin(url) as admin:
        if not _database_exists(admin, live):
            return None
    try:
        with psycopg.connect(url, connect_timeout=10) as conn:
            row = conn.execute(
                "SELECT tag, sha256, skip_tag, skip_sha256 FROM installed_release"
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        return None
    if row is None:
        return None
    tag, sha256, skip_tag, skip_sha256 = row
    return Installed(
        ReleaseId(tag, sha256) if tag else None,
        ReleaseId(skip_tag, skip_sha256) if skip_tag else None,
    )


def _record(url: str, dbname: str, release: ReleaseId) -> None:
    """Record in ``dbname`` that it was installed from ``release``."""
    with psycopg.connect(_admin_url(url, dbname)) as conn:
        conn.execute(_INSTALLED_TABLE)
        conn.execute(
            "INSERT INTO installed_release (tag, sha256) VALUES (%s, %s) "
            "ON CONFLICT (id) DO UPDATE SET tag = EXCLUDED.tag, sha256 = EXCLUDED.sha256, "
            "installed_at = now(), skip_tag = NULL, skip_sha256 = NULL",
            release,
        )


def _pin(url: str, dbname: str, skip: ReleaseId) -> None:
    """Record in ``dbname`` that ``skip`` was rolled back from, so the refresher
    leaves it alone until another Release is published."""
    with psycopg.connect(_admin_url(url, dbname)) as conn:
        conn.execute(_INSTALLED_TABLE)
        conn.execute(
            "INSERT INTO installed_release (skip_tag, skip_sha256) VALUES (%s, %s) "
            "ON CONFLICT (id) DO UPDATE SET skip_tag = EXCLUDED.skip_tag, "
            "skip_sha256 = EXCLUDED.skip_sha256",
            skip,
        )


def repair(url: str) -> None:
    """Finish a swap that was interrupted, so the site serves again without
    downloading anything, and drop copies that are no longer needed.

    With no live database, the verified staging copy goes live if there is one
    (an install stopped between its two renames), else the copy a rollback set
    aside, else the previous dataset."""
    live, staging, previous, swap = _names(url)
    with _connect_admin(url) as admin:
        _drop_database(admin, f"{live}{FAILED_SUFFIX}")
        if _database_exists(admin, live):
            if _database_exists(admin, swap) and not _database_exists(admin, previous):
                log.warning("finishing an interrupted rollback")
                _rename_database(admin, swap, previous)
            return
        exists = {name: _database_exists(admin, name) for name in (staging, swap, previous)}
    if exists[staging]:
        try:
            _verify(url, staging)
        except DataValidationError as exc:
            log.error("the staged copy fails verification (%s); dropping it", exc)
            with _connect_admin(url) as admin:
                _drop_database(admin, staging)
        else:
            log.warning("no live database: finishing an interrupted install")
            with _connect_admin(url) as admin:
                _rename_database(admin, staging, live)
            return
    for name in (swap, previous):
        if exists[name]:
            log.warning("no live database: serving %s again", name)
            with _connect_admin(url) as admin:
                _rename_database(admin, name, live)
            return


def restore(
    url: str, dump: Path, *, dry_run: bool = False, release: ReleaseId | None = None
) -> None:
    """Stage, verify and promote ``dump``, recording ``release`` as its source."""
    repair(url)
    live, staging, previous, _swap = _names(url)

    with _connect_admin(url) as admin:
        # A staging DB may survive an earlier interrupted run; start clean.
        _drop_database(admin, staging)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(staging)))
        log.info("created %s", staging)

    try:
        _pg_restore(url, staging, dump)
        _analyze(url, staging)
        _verify(url, staging)
        if release is not None:
            _record(url, staging, release)
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
    """Swap the live and previous datasets, and keep the refresher from installing
    the Release just rolled back from until another one is published. Running it
    again swaps them back."""
    repair(url)
    live, _staging, previous, swap = _names(url)
    with _connect_admin(url) as admin:
        if not _database_exists(admin, previous):
            raise RestoreError(f"no {previous} database to roll back to")
    # After the first install the previous copy is the empty initial database.
    _verify(url, previous)
    current = installed_release(url)
    with _connect_admin(url) as admin:
        _rename_database(admin, live, swap)
        _rename_database(admin, previous, live)
        _rename_database(admin, swap, previous)
    if current and current.release:
        _pin(url, live, current.release)
    else:
        log.warning(
            "the dataset rolled back from has no recorded Release; the refresher may "
            "install it again"
        )
    log.info(
        "rolled back: %s serves the previous dataset; the one it replaced is %s",
        live,
        previous,
    )


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
