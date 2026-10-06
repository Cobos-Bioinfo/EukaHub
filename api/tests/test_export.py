"""Tests for GET /taxons/report: every taxon a /taxons query matches, as TSV."""

from __future__ import annotations

import dataclasses
import math

from eukahub_api import main, queries
from eukahub_api.queries import EXPORT_HEADER, TaxonFilter
from eukahub_api.settings import get_settings


def _parse(text: str) -> tuple[list[str], list[list[str]]]:
    lines = text.splitlines()
    header = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[1:]]
    return header, rows


def test_report_headers_and_schema(client):
    resp = client.get("/taxons/report?within=2759&rank=phylum")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/tab-separated-values")
    assert resp.headers["content-disposition"] == (
        'attachment; filename="Eukaryota_phylum_data.tsv"'
    )

    header, rows = _parse(resp.text)
    assert header == list(EXPORT_HEADER)
    assert rows, "Eukaryota should have phyla"
    assert all(len(r) == len(header) for r in rows)
    # A well-known phylum is present, and taxon_id/total_species are integers.
    assert "Chordata" in {r[1] for r in rows}
    assert all(r[0].isdigit() and r[2].isdigit() for r in rows)


def test_report_matches_the_list(client):
    """The report holds every taxon /taxons pages through, in the same order."""
    for query in (
        "within=2759&rank=phylum",
        "within=2759&rank=phylum&exclude_empty=true",
        "within=40674&rank=order&sort_by=gap_ass&sort_order=asc",
        "parent=2759&sort_by=name",
    ):
        _, rows = _parse(client.get(f"/taxons/report?{query}").text)
        listed = client.get(f"/taxons?{query}&limit=1000").json()
        assert [int(r[0]) for r in rows] == [it["taxid"] for it in listed["results"]], query
        assert len(rows) == listed["total"]


def test_report_without_within_is_named_after_the_taxa(client):
    resp = client.get("/taxons/report?taxids=40674,9606")
    assert resp.headers["content-disposition"] == 'attachment; filename="taxa_all_data.tsv"'
    assert len(_parse(resp.text)[1]) == 2


def test_report_bad_filters(client):
    assert client.get("/taxons/report?within=999999999&rank=phylum").status_code == 404
    assert client.get("/taxons/report?within=2759&rank=kingdom").status_code == 422


def test_report_streams_one_chunk_per_batch(client, monkeypatch):
    """The batch size changes how rows are chunked, never which rows are sent."""
    url = "/taxons/report?within=40674&rank=species"  # Mammalia: in the full DB and the CI slice
    whole = client.get(url).text.splitlines()

    small_batches = dataclasses.replace(get_settings(), export_batch_rows=3)
    monkeypatch.setattr(main, "get_settings", lambda: small_batches)
    small = client.get(url).text.splitlines()
    assert small == whole

    with main.app.state.pool.connection() as conn:
        _name, _rank, root_path = queries.fetch_root(conn, 40674)
    chunks = list(
        queries.iter_report_tsv(
            main.app.state.pool,
            TaxonFilter(within_path=root_path, rank="species"),
            sort=None,
            descending=True,
            batch_rows=3,
        )
    )
    n_rows = len(whole) - 1
    assert n_rows > 3
    assert len(chunks) == 1 + math.ceil(n_rows / 3)  # header, then one chunk per batch
