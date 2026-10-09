"""AUGMIS Step 54 bounded audit evidence exports.

Authorization is enforced by the caller route before invoking this service.
Export is capped and no audit rows are modified/deleted. The export itself is
recorded atomically in AUGMIS audit before responding.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from services.api.app.services.audit_service import (
    AuditQueryError, audit_event_payload, query_audit_events, record_audit_event,
)

MAX_EXPORT_ROWS = 5000
PAGE_SIZE = 500
CSV_COLUMNS = (
    "id", "createdAt", "actorUserId", "tenantId", "publisherId", "action",
    "resourceType", "resourceId", "outcome", "message", "metadata", "requestId",
)


class AuditExportError(ValueError):
    pass


@dataclass(frozen=True)
class AuditExportArtifact:
    content: bytes
    content_type: str
    filename: str
    sha256: str
    count: int


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _csv_safe(value: Any) -> str:
    """Prevent spreadsheet formula execution, including whitespace prefixes."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        cell = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    else:
        cell = str(value)
    if cell.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + cell
    return cell


def _normalize_date(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuditExportError("Audit evidence dates must include a timezone offset (UTC recommended).")
    return value.astimezone(timezone.utc)


def create_audit_export(
    *, db: Session, actor_user_id: UUID, scope: str,
    format_: str,
    tenant_scope_id: UUID | None = None,
    tenant_id: UUID | None = None,
    publisher_id: UUID | None = None,
    action: str | None = None,
    action_prefix: str | None = None,
    category: str | None = None,
    outcome: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_filter_id: UUID | None = None,
    search: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> AuditExportArtifact:
    if scope not in ("platform", "tenant"):
        raise AuditExportError("Invalid export scope.")
    if format_ not in ("csv", "json"):
        raise AuditExportError("Export format must be csv or json.")
    if scope == "tenant" and (tenant_scope_id is None or tenant_id is not None):
        raise AuditExportError("Tenant evidence requires exactly one authorized tenant scope.")
    if scope == "platform" and tenant_scope_id is not None:
        raise AuditExportError("Platform evidence cannot impersonate a tenant scope.")

    captured = datetime.now(timezone.utc)
    start = _normalize_date(from_date)
    requested_end = _normalize_date(to_date)
    end = min(requested_end, captured) if requested_end else captured
    if start is not None and start > end:
        raise AuditExportError("Export start date must not exceed end date.")

    filters = {
        "tenant_scope_id": tenant_scope_id,
        "tenant_id": tenant_id,
        "publisher_id": publisher_id,
        "action": action,
        "action_prefix": action_prefix,
        "category": category,
        "outcome": outcome,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "actor_user_id": actor_filter_id,
        "from_date": start,
        "to_date": end,
        "search": search,
    }

    try:
        total, first_page = query_audit_events(db=db, limit=PAGE_SIZE, offset=0, **filters)
    except AuditQueryError as exc:
        raise AuditExportError(str(exc)) from exc

    if total > MAX_EXPORT_ROWS:
        raise AuditExportError(
            f"The matching export contains {total} events; maximum is {MAX_EXPORT_ROWS}. "
            "Narrow the date range or filters. No records were exported."
        )

    events = [audit_event_payload(event) for event in first_page]
    for offset in range(PAGE_SIZE, total, PAGE_SIZE):
        try:
            _count, rows = query_audit_events(
                db=db, limit=PAGE_SIZE, offset=offset, **filters,
            )
        except AuditQueryError as exc:
            raise AuditExportError(str(exc)) from exc
        events.extend(audit_event_payload(row) for row in rows)

    # Fail closed if rows changed between batches. A captured time upper-bound
    # excludes newly created audit events but is not a DB snapshot guarantee.
    if len(events) != total:
        raise AuditExportError("Audit result set changed during export. Retry with narrower filters.")
    if len({str(event.get("id")) for event in events}) != len(events):
        raise AuditExportError("Duplicate audit identifiers detected during export. Retry.")

    record_sha = hashlib.sha256(_canonical(events)).hexdigest()
    public_filters = {
        "tenantId": str(tenant_scope_id or tenant_id) if (tenant_scope_id or tenant_id) else None,
        "publisherId": str(publisher_id) if publisher_id else None,
        "action": action,
        "actionPrefix": action_prefix,
        "category": category,
        "outcome": outcome,
        "resourceType": resource_type,
        "resourceId": resource_id,
        "actorUserId": str(actor_filter_id) if actor_filter_id else None,
        "search": search,
        "from": start.isoformat() if start else None,
        "to": end.isoformat(),
    }
    manifest = {
        "schema": "augmis.audit.evidence.v1",
        "scope": scope,
        "generatedAt": captured.isoformat(),
        "recordCount": len(events),
        "recordSha256": record_sha,
        "filters": public_filters,
        "integrityNote": (
            "recordSha256 verifies the canonical events JSON; "
            "it is not a digital signature or proof against database-admin tampering."
        ),
    }

    if format_ == "json":
        content = json.dumps(
            {"manifest": manifest, "events": events}, ensure_ascii=False,
            sort_keys=True, indent=2, default=str,
        ).encode("utf-8")
        mime = "application/json; charset=utf-8"
    else:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(CSV_COLUMNS)
        for event in events:
            writer.writerow([_csv_safe(event.get(column)) for column in CSV_COLUMNS])
        content = ("\ufeff" + output.getvalue()).encode("utf-8")
        mime = "text/csv; charset=utf-8"

    sha = hashlib.sha256(content).hexdigest()
    stamp = captured.strftime("%Y%m%dT%H%M%SZ")
    filename = f"augmis-audit-{scope}-{stamp}.{format_}"

    record_audit_event(
        db,
        action="audit.export.created",
        resource_type="audit_evidence",
        resource_id=sha,
        actor_user_id=actor_user_id,
        tenant_id=tenant_scope_id if scope == "tenant" else tenant_id,
        publisher_id=publisher_id,
        outcome="success",
        message="Audit evidence export generated.",
        metadata={
            "format": format_, "scope": scope, "recordCount": len(events),
            "sha256": sha, "recordSha256": record_sha,
            "filters": public_filters, "schema": manifest["schema"],
        },
    )
    db.commit()
    return AuditExportArtifact(content, mime, filename, sha, len(events))
