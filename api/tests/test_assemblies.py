"""Tests for the assembly filters, the recommended order, the best assembly per
species, and the record downloads (``/assemblies/report``, ``/annotations/report``).

They assert relationships between responses, so they hold on the full dataset and
on the CI slice alike.
"""

from __future__ import annotations

import csv
import io
from itertools import pairwise

import pytest

MAMMALIA = 40674
LEVELS = {"complete": "Complete Genome", "chromosome": "Chromosome", "scaffold": "Scaffold", "contig": "Contig"}
LEVEL_ORDER = list(LEVELS.values())


def _get(client, path: str, **params) -> dict:
    resp = client.get(path, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _walk(client, path: str, **params) -> list[dict]:
    """Every row of a list, following ``next``."""
    page = _get(client, path, limit=200, **params)
    rows = list(page["results"])
    while page["next"]:
        page = _get(client, path, limit=200, cursor=page["next"], **params)
        rows += page["results"]
    return rows


def _recommended_key(r: dict) -> tuple:
    """A row's place in the recommended order, smallest first."""
    level = LEVEL_ORDER.index(r["assembly_level"]) if r["assembly_level"] in LEVEL_ORDER else 4
    return (
        r["refseq_category"] != "reference genome",
        level,
        r["contig_n50"] is None,
        -(r["contig_n50"] or 0),
    )


@pytest.fixture(scope="module")
def mammalia(client) -> dict:
    return _get(client, f"/taxons/{MAMMALIA}")


@pytest.fixture(scope="module")
def checks(client) -> dict:
    return _get(client, "/config")["assembly_checks"]


@pytest.mark.parametrize("level", LEVELS)
def test_level_filter_matches_the_taxon_composition(client, mammalia, level):
    d = _get(client, "/assemblies", within=MAMMALIA, assembly_level=level, limit=50)
    assert d["total"] == mammalia["composition"][level]
    assert all(r["assembly_level"] == LEVELS[level] for r in d["results"])


def test_several_levels_add_up(client, mammalia):
    d = _get(client, "/assemblies", within=MAMMALIA, assembly_level=["complete", "chromosome"], limit=1)
    assert d["total"] == mammalia["composition"]["complete"] + mammalia["composition"]["chromosome"]


def test_reference_filter_matches_the_taxon_composition(client, mammalia):
    d = _get(client, "/assemblies", within=MAMMALIA, reference="true", limit=50)
    assert d["total"] == mammalia["composition"]["reference"]
    assert all(r["refseq_category"] == "reference genome" for r in d["results"])


def test_ebp_and_contig_filters(client, mammalia, checks):
    every = mammalia["resources"]["assemblies"]["total"]
    ebp = _get(client, "/assemblies", within=MAMMALIA, ebp_standard="true", limit=200)
    assert ebp["total"] <= every
    for r in ebp["results"]:
        assert r["ebp_standard"]
        assert r["contig_n50"] >= checks["ebp_min_contig_n50"]
        assert r["scaffold_n50"] >= checks["ebp_min_scaffold_n50"]
    at_least = _get(client, "/assemblies", within=MAMMALIA, min_contig_n50=checks["ebp_min_contig_n50"], limit=200)
    assert ebp["total"] <= at_least["total"] <= every
    assert all(r["contig_n50"] >= checks["ebp_min_contig_n50"] for r in at_least["results"])


def test_filters_combine(client):
    both = _get(client, "/assemblies", within=MAMMALIA, reference="true", assembly_level="chromosome", limit=1)
    assert both["total"] <= _get(client, "/assemblies", within=MAMMALIA, reference="true", limit=1)["total"]
    assert both["total"] <= _get(client, "/assemblies", within=MAMMALIA, assembly_level="chromosome", limit=1)["total"]


def test_recommended_is_the_default_order(client):
    rows = _walk(client, "/assemblies", within=MAMMALIA)
    keys = [_recommended_key(r) for r in rows]
    assert keys == sorted(keys)
    assert [r["assembly_accession"] for r in rows] == [
        r["assembly_accession"] for r in _walk(client, "/assemblies", within=MAMMALIA, sort_by="recommended")
    ]


def test_ebp_flag_follows_the_thresholds(client, checks):
    for r in _walk(client, "/assemblies", within=MAMMALIA):
        meets = (r["contig_n50"] or 0) >= checks["ebp_min_contig_n50"] and (
            r["scaffold_n50"] or 0
        ) >= checks["ebp_min_scaffold_n50"]
        assert r["ebp_standard"] == meets


def test_species_of_a_subspecies_record(client):
    """A record counts under its species: the species is the record's own taxon or
    the nearest species among its ancestors."""
    for r in _walk(client, "/assemblies", within=MAMMALIA)[:300]:
        if r["species_taxid"] != r["taxid"]:
            lineage = _get(client, f"/taxons/{r['taxid']}/ancestors")
            species = [t["taxid"] for t in lineage if t["rank"] in ("species", "informal species")]
            assert r["species_taxid"] == species[-1]
            return
    pytest.skip("no record below a species in the first rows")


def test_best_per_species(client, mammalia):
    rows = _walk(client, "/assemblies", within=MAMMALIA, best_per_species="true")
    total = _get(client, "/assemblies", within=MAMMALIA, best_per_species="true", limit=1)["total"]
    assert len(rows) == total
    assert len({r["species_taxid"] for r in rows}) == total
    # Every assembly is counted once, under its species; hybrids and other informal
    # species count as species of their own, so there are at least as many as the
    # formal species with an assembly.
    assert sum(r["species_assemblies"] for r in rows) == mammalia["resources"]["assemblies"]["total"]
    assert total >= mammalia["resources"]["assemblies"]["covered"]
    keys = [_recommended_key(r) for r in rows]
    assert keys == sorted(keys)


def test_best_per_species_picks_the_recommended_one(client):
    rows = _get(client, "/assemblies", within=MAMMALIA, best_per_species="true", limit=5)["results"]
    for r in rows:
        best = _get(client, "/assemblies", within=r["species_taxid"], limit=1)["results"][0]
        assert best["assembly_accession"] == r["assembly_accession"]
        assert r["species_assemblies"] == _get(client, "/assemblies", within=r["species_taxid"], limit=1)["total"]


def test_best_per_species_applies_the_filters_first(client):
    rows = _walk(client, "/assemblies", within=MAMMALIA, best_per_species="true", assembly_level="scaffold")
    assert all(r["assembly_level"] == "Scaffold" for r in rows)
    assert sum(r["species_assemblies"] for r in rows) == _get(
        client, "/assemblies", within=MAMMALIA, assembly_level="scaffold", limit=1
    )["total"]


def test_species_assemblies_is_null_without_best_per_species(client):
    assert all(r["species_assemblies"] is None for r in _get(client, "/assemblies", within=MAMMALIA)["results"])


@pytest.mark.parametrize(
    "params",
    [
        {"sort_by": "recommended"},
        {"sort_by": "recommended", "sort_order": "asc"},
        {"sort_by": "scaffold_n50"},
        {"sort_by": "release_date", "best_per_species": "true"},
        {"sort_by": "recommended", "best_per_species": "true"},
    ],
)
def test_cursor_walks_every_assembly_once(client, params):
    params = {"within": MAMMALIA, "limit": 3, **params}
    pages = [_get(client, "/assemblies", **params)]
    while pages[-1]["next"] and len(pages) < 6:
        pages.append(_get(client, "/assemblies", **params, cursor=pages[-1]["next"]))
    assert len(pages) > 1
    seen = [r["assembly_accession"] for p in pages for r in p["results"]]
    assert len(seen) == len(set(seen))
    for before, after in pairwise(pages):
        back = _get(client, "/assemblies", **params, cursor=after["previous"])
        assert [r["assembly_accession"] for r in back["results"]] == [
            r["assembly_accession"] for r in before["results"]
        ]


def test_annotations_of_an_assembly(client):
    """``annotations`` counts the annotations of any version of the assembly's
    GenBank or RefSeq accession, and ``best_busco`` is their best score."""
    rows = [r for r in _walk(client, "/assemblies", within=MAMMALIA) if r["annotations"] > 0]
    assert rows, "some mammal assemblies are annotated"
    for r in rows[:5]:
        number = r["assembly_accession"][4:].split(".")[0]
        annotations = [
            a
            for a in _walk(client, "/annotations", within=r["species_taxid"])
            if (a["assembly_accession"] or "")[4:].split(".")[0] == number
        ]
        assert r["annotations"] == len(annotations)
        scored = [a["busco_complete"] for a in annotations if a["busco_complete"] is not None]
        assert r["best_busco"] == (max(scored) if scored else None)


def test_bad_filters_are_a_422(client):
    assert client.get("/assemblies", params={"assembly_level": "whole"}).status_code == 422
    assert client.get("/assemblies", params={"min_contig_n50": -1}).status_code == 422
    assert client.get("/assemblies", params={"best_per_species": "maybe"}).status_code == 422


def _tsv(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/tab-separated-values")
    assert resp.headers["cache-control"] == "no-store"
    return list(csv.DictReader(io.StringIO(resp.text), delimiter="\t", quoting=csv.QUOTE_NONE))


@pytest.mark.parametrize(
    "params", [{}, {"best_per_species": "true"}, {"reference": "true", "sort_by": "contig_n50"}]
)
def test_assemblies_report_is_the_list(client, params):
    listed = _walk(client, "/assemblies", within=MAMMALIA, **params)
    resp = client.get("/assemblies/report", params={"within": MAMMALIA, **params})
    rows = _tsv(resp)
    assert 'filename="Mammalia_assemblies.tsv"' in resp.headers["content-disposition"]
    assert [r["assembly_accession"] for r in rows] == [r["assembly_accession"] for r in listed]
    assert set(rows[0]) == set(listed[0])
    first, row = listed[0], rows[0]
    assert row["ebp_standard"] == ("true" if first["ebp_standard"] else "false")
    assert row["bioprojects"] == ",".join(first["bioprojects"])
    assert row["species_assemblies"] == ("" if first["species_assemblies"] is None else str(first["species_assemblies"]))


def test_annotations_report_is_the_list(client):
    listed = _walk(client, "/annotations", within=MAMMALIA)
    rows = _tsv(client.get("/annotations/report", params={"within": MAMMALIA}))
    assert [r["annotation_id"] for r in rows] == [r["annotation_id"] for r in listed]
    assert set(rows[0]) == set(listed[0])


def test_reports_check_their_parameters(client):
    assert client.get("/assemblies/report", params={"within": 999999999}).status_code == 404
    assert client.get("/annotations/report", params={"within": 999999999}).status_code == 404
    assert client.get("/assemblies/report", params={"limit": 5}).status_code == 422
