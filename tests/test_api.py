"""End-to-end API tests against a disposable synthetic database."""
from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient

import db
import seed
from web.api import api


TOKEN = "test-health-data-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "healthdata.sqlite"))
    monkeypatch.setattr(seed, "RNG", random.Random(20260717))
    monkeypatch.setenv("FASTHEALTHDATA_API_TOKEN", TOKEN)
    monkeypatch.setenv("FASTHEALTHDATA_API_ACTOR", "test-suite")
    seed.build()
    with TestClient(api) as test_client:
        yield test_client


def test_openapi_health_and_consistent_errors(client, monkeypatch):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["version"] == "1.0.0"
    assert len(schema["paths"]) >= 20
    assert "/v1/projects/{project_id}/stage" in schema["paths"]
    assert "/v1/access-requests/{request_id}/decision" in schema["paths"]
    assert "/v1/disclosure/k-anonymity" in schema["paths"]

    health = client.get("/v1/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "product": "FastHealthData",
        "version": "1.0.0",
        "database_ready": True,
        "writes_enabled": True,
        "synthetic_only": True,
    }

    missing = client.get("/v1/not-a-route")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "http_error"

    validation = client.post("/v1/projects", headers=AUTH, json={})
    assert validation.status_code == 422
    assert validation.json()["error"]["code"] == "validation_error"

    monkeypatch.delenv("FASTHEALTHDATA_API_TOKEN")
    disabled = client.get("/v1/audit")
    assert disabled.status_code == 503
    assert disabled.json()["error"]["code"] == "protected_api_disabled"
    assert client.get("/v1/projects").status_code == 200


def test_public_portfolio_catalog_and_aggregate_analytics(client):
    summary = client.get("/v1/summary").json()
    assert summary["total_projects"] == 8
    assert summary["subjects"] == 900
    assert sum(row["count"] for row in summary["by_stage"]) == 8

    projects = client.get("/v1/projects?stage=Active&q=diabetes").json()
    assert projects["meta"]["total"] == 1
    assert "Diabetes" in projects["data"][0]["title"]

    fhir = client.get("/v1/datasets?standard=HL7%20FHIR").json()
    assert fhir["meta"]["total"] > 0
    assert {row["standard"] for row in fhir["data"]} == {"HL7 FHIR"}
    dataset_id = fhir["data"][0]["id"]
    detail = client.get(f"/v1/datasets/{dataset_id}").json()
    assert detail["dataset"]["id"] == dataset_id
    assert detail["variables"]
    pii = client.get(f"/v1/datasets/{dataset_id}/variables?pii_only=true").json()
    assert pii["data"] and all(row["is_pii"] == 1 for row in pii["data"])

    invalid = client.get("/v1/datasets?standard=DROP%20TABLE")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_standard"

    cohort = client.get("/v1/analytics/cohort?group_by=condition").json()
    assert cohort["total"] == 900
    outcomes = client.get("/v1/analytics/outcomes").json()
    assert sum(row["count"] for row in outcomes) == 900
    enrollment = client.get("/v1/analytics/enrollment").json()
    assert sum(row["count"] for row in enrollment) == 900


