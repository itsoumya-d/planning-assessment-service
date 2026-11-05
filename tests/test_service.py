from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from planning.api import create_app
from planning.db import Base
from planning.service import NotFoundError, PlanningService, ValidationError

API_KEYS = {"admin-key": "admin", "planner-key": "planner", "viewer-key": "viewer"}
ZONE = '{"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}'
OVERLAY = '{"type":"Polygon","coordinates":[[[0,0],[5,0],[5,5],[0,5],[0,0]]]}'
POINT = '{"type":"Point","coordinates":[1,1]}'


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    yield db
    db.close()


@pytest.fixture()
def client(session):
    factory = sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)
    return TestClient(create_app(session_factory=factory, api_keys=API_KEYS, init_database=False))


def seed(service: PlanningService):
    service.create_zone("RES", "Residential", ZONE)
    service.create_overlay("FLOOD", "Flood overlay", OVERLAY)
    service.create_rule("R1", "All activities", "General requirement")
    service.create_rule("R2", "Residential rule", "Zone requirement", "zone", "RES")
    service.create_rule("R3", "Flood rule", "Flood requirement", "overlay", "FLOOD", "restricted_discretionary", True)
    service.create_rule("R4", "Other zone", "Other requirement", "zone", "OTHER")
    return service.create_application("APP-1", "1 Example Street", POINT)


def test_create_zone(session):
    row = PlanningService(session).create_zone("RES", "Residential", ZONE)
    assert row.code == "RES"


def test_invalid_geometry(session):
    with pytest.raises(ValidationError):
        PlanningService(session).create_zone("BAD", "Bad", "not-json")


def test_create_overlay(session):
    row = PlanningService(session).create_overlay("FLOOD", "Flood", OVERLAY)
    assert row.code == "FLOOD"


def test_create_rule(session):
    row = PlanningService(session).create_rule("R1", "All", "Requirement")
    assert row.scope_type == "all"


def test_application_detects_zone_and_overlay(session):
    service = PlanningService(session)
    app = seed(service)
    assert app.zone_code == "RES"
    assert app.overlay_codes == "FLOOD"


def test_point_outside_zone_rejected(session):
    service = PlanningService(session)
    service.create_zone("RES", "Residential", ZONE)
    with pytest.raises(ValidationError):
        service.create_application("APP-X", "Outside", '{"type":"Point","coordinates":[99,99]}')


def test_duplicate_application_rejected(session):
    service = PlanningService(session)
    seed(service)
    with pytest.raises(ValidationError):
        service.create_application("APP-1", "1 Example Street", POINT)


def test_checklist_filters_rules(session):
    service = PlanningService(session)
    app = seed(service)
    codes = [r.code for r in service.checklist(app.id)]
    assert codes == ["R1", "R2", "R3"]


def test_assess_rule(session):
    service = PlanningService(session)
    app = seed(service)
    row = service.assess(app.id, "R1", "complies", "Site plan")
    assert row.outcome == "complies"


def test_assess_inapplicable_rule_rejected(session):
    service = PlanningService(session)
    app = seed(service)
    with pytest.raises(ValidationError):
        service.assess(app.id, "R4", "complies")


def test_consent_incomplete(session):
    service = PlanningService(session)
    app = seed(service)
    service.assess(app.id, "R1", "complies")
    status = service.consent_status(app.id)
    assert status["status"] == "incomplete"
    assert set(status["missing"]) == {"R2", "R3"}


def test_consent_permitted(session):
    service = PlanningService(session)
    app = seed(service)
    service.assess(app.id, "R1", "complies")
    service.assess(app.id, "R2", "complies")
    service.assess(app.id, "R3", "not_applicable")
    assert service.consent_status(app.id)["status"] == "permitted"


def test_consent_notified(session):
    service = PlanningService(session)
    app = seed(service)
    service.assess(app.id, "R1", "complies")
    service.assess(app.id, "R2", "complies")
    service.assess(app.id, "R3", "non_complies", "Flood level")
    status = service.consent_status(app.id)
    assert status["status"] == "notified_consent"
    assert status["notified"] is True


def test_generate_report(session):
    service = PlanningService(session)
    app = seed(service)
    service.assess(app.id, "R1", "complies")
    report = service.generate_report(app.id)
    assert report.version == 1
    assert "APP-1" in report.content
    assert "R1" in report.content


def test_signoff_requires_complete(session):
    service = PlanningService(session)
    app = seed(service)
    report = service.generate_report(app.id)
    with pytest.raises(ValidationError):
        service.signoff(report.id, "Aroha")


def test_signoff_success(session):
    service = PlanningService(session)
    app = seed(service)
    for code in ["R1", "R2", "R3"]:
        service.assess(app.id, code, "complies")
    report = service.generate_report(app.id)
    signed = service.signoff(report.id, "Aroha")
    assert signed.status == "final"
    assert signed.signed_off_by == "Aroha"


def test_audit(session):
    service = PlanningService(session)
    seed(service)
    actions = [e["action"] for e in service.audit()]
    assert "zone_created" in actions
    assert "application_created" in actions


def test_api_auth_and_workflow(client):
    assert client.post("/zones", json={}).status_code == 401
    headers = {"X-API-Key": "planner-key"}
    client.post("/zones", json={"code": "RES", "name": "Residential", "geojson": ZONE}, headers=headers)
    application = client.post("/applications", json={"reference": "APP-1", "address": "1 Example St", "point_geojson": POINT}, headers=headers).json()
    client.post("/rules", json={"code": "R1", "title": "All", "requirement": "Req"}, headers=headers)
    checklist = client.get(f"/applications/{application['id']}/checklist", headers={"X-API-Key": "viewer-key"}).json()
    assert checklist["rules"][0]["code"] == "R1"
    client.post(f"/applications/{application['id']}/assessments", json={"rule_code": "R1", "outcome": "complies"}, headers=headers)
    status = client.get(f"/applications/{application['id']}/consent-status", headers={"X-API-Key": "viewer-key"}).json()
    assert status["status"] == "permitted"
    report = client.post(f"/applications/{application['id']}/report", headers=headers).json()
    signed = client.post(f"/reports/{report['id']}/signoff", json={"planner": "Aroha"}, headers=headers).json()
    assert signed["status"] == "final"
