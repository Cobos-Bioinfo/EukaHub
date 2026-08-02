"""Tests for GET /overview — the landing-page totals + featured groups.

Rebuild/slice-safe: asserts cross-endpoint consistency and structural
invariants rather than frozen numbers. Mammalia (40674) is in both the full DB
and the CI seed slice, so it is a stable anchor in the featured list.
"""

from __future__ import annotations

from eukahub_api.queries import FEATURED_TAXIDS


def test_overview_totals_match_eukaryota_summary(client):
    """The global totals are Eukaryota's rollup — cross-check against the summary
    endpoint so the two can't drift."""
    ov = client.get("/overview").json()
    summ = client.get("/clade/2759/summary").json()

    t = ov["totals"]
    assert t["species"] == summ["n_rows"]
    assert t["assemblies"] == summ["resources"]["ass"]["total"]
    assert t["annotations"] == summ["resources"]["ann"]["total"]
    assert t["rna_seq"] == summ["resources"]["rna"]["total"]
    assert t["long_read"] == summ["resources"]["lng"]["total"]
    assert t["reference_genomes"] == summ["composition"]["reference"]


def test_overview_featured_shape(client):
    """Featured groups are a subset of the configured set, in configured order,
    each with sane coverage percentages."""
    ov = client.get("/overview").json()
    featured = ov["featured"]
    assert featured, "at least Mammalia should be featured"

    taxids = [f["taxid"] for f in featured]
    assert set(taxids) <= set(FEATURED_TAXIDS)
    # Preserved FEATURED_TAXIDS order (a filtered subsequence of it).
    assert taxids == [t for t in FEATURED_TAXIDS if t in set(taxids)]

    for f in featured:
        assert f["name"]
        assert f["species"] > 0
        assert f["assemblies"] >= 0
        assert 0.0 <= f["assembly_percent"] <= 100.0
        assert 0.0 <= f["annotation_percent"] <= 100.0


def test_overview_features_mammalia(client):
    """Mammalia (40674) is present in both prod and the CI slice, so it must
    surface with its scientific name and a positive species count."""
    ov = client.get("/overview").json()
    mammalia = next((f for f in ov["featured"] if f["taxid"] == 40674), None)
    assert mammalia is not None
    assert mammalia["name"] == "Mammalia"
    assert mammalia["species"] > 0


def test_overview_is_cacheable(client):
    r = client.get("/overview")
    assert r.status_code == 200
    assert "public" in r.headers.get("cache-control", "")
