# AUGMIS Step 55 + Step 56 — Combined Governance / Freeze Preparation

**Non-destructive add-on, no Alembic migration and no replacements of working source files.**

Copy only the two new files from `tools/` and the four files from `docs/` to the corresponding paths within `D:\Uday_Documents\AUGMIS_PLATFORM`.

These tool names are new; if you already have files with identical names in your repository, compare them first rather than overwrite them.

Add `data/phase5-verification/` to `.gitignore` so locally generated readiness reports do not get pushed.

## Step 55: retention baseline

```powershell
cd D:\Uday_Documents\AUGMIS_PLATFORM
python -m tools.verify_step55_retention_governance
python -m tools.verify_step55_retention_governance --with-db
```

The policy draft states that retention is not approved and no deletion or legal hold or WORM feature exists yet. A proposed *assessment* age of 365 days is not a live retention setting.

## Step 56: consolidated verification

```powershell
python -m tools.verify_phase5_release --mode quick
python -m tools.verify_phase5_release --mode full --evidence "C:\path\to\real-export.json"
```

Full mode executes existing regression verifiers, Python compile, `npx tsc --noEmit`, and `npm run build`, Alembic current/heads and Git status; it cannot prove the live negative API tests, which require an explicit manual acceptance checklist.

**Important:** The current codebase still has two publisher ownership mappings pending. The Step 54 screenshots confirm UI, not evidence download and hash integrity. Do not mark a full Phase 5 release or perform a Git freeze until all release gates are accepted and verified.

## Outstanding work requiring code/source review
- Complete legacy publisher ownership decisions (Step 53F).
- Confirm retention period/jurisdiction, legal hold and immutable archive policy; build enforcement only after approval (Step 55 follow-on).
- Review actual export logs, 403 negative checks and SHA digests, approve the acceptance checklist, then freeze (Step 56).

This release package has no code that deletes, archives, mutates, signs, commits, tags or pushes records; it is intentionally fail-closed and rollback-safe.
