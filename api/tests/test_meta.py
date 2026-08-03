"""Tests for GET /meta — the dataset provenance stamp ("Data updated ...").

Slice-safe: works whether or not the DB has been stamped. The CI loader stamps
dataset_meta after seeding (scripts/load_ci_db.py), and a real build stamps it as
its last step, so built_at is normally present; the test still tolerates the
pre-first-build null state.
"""

from __future__ import annotations

from datetime import datetime


def test_meta_shape(client):
    body = client.get("/meta").json()
    assert set(body) == {
        "built_at",
        "taxon_count",
        "assembly_count",
        "annotation_count",
        "clade_count",
    }
    for k in ("taxon_count", "assembly_count", "annotation_count", "clade_count"):
        assert isinstance(body[k], int) and body[k] >= 0

    if body["built_at"] is None:
        # Valid pre-first-build state: counts are all zero.
        assert all(body[k] == 0 for k in ("taxon_count", "clade_count"))
    else:
        # A stamped build parses as a datetime and isn't empty.
        datetime.fromisoformat(body["built_at"])
        assert body["taxon_count"] > 0
        assert body["clade_count"] > 0


def test_meta_is_cacheable(client):
    r = client.get("/meta")
    assert r.status_code == 200
    assert "public" in r.headers.get("cache-control", "")
