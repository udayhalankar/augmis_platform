# AUGMIS + Techtango B4 Pass 2 — guarded source update

**Scope:** independently signed source-tenant admin proof, one-time verification,
allowlisted immutable metadata snapshot staging. Does **not** publish, deploy,
launch, or replicate Techtango applications/data. Does **not** remove B3 production fail-closed gates.

## 0. Prerequisites

- Stop AUGMIS and Techtango API workers for installation; preserve Git working trees.
- Backup AUGMIS PostgreSQL **before** applying Alembic. Do not use production first.
- Python requirements include PyJWT with cryptography; Node.js supports `crypto.sign` Ed25519.
- Existing Alembic revision `b3b4tenant261012` has been applied and is the migration parent.
- Run `git status --short` in both repos. **Do not discard existing uncommitted work.**

## 1. Install targeted source edits (PowerShell)

Unzip this patch package outside both repos, then from the unzipped directory:

```powershell
python .\apply_b4_pass2.py --check --augmis "D:\AUGMIS_PLATFORM" --techtango "D:\TECHTANGO"
python .\apply_b4_pass2.py --apply --augmis "D:\AUGMIS_PLATFORM" --techtango "D:\TECHTANGO"
```

The patch also makes the existing metadata validator accept digit-first application slugs such as `21augdashboard`, while keeping field names strictly validated. The installer aborts on unexpected anchor changes or existing B4 code, and backs up modified files under `backups/` adjacent to the installer.

## 2. Generate independent Ed25519 keys, one-time

Generate using the AUGMIS Python environment (cryptography installed). Save the **private key only on the Techtango server**, and the public key on the AUGMIS API host:

```powershell
@'
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from pathlib import Path
folder = Path.home() / "augmis-b4-keys"  # OUTSIDE either Git repository
folder.mkdir(mode=0o700, exist_ok=True)
private = Ed25519PrivateKey.generate()
(folder / "techtango-b4-private.pem").write_bytes(private.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
(folder / "techtango-b4-public.pem").write_bytes(private.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
print("Key pair created in:", folder, "(protect the private PEM)")
'@ | python
```

On Techtango server configure `AUGMIS_BRIDGE_SIGNING_KEY_FILE` to the absolute private PEM path.
On AUGMIS API server configure `AUGMIS_TECHTANGO_VERIFY_KEY_FILE` to the absolute public PEM path.
Use restricted filesystem permissions; never commit either file, do not paste the private PEM into chat or logs.
Both services must have clocks synced (NTP). HTTPS must be used between browser/service endpoints. Restart AUGMIS when replacing the public key; the verifier caches its contents.

## 3. Verify code and migrate development DB

```powershell
cd D:\AUGMIS_PLATFORM
python -m compileall -q services\api\app\routes\techtango_integration.py services\api\app\models\techtango_integration.py services\api\app\services\techtango_bridge_service.py
python -m pytest -q tools\test_b4_pass2.py tools\test_b3b4_security.py
alembic current   # confirm your expected existing revision before applying
alembic heads     # expected new head: b4pass2261012
alembic upgrade head

cd D:\TECHTANGO
node --check server\services\augmisBridge.js
node --check server\routes\aiappbuilder.js
```

Confirm existing test suites and runtime tests; do not promote production until B3 release gate and remaining integrations are independently accepted.

## 4. Test bridge API — first verification, then stage

1. On AUGMIS, authenticated **platform operator**, query `GET /api/v1/integrations/techtango/tenant-links`. Locate the existing **pending** Tenant 1 → ABC Engineering Secure link; record its `id` (distinct from tenant UUID).
2. In Techtango, sign in as a **DB-active admin of Tenant 1**. `POST /<your-aiappbuilder-mount>/augmis/tenant-proof` with JSON `{"linkId":"<AUGMIS LINK UUID>","augmisTenantId":"b6e8ccbc-aefb-4a4d-8955-1434dc1213d7"}`. Capture the returned `proof` string; it expires in 120 seconds.
3. On AUGMIS, as platform operator, `POST /api/v1/integrations/techtango/tenant-links/<AUGMIS LINK UUID>/verify` with `{"proof":"<proof from Techtango>"}`. Expected 200 `verified`. Replay/wrong tenant/altered proof must fail.
4. In Techtango, `POST /<your-aiappbuilder-mount>/augmis/stage-proof` with `{"linkId":"...","augmisTenantId":"...","appSlug":"21augdashboard"}` (use the actual DB `app_slug`, including case). Response contains `proof`, `sha256`.
5. On AUGMIS, `POST /api/v1/integrations/techtango/tenant-links/<AUGMIS LINK UUID>/snapshots` with `{"proof":"<new stage proof>"}`. Expected 201 `staged_metadata_only`. `GET` same URL lists all staged immutable snapshots.
6. Repeat with the *same* stage proof and with a *fresh proof for unchanged app metadata*: both must fail with 409. Tampered JWT, other tenant, expired proof, or extra fields must fail.

**Note:** Your actual Techtango mount URL is configured in its main Express server file and was not part of this snapshot. Do not assume the route's mount prefix is `/api/aiappbuilder` until confirmed there.

## Security / semantics

- Techtango checks `users.id`, `users.tenant_id`, `is_active`, and a DB-admin role before signing. JWT roles alone are not authorization. Deployment access is **not** implied by verification.
- AUGMIS verifies EdDSA signature, issuer, audience, timestamps, purpose, link ID, both tenant identities; its existing platform operator permission is required.
- PostgreSQL nonce primary key enforces cross-worker one-time proof use. Unique `(link_id, app_slug, sha256)` enforces immutable duplicate prevention.
- Staging only includes validated field metadata; raw records/SQL/credentials are excluded. Each subsequent metadata revision can be staged under a **new digest**, retaining previous snapshots.
- This proves a currently authenticated source-tenant administrator authorized a mapping; it does not establish legal/business ownership of a company.
- Full AAPS export + dependencies, Marketplace publisher workflow, entitlements, sandbox/isolated runtime security and B3 production gate remain **open**.
