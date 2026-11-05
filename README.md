# Planning Assessment Service

Production-oriented backend for resource-consent planning workflows: zones,
overlays, plan rules, site spatial checks, rule assessments, consent triggers,
generated reports and planner sign-off.

## Why this exists

Planning reports are reworked because the underlying decision is fragmented:
which zone applies, which overlays bite, which rules are triggered, what was
assessed, and who signed it off. This service makes that chain explicit and
auditable, with a real GIS point-in-polygon check rather than a manual zone
lookup.

## Features

- Zones and overlays as validated GeoJSON polygons
- Site point must fall inside exactly one zone
- Automatic overlay detection by point-in-polygon
- Rules scoped to all, a zone, or an overlay
- Applicable-rule checklist per application
- Rule assessments with evidence, notes and assessor
- Consent status: incomplete, permitted, consent required, or notified consent
- Structured Markdown report generation with versions
- Sign-off gated on complete assessments
- Append-only audit events
- API-key RBAC: viewer, planner, admin
- PostgreSQL or SQLite, SQLAlchemy 2, Shapely, Alembic, Docker, GitHub Actions

## Run locally

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
DATABASE_URL=sqlite:///./planning.db .venv/bin/alembic upgrade head
API_KEYS='{"dev-admin":"admin","dev-planner":"planner","dev-viewer":"viewer"}' \
  .venv/bin/uvicorn planning.api:app --reload
```

## Test

```bash
.venv/bin/pytest
```

## Honest scope

This is a real, tested backend service, not a production deployment. It does
not parse district-plan PDFs, import council GIS services, model every plan
rule type, generate AI prose, or integrate with council consent systems. The
README does not claim production usage.
