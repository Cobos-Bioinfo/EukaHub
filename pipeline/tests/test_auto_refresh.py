"""Unit tests for the refresher's "is there newer data?" decision.

The network and database calls are stubbed: what matters here is the branch
that decides whether to promote a snapshot. Getting it wrong either pins the
deployment to stale data forever or re-restores the same dataset every cycle.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
# auto_refresh imports its sibling restore_snapshot by plain name, the way it
# does when run as scripts/auto_refresh.py.
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("auto_refresh", SCRIPTS / "auto_refresh.py")
assert _spec and _spec.loader
auto_refresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auto_refresh)

RELEASE = date(2026, 9, 1)
URL = "postgresql://eukahub:eukahub@db:5432/eukahub"


@pytest.fixture
def stubbed(monkeypatch):
    """Stub the network and the restore, recording whether a restore happened."""
    calls: list[str] = []
    monkeypatch.setattr(
        auto_refresh, "_latest_release", lambda repo: (RELEASE, "https://example/snap.dump")
    )
    monkeypatch.setattr(auto_refresh, "_download", lambda url, dest: dest, raising=False)
    monkeypatch.setattr(auto_refresh.restore_snapshot, "_download", lambda url, dest: dest)
    monkeypatch.setattr(
        auto_refresh.restore_snapshot,
        "restore",
        lambda url, dump, **kw: calls.append("restored"),
    )
    return calls


def test_installs_when_no_dataset_is_loaded(monkeypatch, stubbed):
    monkeypatch.setattr(auto_refresh, "_loaded_dataset_date", lambda url: None)
    assert auto_refresh.refresh_once(URL, "owner/repo") is True
    assert stubbed == ["restored"]


def test_promotes_a_newer_release(monkeypatch, stubbed):
    monkeypatch.setattr(auto_refresh, "_loaded_dataset_date", lambda url: date(2026, 8, 1))
    assert auto_refresh.refresh_once(URL, "owner/repo") is True
    assert stubbed == ["restored"]


def test_does_nothing_when_already_current(monkeypatch, stubbed):
    monkeypatch.setattr(auto_refresh, "_loaded_dataset_date", lambda url: RELEASE)
    assert auto_refresh.refresh_once(URL, "owner/repo") is False
    assert stubbed == []


def test_does_not_downgrade_to_an_older_release(monkeypatch, stubbed):
    """A Release republished out of order must not replace newer loaded data."""
    monkeypatch.setattr(auto_refresh, "_loaded_dataset_date", lambda url: date(2026, 10, 1))
    assert auto_refresh.refresh_once(URL, "owner/repo") is False
    assert stubbed == []


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("dataset-20260901", date(2026, 9, 1)),
        ("dataset-20261231", date(2026, 12, 31)),
    ],
)
def test_tag_pattern_reads_the_dataset_date(tag, expected):
    match = auto_refresh.TAG_PATTERN.match(tag)
    assert match
    assert date(int(match[1]), int(match[2]), int(match[3])) == expected


@pytest.mark.parametrize("tag", ["v1.0.0", "dataset-2026-09-01", "dataset-", "latest", ""])
def test_tag_pattern_rejects_non_dataset_tags(tag):
    """A stray release (a code tag, say) must not be mistaken for a dataset."""
    assert auto_refresh.TAG_PATTERN.match(tag) is None


def test_asset_name_matches_the_stable_release_url():
    """The workflow publishes this exact filename; the pull URL depends on it."""
    assert auto_refresh.ASSET_NAME == "eukahub-dataset.dump"


def test_loaded_date_accepts_a_timestamp(monkeypatch):
    """dataset_meta.built_at is a timestamptz; only its date is compared."""

    class _Conn:
        def execute(self, *_):
            return self

        def fetchone(self):
            return (datetime(2026, 9, 1, 4, 30, tzinfo=UTC),)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(auto_refresh.psycopg, "connect", lambda *a, **k: _Conn())
    assert auto_refresh._loaded_dataset_date(URL) == date(2026, 9, 1)
