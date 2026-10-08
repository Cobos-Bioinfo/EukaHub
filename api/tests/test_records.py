"""Tests for the record lists, ``GET /assemblies`` and ``GET /annotations``, and
their cursor paging.

DB-backed via the shared ``client`` fixture; the facts asserted are stable NCBI
biology (Homo sapiens has many assemblies + Ensembl annotations; Mammalia is a
large subtree) plus structural invariants that survive a data rebuild.
"""

from __future__ import annotations

import base64
import json
from itertools import pairwise

import pytest


def _ids(page: dict) -> list[str]:
    return [r.get("annotation_id") or r["assembly_accession"] for r in page["results"]]


def test_assemblies_human(client):
    d = client.get("/assemblies", params={"within": 9606, "limit": 3}).json()
    assert set(d) == {"total", "limit", "next", "previous", "results"}
    assert d["total"] > 100  # thousands of human assemblies
    assert d["limit"] == 3 and len(d["results"]) == 3
    assert d["previous"] is None and d["next"]

    it = d["results"][0]
    assert it["assembly_accession"].startswith(("GCA_", "GCF_"))
    assert it["download_url"].endswith("/")  # deep link to the NCBI genome page
    assert isinstance(it["bioprojects"], list)
    assert it["organism_name"]  # scientific name at the record's taxid


def test_annotations_human_busco_sorted(client):
    """Default sort: best BUSCO first, records without BUSCO last."""
    d = client.get("/annotations", params={"within": 9606, "limit": 5}).json()
    assert d["total"] > 10
    it = d["results"][0]
    assert it["annotation_id"]
    assert it["source_database"]  # e.g. Ensembl / NCBI
    buscos = [i["busco_complete"] for i in d["results"] if i["busco_complete"] is not None]
    assert buscos == sorted(buscos, reverse=True)


def test_without_within_lists_every_record(client):
    everything = client.get("/assemblies", params={"limit": 1}).json()["total"]
    assert everything >= client.get("/assemblies", params={"within": 40674, "limit": 1}).json()[
        "total"
    ]
    assert everything == client.get("/taxons/2759").json()["resources"]["ass"]["total"]


@pytest.mark.parametrize(
    ("path", "sort_by"),
    [
        ("/assemblies", "contig_n50"),
        ("/assemblies", "release_date"),
        ("/annotations", "protein_coding_count"),
    ],
)
@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_cursor_walks_every_record_once(client, path, sort_by, sort_order):
    """Following ``next`` visits each record once, in order, and stops; ``previous``
    from any page returns the page before it."""
    params = {"within": 40674, "sort_by": sort_by, "sort_order": sort_order, "limit": 7}
    pages = [client.get(path, params=params).json()]
    while pages[-1]["next"] and len(pages) < 6:
        pages.append(client.get(path, params={**params, "cursor": pages[-1]["next"]}).json())
    assert len(pages) > 1, "Mammalia has more than 7 records of each kind"

    seen = [i for p in pages for i in _ids(p)]
    assert len(seen) == len(set(seen))
    assert all(p["total"] == pages[0]["total"] for p in pages)

    values = [r[sort_by] for p in pages for r in p["results"]]
    present = [v for v in values if v is not None]
    assert present == sorted(present, reverse=sort_order == "desc")
    assert values[: len(present)] == present  # missing values come last

    for before, after in pairwise(pages):
        back = client.get(path, params={**params, "cursor": after["previous"]}).json()
        assert _ids(back) == _ids(before)
    assert pages[0]["previous"] is None


def test_last_page_has_no_next(client):
    total = client.get("/assemblies", params={"within": 9606, "limit": 1}).json()["total"]
    assert total >= 2
    params = {"within": 9606, "limit": min(200, (total + 1) // 2)}
    d = client.get("/assemblies", params=params).json()
    while d["next"]:
        d = client.get("/assemblies", params={**params, "cursor": d["next"]}).json()
    assert d["previous"] and 0 < len(d["results"]) <= params["limit"]


def test_cursor_of_another_sort_is_rejected(client):
    first = client.get("/assemblies", params={"within": 40674, "limit": 2}).json()
    resp = client.get(
        "/assemblies",
        params={"within": 40674, "limit": 2, "sort_by": "contig_n50", "cursor": first["next"]},
    )
    assert resp.status_code == 422
    assert "another sort order" in resp.json()["detail"]


def _token(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


_RELEASE = "assembly:release_date:desc"


@pytest.mark.parametrize(
    ("sort_by", "cursor"),
    [
        ("release_date", "not a cursor"),
        ("release_date", _token([1, 2, 3])),
        ("release_date", _token({"o": _RELEASE, "b": False, "v": [False, "2020-01-01"]})),
        ("release_date", _token({"o": _RELEASE, "b": False, "v": [False, 5, "GCA_1"]})),
        ("release_date", _token({"o": _RELEASE, "b": False, "v": [False, "13/01/2020", "GCA_1"]})),
        ("release_date", _token({"o": _RELEASE, "b": "no", "v": [False, "2020-01-01", "GCA_1"]})),
        ("release_date", _token({"o": _RELEASE, "b": False, "v": [1, "2020-01-01", "GCA_1"]})),
        ("release_date", _token({"o": _RELEASE, "b": False, "v": [False, None, "x" * 501]})),
        (
            "contig_n50",
            _token({"o": "assembly:contig_n50:desc", "b": False, "v": [False, 2**70, "GCA_1"]}),
        ),
    ],
)
def test_forged_cursors_are_a_422(client, sort_by, cursor):
    resp = client.get("/assemblies", params={"sort_by": sort_by, "cursor": cursor})
    assert resp.status_code == 422


def test_records_unknown_within_is_a_404(client):
    assert client.get("/assemblies", params={"within": 999999999}).status_code == 404
    assert client.get("/annotations", params={"within": 999999999}).status_code == 404


def test_records_limits(client):
    assert client.get("/assemblies", params={"limit": 201}).status_code == 422
    assert client.get("/assemblies", params={"limit": 0}).status_code == 422
    assert client.get("/assemblies", params={"cursor": "x" * 1001}).status_code == 422
