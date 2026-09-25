"""Unit tests for the snapshot restore helpers.

The promote/rollback paths rename and drop databases, so they are exercised
against a real Postgres by the rehearsal documented in the script's docstring,
not here. What is worth pinning down in a unit test is the URL rewriting: every
DDL step connects to a maintenance database derived from DATABASE_URL, and a
bug there would point the restore at the wrong server or the wrong database.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
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
    with pytest.raises(SystemExit):
        restore_snapshot._live_dbname("postgresql://eukahub:secret@db.example.org:5433/")


def test_staging_and_previous_names_do_not_collide_with_the_live_name():
    live = restore_snapshot._live_dbname(LIVE)
    staging = f"{live}{restore_snapshot.STAGING_SUFFIX}"
    previous = f"{live}{restore_snapshot.PREVIOUS_SUFFIX}"
    assert len({live, staging, previous}) == 3
    # Postgres truncates identifiers past 63 bytes, which would alias them.
    assert all(len(name.encode()) <= 63 for name in (live, staging, previous))
