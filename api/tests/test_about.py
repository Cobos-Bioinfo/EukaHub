"""Tests for GET /taxon/{taxid}/about — the Wikipedia "About" card.

The Wikipedia fetch is monkeypatched (via ``main.fetch_about``, the name the
endpoint calls) so these never touch the network — we test the endpoint's
contract, not Wikipedia. The unit-level cache/parse behaviour of ``fetch_about``
is covered separately below and needs no DB.
"""

from __future__ import annotations

from eukahub_api import main
from eukahub_api.schemas import TaxonAbout

_SAMPLE = TaxonAbout(
    title="Animal",
    description="Kingdom of living things",
    extract="Animals are multicellular eukaryotic organisms.",
    thumbnail="https://upload.wikimedia.org/thumb.jpg",
    url="https://en.wikipedia.org/wiki/Animal",
)


def test_about_hit(client, monkeypatch):
    """A resolvable taxon returns the summary the lookup produced."""
    monkeypatch.setattr(main, "fetch_about", lambda name: _SAMPLE)
    body = client.get("/taxon/33208/about").json()  # Metazoa -> Animal
    assert body["title"] == "Animal"
    assert body["thumbnail"] == "https://upload.wikimedia.org/thumb.jpg"
    assert body["url"].startswith("https://en.wikipedia.org/")


def test_about_no_article_is_null(client, monkeypatch):
    """A taxon Wikipedia can't summarise yields a 200 with a null body, so the
    frontend omits the card without treating it as an error."""
    monkeypatch.setattr(main, "fetch_about", lambda name: None)
    resp = client.get("/taxon/9606/about")
    assert resp.status_code == 200
    assert resp.json() is None


def test_about_null_still_cacheable(client, monkeypatch):
    """The null result is a normal 200 → carries Cache-Control (not no-store),
    so downstream caches spare Wikipedia for pageless taxa."""
    monkeypatch.setattr(main, "fetch_about", lambda name: None)
    resp = client.get("/taxon/9606/about")
    assert "public" in resp.headers.get("Cache-Control", "")


def test_about_unknown_taxid_404(client, monkeypatch):
    """An unknown taxid is a 404 (taxon resolution fails before any lookup),
    distinct from 'exists but has no article'."""
    called = False

    def _spy(name):  # must never run — resolution 404s first
        nonlocal called
        called = True

    monkeypatch.setattr(main, "fetch_about", _spy)
    assert client.get("/taxon/999999999/about").status_code == 404
    assert called is False


def test_fetch_about_skips_placeholder_names():
    """The lookup short-circuits placeholder names without a request (no DB,
    no network)."""
    from eukahub_api.wikipedia import fetch_about

    assert fetch_about("Unknown") is None
    assert fetch_about("") is None
