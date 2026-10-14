# AUGMIS B3+B4 — Pass 1: secure foundations (2026-10-12)

## What is implemented

- AUGMIS gateway and static runtime sessions may use Redis using `AUGMIS_SESSION_STORE=redis` and `AUGMIS_SESSION_REDIS_URL=rediss://...` (or `redis://` on a strictly private development network). Connection failure is fatal, not a fallback.
- Atomic Redis Lua one-time ticket exchange across worker processes; session TTL and revocation preserved.
- Docker drops Linux capabilities and sets `no-new-privileges`. This is *not* complete container isolation; no public deployments yet.
- Production fails closed until a verified private runtime gateway, separated browser origins, secret manager and staging security review are installed.
- Techtango numeric tenant IDs have no implicit relationship to AUGMIS UUIDs. A platform-authorized API proposes one-to-one *pending* bindings; none are active or authorize a publish/launch.
- Read-only AI Builder metadata snapshot validator (no user records, raw SQL, secret values or application runtime; NOT yet a hostable AAPS export).
- Techtango tenant context no longer trusts x-tenant/user/role headers and its JWT inactivity check no longer accepts a client-supplied last-seen time.
- GitHub Actions checks Python, pytest, TypeScript, ESLint, Next build, dependency vulnerability audit. Production promotion NOT implemented.

## Installation prerequisites

1. Commit/backup both source trees individually and back up PostgreSQL before Alembic.
2. Run guarded `install.py --check` before `--apply` and stop Uvicorn workers beforehand.
3. `pip install -r requirements.txt` includes Redis client. Start **private Redis** with ACL and authentication. Avoid sending secrets in URLs that you share.
4. `AUGMIS_SESSION_STORE=redis` + `AUGMIS_SESSION_REDIS_URL=...`. Restart API; test session access across at least two API workers and after process restarts. Sessions are intentionally invalidated when switching from in-memory to Redis mode.
5. Run `alembic upgrade head` after checking current/head. The only schema addition is `techtango_tenant_links`.
6. Run `python -m pytest -q tools/test_b3b4_security.py` and existing B1B2/RBAC suites; run frontend TypeScript, lint and Next build; run `node --check` on the two Techtango middleware files.
7. Test invalid ticket replay (401), stopped application access (409), subscription suspension revocation (403), other tenant authorization (403), and Redis unavailable response (fail closed). Test provider secrets do not enter logs.

## Important limitations / remaining gates

**B3 is NOT production accepted:** container gateway still uses host-loopback Docker port publishing, package isolation/egress policy, Redis HA/TLS and origin separation require deployment architecture & live tests. The production safety gate intentionally blocks startup.

**B4 is NOT end-to-end accepted:** one-to-one tenant mapping stays *pending* until independently authenticated proof, Techtango renderers depend on dynamic tables/database, no immutable AAPS converter or publish job yet, no federated entitlement-safe launch/favorites integration yet. Never claim snapshot validator alone is a fully hostable application.

**B5 is untouched in this pass:** real payment processing requires a selected payment provider and sandbox credentials, tax/invoicing rules, ledger and reconciliation design. No live charging.

## Backout

- Roll back both Git worktrees to their **own** pre-change checkpoints. Do not revert by deleting test data.
- Redis sessions issued after cutover are not interoperable with in-memory sessions; plan a maintenance session reset for any rollback.
- Database downgrade (`alembic downgrade b1b2stop261011`) drops pending link rows; export/review them first.
- Production must remain blocked on rollback unless the full secure gateway is deployed and independently verified.
