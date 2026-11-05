from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ZoneRow(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    geometry: Mapped[str] = mapped_column(Text)


class OverlayRow(Base):
    __tablename__ = "overlays"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    geometry: Mapped[str] = mapped_column(Text)


class RuleRow(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    requirement: Mapped[str] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(String(20), default="all")
    scope_code: Mapped[str] = mapped_column(String(40), default="")
    activity_status: Mapped[str] = mapped_column(String(30), default="permitted")
    notification_required: Mapped[bool] = mapped_column(Boolean, default=False)


class ApplicationRow(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    address: Mapped[str] = mapped_column(String(300))
    site_point: Mapped[str] = mapped_column(Text)
    zone_code: Mapped[str] = mapped_column(String(40), index=True)
    overlay_codes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    assessments: Mapped[list["AssessmentRow"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    reports: Mapped[list["ReportRow"]] = relationship(back_populates="application", cascade="all, delete-orphan")


class AssessmentRow(Base):
    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("application_id", "rule_code", name="uq_assessment_rule"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    rule_code: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    assessed_by: Mapped[str] = mapped_column(String(120), default="")
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    application: Mapped[ApplicationRow] = relationship(back_populates="assessments")


class ReportRow(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    signed_off_by: Mapped[str] = mapped_column(String(120), default="")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    application: Mapped[ApplicationRow] = relationship(back_populates="reports")


class AuditRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="")
    reference: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
