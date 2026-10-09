# AUGMIS Phase 5 — Step 55 Retention & Governance

**Status:** DRAFT baseline. No production retention, legal hold, or purge operation is claimed.

## Existing controls (Step 54)
- `POST /api/v1/audit-events/export` and platform export with authoritative `audit.view` / `platform.audit.view` permissions.
- Bounded CSV/JSON exports, SHA-256 evidence manifests, audit export records.
- `tools/report_audit_retention.py` read-only database age/count assessment.

## Proposed initial operating rules — explicitly NOT approved
1. **Operational retention:** assess 365 days as a planning baseline, never a data deletion schedule. Actual values depend on law, sector, contract, incident response, tax, security and dispute requirements, and tenant geography.
2. **Legal holds:** must be enforceable for tenant, person, resource, date range and case; all relevant events must be included. No legal-hold registry or hold-aware purge exists today.
3. **Archive evidence:** require independent durable/WORM or equivalent archive with stored checksums, manifest, verified restoration and documented access logs. Step 54 JSON hashes are *not* digital signatures or immutable archives.
4. **Destruction:** forbidden now. Future controlled purge needs a separately approved implementation with quarantine of eligible data, privileged dual approval, legal hold exclusion, archive verification, dry-run preview, immutable deletion evidence and independent recovery test.
5. **Multitenancy:** tenant audit access must remain tenant-scoped even after archival; platform authority must remain separate.
6. **Data protection:** audit metadata may contain user identifiers and confidential business data. Avoid committing actual exports, local private logs or retention reports to GitHub. Apply encryption and access control to offline files.
7. **Database backups:** GitHub does not back up PostgreSQL. Maintain tested, encrypted DB backups with independent recovery verification.

## Step 55 baseline delivered in this package
- `docs/AUGMIS_AUDIT_RETENTION_POLICY_DRAFT.json` (not consumed by the API, cannot accidentally enable purge).
- `tools/verify_step55_retention_governance.py` validates the fail-closed draft and optionally calls the current read-only reporter.
- Governance design, risks and operational controls captured for review.

**This baseline is not an implementation of retention policy editing, WORM storage, legal-hold CRUD, or purge execution.** Those features need a separate approved design and code review. Do not mark full retention compliance complete from this report alone.

## Ownership decision still outstanding (Step 53F)
The two legacy publishing workspaces `Infomentica` and `Infomentica Platform` remain unassigned in the latest verification. One-workspace-per-tenant uniqueness is already enforced. Preserve both until application/offer/subscription dependencies and ownership are explicitly approved; do not force a second artificial organization or infer ownership by name.
