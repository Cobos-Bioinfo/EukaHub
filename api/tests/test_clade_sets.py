"""Sets of clades and custom groups: the groups-file rules, resolution against the
taxonomy, ``/taxons/aggregate``, and the custom groups in ``/config``. Only the endpoint
tests need the database."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import psycopg
import pytest
from eukahub_api import main, queries
from eukahub_api.clade_sets import (
    SetTaxon,
    clade_set,
    resolve_groups,
    set_metadata,
    set_pieces,
)
from eukahub_api.db import database_url
from eukahub_api.schemas import MAX_CLADES_PER_GROUP, CustomGroup
from eukahub_api.settings import MAX_CUSTOM_GROUPS, load_settings
from eukahub_core.metrics import METRIC_KEYS, QUALITY_STATS, CladeMetadata

CURATED = [{"taxid": 40674, "label": "Mammals"}]


def _settings(tmp_path: Path, custom_groups: list[dict]):
    path = tmp_path / "groups.json"
    path.write_text(json.dumps({"groups": CURATED, "custom_groups": custom_groups}))
    return load_settings({"GROUPS_FILE": str(path)})


# --- Resolution on a small made-up tree -----------------------------------------
#
# 1 > 2759 > 10 > 11
#               > 12 > 121
#               > 13 (informal species)
#          > 20 > 21 (subspecies under species 20)


def _taxon(path: tuple[int, ...], rank: str = "clade", n_rows: int = 0, **flags) -> SetTaxon:
    taxid = path[-1]
    return SetTaxon(
        taxid=taxid,
        name=f"T{taxid}",
        rank=rank,
        path=path,
        infraspecific=flags.get("infraspecific", False),
        features=CladeMetadata(taxid, n_rows, 0, 0, 0, 0, n_rows, 0, 0, 0),
    )


TAXA = {
    t.taxid: t
    for t in (
        _taxon((1,)),
        _taxon((1, 2759), n_rows=100),
        _taxon((1, 2759, 10), n_rows=60),
        _taxon((1, 2759, 10, 11), n_rows=25),
        _taxon((1, 2759, 10, 12), n_rows=30),
        _taxon((1, 2759, 10, 12, 121), n_rows=10),
        _taxon((1, 2759, 10, 13), rank="informal species", n_rows=1),
        _taxon((1, 2759, 20), rank="species", n_rows=1),
        _taxon((1, 2759, 20, 21), rank="subspecies", n_rows=1, infraspecific=True),
    )
}


def _resolve(*groups: dict) -> dict[str, dict[int, bool]]:
    resolved = resolve_groups([CustomGroup(**g) for g in groups], TAXA)
    return {r.group.id: dict(r.marks) for r in resolved}


def test_include_and_exclude_become_marks():
    marks = _resolve({"id": "a", "label": "A", "include": [10, 121], "exclude": [12]})
    assert marks == {"a": {10: True, 12: False, 121: True}}


def test_marks_that_change_nothing_are_dropped():
    marks = _resolve({"id": "a", "label": "A", "include": [10, 11], "exclude": [12, 121]})
    assert marks == {"a": {10: True, 12: False}}


def test_a_set_splits_into_disjoint_pieces():
    marks = clade_set([2759, 121], [10], TAXA)
    assert marks == {2759: True, 10: False, 121: True}
    assert sorted(set_pieces(marks, TAXA)) == [(121, []), (2759, [10])]


def test_counts_are_inside_rows_minus_outside_rows():
    meta = set_metadata({10: True, 12: False, 121: True}, TAXA)
    assert meta.n_rows == 60 - 30 + 10
    assert meta.s_ass == 60 - 30 + 10


@pytest.mark.parametrize(
    ("group", "reason"),
    [
        ({"include": [999]}, "not in the dataset"),
        ({"include": [1]}, "not in the dataset"),
        ({"include": [13]}, "informal species or below a species"),
        ({"include": [21]}, "informal species or below a species"),
        ({"include": [10], "exclude": [20]}, "is excluded but is not inside an included clade"),
    ],
)
def test_a_group_that_does_not_fit_is_skipped(caplog, group, reason):
    caplog.set_level(logging.WARNING, logger="eukahub.api.clade_sets")
    assert _resolve({"id": "bad", "label": "Bad", **group}, {"id": "ok", "label": "OK", "include": [20]}) == {
        "ok": {20: True}
    }
    assert "'bad'" in caplog.text and reason in caplog.text


def test_rest_is_the_parent_minus_its_other_groups():
    marks = _resolve(
        {"id": "rest", "label": "Rest", "parent": "p", "rest": True},
        {"id": "p", "label": "P", "include": [2759]},
        {"id": "most-of-10", "label": "10 without 11", "parent": "p", "include": [10], "exclude": [11]},
    )
    assert marks["rest"] == {2759: True, 10: False, 11: True}


def test_rest_of_a_fully_covered_parent_is_empty():
    marks = _resolve(
        {"id": "p", "label": "P", "include": [10]},
        {"id": "a", "label": "A", "parent": "p", "include": [10], "exclude": [11]},
        {"id": "b", "label": "B", "parent": "p", "include": [11]},
        {"id": "rest", "label": "Rest", "parent": "p", "rest": True},
    )
    assert marks["rest"] == {}


def test_group_rules_under_a_parent(caplog):
    caplog.set_level(logging.WARNING, logger="eukahub.api.clade_sets")
    marks = _resolve(
        {"id": "p", "label": "P", "include": [10]},
        {"id": "a", "label": "A", "parent": "p", "include": [12]},
        {"id": "overlaps-a", "label": "X", "parent": "p", "include": [121]},
        {"id": "outside", "label": "Y", "parent": "p", "include": [20]},
        {"id": "under-outside", "label": "Z", "parent": "outside", "include": [20]},
        {"id": "rest", "label": "Rest", "parent": "p", "rest": True},
    )
    assert set(marks) == {"p", "a", "rest"}
    assert marks["rest"] == {10: True, 12: False}
    assert "'overlaps-a': it overlaps the group 'a'" in caplog.text
    assert "'outside': it is not inside its parent group 'p'" in caplog.text
    assert "'under-outside': its parent 'outside' was skipped" in caplog.text


def test_top_level_groups_may_overlap():
    marks = _resolve(
        {"id": "a", "label": "A", "include": [10]},
        {"id": "b", "label": "B", "include": [12]},
    )
    assert set(marks) == {"a", "b"}


# --- The groups file ----------------------------------------------------------------


def test_custom_groups_are_read_from_the_groups_file(tmp_path):
    s = _settings(
        tmp_path,
        [
            {"id": "fish", "label": " Fish ", "include": [7742], "exclude": [32523]},
            {"id": "rest", "label": "Rest", "parent": "fish", "rest": True},
        ],
    )
    assert [(g.id, g.label, g.include, g.exclude) for g in s.custom_groups] == [
        ("fish", "Fish", (7742,), (32523,)),
        ("rest", "Rest", (), ()),
    ]
    assert [g.taxid for g in s.groups] == [40674]


def test_no_custom_groups_by_default():
    assert load_settings({}).custom_groups == ()


def _group(i: int, **fields) -> dict:
    return {"id": f"g{i}", "label": f"G{i}", "include": [i], **fields}


@pytest.mark.parametrize(
    "custom_groups",
    [
        [_group(1), _group(1)],
        [_group(1, parent="nowhere")],
        [_group(1, parent="g2"), _group(2, parent="g1")],
        [_group(1, parent="g1")],
        [_group(1), {"id": "r", "label": "R", "rest": True}],
        [_group(1), {"id": "r", "label": "R", "parent": "g1", "rest": True, "include": [5]}],
        [
            _group(1),
            {"id": "r1", "label": "R", "parent": "g1", "rest": True},
            {"id": "r2", "label": "R", "parent": "g1", "rest": True},
        ],
        [{"id": "g1", "label": "G1"}],
        [_group(1, exclude=[1])],
        [_group(1, include=list(range(1, MAX_CLADES_PER_GROUP + 2)))],
        [_group(1, include=["7742"])],
        [{**_group(1), "id": "Not A Slug"}],
        [{**_group(1), "colour": "red"}],
        [_group(i) for i in range(1, MAX_CUSTOM_GROUPS + 2)],
    ],
)
def test_invalid_custom_groups_reject_the_file(tmp_path, caplog, custom_groups):
    caplog.set_level(logging.WARNING, logger="eukahub.api.settings")
    s = _settings(tmp_path, custom_groups)
    assert s.custom_groups == () and s.groups == load_settings({}).groups
    assert "groups file" in caplog.text


# --- The endpoints (Vertebrata, Tetrapoda, Mammalia and Primates are in both the full
# dataset and the CI slice) -----------------------------------------------------------

ENDPOINT_GROUPS = [
    {"id": "vertebrates", "label": "Vertebrates", "include": [7742]},
    {"id": "mammals", "label": "Mammals", "parent": "vertebrates", "include": [40674]},
    {
        "id": "non-tetrapods",
        "label": "Fish",
        "parent": "vertebrates",
        "include": [7742],
        "exclude": [32523],
    },
    {"id": "other-vertebrates", "label": "Other", "parent": "vertebrates", "rest": True},
    {"id": "missing", "label": "Missing", "include": [999999999]},
    {"id": "under-missing", "label": "Orphan", "parent": "missing", "include": [40674]},
]


def _counts(body: dict) -> list[int]:
    return (
        [body["n_rows"]]
        + [body["resources"][k][f] for k in METRIC_KEYS for f in ("covered", "total")]
        + list(body["composition"].values())
    )


def _stats(body: dict) -> dict[str, float | None]:
    return {s["key"]: s["value"] for s in body["stats"]}


def _aggregate(client, include: list[int], exclude: list[int] = ()) -> dict:
    response = client.get(
        "/taxons/aggregate",
        params={"include": ",".join(map(str, include)), "exclude": ",".join(map(str, exclude))},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _expected_quality(where: str, paths: list[str]) -> dict[str, float | None]:
    """The quality stats of the records matching ``where``, a hand-written subtree
    filter over ``t.path``."""
    expected: dict[str, float | None] = {}
    with psycopg.connect(database_url()) as conn:
        for source in ("assembly", "annotation"):
            keys = [q.key for q in QUALITY_STATS if q.source == source]
            row = conn.execute(
                f"SELECT {queries._quality_stats_agg(source)} FROM {source} r "
                f"JOIN taxon t USING (taxid) WHERE {where}",
                paths,
            ).fetchone()
            expected |= {k: float(v) if v is not None else None for k, v in zip(keys, row)}
    return expected


def _path(taxid: int) -> str:
    with psycopg.connect(database_url()) as conn:
        return conn.execute("SELECT path::text FROM taxon WHERE taxid = %s", (taxid,)).fetchone()[0]


def test_aggregate_counts_are_clade_differences(client):
    body = _aggregate(client, [40674], [9443])
    mammals = client.get("/taxons/40674").json()
    primates = client.get("/taxons/9443").json()
    assert _counts(body) == [m - p for m, p in zip(_counts(mammals), _counts(primates))]
    assert [t["taxid"] for t in body["include"]] == [40674]
    assert [t["taxid"] for t in body["exclude"]] == [9443]
    assert _stats(body) == _expected_quality(
        "t.path <@ %s::ltree AND NOT t.path <@ %s::ltree", [_path(40674), _path(9443)]
    )


def test_aggregate_of_one_clade_matches_the_clade(client):
    body = _aggregate(client, [40674])
    assert _counts(body) == _counts(client.get("/taxons/40674").json())
    assert body["stats"] == client.get("/taxons/40674/stats").json()["stats"]


def test_aggregate_can_include_inside_an_excluded_clade(client):
    body = _aggregate(client, [7742, 40674], [32523])
    summaries = {t: _counts(client.get(f"/taxons/{t}").json()) for t in (7742, 32523, 40674)}
    assert _counts(body) == [
        v - t + m for v, t, m in zip(summaries[7742], summaries[32523], summaries[40674])
    ]
    assert _stats(body) == _expected_quality(
        "(t.path <@ %s::ltree AND NOT t.path <@ %s::ltree) OR t.path <@ %s::ltree",
        [_path(7742), _path(32523), _path(40674)],
    )


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"include": ""}, "at least one taxid"),
        ({"include": "40674,abc"}, "is not a taxid"),
        ({"include": "-5"}, "is not a taxid"),
        ({"include": ",".join(str(i) for i in range(1, MAX_CLADES_PER_GROUP + 2))}, "at most"),
        ({"include": "40674", "exclude": ",".join(str(i) for i in range(1, 2001))}, "at most"),
        ({"include": "40674", "exclude": "40674"}, "both included and excluded"),
        ({"include": "999999999"}, "not in the dataset"),
        ({"include": "9443", "exclude": "40674"}, "not inside an included clade"),
    ],
)
def test_aggregate_rejects_what_is_not_a_set(client, params, detail):
    response = client.get("/taxons/aggregate", params=params)
    assert response.status_code == 422
    assert detail in response.json()["detail"]


@pytest.fixture
def custom_groups_body(client, monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="eukahub.api.clade_sets")
    monkeypatch.setattr(main, "get_settings", lambda: _settings(tmp_path, ENDPOINT_GROUPS))
    response = client.get("/config")
    assert response.status_code == 200
    return {g["id"]: g for g in response.json()["custom_groups"]}


def test_custom_groups_without_any(client):
    assert client.get("/config").json()["custom_groups"] == []


def test_custom_groups_keep_file_order_and_skip_what_does_not_fit(custom_groups_body, caplog):
    assert list(custom_groups_body) == ["vertebrates", "mammals", "non-tetrapods", "other-vertebrates"]
    logged = " ".join(r.getMessage() for r in caplog.get_records("setup"))
    assert "taxid 999999999 is not in the dataset" in logged
    assert "'under-missing'" in logged
    rest = custom_groups_body["other-vertebrates"]
    assert rest["rest"] and rest["parent"] == "vertebrates"
    assert [t["taxid"] for t in rest["include"]] == [32523]
    assert [t["taxid"] for t in rest["exclude"]] == [40674]


def test_custom_groups_under_a_parent_add_up_to_it(client, custom_groups_body):
    def counts(group_id: str) -> list[int]:
        g = custom_groups_body[group_id]
        return _counts(
            _aggregate(client, [t["taxid"] for t in g["include"]], [t["taxid"] for t in g["exclude"]])
        )

    children = ("mammals", "non-tetrapods", "other-vertebrates")
    assert [sum(c) for c in zip(*map(counts, children))] == counts("vertebrates")
