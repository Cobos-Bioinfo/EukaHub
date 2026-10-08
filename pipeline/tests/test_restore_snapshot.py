"""Tests for the snapshot installer.

The URL rewriting is pinned down without a database: every DDL step connects to a
maintenance database derived from DATABASE_URL, and a bug there would point the
restore at the wrong server or database. The swaps (install, repair of an
interrupted one, rollback) run against the test Postgres on scratch databases
that hold a one-row ``marker`` table instead of a dataset.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

_spec = importlib.util.spec_from_file_location(
    "restore_snapshot",
    Path(__file__).resolve().parents[2] / "scripts" / "restore_snapshot.py",
)
assert _spec and _spec.loader
restore_snapshot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(restore_snapshot)

LIVE = "postgresql://eukahub:secret@db.example.org:5433/eukahub"


def test_admin_url_repoints_database_keeping_server_and_credentials():
    params = conninfo_to_dict(restore_snapshot._admin_url(LIVE))
    assert params["dbname"] == "postgres"
    assert params["host"] == "db.example.org"
    assert params["port"] == "5433"
    assert params["user"] == "eukahub"
    assert params["password"] == "secret"


def test_admin_url_can_target_the_staging_database():
    params = conninfo_to_dict(restore_snapshot._admin_url(LIVE, "eukahub_next"))
    assert params["dbname"] == "eukahub_next"
    assert params["host"] == "db.example.org"


def test_live_dbname_reads_the_database_from_the_url():
    assert restore_snapshot._live_dbname(LIVE) == "eukahub"


def test_live_dbname_rejects_a_url_without_a_database():
    with pytest.raises(restore_snapshot.RestoreError):
        restore_snapshot._live_dbname("postgresql://eukahub:secret@db.example.org:5433/")


def test_staging_and_previous_names_do_not_collide_with_the_live_name():
    live = restore_snapshot._live_dbname(LIVE)
    staging = f"{live}{restore_snapshot.STAGING_SUFFIX}"
    previous = f"{live}{restore_snapshot.PREVIOUS_SUFFIX}"
    assert len({live, staging, previous}) == 3
    # Postgres truncates identifiers past 63 bytes, which would alias them.
    assert all(len(name.encode()) <= 63 for name in (live, staging, previous))


def test_restore_runs_as_a_single_job(monkeypatch, tmp_path):
    # The target host has one CPU core; parallel restore jobs would compete
    # with the site that keeps serving during the restore.
    seen = {}

    def _run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(restore_snapshot.shutil, "which", lambda _: "/usr/bin/pg_restore")
    monkeypatch.setattr(restore_snapshot.subprocess, "run", _run)
    restore_snapshot._pg_restore(LIVE, "eukahub_next", tmp_path / "snapshot.dump")
    assert "--jobs" not in seen["cmd"] and "-j" not in seen["cmd"]


def test_staging_is_analyzed_before_it_is_verified(monkeypatch, tmp_path):
    """A dump carries no planner statistics; the swap must not go live without them."""
    steps: list[str] = []

    class _Admin:
        def execute(self, *_):
            return self

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(restore_snapshot, "_connect_admin", lambda url: _Admin())
    monkeypatch.setattr(restore_snapshot, "_pg_restore", lambda *a: steps.append("restore"))
    monkeypatch.setattr(restore_snapshot, "_analyze", lambda *a: steps.append("analyze"))
    monkeypatch.setattr(restore_snapshot, "_verify", lambda *a: steps.append("verify"))
    restore_snapshot.restore(LIVE, tmp_path / "snapshot.dump", dry_run=True)
    assert steps == ["restore", "analyze", "verify"]


class Server(NamedTuple):
    url: str  # DATABASE_URL naming a scratch live database
    live: str
    admin: psycopg.Connection

    def name(self, suffix: str = "") -> str:
        return f"{self.live}{suffix}"

    def make(self, suffix: str, label: str | None) -> None:
        """A copy holding ``label`` in its marker table, or an empty one (None)."""
        name = self.name(suffix)
        self.admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        if label is not None:
            with psycopg.connect(restore_snapshot._admin_url(self.url, name)) as conn:
                conn.execute("CREATE TABLE marker (label TEXT)")
                conn.execute("INSERT INTO marker VALUES (%s)", (label,))

    def label(self, suffix: str = "") -> str | None:
        """The marker of a copy, or None when the copy does not exist."""
        name = self.name(suffix)
        if not restore_snapshot._database_exists(self.admin, name):
            return None
        with psycopg.connect(restore_snapshot._admin_url(self.url, name)) as conn:
            return conn.execute("SELECT label FROM marker").fetchone()[0]


SUFFIXES = ("", "_next", "_prev", "_swap", "_failed", "_source")
OLD = restore_snapshot.ReleaseId("dataset-20260901", "a" * 64)
NEW = restore_snapshot.ReleaseId("dataset-20261001", "b" * 64)


@pytest.fixture
def server(monkeypatch):
    base = os.environ.get("DATABASE_URL", restore_snapshot.DEFAULT_URL)
    try:
        admin = psycopg.connect(
            restore_snapshot._admin_url(base), autocommit=True, connect_timeout=3
        )
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable")
    live = f"eukahub_test_{secrets.token_hex(4)}"

    def verify(url: str, dbname: str) -> None:
        with psycopg.connect(restore_snapshot._admin_url(url, dbname)) as conn:
            if conn.execute("SELECT to_regclass('marker')").fetchone()[0] is None:
                raise restore_snapshot.DataValidationError(f"{dbname} holds no dataset")

    monkeypatch.setattr(restore_snapshot, "_verify", verify)
    try:
        yield Server(restore_snapshot._admin_url(base, live), live, admin)
    finally:
        for suffix in SUFFIXES:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(f"{live}{suffix}")
                )
            )
        admin.close()


def test_a_rename_closes_open_sessions_and_leaves_the_database_open(server):
    server.make("_next", "new")
    session = psycopg.connect(restore_snapshot._admin_url(server.url, server.name("_next")))
    restore_snapshot._rename_database(server.admin, server.name("_next"), server.live)
    with pytest.raises(psycopg.OperationalError):
        session.execute("SELECT 1")
    assert server.label() == "new"


def test_repair_finishes_an_install_stopped_between_its_renames(server):
    server.make("_prev", "old")
    server.make("_next", "new")
    restore_snapshot.repair(server.url)
    assert (server.label(), server.label("_prev"), server.label("_next")) == ("new", "old", None)


def test_repair_serves_the_previous_dataset_when_the_staged_one_fails(server):
    server.make("_prev", "old")
    server.make("_next", None)
    restore_snapshot.repair(server.url)
    assert (server.label(), server.label("_prev"), server.label("_next")) == ("old", None, None)


def test_repair_undoes_a_rollback_stopped_after_its_first_rename(server):
    server.make("_swap", "new")
    server.make("_prev", "old")
    restore_snapshot.repair(server.url)
    assert (server.label(), server.label("_prev"), server.label("_swap")) == ("new", "old", None)


def test_repair_finishes_a_rollback_stopped_after_its_second_rename(server):
    server.make("", "old")
    server.make("_swap", "new")
    restore_snapshot.repair(server.url)
    assert (server.label(), server.label("_prev"), server.label("_swap")) == ("old", "new", None)


def test_repair_drops_the_copy_an_old_rollback_left(server):
    server.make("", "live")
    server.make("_failed", "failed")
    restore_snapshot.repair(server.url)
    assert (server.label(), server.label("_failed")) == ("live", None)


def test_nothing_is_installed_without_a_live_database_or_a_record(server):
    assert restore_snapshot.installed_release(server.url) is None
    server.make("", "live")
    assert restore_snapshot.installed_release(server.url) is None


def test_a_rollback_swaps_the_datasets_and_pins_the_release_it_left(server):
    server.make("", "new")
    restore_snapshot._record(server.url, server.live, NEW)
    server.make("_prev", "old")
    restore_snapshot._record(server.url, server.name("_prev"), OLD)

    restore_snapshot.rollback(server.url)
    assert (server.label(), server.label("_prev")) == ("old", "new")
    assert restore_snapshot.installed_release(server.url) == restore_snapshot.Installed(OLD, NEW)

    # Running it again swaps them back, leaving the older Release pinned instead.
    restore_snapshot.rollback(server.url)
    assert (server.label(), server.label("_prev")) == ("new", "old")
    assert restore_snapshot.installed_release(server.url) == restore_snapshot.Installed(NEW, OLD)


def test_a_rollback_refuses_a_previous_copy_without_a_dataset(server):
    server.make("", "new")
    server.make("_prev", None)  # the empty database Postgres starts with
    with pytest.raises(restore_snapshot.DataValidationError):
        restore_snapshot.rollback(server.url)
    assert server.label() == "new"


def test_an_install_records_its_release_and_keeps_the_old_dataset(server, tmp_path):
    server.make("_source", "new")
    dump = tmp_path / "snapshot.dump"
    source = restore_snapshot._admin_url(server.url, server.name("_source"))
    made = subprocess.run(
        ["pg_dump", "--format=custom", f"--file={dump}", source],
        capture_output=True,
        text=True,
        check=False,
    )
    server.admin.execute(
        sql.SQL("DROP DATABASE {}").format(sql.Identifier(server.name("_source")))
    )
    if shutil.which("pg_restore") is None or made.returncode != 0:
        pytest.skip(f"no usable pg_dump/pg_restore: {made.stderr.strip()[:200]}")
    server.make("", "old")
    restore_snapshot._record(server.url, server.live, OLD)

    restore_snapshot.restore(server.url, dump, release=NEW)
    assert (server.label(), server.label("_prev"), server.label("_next")) == ("new", "old", None)
    assert restore_snapshot.installed_release(server.url) == restore_snapshot.Installed(NEW, None)
