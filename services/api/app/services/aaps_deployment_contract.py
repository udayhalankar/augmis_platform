"""C1-C supported-AAPS compatibility gate (no I/O, no Docker).

This is an explicit capability contract, not a permissive guess from a Dockerfile.
Unsupported dependencies MUST fail before the ordinary host-port launcher is used.
The existing tested C1-B4 private CRUD deployment remains unchanged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class DeploymentContractError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class DeploymentContract:
    build_type: str
    service_name: str
    service_port: int
    health_path: str
    requires_private_database: bool
    database_engine: str | None
    database_version: str | None
    authentication: str
    has_migration_contract: bool
    has_route_contract: bool


_SEGMENT = re.compile(r"/[a-zA-Z0-9/_-]{0,120}\Z")
_ROUTE = re.compile(r"/api(?:/[a-z][a-z0-9-]{0,60}|/\{id:uuid\}){1,4}\Z")
_SQLPATH = re.compile(r"db/migrations/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,120}\.sql\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})


def route_contract(manifest: dict) -> tuple[tuple[str, tuple[str, ...]], ...]:
    gateway = manifest.get("gateway")
    if gateway is None:
        return ()
    if not isinstance(gateway, dict) or set(gateway) != {"routes"}:
        raise DeploymentContractError("AAPS_GATEWAY_INVALID", "Expected only gateway.routes")
    entries = gateway["routes"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise DeploymentContractError("AAPS_GATEWAY_ROUTES_INVALID", "Provide 1–32 API routes")
    result = []
    seen = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "methods"}:
            raise DeploymentContractError("AAPS_GATEWAY_ROUTE_INVALID", "Each route needs path and methods")
        path, methods = item["path"], item["methods"]
        if not isinstance(path, str) or not _ROUTE.fullmatch(path) or "//" in path:
            raise DeploymentContractError("AAPS_GATEWAY_ROUTE_PATH_INVALID", "Invalid canonical API route")
        if (not isinstance(methods, list) or not 1 <= len(methods) <= 5
                or any(not isinstance(m, str) or m not in _METHODS for m in methods)
                or len(set(methods)) != len(methods)):
            raise DeploymentContractError("AAPS_GATEWAY_METHOD_INVALID", "Only explicit unique API methods are supported")
        if path in seen:
            raise DeploymentContractError("AAPS_GATEWAY_ROUTE_DUPLICATE", "Duplicate API route")
        seen.add(path)
        result.append((path, tuple(methods)))
    return tuple(result)


def migration_contract(manifest: dict) -> tuple[tuple[str, str], ...]:
    database = (manifest.get("addons") or {}).get("database") or {}
    entries = database.get("migrations")
    if entries is None:
        return ()
    if not isinstance(entries, list) or not 1 <= len(entries) <= 24:
        raise DeploymentContractError("AAPS_MIGRATIONS_INVALID", "Provide 1–24 versioned SQL files")
    result = []
    seen = set()
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise DeploymentContractError("AAPS_MIGRATION_INVALID", "Each migration needs path and sha256")
        path, checksum = item["path"], item["sha256"]
        if not isinstance(path, str) or not _SQLPATH.fullmatch(path) or '..' in path:
            raise DeploymentContractError("AAPS_MIGRATION_PATH_INVALID", "Invalid migration file path")
        if not isinstance(checksum, str) or not _SHA.fullmatch(checksum):
            raise DeploymentContractError("AAPS_MIGRATION_DIGEST_INVALID", "SHA-256 digest required")
        if path in seen:
            raise DeploymentContractError("AAPS_MIGRATION_DUPLICATE", "Duplicate migration file")
        seen.add(path)
        result.append((path, checksum))
    if [path for path,_ in result] != sorted(path for path,_ in result):
        raise DeploymentContractError("AAPS_MIGRATION_ORDER_INVALID", "Migration paths must sort in execution order")
    return tuple(result)


def assess_manifest(manifest: dict[str, Any]) -> DeploymentContract:
    if not isinstance(manifest, dict):
        raise DeploymentContractError("AAPS_MANIFEST_INVALID", "Manifest must be an object")
    runtime = manifest.get("runtime") or {}
    if runtime.get("deploymentMode") != "dedicated" or runtime.get("buildType") != "dockerfile":
        raise DeploymentContractError("AAPS_RUNTIME_UNSUPPORTED", "Dedicated Dockerfile runtime required")
    services = manifest.get("services") or {}
    if not isinstance(services, dict):
        raise DeploymentContractError("AAPS_SERVICE_INVALID", "Services must be a map")
    public = [(k,v) for k,v in services.items() if isinstance(v,dict) and v.get("public") is True]
    if len(public) != 1 or len(services) != 1:
        raise DeploymentContractError("AAPS_SERVICE_TOPOLOGY_UNSUPPORTED", "Exactly one public HTTP service is currently supported")
    name, service = public[0]
    port = service.get("port")
    health = (service.get("health") or {}).get("path")
    if type(port) is not int or not 1 <= port <= 65535:
        raise DeploymentContractError("AAPS_PORT_INVALID", "Valid service TCP port required")
    if (not isinstance(health,str) or not health.startswith('/') or not _SEGMENT.fullmatch(health)
            or '//' in health or '..' in health):
        raise DeploymentContractError("AAPS_HEALTH_PATH_INVALID", "Canonical HTTP health path required")
    auth = manifest.get("authentication") or {}
    authentication = auth.get("type", "none")
    addons = manifest.get("addons") or {}
    database = addons.get("database") if isinstance(addons,dict) else None
    if database:
        if database.get("type") != "postgresql" or str(database.get("version")) != "15":
            raise DeploymentContractError("AAPS_DATABASE_UNSUPPORTED", "Only PostgreSQL 15 is available")
        if authentication != 'augmis_oidc' or auth.get('required') is not True:
            raise DeploymentContractError("AAPS_AUTH_REQUIRED", "Database-backed applications require AUGMIS authentication")
    migrations = migration_contract(manifest)
    from services.api.app.services.aaps_declarative_schema import read_declarative_schema, SchemaContractError
    try:
        declared = read_declarative_schema(manifest)
    except SchemaContractError as exc:
        raise DeploymentContractError(exc.code, "Invalid declarative PostgreSQL schema") from exc
    if migrations and declared:
        raise DeploymentContractError("C1C_SCHEMA_MODE_CONFLICT", "Choose declarative schema or SQL migration descriptors, never both")
    routes = route_contract(manifest)
    return DeploymentContract(runtime['buildType'],name,port,health,bool(database),
                              database.get('type') if database else None,
                              str(database.get('version')) if database else None,
                              authentication,bool(migrations or declared),bool(routes))


def fail_closed_if_unimplemented(manifest: dict, *, legacy_crud: bool) -> None:
    """Do not accidentally run DB apps on ordinary published-host-port Docker path.

    C1-C requires approved schema execution, generic gateway assertions and relay
    before lifting this guard; the legacy verified CRUD path remains permitted.
    """
    plan = assess_manifest(manifest)
    if not plan.requires_private_database or legacy_crud:
        return
    if not plan.has_migration_contract:
        raise DeploymentContractError("C1C_SCHEMA_DECLARATION_REQUIRED", "AAPS database.migrations contract missing; no automatic SQL execution")
    if not plan.has_route_contract:
        raise DeploymentContractError("C1C_GATEWAY_ROUTE_CONTRACT_REQUIRED", "AAPS gateway.routes contract missing")
    # C1-C3: explicitly enabled only in development and only for bounded,
    # declarative schema packages. SQL-file descriptors remain review-only.
    from services.api.app.services.aaps_declarative_schema import read_declarative_schema
    import os
    from services.api.app.core.config import settings
    if (os.environ.get("AUGMIS_C1C_GENERIC_RUNTIME_ENABLED") == "1"
            and str(settings.app_env).lower() in {"dev", "development"}
            and read_declarative_schema(manifest) is not None):
        return
    raise DeploymentContractError("C1C_PRIVATE_DB_ADAPTER_PENDING", "Private database-backed generic runtime not enabled; ordinary Docker fallback blocked")
