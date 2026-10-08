"""Every error is problem details (RFC 9457), and an unknown parameter is refused."""

from __future__ import annotations

from eukahub_api import main
from eukahub_api.resources import taxons
from fastapi.testclient import TestClient

PROBLEM = "application/problem+json"


def _problem(resp, status: int) -> dict:
    assert resp.status_code == status
    assert resp.headers["content-type"] == PROBLEM
    body = resp.json()
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["title"]
    assert isinstance(body["detail"], str) and body["detail"]
    return body


def test_an_unknown_taxon(client):
    assert _problem(client.get("/taxons/999999999"), 404)["title"] == "Not Found"


def test_an_unknown_path(client):
    _problem(client.get("/taxonz"), 404)


def test_a_method_not_routed_keeps_allow(client):
    resp = client.post("/taxons")
    _problem(resp, 405)
    assert resp.headers["allow"] == "GET"


def test_a_bad_parameter_is_named(client):
    body = _problem(client.get("/taxons", params={"rank": "superclass"}), 422)
    assert [e["parameter"] for e in body["errors"]] == ["rank"]
    assert body["detail"].startswith("rank: ")


def test_a_bad_list_item_names_its_parameter(client):
    body = _problem(client.get("/taxons", params={"filter": ["assemblies", "nope"]}), 422)
    assert [e["parameter"] for e in body["errors"]] == ["filter"]


def test_an_invalid_cursor_is_a_parameter_error(client):
    body = _problem(client.get("/assemblies", params={"cursor": "garbage"}), 422)
    assert [e["parameter"] for e in body["errors"]] == ["cursor"]


def test_an_unknown_parameter_is_refused(client):
    body = _problem(client.get("/taxons", params={"within": 40674, "rnak": "species"}), 422)
    assert [e["parameter"] for e in body["errors"]] == ["rnak"]
    assert "rank" in body["detail"]  # the parameters it takes are listed


def test_parameters_of_shared_dependencies_are_known(client):
    params = {
        "within": 40674,
        "rank": "family",
        "filter": ["assemblies", "annotations"],
        "logic": "or",
        "sort_by": "name",
        "sort_order": "asc",
        "limit": 2,
    }
    assert client.get("/taxons", params=params).status_code == 200


def test_an_endpoint_without_parameters_takes_none(client):
    assert client.get("/taxons/9606/ancestors").status_code == 200
    assert "takes none" in _problem(client.get("/config", params={"x": 1}), 422)["detail"]


def test_logic_is_lower_case(client):
    params = {"within": 40674, "rank": "order", "filter": ["assemblies", "annotations"]}
    assert client.get("/taxons", params={**params, "logic": "or"}).status_code == 200
    _problem(client.get("/taxons", params={**params, "logic": "OR"}), 422)


def test_an_unexpected_error_hides_its_cause(client, monkeypatch):
    def _broken(conn, taxid):
        raise RuntimeError("a bug")

    monkeypatch.setattr(taxons, "fetch_taxon", _broken)
    resp = TestClient(main.app, raise_server_exceptions=False).get("/taxons/2759")
    assert "bug" not in _problem(resp, 500)["detail"]


def test_openapi_documents_every_error_as_a_problem():
    schema = main.app.openapi()
    for path, operations in schema["paths"].items():
        for operation in operations.values():
            assert list(operation["responses"]["default"]["content"]) == [PROBLEM], path
    assert "HTTPValidationError" not in schema["components"]["schemas"]
