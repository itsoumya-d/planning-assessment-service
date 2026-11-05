from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from .auth import load_api_keys, require_role
from .db import SessionLocal, init_db
from .service import ConflictError, NotFoundError, PlanningService, ValidationError


class ZoneIn(BaseModel):
    code: str
    name: str
    geojson: str


class OverlayIn(BaseModel):
    code: str
    name: str
    geojson: str


class RuleIn(BaseModel):
    code: str
    title: str
    requirement: str
    scope_type: str = "all"
    scope_code: str = ""
    activity_status: str = "permitted"
    notification_required: bool = False


class ApplicationIn(BaseModel):
    reference: str
    address: str
    point_geojson: str


class AssessmentIn(BaseModel):
    rule_code: str
    outcome: str
    evidence: str = ""
    notes: str = ""


class SignoffIn(BaseModel):
    planner: str


def create_app(session_factory: sessionmaker = SessionLocal, api_keys: dict[str, str] | None = None, init_database: bool = True) -> FastAPI:
    if init_database:
        init_db()
    keys = api_keys or load_api_keys()
    app = FastAPI(title="Planning assessment service", version="1.0.0")

    def db_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    viewer = require_role("viewer", keys)
    planner = require_role("planner", keys)

    def handle(exc: Exception):
        if isinstance(exc, NotFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(exc, ConflictError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/zones")
    def zone(payload: ZoneIn, session: Session = Depends(db_session), actor: str = Depends(planner)) -> dict[str, Any]:
        try:
            row = PlanningService(session, actor).create_zone(payload.code, payload.name, payload.geojson)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)
        return {"id": row.id, "code": row.code}

    @app.post("/overlays")
    def overlay(payload: OverlayIn, session: Session = Depends(db_session), actor: str = Depends(planner)) -> dict[str, Any]:
        try:
            row = PlanningService(session, actor).create_overlay(payload.code, payload.name, payload.geojson)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)
        return {"id": row.id, "code": row.code}

    @app.post("/rules")
    def rule(payload: RuleIn, session: Session = Depends(db_session), actor: str = Depends(planner)) -> dict[str, Any]:
        try:
            row = PlanningService(session, actor).create_rule(payload.code, payload.title, payload.requirement, payload.scope_type, payload.scope_code, payload.activity_status, payload.notification_required)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)
        return {"id": row.id, "code": row.code}

    @app.post("/applications")
    def application(payload: ApplicationIn, session: Session = Depends(db_session), actor: str = Depends(planner)) -> dict[str, Any]:
        try:
            row = PlanningService(session, actor).create_application(payload.reference, payload.address, payload.point_geojson)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)
        return {"id": row.id, "zone_code": row.zone_code, "overlay_codes": row.overlay_codes}

    @app.get("/applications/{application_id}/checklist")
    def checklist(application_id: int, session: Session = Depends(db_session), _: str = Depends(viewer)) -> dict[str, Any]:
        try:
            rows = PlanningService(session).checklist(application_id)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)
        return {"rules": [{"code": r.code, "title": r.title, "activity_status": r.activity_status} for r in rows]}

    @app.post("/applications/{application_id}/assessments")
    def assess(application_id: int, payload: AssessmentIn, session: Session = Depends(db_session), actor: str = Depends(planner)) -> dict[str, Any]:
        try:
            row = PlanningService(session, actor).assess(application_id, payload.rule_code, payload.outcome, payload.evidence, payload.notes)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)
        return {"id": row.id, "outcome": row.outcome}

    @app.get("/applications/{application_id}/consent-status")
    def consent_status(application_id: int, session: Session = Depends(db_session), _: str = Depends(viewer)) -> dict[str, Any]:
        try:
            return PlanningService(session).consent_status(application_id)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)

    @app.post("/applications/{application_id}/report")
    def report(application_id: int, session: Session = Depends(db_session), actor: str = Depends(planner)) -> dict[str, Any]:
        try:
            row = PlanningService(session, actor).generate_report(application_id)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)
        return {"id": row.id, "version": row.version, "content": row.content}

    @app.post("/reports/{report_id}/signoff")
    def signoff(report_id: int, payload: SignoffIn, session: Session = Depends(db_session), actor: str = Depends(planner)) -> dict[str, Any]:
        try:
            row = PlanningService(session, actor).signoff(report_id, payload.planner)
        except (NotFoundError, ConflictError, ValidationError) as exc:
            handle(exc)
        return {"id": row.id, "status": row.status, "signed_off_by": row.signed_off_by}

    @app.get("/audit")
    def audit(session: Session = Depends(db_session), _: str = Depends(viewer)) -> dict[str, Any]:
        return {"audit": PlanningService(session).audit()}

    return app


app = create_app()
