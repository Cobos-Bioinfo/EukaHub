"""Unit tests for the refresher's "which Release should be serving?" decision.

The network and database calls are stubbed: what matters here is the branch
that decides whether to promote a snapshot. Getting it wrong either pins the
deployment to stale data forever or re-restores the same dataset every cycle.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import logging
import sys
from collections import Counter
from datetime import date
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
NEWEST = auto_refresh.Release(TAG, RELEASE, "https://example/snap.dump", sha256="a" * 64)
ReleaseId = auto_refresh.ReleaseId
Installed = auto_refresh.restore_snapshot.Installed
VERIFY_DOWNLOAD = auto_refresh._verify_download


@pytest.fixture
def stubbed(monkeypatch):
    """Stub the network, the database and the restore, recording each step."""
    calls: list[object] = []
    monkeypatch.setattr(auto_refresh, "_newest_release", lambda repo: NEWEST)
    monkeypatch.setattr(
        auto_refresh.restore_snapshot, "repair", lambda url: calls.append("repaired")
    )
    monkeypatch.setattr(auto_refresh.restore_snapshot, "download", lambda url, dest: dest)
    monkeypatch.setattr(auto_refresh, "_verify_download", lambda dump, release: None)
    monkeypatch.setattr(
        auto_refresh.restore_snapshot,
        "restore",
        lambda url, dump, **kw: calls.append(("restored", kw["release"])),
    )
    installed(monkeypatch, None)
    return calls


def installed(monkeypatch, release: ReleaseId | None, skip: ReleaseId | None = None) -> None:
    record = Installed(release, skip) if release or skip else None
    monkeypatch.setattr(auto_refresh.restore_snapshot, "installed_release", lambda url: record)


def test_repairs_an_interrupted_swap_first_then_installs_when_nothing_is_recorded(stubbed):
    assert auto_refresh.refresh_once(URL, "owner/repo") is True
    assert stubbed == ["repaired", ("restored", NEWEST.id)]


def test_installs_a_newer_release(monkeypatch, stubbed):
    installed(monkeypatch, ReleaseId("dataset-20260801", "b" * 64))
    assert auto_refresh.refresh_once(URL, "owner/repo") is True
    assert ("restored", NEWEST.id) in stubbed


def test_does_nothing_when_the_release_is_already_installed(monkeypatch, stubbed):
    installed(monkeypatch, NEWEST.id)
    assert auto_refresh.refresh_once(URL, "owner/repo") is False
    assert stubbed == ["repaired"]


def test_reinstalls_a_release_whose_dump_was_replaced(monkeypatch, stubbed):
    """A second rebuild on the same day keeps the tag and replaces the dump."""
    installed(monkeypatch, ReleaseId(TAG, "b" * 64))
    assert auto_refresh.refresh_once(URL, "owner/repo") is True


def test_a_release_without_a_digest_is_compared_by_tag(monkeypatch, stubbed):
    installed(monkeypatch, ReleaseId(TAG, None))
    assert auto_refresh.refresh_once(URL, "owner/repo") is False


def test_does_not_downgrade_to_an_older_release(monkeypatch, stubbed):
    """A newer Release deleted after install must not send servers back."""
    installed(monkeypatch, ReleaseId("dataset-20261001", "b" * 64))
    assert auto_refresh.refresh_once(URL, "owner/repo") is False
    assert stubbed == ["repaired"]


def test_a_release_rolled_back_from_is_not_installed_again(monkeypatch, stubbed, caplog):
    caplog.set_level(logging.INFO)
    installed(monkeypatch, ReleaseId("dataset-20260801", "b" * 64), skip=NEWEST.id)
    assert auto_refresh.refresh_once(URL, "owner/repo") is False
    assert "rolled back" in caplog.text


def test_a_newer_release_ends_a_rollback(monkeypatch, stubbed):
    installed(
        monkeypatch,
        ReleaseId("dataset-20260701", "c" * 64),
        skip=ReleaseId("dataset-20260801", "b" * 64),
    )
    assert auto_refresh.refresh_once(URL, "owner/repo") is True


def _failing_restore(monkeypatch, exc: Exception) -> list[str]:
    calls: list[str] = []

    def restore(url, dump, **kw):
        calls.append("attempted")
        raise exc

    monkeypatch.setattr(auto_refresh.restore_snapshot, "restore", restore)
    return calls


def test_a_release_that_keeps_failing_is_skipped_until_republished(monkeypatch, stubbed):
    calls = _failing_restore(monkeypatch, auto_refresh.restore_snapshot.RestoreError("boom"))
    failures = Counter()
    for _ in range(auto_refresh.MAX_INSTALL_ATTEMPTS):
        with pytest.raises(auto_refresh.restore_snapshot.RestoreError):
            auto_refresh.refresh_once(URL, "owner/repo", failures)
    assert auto_refresh.refresh_once(URL, "owner/repo", failures) is False
    assert len(calls) == auto_refresh.MAX_INSTALL_ATTEMPTS

    republished = NEWEST._replace(sha256="d" * 64)
    monkeypatch.setattr(auto_refresh, "_newest_release", lambda repo: republished)
    with pytest.raises(auto_refresh.restore_snapshot.RestoreError):
        auto_refresh.refresh_once(URL, "owner/repo", failures)
    assert len(calls) == auto_refresh.MAX_INSTALL_ATTEMPTS + 1


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


def test_warns_when_the_installed_dataset_is_stale(monkeypatch, stubbed, caplog):
    old = auto_refresh.Release("dataset-20200101", date(2020, 1, 1), "https://x", sha256="e" * 64)
    monkeypatch.setattr(auto_refresh, "_newest_release", lambda repo: old)
    installed(monkeypatch, old.id)
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


def _release_for(data: bytes, **overrides) -> auto_refresh.Release:
    """A Release whose published size and digest describe ``data``."""
    fields = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} | overrides
    return auto_refresh.Release(TAG, RELEASE, "https://example/snap.dump", **fields)


def _payload(tag: str, *, dump: bool = True, **flags) -> dict:
    asset = {
        "name": auto_refresh.ASSET_NAME,
        "browser_download_url": f"https://example/{tag}.dump",
        "size": 51_570_408,
        "digest": "sha256:1620c25c",
    }
    return {"tag_name": tag, "assets": [asset] if dump else [], **flags}


def _serve_releases(monkeypatch, payloads: list[dict]) -> None:
    monkeypatch.setattr(
        auto_refresh.urllib.request,
        "urlopen",
        lambda request, timeout: io.BytesIO(json.dumps(payloads).encode()),
    )


def test_newest_release_skips_other_releases_and_ones_without_the_dump(monkeypatch):
    _serve_releases(
        monkeypatch,
        [
            _payload("v2.0.0"),  # a code release marked latest
            _payload("dataset-20261201", draft=True),
            _payload("dataset-20261101", prerelease=True),
            _payload("dataset-20261015", dump=False),
            _payload("dataset-20260901"),
            _payload("dataset-20261001"),
        ],
    )
    release = auto_refresh._newest_release("owner/repo")
    assert release.tag == "dataset-20261001"
    assert (release.size, release.sha256) == (51_570_408, "1620c25c")
    assert release.download_url == "https://example/dataset-20261001.dump"


def test_no_dataset_release_is_an_error(monkeypatch):
    _serve_releases(monkeypatch, [_payload("v2.0.0")])
    with pytest.raises(RuntimeError, match="no dataset-YYYYMMDD Release"):
        auto_refresh._newest_release("owner/repo")


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
    monkeypatch.setattr(auto_refresh, "_newest_release", lambda repo: _release_for(b"expected"))
    monkeypatch.setattr(auto_refresh, "_verify_download", VERIFY_DOWNLOAD)

    def download(url, dest):
        dest.write_bytes(b"tampered")  # same length, different content
        return dest

    monkeypatch.setattr(auto_refresh.restore_snapshot, "download", download)
    failures = Counter()
    with pytest.raises(RuntimeError, match="checksum"):
        auto_refresh.refresh_once(URL, "owner/repo", failures)
    assert stubbed == ["repaired"]
    assert failures[_release_for(b"expected").id] == 1
