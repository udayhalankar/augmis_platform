"""C1-B3: explicitly allowlisted reference-app PostgreSQL DDL/RLS installer.

Only called with a trusted ApplicationInstance after secured reservation + C1-B1/B2.
DDL is approved source controlled by AUGMIS, NEVER extracted/executed from untrusted AAPS.
No credentials in logs or SQL argv. No runtime DDL, no data migration.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models.platform import ApplicationInstance, ApplicationVersion
from services.api.app.models.runtime_control import ApplicationDatabaseResource
from services.api.app.services.application_database_docker import (
    DatabaseInfrastructureError, DockerDatabaseSettings, PostgreSQLInfrastructure,
    DockerCall, docker_call,
)
from services.api.app.services.application_database_credentials import (
    _validate_resource, runtime_role,
)

SCHEMA_REVISION = "augmis_crud_reference_v1"
_REFERENCE_MANIFEST_ID = "augmis-crud-reference"
_FLAG = "AUGMIS_C1B_DEV_SCHEMA_ENABLED"
_ALLOW_APP = "AUGMIS_C1B_CRUD_APPLICATION_ID"


def _allowlisted(instance: ApplicationInstance, manifest: dict, settings: DockerDatabaseSettings) -> None:
    settings.validate()  # Explicit dev opt-in AND pinned PostgreSQL 15 image.
    if os.environ.get(_FLAG) != "1":
        raise DatabaseInfrastructureError("C1B3_SCHEMA_INSTALL_DISABLED")
    try:
        allowed = uuid.UUID(os.environ.get(_ALLOW_APP, ""))
    except (TypeError, ValueError):
        raise DatabaseInfrastructureError("C1B3_APPLICATION_ALLOWLIST_REQUIRED") from None
    if instance.application_id != allowed or not isinstance(manifest, dict):
        raise DatabaseInfrastructureError("C1B3_APPLICATION_NOT_APPROVED")
    metadata = manifest.get("metadata") or {}
    if not isinstance(metadata, dict) or metadata.get("id") != _REFERENCE_MANIFEST_ID:
        raise DatabaseInfrastructureError("C1B3_REFERENCE_MANIFEST_MISMATCH")
    addon = (manifest.get("addons") or {}).get("database") or {}
    if addon.get("type") != "postgresql" or str(addon.get("version")) != "15":
        raise DatabaseInfrastructureError("C1B3_REFERENCE_DB_MISMATCH")


def reference_schema_sql(instance: ApplicationInstance) -> str:
    """Fixed, trusted schema: runtime user never owns tables or migrations."""
    role = runtime_role(instance.id)  # UUID-derived, strictly predictable SQL identifier.
    return f"""
