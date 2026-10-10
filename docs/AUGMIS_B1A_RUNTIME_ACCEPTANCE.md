# AUGMIS B0+B1 — Runtime Safety Checkpoint B1A

**Source baseline:** `b0b1-runtime-review.zip`, captured 2026-10-10.
**Prior Alembic head:** `9d3a4c7e1b20`
**New Alembic head:** `b1a2026101001`

## Implemented (B1A)

- Keep at most **256 KiB** of the last **2,000 timestamped Docker log lines** when a deployment is intentionally stopped, upgraded or rolled back. The application deployment row is the durable record, and the existing `application.instance.view` check still controls retrieval.
- If a container is removed, `/api/v1/deployments/{id}/logs` returns the saved log snapshot (`source=archived`) instead of 410 when one was obtained. Old deployments predating this migration may still return 410.
- Retain up to 256 KiB of failed-start logs captured before a failed health-check container is removed.
- Persist a healthy candidate's Docker container ID, port and runtime URL **before** removing its old deployment during manual upgrade and rollback. A new **read-only** recovery report helps operators identify interrupted operations; it does not automatically recover or mutate instances.
- Record an instance `stopping` intent before destructive stop and prevent a competing lifecycle request from taking over an instance during stop.
- Default platform-owned Docker resource caps per container: 1024 MiB RAM, 1 CPU and 256 PIDs. The manifest cannot override these caps. Optional host configuration: `AUGMIS_RUNTIME_MEMORY_MB` (128–32768), `AUGMIS_RUNTIME_CPUS` (0.25–16), `AUGMIS_RUNTIME_PIDS` (32–4096). These are **per-container development baseline limits**, not full tenant quota, storage quota or consumption metering.
- Preserve Docker loopback-only host binding. **Do not** expose container ports to the public internet.

## Limitations and required follow-up

- Log snapshots are *best effort*: Docker may be unavailable when logs are requested. Archive errors are stored as fixed error codes; no claim of lossless logging, redaction, legal hold, encryption at rest or immutability is made. Logs might contain application secrets; preserve strict RBAC and apply PostgreSQL storage controls.
- Resource limits depend on Docker host capabilities. Full per-tenant quotas, I/O/disk limits, configuration API, secret reference/injection/rotation, image digest/signature policy, private networks, distributed workers, shared gateway sessions, automatic crash recovery, and full version automation remain outstanding.
- The crash-recovery reporter is **read-only** to prevent an automatic recovery routine from deleting healthy tenant containers based on incomplete observations.
- No changes to the static-runtime Next.js security route, runtime gateway, tenant role matrix, subscriptions or offers.

## Installation

1. Back up PostgreSQL (`pg_dump` outside Git) and confirm a safe development/test environment.
2. Stop FastAPI workers (so SQLAlchemy model changes and the migration are not briefly out of sync).
3. Extract package anywhere, then from `D:\Uday_Documents\AUGMIS_PLATFORM`:

```powershell
python "D:\Downloads\AUGMIS_B1A_RUNTIME\install.py" --repo . --check
python "D:\Downloads\AUGMIS_B1A_RUNTIME\install.py" --repo . --apply
alembic heads
alembic upgrade head
alembic current
python -m compileall services/api/app tools
python -m tools.verify_b1_runtime_safety
python -m tools.b1_runtime_recovery_report --with-docker
python -m tools.verify_phase4_rbac
python -m tools.verify_phase4_rbac_matrix
python -m tools.verify_single_publisher_workspace
git diff --check
```

Replace the example installer path with the extracted actual location. The installer checks SHA-256 against the **exact uploaded source** and refuses changed files. No `--force` mode exists. Existing changed files are backed up as `*.before-b1a.bak`; these are local and must not be added to Git.

## Manual acceptance — perform on disposable container test instance

1. Deploy and open a known test container. Inspect its Docker limits using `docker inspect` and verify loopback-only port binding; verify health and live logs (`source=docker`).
2. Generate recognizable test log output (do **not** log credentials), stop the instance, call the same deployment logs endpoint: expect HTTP 200 with `source=archived` and the old lines; test `tail=1`.
3. Restart the instance, confirm a *new* deployment record is created and old logs remain accessible.
4. Upgrade a test 1.0 to 1.1; if it succeeds, old deployment logs must be archived; if new candidate health fails, its logs should be archived if Docker supplied them and old version must remain running.
5. Test rollback similarly. Simulate a refused old-container stop using mocks or a controlled test fixture; old runtime must remain active if retirement fails.
6. Test an account without `application.instance.view`: `/deployments/{id}/logs` must deny across tenants even when logs are archived. Verify `application.deploy`/stop privilege boundaries remain intact.
7. Stop FastAPI or Docker during a **disposable** long-running lifecycle operation and run the read-only reconciliation report. Do not treat the tool as automatic recovery.
8. Verify that PostgreSQL Alembic `current` matches `heads`, and the standard frontend production build still passes.

## Rollback

The installer backs up existing changed source files. Restoring source from those backups must be coordinated with Alembic. A database downgrade **drops saved logs**, so first back up the database. Do not run `alembic downgrade` casually.

## Gate

**B1A** acceptance requires unit verification, local DB migration, smoke tests for stop / restart / upgrade / rollback, archived-log retrieval, negative cross-tenant authorization, and Git clean checkpoint. **B1 as a whole is not finished** until the remaining runtime configuration, secrets, tenant quotas, crash recovery, image pinning and production isolation work is implemented and tested.
