"""Tests for GET /clade/{taxid}/export.tsv — the full-breakdown TSV download."""

from __future__ import annotations

from eukahub_api.queries import EXPORT_HEADER


def _parse(text: str) -> tuple[list[str], list[list[str]]]:
    lines = text.splitlines()
    header = lines[0].split("\t")
    rows = [ln.split("\t") for ln in lines[1:]]
    return header, rows


def test_export_headers_and_schema(client):
    resp = client.get("/clade/2759/export.tsv?rank=phylum")
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
    names = {r[1] for r in rows}
    assert "Chordata" in names
    assert all(r[0].isdigit() and r[2].isdigit() for r in rows)


def test_export_full_matches_breakdown_total(client):
    # Default export = exclude_empty False → every phylum-rank taxon.
    _, rows = _parse(client.get("/clade/2759/export.tsv?rank=phylum").text)
    bd = client.get("/clade/2759/breakdown?rank=phylum&exclude_empty=false&limit=1").json()
    assert len(rows) == bd["total_matches"]


def test_export_exclude_empty_matches_filtered_total(client):
    _, rows = _parse(
        client.get("/clade/2759/export.tsv?rank=phylum&exclude_empty=true").text
    )
    bd = client.get("/clade/2759/breakdown?rank=phylum&exclude_empty=true&limit=1").json()
    assert len(rows) == bd["total_matches"]


def test_export_bad_root_404(client):
    assert client.get("/clade/999999999/export.tsv?rank=phylum").status_code == 404


def test_export_invalid_rank_422(client):
    assert client.get("/clade/2759/export.tsv?rank=kingdom").status_code == 422