BEGIN;
CREATE TABLE IF NOT EXISTS public.sample_records (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  name varchar(120) NOT NULL CHECK(length(trim(name)) > 0),
  category varchar(50) NOT NULL CHECK(length(trim(category)) > 0),
  quantity integer NOT NULL CHECK(quantity >= 0 AND quantity <= 10000000),
  unit_price numeric(12,2) NOT NULL CHECK(unit_price >= 0),
  notes varchar(1000) NOT NULL DEFAULT '',
  is_deleted boolean NOT NULL DEFAULT FALSE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sample_records_tenant_active
  ON public.sample_records (tenant_id, created_at DESC)
  WHERE is_deleted IS FALSE;
ALTER TABLE public.sample_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sample_records FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS c1b3_select ON public.sample_records;
CREATE POLICY c1b3_select ON public.sample_records FOR SELECT TO {role}
  USING (tenant_id = NULLIF(current_setting('augmis.tenant_id', TRUE), '')::uuid
         AND is_deleted IS FALSE);
DROP POLICY IF EXISTS c1b3_insert ON public.sample_records;
CREATE POLICY c1b3_insert ON public.sample_records FOR INSERT TO {role}
  WITH CHECK (tenant_id = NULLIF(current_setting('augmis.tenant_id', TRUE), '')::uuid
              AND is_deleted IS FALSE);
DROP POLICY IF EXISTS c1b3_update ON public.sample_records;
CREATE POLICY c1b3_update ON public.sample_records FOR UPDATE TO {role}
  USING (tenant_id = NULLIF(current_setting('augmis.tenant_id', TRUE), '')::uuid
         AND is_deleted IS FALSE)
  WITH CHECK (tenant_id = NULLIF(current_setting('augmis.tenant_id', TRUE), '')::uuid);
REVOKE ALL ON public.sample_records FROM PUBLIC;
REVOKE ALL ON public.sample_records FROM {role};
GRANT SELECT ON public.sample_records TO {role};
GRANT INSERT (id, tenant_id, name, category, quantity, unit_price, notes)
  ON public.sample_records TO {role};
GRANT UPDATE (name, category, quantity, unit_price, notes, is_deleted, updated_at)
  ON public.sample_records TO {role};
COMMIT;
"""


def _admin_sql(driver: PostgreSQLInfrastructure, row: ApplicationDatabaseResource, sql: str) -> str:
    return driver._docker(
        "exec", "-i", "--user", "postgres", row.container_name,
        "psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1",
        "-U", "postgres", "-d", row.database_name,
        payload=sql.encode("utf-8"),
    ).strip()


def _verify(driver: PostgreSQLInfrastructure, row: ApplicationDatabaseResource, instance: ApplicationInstance) -> None:
    role = runtime_role(instance.id)
    sql = f"""
SELECT CASE WHEN
  (SELECT c.relrowsecurity AND c.relforcerowsecurity
     FROM pg_class c WHERE c.oid=to_regclass('public.sample_records')) IS TRUE
  AND (SELECT count(*) FROM pg_policies
       WHERE schemaname='public' AND tablename='sample_records'
         AND policyname IN ('c1b3_select','c1b3_insert','c1b3_update')) = 3
  AND has_table_privilege('{role}', 'public.sample_records','SELECT')
  AND has_column_privilege('{role}', 'public.sample_records','id','INSERT')
  AND has_column_privilege('{role}', 'public.sample_records','is_deleted','UPDATE')
  AND NOT has_table_privilege('{role}', 'public.sample_records','DELETE')
  AND NOT has_schema_privilege('{role}', 'public','CREATE')
  THEN '1' ELSE '0' END;
"""
    if _admin_sql(driver, row, sql) != "1":
        raise DatabaseInfrastructureError("C1B3_SCHEMA_RLS_PREFLIGHT_FAILED")


def install_reference_schema(
    *, db: Session, instance_id: uuid.UUID, settings: DockerDatabaseSettings,
    call: DockerCall = docker_call, recover_stale: bool = False,
) -> ApplicationDatabaseResource:
    """One instance at a time. DB resources retained and retried on failure.

    C1-B3 does not launch the app or grant browser access. Caller must complete
    B4/C1 private-network ingress and signed write-path before marking deployable.
    """
    instance = db.scalar(select(ApplicationInstance).where(
        ApplicationInstance.id == instance_id).with_for_update())
    if instance is None:
        raise DatabaseInfrastructureError("C1B3_INSTANCE_NOT_FOUND")
    version = db.get(ApplicationVersion, instance.active_version_id)
    if version is None:
        raise DatabaseInfrastructureError("C1B3_VERSION_NOT_FOUND")
    _allowlisted(instance, version.manifest, settings)
    row = db.scalar(select(ApplicationDatabaseResource).where(
        ApplicationDatabaseResource.instance_id == instance.id).with_for_update())
    _validate_resource(instance, row)
    if row.status == "schema_setup":
        last = getattr(row, "updated_at", None)
        stale = (last is not None and last.tzinfo is not None and
                 datetime.now(timezone.utc) - last >= timedelta(minutes=15))
        if not (recover_stale and stale):
            raise DatabaseInfrastructureError("C1B3_SCHEMA_SETUP_ALREADY_IN_PROGRESS")
    elif row.status not in {"credentials_ready", "ready"}:
        raise DatabaseInfrastructureError("C1B3_CREDENTIALS_NOT_READY")
    if row.database_image_id != settings.image_id:
        raise DatabaseInfrastructureError("C1B3_DATABASE_IMAGE_MISMATCH")

    # Verify existing, pinned, private DB *before* trusting an existing ready state.
    driver = PostgreSQLInfrastructure(settings, call=call)
    driver.ensure_network(row)
    driver.ensure_postgres(row)
    driver.assert_database_ready(row)
    if row.status == "ready":
        if row.migration_revision != SCHEMA_REVISION:
            raise DatabaseInfrastructureError("C1B3_SCHEMA_REVISION_DRIFT")
        _verify(driver, row, instance)
        return row

    row.status = "schema_setup"
    row.error_code = None
    db.commit()
    try:
        _admin_sql(driver, row, reference_schema_sql(instance))
        _verify(driver, row, instance)
    except DatabaseInfrastructureError as exc:
        row.status = "credentials_ready"  # DDL transaction rolls back; safe explicit retry.
        row.error_code = exc.code
        db.commit()
        raise
    except Exception as exc:
        row.status = "credentials_ready"
        row.error_code = "C1B3_SCHEMA_SETUP_FAILED"
        db.commit()
        raise DatabaseInfrastructureError("C1B3_SCHEMA_SETUP_FAILED") from exc
    row.migration_revision = SCHEMA_REVISION
    row.status = "ready"
    row.ready_at = datetime.now(timezone.utc)
    row.error_code = None
    db.commit()
    return row
