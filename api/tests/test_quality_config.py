"""Test for GET /quality-config — the quality-dimension card chrome (the
analogue of /metrics-config for BUSCO / gene count / genome size / N50)."""

from __future__ import annotations

from eukahub_core.metrics import QUALITY_KEYS


def test_quality_config(client):
    body = client.get("/quality-config").json()
    assert [q["key"] for q in body] == list(QUALITY_KEYS)
    for q in body:
        assert q["card_title"]
        assert q["help"]
        assert q["source"] in {"assembly", "annotation"}
        assert q["fmt"] in {"percent", "integer", "basepairs"}
    # The headline stats compare groups on the Gaps page, so they are medians, and
    # every label says which summary it shows.
    headline = {q["key"] for q in body if q["headline"]}
    assert headline == {"genes", "genome_size"}
    for q in body:
        assert q["card_title"].startswith("Median" if q["key"] != "busco" else "Best")
