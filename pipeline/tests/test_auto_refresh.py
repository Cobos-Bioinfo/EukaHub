"""Unit tests for the refresher's "is there newer data?" decision.

The network and database calls are stubbed: what matters here is the branch
that decides whether to promote a snapshot. Getting it wrong either pins the
deployment to stale data forever or re-restores the same dataset every cycle.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from eukahub_pipeline.validate import DataValidationError

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
# auto_refresh imports its sibling restore_snapshot by plain name, the way it
# does when run as scripts/auto_refresh.py.
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("auto_refresh", SCRIPTS / "auto_refresh.py")
assert _spec and _spec.loader
auto_refresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auto_refresh)

RELEASE = date(2026, 9, 1)
TAG = "dataset-20260901"
URL = "postgresql://eukahub:eukahub@db:5432/eukahub"


@pytest.fixture
def stubbed(monkeypatch):
    """Stub the network and the restore, recording whether a restore happened."""
    calls: list[str] = []
    monkeypatch.setattr(
        auto_refresh,
        "_latest_release",
        lambda repo: auto_refresh.Release(TAG, RELEASE, "https://example/snap.dump"),
    )
    monkeypatch.setattr(auto_refresh.restore_snapshot, "download", lambda url, dest: dest)
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


def _failing_restore(monkeypatch, exc: Exception) -> list[str]:
    calls: list[str] = []

    def restore(url, dump, **kw):
        calls.append("attempted")
        raise exc

    monkeypatch.setattr(auto_refresh.restore_snapshot, "restore", restore)
    monkeypatch.setattr(auto_refresh, "_loaded_dataset_date", lambda url: None)
    return calls


def test_a_release_that_keeps_failing_is_skipped(monkeypatch, stubbed):
    calls = _failing_restore(monkeypatch, auto_refresh.restore_snapshot.RestoreError("boom"))
    failures = Counter()
    for _ in range(auto_refresh.MAX_INSTALL_ATTEMPTS):
        with pytest.raises(auto_refresh.restore_snapshot.RestoreError):
            auto_refresh.refresh_once(URL, "owner/repo", failures)
    assert auto_refresh.refresh_once(URL, "owner/repo", failures) is False
    assert len(calls) == auto_refresh.MAX_INSTALL_ATTEMPTS


@pytest.mark.parametrize(
    "exc",
    [
        auto_refresh.restore_snapshot.RestoreError("pg_restore exited 1"),
        DataValidationError("coverage exceeds species"),
        TypeError("cannot unpack non-iterable NoneType object"),
        ValueError("bad payload"),
    ],
)
def test_main_survives_any_failed_cycle(monkeypatch, stubbed, exc):
    """A crash would restart the container and retry the same Release immediately."""
    _failing_restore(monkeypatch, exc)
    monkeypatch.setattr(sys, "argv", ["auto_refresh.py", "--once"])
    auto_refresh.main()


def test_warns_when_the_loaded_dataset_is_stale(monkeypatch, stubbed, caplog):
    monkeypatch.setattr(auto_refresh, "_loaded_dataset_date", lambda url: date(2020, 1, 1))
    monkeypatch.setattr(
        auto_refresh,
        "_latest_release",
        lambda repo: auto_refresh.Release("dataset-20200101", date(2020, 1, 1), "https://x"),
    )
    assert auto_refresh.refresh_once(URL, "owner/repo") is False
    assert "days old" in caplog.text


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


def _release_for(data: bytes, **overrides) -> auto_refresh.Release:
    """A Release whose published size and digest describe ``data``."""
    fields = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} | overrides
    return auto_refresh.Release(TAG, RELEASE, "https://example/snap.dump", **fields)


def test_latest_release_reads_the_published_size_and_digest(monkeypatch):
    payload = {
        "tag_name": TAG,
        "assets": [
            {
                "name": auto_refresh.ASSET_NAME,
                "browser_download_url": "https://example/snap.dump",
                "size": 51_570_408,
                "digest": "sha256:1620c25c",
            }
        ],
    }
    monkeypatch.setattr(
        auto_refresh.urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(json.dumps(payload).encode()),
    )
    release = auto_refresh._latest_release("owner/repo")
    assert (release.size, release.sha256) == (51_570_408, "1620c25c")


def test_a_download_matching_the_digest_passes(tmp_path):
    dump = tmp_path / "snap.dump"
    dump.write_bytes(b"PGDMP snapshot")
    auto_refresh._verify_download(dump, _release_for(b"PGDMP snapshot"))


@pytest.mark.parametrize("overrides", [{"size": 3}, {"sha256": "0" * 64}])
def test_a_truncated_or_corrupted_download_is_rejected(tmp_path, overrides):
    dump = tmp_path / "snap.dump"
    dump.write_bytes(b"PGDMP snapshot")
    with pytest.raises(RuntimeError):
        auto_refresh._verify_download(dump, _release_for(b"PGDMP snapshot", **overrides))


def test_a_release_without_a_digest_is_checked_by_size_only(tmp_path, caplog):
    dump = tmp_path / "snap.dump"
    dump.write_bytes(b"PGDMP snapshot")
    auto_refresh._verify_download(dump, _release_for(b"PGDMP snapshot", sha256=None))
    assert "no published digest" in caplog.text


def test_a_download_that_fails_verification_is_never_restored(monkeypatch, stubbed):
    monkeypatch.setattr(auto_refresh, "_loaded_dataset_date", lambda url: None)
    monkeypatch.setattr(auto_refresh, "_latest_release", lambda repo: _release_for(b"expected"))

    def download(url, dest):
        dest.write_bytes(b"tampered")  # same length, different content
        return dest

    monkeypatch.setattr(auto_refresh.restore_snapshot, "download", download)
    failures = Counter()
    with pytest.raises(RuntimeError, match="checksum"):
        auto_refresh.refresh_once(URL, "owner/repo", failures)
    assert stubbed == []
    assert failures[TAG] == 1
