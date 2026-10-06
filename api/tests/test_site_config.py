"""Deployment settings: defaults, environment overrides, the groups file, and the
endpoints that serve them. Only the endpoint tests need the database."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from eukahub_api import main
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
            "EXPORT_BATCH_ROWS": "10000",
        }
    )
    assert s.export_batch_rows == 10000
    assert s.link_templates["ass"] == "https://assemblies.example.org/?taxon={taxid}"
    assert s.link_templates["ann"] == METRICS[1].external_url_template
    assert s.feedback_url == "https://example.org/feedback"
    assert s.privacy_contact_email == "dpo@example.org"
    assert s.wikipedia_summary_url.startswith("https://es.wikipedia.org/")
    assert s.source_code_url == "https://github.com/guigolab/EukaHub"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ASSEMBLY_LINK_TEMPLATE", "http://example.org/?taxon={taxid}"),
        ("ANNOTATION_LINK_TEMPLATE", "https://example.org/no-placeholder"),
        ("FEEDBACK_URL", "javascript:alert(1)"),
        ("SOURCE_CODE_URL", "https://"),
        ("PRIVACY_CONTACT_EMAIL", "not an email"),
        ("WIKIPEDIA_SUMMARY_URL", "https://en.wikipedia.org/api/rest_v1/page/summary/"),
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


def test_endpoints_follow_the_settings(client, monkeypatch, tmp_path):
    settings = load_settings(
        {
            "ASSEMBLY_LINK_TEMPLATE": "https://assemblies.example.org/?taxon={taxid}",
            "FEEDBACK_URL": "https://example.org/feedback",
            "WIKIPEDIA_SUMMARY_URL": "https://es.wikipedia.org/api/rest_v1/page/summary/{title}",
            **_groups_file(
                tmp_path,
                {"groups": [{"taxid": 40674, "label": "Mammals", "featured": True}]},
            ),
        }
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    config = client.get("/config").json()
    links = {m["key"]: m["external_url_template"] for m in config["metrics"]}
    assert links["ass"] == "https://assemblies.example.org/?taxon={taxid}"
    assert config["feedback_url"] == "https://example.org/feedback"
    assert config["wikipedia_summary_url"].startswith("https://es.wikipedia.org/")
    assert config["groups"] == [{"taxid": 40674, "label": "Mammals", "featured": True}]

    # Mammalia is in both the full dataset and the CI slice.
    assert [f["taxid"] for f in client.get("/overview").json()["featured"]] == [40674]
