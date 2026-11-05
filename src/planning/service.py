from __future__ import annotations

import json

from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.orm import Session

from .tables import ApplicationRow, AssessmentRow, AuditRow, OverlayRow, ReportRow, RuleRow, ZoneRow

OUTCOMES = {"complies", "non_complies", "not_applicable"}
ACTIVITY = {"permitted", "controlled", "restricted_discretionary", "discretionary", "non_complying"}


class NotFoundError(Exception):
    pass


class ValidationError(Exception):
    pass


class ConflictError(Exception):
    pass


def parse_geometry(raw: str) -> BaseGeometry:
    try:
        data = json.loads(raw)
        geom = shape(data)
    except Exception as exc:
        raise ValidationError("invalid GeoJSON geometry") from exc
    if geom.is_empty or not geom.is_valid:
        raise ValidationError("geometry is empty or invalid")
    if geom.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValidationError("geometry must be a Polygon or MultiPolygon")
    return geom


class PlanningService:
    def __init__(self, session: Session, actor: str = "system") -> None:
        self.session = session
        self.actor = actor

    def _audit(self, action: str, reference: str, detail: str = "") -> None:
        self.session.add(AuditRow(action=action, actor=self.actor, reference=reference, detail=detail))

    def create_zone(self, code: str, name: str, geojson: str) -> ZoneRow:
        if not code.strip() or not name.strip():
            raise ValidationError("zone code and name are required")
        parse_geometry(geojson)
        if self.session.scalar(select(ZoneRow).where(ZoneRow.code == code)):
            raise ValidationError("zone already exists")
        row = ZoneRow(code=code, name=name, geometry=geojson)
        self.session.add(row)
        self.session.flush()
        self._audit("zone_created", code)
        self.session.commit()
        return row

    def create_overlay(self, code: str, name: str, geojson: str) -> OverlayRow:
        if not code.strip() or not name.strip():
            raise ValidationError("overlay code and name are required")
        parse_geometry(geojson)
        if self.session.scalar(select(OverlayRow).where(OverlayRow.code == code)):
            raise ValidationError("overlay already exists")
        row = OverlayRow(code=code, name=name, geometry=geojson)
        self.session.add(row)
        self.session.flush()
        self._audit("overlay_created", code)
        self.session.commit()
        return row

    def create_rule(self, code: str, title: str, requirement: str, scope_type: str = "all", scope_code: str = "", activity_status: str = "permitted", notification_required: bool = False) -> RuleRow:
        if not code.strip() or not title.strip() or not requirement.strip():
            raise ValidationError("rule code, title and requirement are required")
        if scope_type not in {"all", "zone", "overlay"}:
            raise ValidationError("scope_type must be all, zone or overlay")
        if activity_status not in ACTIVITY:
            raise ValidationError("invalid activity_status")
        if scope_type != "all" and not scope_code.strip():
            raise ValidationError("scope_code is required for zone/overlay rules")
        if self.session.scalar(select(RuleRow).where(RuleRow.code == code)):
            raise ValidationError("rule already exists")
        row = RuleRow(code=code, title=title, requirement=requirement, scope_type=scope_type, scope_code=scope_code, activity_status=activity_status, notification_required=notification_required)
        self.session.add(row)
        self.session.flush()
        self._audit("rule_created", code)
        self.session.commit()
        return row

    def create_application(self, reference: str, address: str, point_geojson: str) -> ApplicationRow:
        if not reference.strip() or not address.strip():
            raise ValidationError("reference and address are required")
        if self.session.scalar(select(ApplicationRow).where(ApplicationRow.reference == reference)):
            raise ValidationError("application reference already exists")
        try:
            point_data = json.loads(point_geojson)
            point = Point(point_data["coordinates"])
        except Exception as exc:
            raise ValidationError("site_point must be a GeoJSON Point") from exc
        zones = self.session.scalars(select(ZoneRow)).all()
        matched = [z for z in zones if parse_geometry(z.geometry).covers(point)]
        if len(matched) != 1:
            raise ValidationError("site point must fall inside exactly one zone")
        zone = matched[0]
        overlays = [o.code for o in self.session.scalars(select(OverlayRow)).all() if parse_geometry(o.geometry).covers(point)]
        row = ApplicationRow(reference=reference, address=address, site_point=point_geojson, zone_code=zone.code, overlay_codes=",".join(sorted(overlays)))
        self.session.add(row)
        self.session.flush()
        self._audit("application_created", reference, f"zone={zone.code} overlays={len(overlays)}")
        self.session.commit()
        return row

    def checklist(self, application_id: int) -> list[RuleRow]:
        application = self.session.get(ApplicationRow, application_id)
        if application is None:
            raise NotFoundError("application not found")
        overlays = set(filter(None, application.overlay_codes.split(",")))
        rules = self.session.scalars(select(RuleRow).order_by(RuleRow.id)).all()
        return [
            r for r in rules
            if r.scope_type == "all"
            or (r.scope_type == "zone" and r.scope_code == application.zone_code)
            or (r.scope_type == "overlay" and r.scope_code in overlays)
        ]

    def assess(self, application_id: int, rule_code: str, outcome: str, evidence: str = "", notes: str = "") -> AssessmentRow:
        application = self.session.get(ApplicationRow, application_id)
        if application is None:
            raise NotFoundError("application not found")
        if outcome not in OUTCOMES:
            raise ValidationError("invalid outcome")
        allowed = {r.code for r in self.checklist(application_id)}
        if rule_code not in allowed:
            raise ValidationError("rule is not applicable to this application")
        row = self.session.scalar(select(AssessmentRow).where(AssessmentRow.application_id == application_id, AssessmentRow.rule_code == rule_code))
        if row is None:
            row = AssessmentRow(application_id=application_id, rule_code=rule_code)
            self.session.add(row)
        row.outcome = outcome
        row.evidence = evidence
        row.notes = notes
        row.assessed_by = self.actor
        self._audit("rule_assessed", f"{application.reference}/{rule_code}", outcome)
        self.session.commit()
        return row

    def consent_status(self, application_id: int) -> dict:
        application = self.session.get(ApplicationRow, application_id)
        if application is None:
            raise NotFoundError("application not found")
        rules = {r.code: r for r in self.checklist(application_id)}
        assessments = {a.rule_code: a for a in application.assessments}
        missing = sorted(set(rules) - set(assessments))
        if missing:
            return {"status": "incomplete", "missing": missing, "notified": False}
        if any(a.outcome == "non_complies" and rules[a.rule_code].notification_required for a in assessments.values()):
            return {"status": "notified_consent", "missing": [], "notified": True}
        if any(a.outcome == "non_complies" for a in assessments.values()):
            return {"status": "consent_required", "missing": [], "notified": False}
        if any(rules[a.rule_code].activity_status != "permitted" for a in assessments.values() if a.outcome != "not_applicable"):
            return {"status": "consent_required", "missing": [], "notified": False}
        return {"status": "permitted", "missing": [], "notified": False}

    def generate_report(self, application_id: int) -> ReportRow:
        application = self.session.get(ApplicationRow, application_id)
        if application is None:
            raise NotFoundError("application not found")
        rules = self.checklist(application_id)
        assessments = {a.rule_code: a for a in application.assessments}
        missing = [r.code for r in rules if r.code not in assessments]
        status = self.consent_status(application_id)
        lines = [
            f"# Planning assessment — {application.reference}",
            "",
            f"**Site:** {application.address}",
            f"**Zone:** {application.zone_code}",
            f"**Overlays:** {application.overlay_codes or 'None'}",
            f"**Consent status:** {status['status']}",
            "",
            "## Rule assessments",
        ]
        for rule in rules:
            assessment = assessments.get(rule.code)
            if assessment is None:
                lines.append(f"- **{rule.code} — {rule.title}**: not assessed")
            else:
                lines.append(f"- **{rule.code} — {rule.title}**: {assessment.outcome}. {assessment.evidence} {assessment.notes}".rstrip())
        if missing:
            lines += ["", f"**Missing assessments:** {', '.join(missing)}"]
        content = "\n".join(lines) + "\n"
        version = len(application.reports) + 1
        report = ReportRow(application_id=application_id, version=version, content=content)
        self.session.add(report)
        self._audit("report_generated", application.reference, f"version={version}")
        self.session.commit()
        return report

    def signoff(self, report_id: int, planner: str) -> ReportRow:
        report = self.session.get(ReportRow, report_id)
        if report is None:
            raise NotFoundError("report not found")
        if report.status == "final":
            return report
        status = self.consent_status(report.application_id)
        if status["missing"]:
            raise ValidationError(f"assessments incomplete: {', '.join(status['missing'])}")
        report.status = "final"
        report.signed_off_by = planner
        report.signed_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        report.application.status = "reviewed"
        self._audit("report_signed_off", report.application.reference, planner)
        self.session.commit()
        return report

    def audit(self) -> list[dict]:
        rows = self.session.scalars(select(AuditRow).order_by(AuditRow.id)).all()
        return [{"at": r.at.isoformat(), "action": r.action, "actor": r.actor, "reference": r.reference, "detail": r.detail} for r in rows]
