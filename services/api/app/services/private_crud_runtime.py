"""C1-B4 explicitly allowlisted, development-only private CRUD launch.

The caller is the EXISTING authenticated instance lifecycle; this module does
not authorize tenants, publish versions or create subscriptions.
"""
from __future__ import annotations
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy.orm import Session
from services.api.app.core.config import settings
from services.api.app.services.r05_secret_files import read_production_signing_key, SecretMaterialError
from services.api.app.models.platform import ApplicationInstance
from services.api.app.services.application_database_provisioning import (
    reserve_application_database, ApplicationDatabaseError,
)
from services.api.app.services.application_database_docker import (
    DockerDatabaseSettings, DatabaseInfrastructureError, PostgreSQLInfrastructure, provision_private_postgres,
)
from services.api.app.services.application_database_credentials import (
    RestrictedPostgresCredentials, provision_restricted_database_login, runtime_role,
)
from services.api.app.services.application_database_schema import install_reference_schema

class CrudRuntimeError(ValueError):
    """Safe error code without credentials."""

@dataclass(frozen=True)
class CrudRuntimeLaunch:
    network_name: str
    secret_volume: str
    public_key_file: Path
    ingress_network: str
    relay_image_id: str
    environment: dict[str, str]
    declared_routes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    service_port: int = 8080
    health_path: str = "/health"


def _expected_application() -> uuid.UUID:
    raw = os.environ.get('AUGMIS_C1B_CRUD_APPLICATION_ID', '')
    try:
        ident = uuid.UUID(raw)
        if str(ident) == raw:
            return ident
    except (ValueError, TypeError):
        pass
    raise CrudRuntimeError('C1B4_APPLICATION_ALLOWLIST_REQUIRED')


def signing_private_key_bytes(private: Path) -> bytes:
    if str(settings.app_env).strip().lower() in ("production", "prod"):
        try:
            return read_production_signing_key(private)
        except SecretMaterialError:
            raise CrudRuntimeError("R05_SIGNING_KEY_FILE_UNSAFE") from None
    return private.read_bytes()


def signing_material() -> tuple[Path, Path]:
    files = [os.environ.get('AUGMIS_C1B_CRUD_SIGNING_PRIVATE_KEY_FILE', ''),
             os.environ.get('AUGMIS_C1B_CRUD_SIGNING_PUBLIC_KEY_FILE', '')]
    if not all(files):
        raise CrudRuntimeError('C1B4_SIGNING_PAIR_REQUIRED')
    private, public = tuple(Path(item) for item in files)
    if any(not p.is_absolute() or not p.is_file() or p.is_symlink() for p in (private, public)):
        raise CrudRuntimeError('C1B4_SIGNING_PAIR_INVALID')
    try:
        key = serialization.load_pem_private_key(signing_private_key_bytes(private), password=None)
        pub = serialization.load_pem_public_key(public.read_bytes())
    except (OSError, TypeError, ValueError) as exc:
        raise CrudRuntimeError('C1B4_SIGNING_PAIR_INVALID') from exc
    if not isinstance(key, Ed25519PrivateKey) or not isinstance(pub, Ed25519PublicKey):
        raise CrudRuntimeError('C1B4_SIGNING_ALGORITHM_INVALID')
    if key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw) != pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw):
        raise CrudRuntimeError('C1B4_SIGNING_PAIR_MISMATCH')
    return private, public


def enabled_for(instance: ApplicationInstance, manifest: dict) -> bool:
    if (manifest.get('metadata') or {}).get('id') != 'augmis-crud-reference':
        return False
    if (str(settings.app_env).lower() not in {'dev', 'development'} or
            os.environ.get('AUGMIS_C1B_CRUD_PRIVATE_RUNTIME_ENABLED') != '1'):
        raise CrudRuntimeError('C1B4_PRIVATE_RUNTIME_DISABLED')
    if instance.application_id != _expected_application():
        raise CrudRuntimeError('C1B4_APPLICATION_NOT_ALLOWED')
    return True


def prepare_private_crud_runtime(*, db: Session, instance: ApplicationInstance,
                                  manifest: dict) -> CrudRuntimeLaunch | None:
    if not enabled_for(instance, manifest):
        return None
    _, public = signing_material()
    ingress = os.environ.get('AUGMIS_C1B_CRUD_INGRESS_NETWORK', '')
    relay_image = os.environ.get('AUGMIS_C1B_CRUD_RELAY_IMAGE_ID', '')
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', ingress) or
            ingress in {'bridge', 'host', 'none'}):
        raise CrudRuntimeError('C1B4_INGRESS_NETWORK_INVALID')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', relay_image):
        raise CrudRuntimeError('C1B4_RELAY_IMAGE_NOT_PINNED')
    if ((manifest.get('addons') or {}).get('database') or {}).get('type') != 'postgresql':
        raise CrudRuntimeError('C1B4_POSTGRES_REQUIRED')
    if ((manifest.get('services') or {}).get('web') or {}).get('port') != 8080:
        raise CrudRuntimeError('C1B4_SERVICE_PORT_INVALID')
    db_settings = DockerDatabaseSettings.from_platform(platform_environment=str(settings.app_env))
    db_settings.validate()
    try:
        resource = reserve_application_database(db=db, instance_id=instance.id, manifest=manifest)
        if resource is None:
            raise CrudRuntimeError('C1B4_DATABASE_REQUIRED')
        db.commit()
        if resource.status in {'reserved', 'failed'}:
            resource = provision_private_postgres(db=db, instance_id=instance.id, settings=db_settings)
        if resource.status == 'database_ready':
            resource = provision_restricted_database_login(db=db, instance_id=instance.id, settings=db_settings)
        if resource.status in {'credentials_ready', 'ready'}:
            resource = install_reference_schema(db=db, instance_id=instance.id, settings=db_settings)
        if resource.status != 'ready':
            raise CrudRuntimeError('C1B4_DATABASE_NOT_READY')
        driver = PostgreSQLInfrastructure(db_settings)
        driver.ensure_network(resource)
        driver.ensure_postgres(resource)
        driver.assert_database_ready(resource)
        restricted = RestrictedPostgresCredentials(driver)
        restricted._volume_read(resource)
        restricted.verify_runtime_login(resource, runtime_role(instance.id))
    except (ApplicationDatabaseError, DatabaseInfrastructureError) as exc:
        raise CrudRuntimeError(str(exc)) from exc
    return CrudRuntimeLaunch(
        network_name=resource.network_name,
        secret_volume=resource.runtime_secret_volume,
        public_key_file=public, ingress_network=ingress, relay_image_id=relay_image,
        environment={
            'APP_TENANT_ID': str(instance.tenant_id),
            'AUGMIS_RUNTIME_APPLICATION_ID': str(instance.application_id),
            'AUGMIS_RUNTIME_INSTANCE_ID': str(instance.id),
            'AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE': '/run/augmis/public-key.pem',
            'PGHOST': resource.database_host_alias,
            'PGPORT': '5432', 'PGDATABASE': resource.database_name,
            'PGUSER': runtime_role(instance.id),
            'PGPASSWORD_FILE': '/run/secrets/db_password',
        })
