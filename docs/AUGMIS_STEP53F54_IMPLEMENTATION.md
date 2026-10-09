# AUGMIS: Step 53F + Step 54 implementation tracker

## Confirmed baseline

- GitHub source backup checkpoint accepted: `augmis-phase5-step53e-accepted-20261009` on `main`.
- Alembic `9d3a4c7e1b20` is the expected live DB revision.
- One publisher workspace per organization, while publishers without tenant ownership remain legacy pending items.
- Step 53E tenant Users page + Publisher capability and Publisher Users & Roles accepted.

## Step 53F — Legacy ownership reconciliation

Status: **INVENTORY READY; MAPPINGS PENDING USER APPROVAL**.

- Enumerate existing publisher UUIDs, tenant ownership, active owners, application counts.
- Review `Infomentica` and `Infomentica Platform` as legacy unassigned workspaces.
- Confirm whether these represent separate organizations or redundant publishing workspaces in one organization.
- Never infer ownership from naming or user's currently selected tenant.
- Do not assign two publishers to the same tenant; PostgreSQL unique index enforces this.
- If redundant, review application/version/package/offer dependencies and active subscribers before considering data migration, retirement or preservation as a legacy workspace.
- Use existing `POST /api/v1/publishers/{publisher_id}/organization` after approving an explicit owner+organization mapping; audit verifies the assignment.

## Step 54 — Audit evidence and governance

Deliverables:

- Tenant and platform POST export routes protected by existing backend audit permissions.
- Bounded (5,000 rows), filtered JSON/CSV export with no silent truncation.
- JSON evidence manifest with canonical-record SHA-256, file SHA-256 in header and committed audit event.
- Excel/CSV formula-injection neutralization.
- Audit Center export actions; uses existing selected tenant and applied query filters.
- Offline JSON evidence verification CLI.
- Retention-impact assessment CLI that never deletes audit records.
- Backend, frontend and security acceptance matrix in README.

Not part of this release:

- User-approved legal-hold and archive retention policy, immutable/WORM storage, cryptographic document signatures, key rotation, trusted timestamps, retention purge.
- New `audit.export` permission independent of `audit.view` (current backend policy deliberately treats export as part of audit.view).
- Cross-organization publisher mergers or tenant role escalation.
- Runtime gateway changes.

## Exit conditions

- Audited export of the selected tenant only; 403 on other tenant and platform scopes without permissions.
- Platform-wide export only with `platform.audit.view`.
- Evidence hashes verify; `audit.export.created` with correct actor and scope.
- Frontend current filter state and scope are respected.
- Compilers, frontend build, Phase4 RBAC matrix and publisher integrity tests pass.
- No unauthorized publisher mapping or audit deletion has occurred.
