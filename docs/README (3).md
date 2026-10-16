# AUGMIS B0+B1 baseline and current-source review (non-destructive)

This is the **first independently runnable checkpoint** of the combined B0+B1 work, not the finished runtime implementation. It deliberately does not overwrite production runtime code when the exact current deployment engine/service source is unavailable.

### Install
From ZIP, copy `tools/*.py` into project `tools`, `.github/workflows/augmis-baseline.yml` into the matching path (review before pushing), and `docs/AUGMIS_B0_B1_RUNTIME_CONTRACT.md` into `docs`.

### Run
From project root:

```powershell
python -m tools.b0b1_runtime_inventory
python -m tools.b0b1_runtime_inventory --with-db --with-docker
python -m tools.create_b0b1_review_bundle
```

Generated in ignored `data/phase5-verification/`:
- `b0b1-runtime-inventory.json` (no source code, no credentials, hashes + function names only)
- `b0b1-runtime-review.zip` (allowlisted **source code** for the next implementation stage)

**Before uploading ZIP**: review it locally for any credentials inadvertently embedded in source. The tool excludes .env, DB dumps, package files and known suspicious literal secrets, but static scanning cannot guarantee that source contains no credentials. Do not upload files with secrets.

### CI
The optional workflow runs independent static checks; it is not a replacement for DB-backed API tests or Docker integration tests. It requires `apps/web/package-lock.json`, Node 22 and an existing successful local Next.js build. On first use, review the first Actions run; adjust only based on actual failure evidence.

### Data protection
No cleanup, reset, image deletion, Docker changes, Alembic migration, secret manipulation or runtime route changes occur. Existing legacy publishers remain untouched. The read-only Docker/DB probes collect only success status and return code.

### Next action
Share `b0b1-runtime-inventory.json` and the reviewed `b0b1-runtime-review.zip`. With current source in hand, the **same B0+B1 combined batch** can continue into migration-safe lifecycle/service/frontend fixes without multiple speculative patch attempts.
