"""Lightweight Step 53F + 54 verification: no DB mutations."""
from __future__ import annotations

from pathlib import Path
import sys

from services.api.app.services.audit_export_service import (
    _csv_safe, _canonical, MAX_EXPORT_ROWS,
)


def main() -> int:
    assert MAX_EXPORT_ROWS == 5000
    for text in ("=2+3", "  +SUM(A1:A2)", "\t@danger", "-1+2", "\n=cmd"):
        assert _csv_safe(text).startswith("'"), text
    assert _csv_safe("Safe text") == "Safe text"
    assert _canonical({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    route = Path('services/api/app/routes/audit.py').read_text(encoding='utf-8')
    client = Path('apps/web/src/lib/audit.ts').read_text(encoding='utf-8')
    page = Path('apps/web/src/app/audit/page.tsx').read_text(encoding='utf-8')
    for part in (
        'def export_tenant_audit_evidence(', 'def export_platform_audit_evidence(',
        '_require_tenant_audit_access(', '_require_platform_audit_access(',
    ):
        assert part in route, part
    assert 'export async function downloadAuditEvidence(' in client
    assert 'const exportEvidence = async' in page
    assert '"Export CSV"' in page and '"Evidence JSON"' in page
    print('[PASS] CSV formula injection protections, canonical digest and export cap.')
    print('[PASS] Both API export endpoints, authorization guards and UI controls exist.')
    print('[PENDING] Live DB authorization, export SHA-256 and audit event checks (README).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