def test_project_registration_lifecycle_and_audit(client):
    lead = db.users("Researcher")[0]
    payload = {
        "title": "Synthetic FHIR Outcomes Study",
        "code": "FHIR-OUT-API",
        "description": "Synthetic API integration test project.",
        "lead_id": lead["id"],
        "legal_basis": db.LEGAL_BASES[2],
    }
    created = client.post("/v1/projects", headers=AUTH, json=payload)
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["stage"] == "Registered"

    duplicate = client.post("/v1/projects", headers=AUTH, json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "project_conflict"

    changed = client.patch(
        f"/v1/projects/{project['id']}/stage",
        headers=AUTH,
        json={"stage": "Data Intake"},
    )
    assert changed.status_code == 200
    assert changed.json()["stage"] == "Data Intake"

    audit = client.get("/v1/audit?entity=project", headers=AUTH).json()["data"]
    actions = {row["action"] for row in audit if row["entity_id"] == project["id"]}
    assert any("Registered project" in action for action in actions)
    assert "Project stage → Data Intake" in actions


def test_dataset_and_variable_registration_capture_governance_metadata(client):
    project = client.get("/v1/projects?limit=1").json()["data"][0]
    steward = db.users("Data Steward")[0]
    created = client.post(
        "/v1/datasets",
        headers=AUTH,
        json={
            "project_id": project["id"],
            "name": "FastClinic FHIR research extract",
            "standard": "HL7 FHIR",
            "sensitivity": "Pseudonymised",
            "subject_count": 250,
            "steward_id": steward["id"],
        },
    )
    assert created.status_code == 201, created.text
    dataset_id = created.json()["dataset"]["id"]
    assert created.json()["dataset"]["standard"] == "HL7 FHIR"

    variable = client.post(
        f"/v1/datasets/{dataset_id}/variables",
        headers=AUTH,
        json={
            "name": "Patient.identifier",
            "concept": "Research-zone subject pseudonym",
            "data_type": "categorical",
            "standard_code": "FHIR:Patient.identifier",
            "is_pii": True,
        },
    )
    assert variable.status_code == 201, variable.text
    assert variable.json()["is_pii"] == 1

    changed = client.patch(
        f"/v1/datasets/{dataset_id}",
        headers=AUTH,
        json={
            "standard": "HL7 FHIR",
            "sensitivity": "Anonymised",
            "subject_count": 245,
            "steward_id": steward["id"],
        },
    )
    assert changed.status_code == 200
    assert changed.json()["dataset"]["sensitivity"] == "Anonymised"
    assert changed.json()["variables"][0]["standard_code"] == "FHIR:Patient.identifier"

    duplicate = client.post(
        f"/v1/datasets/{dataset_id}/variables",
        headers=AUTH,
        json={
            "name": "Patient.identifier",
            "data_type": "categorical",
        },
    )
    assert duplicate.status_code == 409
    audit = client.get("/v1/audit", headers=AUTH).json()["data"]
    assert any(row["entity"] == "dataset" and row["entity_id"] == dataset_id for row in audit)
    assert any(row["entity"] == "variable" and row["entity_id"] == variable.json()["id"] for row in audit)


def test_access_request_decision_is_one_way_and_audited(client):
    dataset = client.get("/v1/datasets?limit=1").json()["data"][0]
    requester = db.users("Researcher")[0]
    created = client.post(
        "/v1/access-requests",
        headers=AUTH,
        json={
            "dataset_id": dataset["id"],
            "requester_id": requester["id"],
            "purpose": "Synthetic evaluation of a governed research cohort.",
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    assert created.json()["status"] == "Pending"

    decided = client.post(
        f"/v1/access-requests/{request_id}/decision",
        headers=AUTH,
        json={"decision": "Approved"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "Approved"

    second = client.post(
        f"/v1/access-requests/{request_id}/decision",
        headers=AUTH,
        json={"decision": "Rejected"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "already_decided"

    audit = client.get("/v1/audit?entity=access_request", headers=AUTH).json()["data"]
    assert any(row["entity_id"] == request_id and "approved" in row["action"] for row in audit)


def test_disclosure_endpoints_are_protected_bounded_and_do_not_log_identifiers(client):
    identifier = "synthetic-direct-identifier@example.test"
    first = client.post("/v1/pseudonymise", headers=AUTH, json={"identifier": identifier})
    second = client.post("/v1/pseudonymise", headers=AUTH, json={"identifier": identifier})
    assert first.status_code == second.status_code == 200
    assert first.json()["pseudonym"] == second.json()["pseudonym"]
    assert first.json()["pseudonym"].startswith("PSN-")
    assert first.json()["production_ready"] is False

    risk = client.get("/v1/disclosure/k-anonymity", headers=AUTH)
    assert risk.status_code == 200
    assert risk.json()["quasi_identifiers"] == ["age_band", "sex", "region"]
    assert risk.json()["threshold"] == 5
    assert "guarantee" in risk.json()["warning"]

    injection = client.get(
        "/v1/disclosure/k-anonymity?quasi_identifiers=age_band,sqlite_version()",
        headers=AUTH,
    )
    assert injection.status_code == 422
    assert injection.json()["error"]["code"] == "invalid_quasi_identifiers"

    audit = client.get("/v1/audit", headers=AUTH)
    assert identifier not in audit.text
    assert "Pseudonymised identifier via API" in audit.text


def test_developer_page_and_mounted_api(client):
    import web_app

    with TestClient(web_app.app) as app_client:
        developers = app_client.get("/developers")
        assert developers.status_code == 200
        assert "Governed health research data" in developers.text
        assert "/api/docs" in developers.text
        health = app_client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["product"] == "FastHealthData"
