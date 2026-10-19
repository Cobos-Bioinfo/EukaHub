"""Taxids NCBI has merged into another: every request that names a taxon answers
for the one it was merged into."""

from __future__ import annotations

import psycopg
import pytest
from eukahub_api.db import database_url


@pytest.fixture(scope="module")
def merged(client) -> tuple[int, int]:
    """``(old taxid, current taxid)`` of a merged taxid in the dataset."""
    with psycopg.connect(database_url()) as conn:
        row = conn.execute(
            "SELECT taxid, merged_into FROM taxon_merged ORDER BY taxid LIMIT 1"
        ).fetchone()
    if row is None:
        pytest.skip("no merged taxids in this dataset")
    return row


def _json(client, path: str, **params) -> object:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("suffix", ["", "/ancestors", "/stats"])
def test_a_merged_taxid_answers_for_its_current_taxon(client, merged, suffix):
    old, current = merged
    assert _json(client, f"/taxons/{old}{suffix}") == _json(client, f"/taxons/{current}{suffix}")


def test_the_answer_names_the_current_taxid(client, merged):
    old, current = merged
    assert _json(client, f"/taxons/{old}")["taxid"] == current
    assert _json(client, f"/taxons/{old}/stats")["taxid"] == current


@pytest.mark.parametrize(
    ("path", "param"),
    [("/taxons", "within"), ("/taxons", "parent"), ("/assemblies", "within"), ("/annotations", "within")],
)
def test_a_merged_taxid_works_as_a_filter(client, merged, path, param):
    old, current = merged
    assert _json(client, path, **{param: old}) == _json(client, path, **{param: current})


def test_an_unknown_taxid_is_still_not_found(client):
    assert client.get("/taxons/999999999").status_code == 404
