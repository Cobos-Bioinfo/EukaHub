"""Tests for GET /config: the dataset stamp, the measure and quality-stat chrome,
and the deployment's links and groups. The settings themselves are tested in
test_site_config.py."""

from __future__ import annotations

from datetime import datetime

from eukahub_core.metrics import METRIC_NAMES, QUALITY_KEYS


def test_config_shape(client):
    body = client.get("/config").json()
    assert set(body) == {
        "dataset",
        "metrics",
        "quality_stats",
        "feedback_url",
        "source_code_url",
        "privacy_contact_email",
        "wikipedia_summary_url",
        "groups",
        "custom_groups",
    }
    assert body["feedback_url"].startswith("https://")
    assert body["source_code_url"].startswith("https://")
    assert "{title}" in body["wikipedia_summary_url"]
    assert any(g["featured"] for g in body["groups"])
    for g in body["groups"]:
        assert set(g) == {"taxid", "label", "featured"}


def test_config_dataset(client):
    """Slice-safe: the CI loader and a real build both stamp dataset_meta, and the
    pre-first-build null state is still accepted."""
    dataset = client.get("/config").json()["dataset"]
    counts = ("taxon_count", "assembly_count", "annotation_count", "clade_count")
    assert set(dataset) == {"built_at", *counts}
    for k in counts:
        assert isinstance(dataset[k], int) and dataset[k] >= 0
    if dataset["built_at"] is None:
        assert dataset["taxon_count"] == dataset["clade_count"] == 0
    else:
        datetime.fromisoformat(dataset["built_at"])
        assert dataset["taxon_count"] > 0
        assert dataset["clade_count"] > 0


def test_config_metrics(client):
    metrics = client.get("/config").json()["metrics"]
    assert [m["key"] for m in metrics] == list(METRIC_NAMES)
    for m in metrics:
        assert m["card_title"]
        assert m["empty_text"].startswith("No ")
        assert m["color"].startswith("#")
        assert "{taxid}" in m["external_url_template"]  # client substitutes


def test_config_quality_stats(client):
    stats = client.get("/config").json()["quality_stats"]
    assert [q["key"] for q in stats] == list(QUALITY_KEYS)
    for q in stats:
        assert q["card_title"]
        assert q["help"]
        assert q["source"] in {"assembly", "annotation"}
        assert q["fmt"] in {"percent", "integer", "basepairs"}
        assert q["aggregation"] == ("max" if q["key"] == "busco" else "median")
    # The headline stats compare groups on the Gaps page, so they are medians, and
    # every label says which summary it shows.
    assert {q["key"] for q in stats if q["headline"]} == {"genes", "genome_size"}
    for q in stats:
        assert q["card_title"].startswith("Median" if q["key"] != "busco" else "Best")


def test_config_is_cacheable(client):
    r = client.get("/config")
    assert r.status_code == 200
    assert "public" in r.headers.get("cache-control", "")
