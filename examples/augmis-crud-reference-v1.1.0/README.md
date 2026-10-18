# AUGMIS CRUD Reference v1.1.0 — not ready for standalone upload

C1-B3 staged source with runtime DDL removed, PostgreSQL RLS session context,
private secret-file config and signed request verification. This image expects
C1-B4 private ingress, trusted identity injection, mounted public verifier key,
and the authorized AUGMIS gateway signer before it can serve CRUD endpoints.
Do NOT upload/deploy in AUGMIS until C1-B4 is complete.

Required trusted runtime environment (not browser supplied): PGHOST, PGDATABASE,
PGUSER, PGPASSWORD_FILE, APP_TENANT_ID, AUGMIS_RUNTIME_INSTANCE_ID,
AUGMIS_RUNTIME_APPLICATION_ID, AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE.

AUGMIS gateway will sign JWT requests with issuer augmis.control-plane,
audience augmis.runtime:<instance uuid>, typ augmis.runtime.crud.v1,
tenantId, applicationId, instanceId, method, path, bodySha256 and scope.
The server refuses direct or unsigned data reads/writes.
