"""Source settings: defaults, environment overrides, and rejection of bad values."""

from __future__ import annotations

import pytest
from eukahub_core.config import check_https_url, check_seconds
from eukahub_pipeline import build
from eukahub_pipeline import fetch_reads as fr
from eukahub_pipeline.sources import ANNOTRIEVE, ENA, TAXDUMP, Source, load_sources


def test_defaults_when_unset_or_empty():
    sources = load_sources({"ENA_PORTAL_URL": "", "ANNOTRIEVE_TIMEOUT_SECONDS": "  "})
    assert (sources.taxdump, sources.ena, sources.annotrieve) == (TAXDUMP, ENA, ANNOTRIEVE)


def test_overrides():
    sources = load_sources(
        {
            "ENA_PORTAL_URL": "https://ena.example.org/portal/api/",
            "ENA_TIMEOUT_SECONDS": "45.5",
            "ANNOTRIEVE_API_URL": "https://annotrieve.example.org/api/v1",
        }
    )
    assert sources.ena == Source("https://ena.example.org/portal/api", 45.5)
    assert sources.annotrieve.url == "https://annotrieve.example.org/api/v1"
    assert sources.annotrieve.timeout == ANNOTRIEVE.timeout
    assert sources.taxdump == TAXDUMP


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("TAXDUMP_URL", "http://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz"),
        ("ENA_PORTAL_URL", "ftp://ena.example.org"),
        ("ANNOTRIEVE_API_URL", "https:///no-host"),
        ("ANNOTRIEVE_API_URL", "https://example.org/a b"),
        ("ENA_TIMEOUT_SECONDS", "0"),
        ("TAXDUMP_TIMEOUT_SECONDS", "-5"),
        ("ANNOTRIEVE_TIMEOUT_SECONDS", "ten"),
        ("ENA_TIMEOUT_SECONDS", "inf"),
    ],
)
def test_invalid_values_raise_naming_the_variable(variable, value):
    with pytest.raises(ValueError, match=variable):
        load_sources({variable: value})


def test_build_stops_before_downloading_on_an_invalid_value(monkeypatch):
    monkeypatch.setenv("ENA_PORTAL_URL", "http://ena.example.org")
    monkeypatch.setattr(build, "download_taxdump", pytest.fail)
    with pytest.raises(SystemExit) as exc:
        build.main([])
    assert exc.value.code == 2


def test_fetch_reads_uses_the_configured_source(monkeypatch):
    calls = []

    class _Reply:
        text = "count\n0\n"

        def raise_for_status(self):
            pass

    def post(url, *, timeout, **kwargs):
        calls.append((url, timeout))
        return _Reply()

    monkeypatch.setattr(fr.requests, "post", post)
    assert fr._expected_runs(Source("https://ena.example.org/api", 12)) == 0
    assert calls == [("https://ena.example.org/api/count", 12)]


def test_check_https_url_placeholder():
    url = "https://example.org/?taxon={taxid}"
    assert check_https_url(url, placeholder="{taxid}") == url
    with pytest.raises(ValueError, match="taxid"):
        check_https_url("https://example.org/", placeholder="{taxid}")


def test_check_seconds_maximum():
    assert check_seconds("30", maximum=30) == 30
    with pytest.raises(ValueError):
        check_seconds("31", maximum=30)
    with pytest.raises(ValueError):
        check_seconds("nan")
