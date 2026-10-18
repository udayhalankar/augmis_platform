"""C1-C3 development-only generic AAPS PostgreSQL runtime preparation.

Only invoked from the EXISTING authorized instance lifecycle. No new deployment
engine or browser-access endpoint. C1-C2 declarative schema generation is the
only supported schema mode; uploaded SQL is never executed.
"""
from __future__ import annotations
import os
import re
from sqlalchemy.orm import Session
from services.api.app.core.config import settings
from services.api.app.models.platform import Application, ApplicationInstance
from services.api.app.services.aaps_deployment_contract import assess_manifest, DeploymentContractError, route_contract
from services.api.app.services.aaps_declarative_schema import read_declarative_schema
from services.api.app.services.application_database_provisioning import reserve_application_database, ApplicationDatabaseError
from services.api.app.services.application_database_docker import (DockerDatabaseSettings, DatabaseInfrastructureError,
    PostgreSQLInfrastructure, provision_private_postgres)
from services.api.app.services.application_database_credentials import (
    RestrictedPostgresCredentials, provision_restricted_database_login, runtime_role)
from services.api.app.services.application_database_declared_schema import install_declared_schema, DeclaredSchemaError
from services.api.app.services.private_crud_runtime import CrudRuntimeLaunch, CrudRuntimeError, signing_material

_SHA=re.compile(r'sha256:[a-f0-9]{64}\Z')
_NET=re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}\Z')


def prepare_generic_private_runtime(*, db: Session, instance: ApplicationInstance, manifest: dict) -> CrudRuntimeLaunch:
    if str(settings.app_env).lower() not in {'dev','development'} or os.environ.get('AUGMIS_C1C_GENERIC_RUNTIME_ENABLED')!='1':
        raise CrudRuntimeError('C1C_GENERIC_RUNTIME_DISABLED')
    plan=assess_manifest(manifest)
    if not plan.requires_private_database or plan.database_engine!='postgresql' or plan.database_version!='15':
        raise CrudRuntimeError('C1C_GENERIC_DATABASE_UNSUPPORTED')
    if read_declarative_schema(manifest) is None or not route_contract(manifest):
        raise CrudRuntimeError('C1C_GENERIC_DECLARATION_REQUIRED')
    application=db.get(Application,instance.application_id)
    if application is None or manifest.get('metadata',{}).get('id') != application.app_key:
        raise CrudRuntimeError('C1C_GENERIC_APPLICATION_IDENTITY_MISMATCH')
    _,public=signing_material()
    relay_image=os.environ.get('AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID','')
    ingress=os.environ.get('AUGMIS_C1B_CRUD_INGRESS_NETWORK','')
    if not _SHA.fullmatch(relay_image):
        raise CrudRuntimeError('C1C_GENERIC_RELAY_IMAGE_NOT_PINNED')
    if not _NET.fullmatch(ingress) or ingress in {'bridge','host','none'}:
        raise CrudRuntimeError('C1C_GENERIC_INGRESS_NETWORK_INVALID')
    db_settings=DockerDatabaseSettings.from_platform(platform_environment=str(settings.app_env))
    db_settings.validate()
    try:
        resource=reserve_application_database(db=db,instance_id=instance.id,manifest=manifest)
        if resource is None:raise CrudRuntimeError('C1C_GENERIC_DATABASE_REQUIRED')
        db.commit()
        if resource.status in {'reserved','failed'}:
            resource=provision_private_postgres(db=db,instance_id=instance.id,settings=db_settings)
        if resource.status=='database_ready':
            resource=provision_restricted_database_login(db=db,instance_id=instance.id,settings=db_settings)
        if resource.status in {'credentials_ready','ready'}:
            resource=install_declared_schema(db=db,instance_id=instance.id,settings=db_settings)
        if resource.status!='ready':
            raise CrudRuntimeError('C1C_GENERIC_DATABASE_NOT_READY')
        driver=PostgreSQLInfrastructure(db_settings)
        driver.ensure_network(resource)
        driver.ensure_postgres(resource)
        driver.assert_database_ready(resource)
        restricted=RestrictedPostgresCredentials(driver)
        restricted._volume_read(resource)
        restricted.verify_runtime_login(resource,runtime_role(instance.id))
    except (DatabaseInfrastructureError,ApplicationDatabaseError,DeclaredSchemaError,DeploymentContractError) as exc:
        raise CrudRuntimeError(str(exc)) from exc
    return CrudRuntimeLaunch(network_name=resource.network_name,secret_volume=resource.runtime_secret_volume,
        public_key_file=public,ingress_network=ingress,relay_image_id=relay_image,
        environment={
            'APP_TENANT_ID':str(instance.tenant_id),
            'AUGMIS_RUNTIME_APPLICATION_ID':str(instance.application_id),
            'AUGMIS_RUNTIME_INSTANCE_ID':str(instance.id),
            'AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE':'/run/augmis/public-key.pem',
            'PGHOST':resource.database_host_alias,'PGPORT':'5432',
            'PGDATABASE':resource.database_name,'PGUSER':runtime_role(instance.id),
            'PGPASSWORD_FILE':'/run/secrets/db_password',
        },declared_routes=route_contract(manifest),service_port=plan.service_port,health_path=plan.health_path)
