# AUGMIS B1+B2 — Subscription Upgrade Readiness & Consent

## Change scope

The existing `/runtime-control` page now displays subscription-level automatic-upgrade readiness for a selected instance, with explicit opt-in/out actions. **No new Alembic migration**: the existing `tenant_subscriptions.auto_upgrade` field is reused. The durable job worker is still **off by default**. No Docker modifications occur when consent is changed.

### Backend

- `GET /api/v1/instances/{instance_id}/upgrade-readiness` requires `application.instance.view` **and** `subscription.view` for the instance's tenant.
- `PUT /api/v1/instances/{instance_id}/auto-upgrade` requires `application.instance.view` **and** `subscription.manage`. Payload:
  `{"expected_auto_upgrade":false,"auto_upgrade":true}`.
- The PUT refuses ambiguous duplicate active subscriptions (HTTP 409), stale expected state (409), missing deployment entitlement when enabling (409), and an in-flight or reconciliation-required job (409). Changes are audited as `subscription.auto_upgrade.updated`. Changes apply to the **subscription as a whole**, not just the selected instance.
- GET returns a reason code if the instance isn't running, consent isn't enabled, no eligible published target exists, or active subscriptions are ambiguous. This is read-only and **does not enqueue a job**.

## Installation

Back up database/Git first (your `augmis-pre-b1b2-20261010` checkpoint). Stop API before changing backend source. Extract ZIP outside the repo, then:

```powershell
cd D:\Uday_Documents\AUGMIS_PLATFORM
python "D:\Downloads\AUGMIS_B1B2_NEXT_UPGRADE_CONTROLS\install.py" --repo . --check
python "D:\Downloads\AUGMIS_B1B2_NEXT_UPGRADE_CONTROLS\install.py" --repo . --apply
python -m compileall -q services/api/app tools
python -m tools.verify_b1b2_upgrade_controls
python -m tools.verify_b1b2_runtime
python -m tools.verify_phase4_rbac_matrix
cd apps/web
npx tsc --noEmit
npm run build
```

**If the guard blocks**, do not override it; provide the reported filename for a targeted patch. Existing files are saved as `.before-upgrade-controls.bak`; do not commit these files.

## Live acceptance (disposable tenant only)

1. Restart FastAPI, then open `/runtime` (redirects to `/runtime-control`). Select the tenant and instance and inspect **Subscription upgrade readiness**.
2. With `subscription.manage` (Tenant Owner or Subscription Admin), enable auto-upgrade. Refresh and verify `Opted in`, audit event and persisted setting. The Docker hostname/version MUST NOT change yet. Disabled consent also persists after page refresh.
3. With only `tenant_user` or `operations_admin`, PUT must return **HTTP 403**. GET also needs both viewing permissions; cross-tenant access must fail.
4. If duplicate active subscriptions are present, status shows `MULTIPLE_ACTIVE_CONTRACTS` and PUT returns HTTP 409. **Do not delete existing subscriptions to make the test pass.** Use a clean disposable tenant/app contract for automation testing.
5. Publish a *new healthy* candidate version in the same major series as the running version, ensure it is image-ready and only one active subscription exists. If policy `same_major`, a 2.0.0 candidate must not be selected while running 1.x. `pinned` remains restricted; `any` may allow major changes.
6. Before running worker, check `python -m tools.runtime_upgrade_worker` dry run. After verifying tenant/instance/version and obtaining approval, run `python -m tools.runtime_upgrade_worker --enqueue-and-run` **only on the disposable test instance**. Check healthy candidate, logs, job state and gateway hostname/version.
7. Publish an intentionally unhealthy later candidate and verify the old deployment continues and the worker records failure. Do not auto-retry ambiguous/crashed jobs (`needs_reconciliation`).
8. Perform negative cross-tenant subscription/readiness checks; verify existing static and container gateway regression.

## Security limitations

- This does not provide a secrets vault, shared sessions, remote image signing or private networks; those remain future B3 work.
- Config JSON is non-secret only; do not paste credentials.
- Subscription opt-in is not a process-wide worker enable switch; **never run a continuous worker** until all recovery/authorization tests pass.
