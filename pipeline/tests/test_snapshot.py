"""The source snapshot cache: fetched rows go to disk in batches, and a snapshot
appears only once its fetch completes."""

from __future__ import annotations

import polars as pl
import pytest
from eukahub_pipeline import snapshot
from eukahub_pipeline.snapshot import cached_frame
from tenacity import wait_none

SCHEMA = {"taxid": pl.Int64, "name": pl.String}


def _rows(n: int):
    for i in range(n):
        yield {"taxid": i, "name": f"t{i}" if i % 3 else None}


def test_a_fetch_is_written_in_batches_and_kept_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "BATCH_ROWS", 4)
    df = cached_frame("src", lambda: _rows(10), SCHEMA, tmp_path)
    assert df.schema == SCHEMA
    assert df["taxid"].to_list() == list(range(10))
    assert df.equals(pl.read_parquet(tmp_path / "src.parquet"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["src.parquet"]


def test_a_snapshot_is_reused_until_refreshed(tmp_path):
    cached_frame("src", lambda: _rows(3), SCHEMA, tmp_path)
    assert cached_frame("src", lambda: _rows(5), SCHEMA, tmp_path).height == 3
    assert cached_frame("src", lambda: _rows(5), SCHEMA, tmp_path, refresh=True).height == 5


def test_an_empty_fetch_keeps_the_schema(tmp_path):
    df = cached_frame("src", lambda: iter(()), SCHEMA, tmp_path)
    assert df.height == 0 and df.schema == SCHEMA


def test_a_failed_fetch_leaves_no_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "BATCH_ROWS", 2)

    def failing():
        yield from _rows(5)
        raise RuntimeError("source went away")

    with pytest.raises(RuntimeError):
        cached_frame("src", failing, SCHEMA, tmp_path)
    assert not (tmp_path / "src.parquet").exists()
    assert cached_frame("src", lambda: _rows(2), SCHEMA, tmp_path).height == 2


def _flaky(failures: int, calls: list[int]):
    """A fetch that drops its connection partway through its first ``failures`` runs."""

    def fetch():
        calls.append(1)
        yield from _rows(5 if len(calls) <= failures else 3)
        if len(calls) <= failures:
            raise ConnectionError("connection dropped")

    return fetch


def test_a_failed_fetch_is_retried_from_scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "BATCH_ROWS", 2)
    monkeypatch.setattr(snapshot, "FETCH_WAIT", wait_none())
    calls: list[int] = []
    df = cached_frame("src", _flaky(1, calls), SCHEMA, tmp_path, retry_on=(ConnectionError,))
    assert len(calls) == 2
    assert df["taxid"].to_list() == [0, 1, 2]  # only the run that completed
    assert sorted(p.name for p in tmp_path.iterdir()) == ["src.parquet"]


def test_a_fetch_that_keeps_failing_gives_up(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "FETCH_WAIT", wait_none())
    calls: list[int] = []
    with pytest.raises(ConnectionError):
        cached_frame("src", _flaky(99, calls), SCHEMA, tmp_path, retry_on=(ConnectionError,))
    assert len(calls) == snapshot.FETCH_ATTEMPTS
    assert not (tmp_path / "src.parquet").exists()


def test_only_the_listed_errors_are_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "FETCH_WAIT", wait_none())
    calls: list[int] = []
    with pytest.raises(ConnectionError):
        cached_frame("src", _flaky(1, calls), SCHEMA, tmp_path)
    assert len(calls) == 1
