# AUGMIS B1 + B2 — Final acceptance checklist

**Status:** Not signed off by installer alone. Complete these live tests on a disposable tenant/instance; do not execute automatic upgrades against production data.

## Covered in current implementation

- Dockerfile/AAPS package validation and image-ready publication.
- Container deploy, health, logs, stop, restart and gateway launch (gateway shown passing in AUGMIS Runtime Lab).
- Immutable image identity at start, DB config revisions and next-start snapshots, per-container Docker limits, tenant container cap when set.
- Durable PostgreSQL upgrade queue, idempotency keys, worker opt-in, policies `same_major`, `pinned`, `any`, backend-controlled consent.
- Existing multi-file static ZIP support. B2 static ZIP validation tests pass locally.
- This completion patch quarantines unknown promotion outcomes, synchronizes quota changes with deployment reservations using tenant locks, and adds **read-only** DB/Docker live diagnostics.

## Mandatory live release gates

| Gate | Procedure | Pass criteria |
|---|---|---|
| G01 | `pytest -q tools/test_b1b2_worker_safety.py` | All isolated failure/recovery tests pass |
| G02 | Run `tools.b1b2_live_preflight` with DB+Docker | No unexplained mismatch, expired job, or over-quota state |
| G03 | Set `APP_ENV=development`, save; restart disposable Runtime Lab; verify config snapshot and inside-container env | New deployment uses saved config revision; previous historical deployment unchanged |
| G04 | Platform operator sets cap of 1 on disposable tenant without existing running containers; deploy one instance then attempt second | HTTP 409/422 on excess; old healthy application stays running |
| G05 | Two tenants: attempt config GET/PUT, quota GET, jobs GET, log GET, instance operation cross-tenant as unauthorized account | 403/404, no data leakage or action |
| G06 | Publish healthy 1.1.0; exactly one active sub; `same_major` + consent true; plan then execute once | Job succeeds and gateway reports 1.1.0, deployment switch recorded |
| G07 | Publish intentionally unhealthy 1.2.0 as eligible candidate; run one worker | Job fails or requires reconciliation; original healthy version and gateway unaffected |
| G08 | `pinned` with consent true; `any` for 2.0.0; `same_major` for major-version candidate | Pinned no upgrade, any permits 2.0.0, same_major blocks 2.0.0 |
| G09 | Restart/stop on disposable test instance and inspect old deployment logs | Logs available from Docker while running; bounded archive on stop when available |
| G10 | Deliberate crash simulation in an isolated disposable environment only | Unknown running job quarantined, no second container action without review |
| G11 | Multi-asset static ZIP including relative CSS/JS/images, plus malicious traversal, symlink and missing-index ZIP | Valid files reachable; malicious inputs rejected |
| G12 | Full TS/Next build + RBAC matrix + verify_b1b2_runtime and publisher integrity | All pass |

**Blockers:** Any unexplained `needs_reconciliation` job or a duplicate active subscription affecting the test application. Existing AUGMIS Runtime Lab appears to have duplicate active subscriptions. Never choose a contract arbitrarily or directly edit SQL to force eligibility. Prepare a fresh disposable tenant with one subscription, using authorized UI.

## Safe command sequence

```powershell
cd D:\Uday_Documents\AUGMIS_PLATFORM
python -m compileall -q services/api/app tools
pytest -q tools/test_b1b2_worker_safety.py
python -m tools.verify_b1b2_runtime
python -m tools.verify_b1b2_upgrade_controls
python -m tools.verify_runtime_control_catalog_batch
python -m tools.verify_b1_runtime_safety
python -m tools.verify_phase4_rbac_matrix
python -m tools.b1b2_live_preflight --with-db --with-docker
# After restart, get instance UUID from Runtime Control, then:
python -m tools.b1b2_verify_instance_environment --instance-id YOUR_INSTANCE_UUID --with-docker
python -m tools.runtime_upgrade_worker
cd apps/web
npx tsc --noEmit
npm run build
```

Do NOT use `--enqueue-and-run` until G02, G04, G05 and G06 are set up for a disposable tenant with an explicitly approved candidate. This is a state-changing operation that can replace a running container.

## Production boundaries

B1/B2 is the development-runtime and packaging milestone. B3 remains a separate mandatory production gate: Redis/shared sessions, private networking, container isolation, secrets provider and rotation, supply-chain signature/malware integration, full CI staging pipeline, independently backed-up artifacts. Do not mark production secure at B1/B2.

## Rollback strategy

Restoring a Git checkpoint alone does not restore migrated DB or Docker state. Keep tested PostgreSQL custom-format backups, application packages and Docker images. This patch does not add or downgrade migrations. If an unknown upgrade job is quarantined, reconcile recorded deployment IDs with Docker state before authorizing any rerun.
