"""Deployment settings: defaults, environment overrides, the groups file, and the
endpoints that serve them. Only the endpoint tests need the database."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
from eukahub_api import main, wikipedia
from eukahub_api.settings import (
    DEFAULT_GROUPS,
    DEFAULT_SOURCE_CODE_URL,
    LINK_TEMPLATE_VARS,
    MAX_FEATURED_GROUPS,
    load_settings,
)
from eukahub_core.metrics import METRIC_KEYS, METRICS

EXAMPLE_GROUPS = Path(__file__).resolve().parents[2] / "infra" / "config" / "groups.example.json"


def _groups_file(tmp_path: Path, content: object) -> dict[str, str]:
    path = tmp_path / "groups.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return {"GROUPS_FILE": str(path)}


def test_defaults():
    s = load_settings({})
    assert s.link_templates == {m.key: m.external_url_template for m in METRICS}
    assert s.source_code_url == DEFAULT_SOURCE_CODE_URL
    assert s.wikipedia_user_agent == f"EukaHub/1.0 ({DEFAULT_SOURCE_CODE_URL})"
    assert s.groups == DEFAULT_GROUPS
    assert s.featured_taxids == (40674, 8782, 7898, 50557, 4751, 3398)


def test_every_metric_has_a_link_variable():
    assert set(LINK_TEMPLATE_VARS) == set(METRIC_KEYS)


def test_example_groups_file_matches_the_defaults():
    assert load_settings({"GROUPS_FILE": str(EXAMPLE_GROUPS)}).groups == DEFAULT_GROUPS


def test_overrides():
    s = load_settings(
        {
            "ASSEMBLY_LINK_TEMPLATE": "https://assemblies.example.org/?taxon={taxid}",
            "FEEDBACK_URL": "https://example.org/feedback",
            "SOURCE_CODE_URL": "https://github.com/guigolab/EukaHub",
            "PRIVACY_CONTACT_EMAIL": "dpo@example.org",
            "WIKIPEDIA_SUMMARY_URL": "https://es.wikipedia.org/api/rest_v1/page/summary/{title}",
            "WIKIPEDIA_TIMEOUT_SECONDS": "2.5",
            "EXPORT_BATCH_ROWS": "10000",
        }
    )
    assert s.export_batch_rows == 10000
    assert s.link_templates["ass"] == "https://assemblies.example.org/?taxon={taxid}"
    assert s.link_templates["ann"] == METRICS[1].external_url_template
    assert s.feedback_url == "https://example.org/feedback"
    assert s.privacy_contact_email == "dpo@example.org"
    assert s.wikipedia_summary_url.startswith("https://es.wikipedia.org/")
    assert s.wikipedia_timeout_seconds == 2.5
    # The default User-Agent names whoever runs the server.
    assert s.wikipedia_user_agent == "EukaHub/1.0 (https://github.com/guigolab/EukaHub)"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ASSEMBLY_LINK_TEMPLATE", "http://example.org/?taxon={taxid}"),
        ("ANNOTATION_LINK_TEMPLATE", "https://example.org/no-placeholder"),
        ("FEEDBACK_URL", "javascript:alert(1)"),
        ("SOURCE_CODE_URL", "https://"),
        ("PRIVACY_CONTACT_EMAIL", "not an email"),
        ("WIKIPEDIA_SUMMARY_URL", "https://en.wikipedia.org/api/rest_v1/page/summary/"),
        ("WIKIPEDIA_USER_AGENT", "EukaHub\r\nX-Injected: 1"),
        ("WIKIPEDIA_TIMEOUT_SECONDS", "120"),
        ("EXPORT_BATCH_ROWS", "500"),
        ("EXPORT_BATCH_ROWS", "20000"),
        ("EXPORT_BATCH_ROWS", "5e3"),
    ],
)
def test_invalid_values_fall_back_with_a_warning(caplog, variable, value):
    caplog.set_level(logging.WARNING, logger="eukahub.api.settings")
    assert load_settings({variable: value}) == load_settings({})
    assert variable in caplog.text


def test_groups_file(tmp_path):
    s = load_settings(
        _groups_file(
            tmp_path,
            {
                "groups": [
                    {"taxid": 8782, "label": " Birds ", "featured": True},
                    {"taxid": 9443, "label": "Primates"},
                    {"taxid": 40674, "label": "Mammals", "featured": True},
                ]
            },
        )
    )
    assert [(g.taxid, g.label) for g in s.groups] == [
        (8782, "Birds"),
        (9443, "Primates"),
        (40674, "Mammals"),
    ]
    assert s.featured_taxids == (8782, 40674)


def test_missing_groups_file_uses_the_defaults(tmp_path):
    assert load_settings({"GROUPS_FILE": str(tmp_path / "absent.json")}).groups == DEFAULT_GROUPS


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        [],
        {"groups": []},
        {"groups": [{"taxid": 1, "label": "A"}], "extra": True},
        {"groups": [{"taxid": 1, "label": "A", "colour": "red"}]},
        {"groups": [{"taxid": "40674", "label": "Mammals"}]},
        {"groups": [{"taxid": True, "label": "Root"}]},
        {"groups": [{"taxid": 0, "label": "Zero"}]},
        {"groups": [{"taxid": 1, "label": "   "}]},
        {"groups": [{"taxid": 1, "label": "x" * 61}]},
        {"groups": [{"taxid": 1, "label": "A", "featured": "yes"}]},
        {"groups": [{"taxid": 1, "label": "A"}, {"taxid": 1, "label": "B"}]},
        {
            "groups": [
                {"taxid": t, "label": f"G{t}", "featured": True}
                for t in range(1, MAX_FEATURED_GROUPS + 2)
            ]
        },
    ],
)
def test_invalid_groups_file_uses_the_defaults(tmp_path, caplog, content):
    caplog.set_level(logging.WARNING, logger="eukahub.api.settings")
    assert load_settings(_groups_file(tmp_path, content)).groups == DEFAULT_GROUPS
    assert "groups file" in caplog.text


def test_site_config_endpoint(client):
    body = client.get("/site-config").json()
    assert set(body) == {"feedback_url", "source_code_url", "privacy_contact_email", "groups"}
    assert body["feedback_url"].startswith("https://")
    assert body["source_code_url"].startswith("https://")
    assert any(g["featured"] for g in body["groups"])
    for g in body["groups"]:
        assert set(g) == {"taxid", "label", "featured"}


def test_endpoints_follow_the_settings(client, monkeypatch, tmp_path):
    settings = load_settings(
        {
            "ASSEMBLY_LINK_TEMPLATE": "https://assemblies.example.org/?taxon={taxid}",
            "FEEDBACK_URL": "https://example.org/feedback",
            **_groups_file(
                tmp_path,
                {"groups": [{"taxid": 40674, "label": "Mammals", "featured": True}]},
            ),
        }
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    links = {m["key"]: m["external_url_template"] for m in client.get("/metrics-config").json()}
    assert links["ass"] == "https://assemblies.example.org/?taxon={taxid}"

    site = client.get("/site-config").json()
    assert site["feedback_url"] == "https://example.org/feedback"
    assert site["groups"] == [{"taxid": 40674, "label": "Mammals", "featured": True}]

    # Mammalia is in both the full dataset and the CI slice.
    assert [f["taxid"] for f in client.get("/overview").json()["featured"]] == [40674]


def test_wikipedia_lookup_uses_the_settings(monkeypatch):
    settings = load_settings(
        {
            "WIKIPEDIA_SUMMARY_URL": "https://es.wikipedia.org/api/rest_v1/page/summary/{title}",
            "WIKIPEDIA_USER_AGENT": "EukaHub/1.0 (ops@example.org)",
            "WIKIPEDIA_TIMEOUT_SECONDS": "3",
        }
    )
    monkeypatch.setattr(wikipedia, "get_settings", lambda: settings)
    seen = {}

    class _Response(io.BytesIO):
        status = 200

    def urlopen(request, timeout):
        seen.update(url=request.full_url, agent=request.get_header("User-agent"), timeout=timeout)
        return _Response(json.dumps({"title": "Aves", "extract": "Birds."}).encode())

    monkeypatch.setattr(wikipedia.urllib.request, "urlopen", urlopen)
    about = wikipedia._lookup("Aves")
    assert seen == {
        "url": "https://es.wikipedia.org/api/rest_v1/page/summary/Aves",
        "agent": "EukaHub/1.0 (ops@example.org)",
        "timeout": 3.0,
    }
    # Without content_urls the article link is built on the configured host.
    assert about is not None and about.url == "https://es.wikipedia.org/wiki/Aves"
