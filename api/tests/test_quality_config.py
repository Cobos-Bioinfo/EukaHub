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
    # BUSCO + protein-coding genes are the surfaced (headline) annotation stats.
    headline = {q["key"] for q in body if q["headline"]}
    assert headline == {"busco", "genes"}
    assert all(q["source"] == "annotation" for q in body if q["key"] in headline)
