"""Guarded code edits for AUGMIS one-publisher-per-organization + unified Users entry.

Run from repository root:
  python -m tools.apply_single_workspace_users --check
  python -m tools.apply_single_workspace_users --apply

If local files diverged from supplied snapshots, this refuses to edit anything.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path

ROOT = Path.cwd()
EXPECTED = {
    "services/api/app/models/platform.py": "ba0e1d8dd49a5f5b42ae7e6fec7bb79d2accc27ce03d23404a2e9a0a475ce9d6",
    "services/api/app/routes/publishers.py": "8b51d5013481152e9788c330407299b94e36fa406867dbdc5848f42c295bf2b8",
    "apps/web/src/app/users/page.tsx": "b9840652da6178c618e24331ed3145595b0e900df79963cc81f8329a54647f8b",
    "services/api/app/services/publisher_workspace_service.py": "aaef83fc4c92bb18b1bd3401482c666978428c93a0bca0ef4e347a3cccc6a5b4",
}

def digest(s: str) -> str:
    return hashlib.sha256(s.replace("\r\n", "\n").encode("utf-8")).hexdigest()

def once(s: str, before: str, after: str, desc: str) -> str:
    count = s.count(before)
    if count != 1:
        raise ValueError(f"{desc}: expected one anchor; found {count}")
    return s.replace(before, after, 1)

def patch_model(s: str) -> str:
    return once(s,
        'class Publisher(Base):\n\n    __tablename__ = "publishers"',
        'class Publisher(Base):\n\n    __tablename__ = "publishers"\n\n'
        '    __table_args__ = (\n'
        '        UniqueConstraint("tenant_id", name="uq_publishers_single_workspace_per_tenant"),\n'
        '    )',
        "Publisher SQLAlchemy uniqueness")

def patch_routes(s: str) -> str:
    s = once(s,
        'from services.api.app.services.publisher_ownership_service import (\n'
        '    PublisherOwnershipError,\n'
        '    get_active_organization,\n'
        '    resolve_initial_publisher_owner,\n'
        '    assign_publisher_organization,\n'
        ')',
        'from services.api.app.services.publisher_ownership_service import (\n'
        '    PublisherOwnershipError,\n'
        '    get_active_organization,\n'
        '    resolve_initial_publisher_owner,\n'
        '    assign_publisher_organization,\n'
        ')\n'
        'from services.api.app.services.publisher_workspace_service import (\n'
        '    activate_organization_publisher,\n'
        ')',
        "Service import")
    s = once(s,
        '        tenant = get_active_organization(db, payload.tenantId, lock=True)\n'
        '        initial_owner = resolve_initial_publisher_owner(',
        '        tenant = get_active_organization(db, payload.tenantId, lock=True)\n'
        '        if db.scalar(select(Publisher.id).where(Publisher.tenant_id == tenant.id)):\n'
        '            raise PublisherOwnershipError(\n'
        '                "This organization already has a publisher workspace.", 409\n'
        '            )\n'
        '        initial_owner = resolve_initial_publisher_owner(',
        "Platform-managed publisher create guard")
    s = once(s,
        '# ============================================================\n# EXPLICIT ORGANIZATION OWNERSHIP (STEP 53D)\n# ============================================================',
        '# ============================================================\n# ORGANIZATION PUBLISHER ACTIVATION (STEP 53E)\n# ============================================================\n\n'
        '@router.post("/organizations/{tenant_id}/activate", response_model=PublisherResponse)\n'
        'def activate_publisher_for_organization(\n'
        '    tenant_id: uuid.UUID,\n'
        '    db: Session = Depends(get_db),\n'
        '    current_user: User = Depends(get_current_user),\n'
        '):\n'
        '    try:\n'
        '        require_tenant_permission(\n'
        '            db=db, user=current_user, tenant_id=tenant_id,\n'
        '            permission_code="tenant.manage",\n'
        '        )\n'
        '    except AuthorizationError as exc:\n'
        '        raise HTTPException(status_code=403, detail=str(exc)) from exc\n'
        '    try:\n'
        '        publisher, _created = activate_organization_publisher(\n'
        '            db, tenant_id=tenant_id, actor=current_user,\n'
        '        )\n'
        '        db.commit()\n'
        '        db.refresh(publisher)\n'
        '        return publisher\n'
        '    except PublisherOwnershipError as exc:\n'
        '        db.rollback()\n'
        '        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc\n'
        '    except MembershipSetupError as exc:\n'
        '        db.rollback()\n'
        '        raise HTTPException(status_code=500, detail=str(exc)) from exc\n'
        '    except IntegrityError as exc:\n'
        '        db.rollback()\n'
        '        raise HTTPException(status_code=409, detail="Organization already has a publisher workspace.") from exc\n\n\n'
        '# ============================================================\n# EXPLICIT ORGANIZATION OWNERSHIP (STEP 53D)\n# ============================================================',
        "Activation route")
    s = once(s,
        '    except PublisherOwnershipError as exc:\n'
        '        db.rollback()\n'
        '        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc\n\n\n'
        '# ============================================================\n# PUBLISHER USERS & ROLES ADMINISTRATION',
        '    except PublisherOwnershipError as exc:\n'
        '        db.rollback()\n'
        '        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc\n'
        '    except IntegrityError as exc:\n'
        '        db.rollback()\n'
        '        raise HTTPException(status_code=409, detail="Organization already has a publisher workspace.") from exc\n\n\n'
        '# ============================================================\n# PUBLISHER USERS & ROLES ADMINISTRATION',
        "Legacy binding uniqueness error")
    return s

def patch_users(s: str) -> str:
    s = once(s,
        'import AppShell from "@/components/app-shell";',
        'import AppShell from "@/components/app-shell";\n'
        'import PublisherUsersDialog from "@/components/publisher-users-dialog";\n'
        'import { loadMyPublisherPermissions } from "@/lib/publisher-users";\n'
        'import { loadOrganizationPublishers, activateOrganizationPublisher,\n'
        '  type OrganizationPublisher } from "@/lib/organization-publisher";',
        "Users page imports")
    s = once(s,
        '  const [\n    memberships,\n    setMemberships,\n  ] =',
        '  const [orgPublisher, setOrgPublisher] = useState<OrganizationPublisher | null>(null);\n'
        '  const [publisherAccess, setPublisherAccess] = useState(false);\n'
        '  const [publisherBusy, setPublisherBusy] = useState(false);\n'
        '  const [publisherDialogOpen, setPublisherDialogOpen] = useState(false);\n'
        '  const [publisherError, setPublisherError] = useState("");\n\n'
        '  const [\n    memberships,\n    setMemberships,\n  ] =',
        "Users publisher state")
    s = once(s,
        '  const assignableRoles =\n    useMemo(',
        '  useEffect(() => {\n'
        '    let ignore = false;\n'
        '    setOrgPublisher(null);\n'
        '    setPublisherAccess(false);\n'
        '    setPublisherDialogOpen(false);\n'
        '    setPublisherError("");\n'
        '    if (!selectedTenantId || !canManageUsers) return () => { ignore = true; };\n'
        '    const fetchPublisher = async () => {\n'
        '      try {\n'
        '        const rows = await loadOrganizationPublishers(selectedTenantId);\n'
        '        const workspace = rows[0] ?? null;\n'
        '        if (ignore) return;\n'
        '        setOrgPublisher(workspace);\n'
        '        if (!workspace) return;\n'
        '        try {\n'
        '          const permissions = await loadMyPublisherPermissions(workspace.id);\n'
        '          if (!ignore) setPublisherAccess(permissions.includes("publisher.manage"));\n'
        '        } catch {\n'
        '          if (!ignore) setPublisherAccess(false);\n'
        '        }\n'
        '      } catch (e) {\n'
        '        if (!ignore) setPublisherError(apiError(e, "Publisher workspace could not be loaded."));\n'
        '      }\n'
        '    };\n'
        '    void fetchPublisher();\n'
        '    return () => { ignore = true; };\n'
        '  }, [selectedTenantId, canManageUsers]);\n\n'
        '  const enablePublisherWorkspace = async () => {\n'
        '    if (!selectedTenantId || !canManageTenantOwners) return;\n'
        '    setPublisherBusy(true);\n'
        '    setPublisherError("");\n'
        '    try {\n'
        '      const workspace = await activateOrganizationPublisher(selectedTenantId);\n'
        '      setOrgPublisher(workspace);\n'
        '      const permissions = await loadMyPublisherPermissions(workspace.id);\n'
        '      setPublisherAccess(permissions.includes("publisher.manage"));\n'
        '    } catch (e) {\n'
        '      setPublisherError(apiError(e, "Publisher workspace activation failed."));\n'
        '    } finally {\n'
        '      setPublisherBusy(false);\n'
        '    }\n'
        '  };\n\n'
        '  const assignableRoles =\n    useMemo(',
        "Users page hooks and activation")
    s = once(s,
        '          {message && (',
        '          {canManageUsers && selectedTenantId && (\n'
        '            <Box sx={{ bgcolor: "background.paper", border: "1px solid", borderColor: "divider", p: 2, mb: 2 }}>\n'
        '              <Typography sx={{ fontSize: 11, color: "text.secondary", textTransform: "uppercase", mb: 0.5 }}>\n'
        '                Publisher capability\n'
        '              </Typography>\n'
        '              <Box sx={{ display: "flex", flexDirection: { xs: "column", sm: "row" }, alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between", gap: 2 }}>\n'
        '                <Box>\n'
        '                  <Typography sx={{ fontWeight: 600 }}>\n'
        '                    {orgPublisher ? orgPublisher.name : "No publisher workspace enabled"}\n'
        '                  </Typography>\n'
        '                  <Typography sx={{ fontSize: 12, color: "text.secondary" }}>\n'
        '                    One publishing workspace per organization. Tenant membership does not grant publisher access.\n'
        '                  </Typography>\n'
        '                </Box>\n'
        '                {orgPublisher && publisherAccess ? (\n'
        '                  <Button variant="outlined" onClick={() => setPublisherDialogOpen(true)}>Publisher Users & Roles</Button>\n'
        '                ) : !orgPublisher && canManageTenantOwners ? (\n'
        '                  <Button variant="contained" disabled={publisherBusy} onClick={() => void enablePublisherWorkspace()}>\n'
        '                    {publisherBusy ? "Enabling..." : "Enable Publisher"}\n'
        '                  </Button>\n'
        '                ) : (\n'
        '                  <Typography sx={{ fontSize: 12, color: "text.secondary" }}>\n'
        '                    {orgPublisher ? "Publisher administrator access is required." : "Ask an active Tenant Owner to enable publishing."}\n'
        '                  </Typography>\n'
        '                )}\n'
        '              </Box>\n'
        '              {publisherError && <Alert severity="error" sx={{ mt: 1 }}>{publisherError}</Alert>}\n'
        '              {orgPublisher && (\n'
        '                <PublisherUsersDialog\n'
        '                  open={publisherDialogOpen}\n'
        '                  publisherId={orgPublisher.id}\n'
        '                  publisherName={orgPublisher.name}\n'
        '                  onClose={() => setPublisherDialogOpen(false)}\n'
        '                />\n'
        '              )}\n'
        '            </Box>\n'
        '          )}\n\n'
        '          {message && (',
        "Users publisher administration panel")
    return s


# Step 53E update: only the source-matched Users page receives these
# naming and activation-feedback adjustments. This wrapper preserves all
# existing tenant user / invitation logic and the guarded backend patches.
_original_patch_users = patch_users

def patch_users(s: str) -> str:
    out = _original_patch_users(s)
    out = once(
        out,
        '{orgPublisher ? orgPublisher.name : "No publisher workspace enabled"}',
        '{orgPublisher ? orgPublisher.name : `${selectedTenant?.tenant.name ?? "Organization"} Workspace (not enabled)`}',
        "Default publisher workspace display name",
    )
    out = once(
        out,
        '      const permissions = await loadMyPublisherPermissions(workspace.id);\n'
        '      setPublisherAccess(permissions.includes("publisher.manage"));\n'
        '    } catch (e) {\n'
        '      setPublisherError(apiError(e, "Publisher workspace activation failed."));',
        '      try {\n'
        '        const permissions = await loadMyPublisherPermissions(workspace.id);\n'
        '        setPublisherAccess(permissions.includes("publisher.manage"));\n'
        '      } catch (accessError) {\n'
        '        setPublisherAccess(false);\n'
        '        setPublisherError(apiError(accessError, "Workspace enabled but publisher permissions could not be loaded. Refresh the page."));\n'
        '      }\n'
        '      setMessage(`Publisher workspace ${workspace.name} is enabled.`);\n'
        '    } catch (e) {\n'
        '      setPublisherError(apiError(e, "Publisher workspace activation failed."));',
        "Separate activation errors from permission refresh errors",
    )
    return out

def patch_publisher_workspace_service(s: str) -> str:
    return once(
        s,
        'tenant_id=tenant.id, name=tenant.name, slug=slug, status="active"',
        'tenant_id=tenant.id, name=f"{tenant.name} Workspace", slug=slug, status="active"',
        "Publisher display name Tenant name + Workspace",
    )

PATCHES = {
    "services/api/app/models/platform.py": patch_model,
    "services/api/app/routes/publishers.py": patch_routes,
    "apps/web/src/app/users/page.tsx": patch_users,
    "services/api/app/services/publisher_workspace_service.py": patch_publisher_workspace_service,
}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    updated: dict[Path, str] = {}
    for rel, expected in EXPECTED.items():
        path = ROOT / rel
        if not path.exists():
            raise SystemExit(f"[BLOCKED] Missing: {rel}")
        original = path.read_text(encoding="utf-8-sig")
        if digest(original) != expected:
            raise SystemExit(f"[BLOCKED] Modified since the reviewed snapshot: {rel}; no files changed. Share the latest file for targeted changes.")
        try:
            updated[path] = PATCHES[rel](original)
        except ValueError as exc:
            raise SystemExit(f"[BLOCKED] {exc}; no files changed") from exc
        print(f"[PASS] Compatible: {rel}")
    if args.check:
        print("[CHECK ONLY] Nothing modified.")
        return
    for path, new_source in updated.items():
        backup = path.with_name(path.name + ".before-single-workspace.bak")
        if backup.exists():
            raise SystemExit(f"[BLOCKED] Backup already exists: {backup}")
    for path, new_source in updated.items():
        backup = path.with_name(path.name + ".before-single-workspace.bak")
        backup.write_bytes(path.read_bytes())
        path.write_text(new_source, encoding="utf-8")
        print(f"[APPLIED] {path.relative_to(ROOT)} (backup: {backup.name})")

if __name__ == "__main__":
    main()
