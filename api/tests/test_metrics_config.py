"""Test for GET /metrics-config — the static card chrome the frontend renders."""

from __future__ import annotations

from eukahub_core.metrics import METRIC_KEYS


def test_metrics_config(client):
    body = client.get("/metrics-config").json()
    assert [m["key"] for m in body] == list(METRIC_KEYS)
    for m in body:
        assert m["card_title"]
        assert m["color"].startswith("#")
        assert "{taxid}" in m["external_url_template"]  # client substitutes
        assert m["coverage_column"] == f"c_{m['key']}"
        assert m["total_column"] == f"s_{m['key']}"
