"""Guarded Step 53F+54 patcher for existing AUDIT route, API helper and page.

    python -m tools.apply_step53f54 --check
    python -m tools.apply_step53f54 --apply

This script NEVER touches runtime/auth/RBAC or existing publisher mappings.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys

ROUTE = Path('services/api/app/routes/audit.py')
CLIENT = Path('apps/web/src/lib/audit.ts')
PAGE = Path('apps/web/src/app/audit/page.tsx')
SERVICE = Path('services/api/app/services/audit_export_service.py')

ROUTE_APPEND = '''

# ============================================================
# STEP 54 — AUTHORIZED AUDIT EVIDENCE EXPORT (CSV / JSON)
# ============================================================
from typing import Literal as _AuditExportLiteral
from fastapi import Response as _AuditExportResponse
from services.api.app.services.audit_export_service import (
    AuditExportError as _AuditExportError,
    create_audit_export as _create_audit_export,
)


def _audit_evidence_response(*, db, actor, scope, format_, **filters):
    try:
        artifact = _create_audit_export(
            db=db, actor_user_id=actor.id, scope=scope, format_=format_, **filters,
        )
    except _AuditExportError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return _AuditExportResponse(
        content=artifact.content,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-AUGMIS-Export-SHA256": artifact.sha256,
            "X-AUGMIS-Export-Count": str(artifact.count),
        },
    )


@router.post("/audit-events/export", include_in_schema=True)
def export_tenant_audit_evidence(
    tenant_id: uuid.UUID,
    format_: _AuditExportLiteral["csv", "json"] = Query(default="csv", alias="format"),
    publisher_id: uuid.UUID | None = None,
    action: str | None = None,
    action_prefix: str | None = None,
    category: str | None = None,
    outcome: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    search: str | None = None,
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tenant = _require_tenant_audit_access(
        db=db, current_user=current_user, tenant_id=tenant_id,
    )
    return _audit_evidence_response(
        db=db, actor=current_user, scope="tenant", format_=format_,
        tenant_scope_id=tenant.id,
        publisher_id=publisher_id, action=action, action_prefix=action_prefix,
        category=category, outcome=outcome, resource_type=resource_type,
        resource_id=resource_id, actor_filter_id=actor_user_id,
        search=search, from_date=from_date, to_date=to_date,
    )


@router.post("/platform/audit-events/export", include_in_schema=True)
def export_platform_audit_evidence(
    format_: _AuditExportLiteral["csv", "json"] = Query(default="csv", alias="format"),
    tenant_id: uuid.UUID | None = None,
    publisher_id: uuid.UUID | None = None,
    action: str | None = None,
    action_prefix: str | None = None,
    category: str | None = None,
    outcome: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    search: str | None = None,
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_platform_audit_access(db=db, current_user=current_user)
    return _audit_evidence_response(
        db=db, actor=current_user, scope="platform", format_=format_,
        tenant_id=tenant_id, publisher_id=publisher_id,
        action=action, action_prefix=action_prefix, category=category,
        outcome=outcome, resource_type=resource_type, resource_id=resource_id,
        actor_filter_id=actor_user_id, search=search,
        from_date=from_date, to_date=to_date,
    )
'''

CLIENT_APPEND = '''

// Step 54 — Audit evidence exports. Uses the existing configured API client.
export type AuditEvidenceFormat = "csv" | "json";

export async function downloadAuditEvidence(
  scope: AuditScopeType,
  tenantId: string | null,
  filters: AuditEventFilters,
  format: AuditEvidenceFormat,
): Promise<{ blob: Blob; sha256: string | null; count: number | null }> {
  // Personal audit export is deliberately unsupported until a dedicated,
  // server-authorized personal export endpoint is implemented.
  if (scope !== "tenant" && scope !== "platform") {
    throw new Error("Choose Tenant or Platform scope to export audit evidence.");
  }
  if (scope === "tenant" && !tenantId) {
    throw new Error("Select a tenant before exporting audit evidence.");
  }
  const endpoint = scope === "platform"
    ? "/api/v1/platform/audit-events/export"
    : "/api/v1/audit-events/export";
  const params = {
    ...buildAuditParams({ ...filters, limit: undefined, offset: undefined }),
    ...(scope === "tenant" ? { tenant_id: tenantId } : {}),
    format,
  };
  const response = await api.post<Blob>(endpoint, null, {
    params,
    responseType: "blob",
  });
  const countRaw = response.headers["x-augmis-export-count"];
  return {
    blob: response.data,
    sha256: response.headers["x-augmis-export-sha256"] ?? null,
    count: countRaw != null ? Number(countRaw) : null,
  };
}
'''

PAGE_IMPORT = '''  downloadAuditEvidence,
  AuditEvidenceFormat,
'''
PAGE_STATE = '''

  // Step 54: export of *applied* filters, not just the visible page.
  const [exportBusy, setExportBusy] = useState<AuditEvidenceFormat | null>(null);

  const exportEvidence = async (format: AuditEvidenceFormat) => {
    if (exportBusy || permissionLoading || scope === "personal") return;
    if ((scope === "platform" && !canPlatformAudit) ||
        (scope === "tenant" && (!canTenantAudit || !selectedTenantId))) return;

    setExportBusy(format);
    setError("");
    try {
      const result = await downloadAuditEvidence(
        scope, selectedTenantId ?? null, toApiFilters(appliedFilters), format,
      );
      const blobUrl = URL.createObjectURL(result.blob);
      try {
        const anchor = document.createElement("a");
        anchor.href = blobUrl;
        anchor.download = `augmis-audit-${scope}-${new Date().toISOString().replace(/[:.]/g, "-")}.${format}`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      }
    } catch (exportError) {
      setError(apiError(exportError, "Audit evidence export failed."));
    } finally {
      setExportBusy(null);
    }
  };
'''

PAGE_BUTTONS = '''              <Button
                variant="outlined"
                disabled={
                  loading || permissionLoading || scope === "personal" ||
                  (scope === "platform" && !canPlatformAudit) ||
                  (scope === "tenant" && (!canTenantAudit || !selectedTenantId)) ||
                  Boolean(exportBusy)
                }
                onClick={() => void exportEvidence("csv")}
              >
                {exportBusy === "csv" ? "Preparing CSV..." : "Export CSV"}
              </Button>
              <Button
                variant="outlined"
                disabled={
                  loading || permissionLoading || scope === "personal" ||
                  (scope === "platform" && !canPlatformAudit) ||
                  (scope === "tenant" && (!canTenantAudit || !selectedTenantId)) ||
                  Boolean(exportBusy)
                }
                onClick={() => void exportEvidence("json")}
              >
                {exportBusy === "json" ? "Preparing evidence..." : "Evidence JSON"}
              </Button>
'''


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected exactly one insertion point; got {count}. NO files modified.")
    return text.replace(old, new, 1)


def transform(route: str, client: str, page: str):
    # Structural safeguards: require known endpoint functions and auth guards.
    for fragment in (
        'def _require_tenant_audit_access(',
        'def _require_platform_audit_access(',
        'def list_audit_events(',
        'def list_platform_audit_events(',
        'router = APIRouter(',
    ):
        if fragment not in route:
            raise ValueError(f"Audit route has changed; missing {fragment}. STOP and share latest file.")
    if 'def export_tenant_audit_evidence(' in route or 'def export_platform_audit_evidence(' in route:
        raise ValueError('Step 54 route already exists. Do not apply twice.')
    if 'export async function downloadAuditEvidence(' in client:
        raise ValueError('Step 54 audit client already exists. Do not apply twice.')
    if 'const exportEvidence = async' in page:
        raise ValueError('Step 54 audit UI already exists. Do not apply twice.')
    route = route.rstrip() + '\n' + ROUTE_APPEND
    client = client.rstrip() + '\n' + CLIENT_APPEND
    page = once(
        page,
        '  loadTenantAuditFilterOptions,\n} from "@/lib/audit";',
        '  loadTenantAuditFilterOptions,\n' + PAGE_IMPORT + '} from "@/lib/audit";',
        'Audit page import',
    )
    page = once(
        page,
        '  const permissionLoading =\n    platformLoading ||\n    tenantLoading ||\n    tenantContextLoading;\n',
        '  const permissionLoading =\n    platformLoading ||\n    tenantLoading ||\n    tenantContextLoading;\n' + PAGE_STATE,
        'Audit page export state',
    )
    page = once(
        page,
        '''              <Button\n                variant="outlined"\n                startIcon={\n                  <RefreshOutlined />\n                }''',
        PAGE_BUTTONS + '''              <Button\n                variant="outlined"\n                startIcon={\n                  <RefreshOutlined />\n                }''',
        'Audit header buttons',
    )
    if 'export async function loadTenantAuditEvents(' not in client:
        raise ValueError('Audit API client has unexpected shape.')
    if 'loadMyAuditEvents' not in page or 'loadPlatformAuditEvents' not in page:
        raise ValueError('Audit page scope behavior differs from reviewed source. STOP and inspect.')
    return route, client, page


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    paths = (ROUTE, CLIENT, PAGE)
    if any(not p.is_file() for p in paths + (SERVICE,)):
        print('[BLOCKED] Missing required repository files. Copy package new files, then retry.')
        return 1
    originals = {path: path.read_bytes() for path in paths}
    try:
        texts = [originals[path].decode('utf-8').replace('\r\n', '\n') for path in paths]
        replacements = transform(*texts)
        for text in replacements:
            if not text.strip():
                raise ValueError('Empty generated output.')
    except (UnicodeError, ValueError) as exc:
        print('[BLOCKED]', exc)
        return 1

    for path in paths:
        print(f'[PASS] Compatible: {path}')
    if args.check:
        print('[CHECK ONLY] No files changed.')
        return 0

    # All checks are completed before writing. Keep local recovery copies ignored by Git.
    for path in paths:
        backup = path.with_name(path.name + '.before-step54.bak')
        if backup.exists():
            print(f'[BLOCKED] Backup already exists: {backup}; do not overwrite it.')
            return 1
    for path in paths:
        path.with_name(path.name + '.before-step54.bak').write_bytes(originals[path])
    for path, new_text in zip(paths, replacements):
        old_bytes = originals[path]
        new_bytes = new_text.encode('utf-8')
        newline = b'\r\n' if old_bytes.count(b'\r\n') > old_bytes.count(b'\n') // 2 else b'\n'
        if newline == b'\r\n':
            new_bytes = new_bytes.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        path.write_bytes(new_bytes)
        print(f'[APPLIED] {path}')
    print('[SUCCESS] 3 existing files patched. Backups *.before-step54.bak created (do not commit).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
