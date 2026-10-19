"""C1-D2 development-only *executable* qualification probe.

Runs a fresh, bounded, disposable PostgreSQL 15 + app + restricted relay
against an EXACT immutable image. No tenant or application records are touched.
No publisher-controlled SQL is executed. All secrets stay outside the repo.
This is an internal operator tool, NOT an HTTP route and NOT a release gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.api.app.services.aaps_declarative_schema import (
    read_declarative_schema, schema_sql, verification_sql,
)
from services.api.app.services.aaps_deployment_contract import (
    assess_manifest, route_contract,
)

_SHA = re.compile(r"sha256:[a-f0-9]{64}\Z")
_LIMIT = 180


class QualificationFailure(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _cmd(*args: str, timeout: int = 35, stdin: bytes | None = None, check: bool = True) -> str:
    try:
        p = subprocess.run(args, input=stdin, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationFailure("C1D2_DOCKER_COMMAND_UNAVAILABLE") from exc
    if check and p.returncode:
        # Never expose Docker stderr; it can contain sensitive image/environment data.
        raise QualificationFailure("C1D2_DOCKER_COMMAND_FAILED")
    return p.stdout.decode("utf-8", errors="replace").strip()


def _file(path: Path, content: bytes, *, container_readable: bool = False):
    path.write_bytes(content)
    if os.name != "nt":
        # Folder is 0700 on host; app runs as non-root and needs its own mount.
        path.chmod(0o644 if container_readable else 0o600)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _http(url: str, token: str | None = None) -> int:
    headers = {"Cache-Control": "no-store"}
    if token is not None:
        headers["X-Augmis-Runtime-Assertion"] = token
    try:
        with urlopen(Request(url, headers=headers, method="GET"), timeout=8) as r:
            r.read(131072)
            return r.status
    except HTTPError as exc:
        exc.close()
        return exc.code
    except (URLError, OSError):
        return 0


def _jwt(private: Ed25519PrivateKey, *, tenant: uuid.UUID, app: uuid.UUID,
         instance: uuid.UUID, path: str, foreign_tenant: bool = False) -> str:
    now = int(time.time())
    claims = {
        "iss": "augmis.control-plane", "aud": f"augmis.runtime:{instance}",
        "sub": str(uuid.uuid4()), "iat": now, "nbf": now, "exp": now + 20,
        "jti": str(uuid.uuid4()), "typ": "augmis.runtime.crud.v1",
        "tenantId": str(uuid.uuid4()) if foreign_tenant else str(tenant),
        "applicationId": str(app), "instanceId": str(instance),
        "method": "GET", "path": path,
        "querySha256": hashlib.sha256(b"").hexdigest(),
        "bodySha256": hashlib.sha256(b"").hexdigest(),
        "scope": ["records.read"],
    }
    return jwt.encode(claims, private, algorithm="EdDSA", headers={"typ": "JWT"})


def _port(name: str) -> int:
    result = _cmd("docker", "port", name, "18080/tcp")
    lines = [l.strip() for l in result.splitlines()]
    ipv4 = [l for l in lines if l.startswith("127.0.0.1:")]
    if len(ipv4) != 1:
        raise QualificationFailure("C1D2_RELAY_NOT_LOOPBACK_ONLY")
    try:
        return int(ipv4[0].rsplit(":", 1)[1])
    except ValueError as exc:
        raise QualificationFailure("C1D2_RELAY_PORT_INVALID") from exc


def _inspect_network(name: str) -> bool:
    raw = _cmd("docker", "network", "inspect", name,
               "--format", "{{.Internal}}")
    if raw not in {"true", "false"}:
        raise QualificationFailure("C1D2_NETWORK_POLICY_UNKNOWN")
    return raw == "true"


def _inspect_ports(name: str) -> bool:
    raw = _cmd("docker", "inspect", name,
               "--format", "{{json .NetworkSettings.Ports}}")
    try:
        ports = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return ports is None or (isinstance(ports, dict) and all(v is None for v in ports.values()))


@dataclass(frozen=True)
class RuntimeImages:
    postgres_image_id: str
    relay_image_id: str
    ingress_network: str

    def validate(self):
        if not _SHA.fullmatch(self.postgres_image_id) or not _SHA.fullmatch(self.relay_image_id):
            raise QualificationFailure("C1D2_IMAGE_ID_INVALID")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", self.ingress_network):
            raise QualificationFailure("C1D2_INGRESS_NETWORK_INVALID")
        if self.ingress_network in {"host", "bridge", "none"}:
            raise QualificationFailure("C1D2_INGRESS_NETWORK_INVALID")


class DisposableQualification:
    def __init__(self, *, manifest: dict, image_id: str, images: RuntimeImages):
        if not isinstance(image_id, str) or not _SHA.fullmatch(image_id):
            raise QualificationFailure("C1D2_IMMUTABLE_APP_IMAGE_REQUIRED")
        images.validate()
        plan = assess_manifest(manifest)
        schema = read_declarative_schema(manifest)
        if not plan.requires_private_database or schema is None or not plan.has_route_contract:
            raise QualificationFailure("C1D2_UNSUPPORTED_SMOKE_CONTRACT")
        get_routes = [r for r, methods in route_contract(manifest)
                      if "GET" in methods and "{" not in r]
        if not get_routes:
            raise QualificationFailure("C1D2_READONLY_SMOKE_ROUTE_REQUIRED")
        self.manifest, self.image_id, self.images = manifest, image_id, images
        self.schema, self.plan, self.get_path = schema, plan, get_routes[0]

    def run(self) -> dict[str, bool]:
        """Creates only uniquely named test resources. Cleanup always attempted."""
        self.images.validate()
        tag = uuid.uuid4().hex[:16]
        db_name = f"augmis-q-{tag}-db"
        app_name = f"augmis-q-{tag}-app"
        relay_name = f"augmis-q-{tag}-relay"
        private_net = f"augmis-q-{tag}-net"
        tenant, application, instance = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        runtime_role = "augmis_qualifier"
        db_password = secrets.token_urlsafe(36)
        admin_password = secrets.token_urlsafe(36)
        private = Ed25519PrivateKey.generate()
        public_pem = private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        checked = {k: False for k in (
            'image_identity', 'database_isolation', 'schema_rls',
            'internal_health', 'gateway_auth', 'gateway_rejection',
        )}
        created: list[tuple[str, str]] = []
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="augmis-qualification-") as folder:
            secrets_dir = Path(folder)
            if os.name != "nt":
                secrets_dir.chmod(0o700)
            admin_path, runtime_path, public_path = (
                secrets_dir / "pg_admin", secrets_dir / "db_password", secrets_dir / "public.pem")
            _file(admin_path, admin_password.encode())
            _file(runtime_path, db_password.encode(), container_readable=True)
            _file(public_path, public_pem, container_readable=True)

            def docker(*args: str, timeout: int = 35, stdin: bytes | None = None):
                return _cmd('docker', *args, timeout=timeout, stdin=stdin)

            def psql(sql: str):
                return docker('exec', '-i', '--user', 'postgres', db_name,
                              'psql', '-X', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
                              '-U', 'postgres', '-d', 'augmis_app',
                              timeout=45, stdin=sql.encode('utf-8'))

            try:
                if _inspect_network(self.images.ingress_network):
                    raise QualificationFailure("C1D2_INGRESS_IS_INTERNAL")
                for image in (self.image_id, self.images.postgres_image_id,
                              self.images.relay_image_id):
                    reported = docker('image', 'inspect', image, '--format', '{{.Id}}')
                    if reported != image:
                        raise QualificationFailure('C1D2_IMAGE_ID_DRIFT')
                for image in (self.image_id, self.images.relay_image_id):
                    user = docker('image', 'inspect', image, '--format', '{{.Config.User}}').strip().lower()
                    if not user or user in {'root', '0', '0:0', 'root:root'}:
                        raise QualificationFailure('C1D2_IMAGE_MUST_BE_NONROOT')
                checked['image_identity'] = True
                created.append(('network', private_net))
                docker('network', 'create', '--internal', '--driver', 'bridge',
                       '--label', 'augmis.qualifier=true', private_net)
                created.append(('container', db_name))
                docker('run', '-d', '--rm', '--name', db_name, '--network', private_net,
                       '--network-alias', db_name, '--label', 'augmis.qualifier=true',
                       '--memory', '512m', '--pids-limit', '128',
                       '--mount', f'type=bind,source={admin_path},target=/run/secrets/admin,readonly',
                       '-e', 'POSTGRES_PASSWORD_FILE=/run/secrets/admin',
                       '-e', 'POSTGRES_DB=augmis_app', self.images.postgres_image_id)
                while time.monotonic() - start < _LIMIT:
                    ok = subprocess.run(['docker', 'exec', db_name, 'pg_isready',
                        '-U', 'postgres', '-d', 'augmis_app'], capture_output=True, timeout=8)
                    if ok.returncode == 0:
                        break
                    time.sleep(2)
                else:
                    raise QualificationFailure('C1D2_POSTGRES_TIMEOUT')
                create_role = (f'CREATE ROLE "{runtime_role}" LOGIN PASSWORD '
                               f'{_quote(db_password)} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;'
                               f' GRANT CONNECT ON DATABASE augmis_app TO "{runtime_role}";'
                               f' GRANT USAGE ON SCHEMA public TO "{runtime_role}";')
                psql(create_role)
                psql(schema_sql(self.schema, runtime_role=runtime_role))
                if psql(verification_sql(self.schema, runtime_role=runtime_role)) != '1':
                    raise QualificationFailure('C1D2_RLS_SCHEMA_VERIFICATION_FAILED')
                checked['schema_rls'] = True
                env = {
                    'NODE_ENV': 'production',
                    'APP_TENANT_ID': str(tenant),
                    'AUGMIS_RUNTIME_APPLICATION_ID': str(application),
                    'AUGMIS_RUNTIME_INSTANCE_ID': str(instance),
                    'AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE': '/run/augmis/public-key.pem',
                    'PGHOST': db_name, 'PGPORT': '5432', 'PGDATABASE': 'augmis_app',
                    'PGUSER': runtime_role, 'PGPASSWORD_FILE': '/run/secrets/db_password',
                }
                params = ['run', '-d', '--rm', '--name', app_name,
                          '--network', private_net, '--network-alias', app_name,
                          '--label', 'augmis.qualifier=true',
                          '--memory', '512m', '--pids-limit', '128',
                          '--security-opt', 'no-new-privileges', '--cap-drop', 'ALL',
                          '--mount', f'type=bind,source={runtime_path},target=/run/secrets/db_password,readonly',
                          '--mount', f'type=bind,source={public_path},target=/run/augmis/public-key.pem,readonly']
                for key, value in env.items():
                    params += ['-e', f'{key}={value}']
                created.append(('container', app_name))
                docker(*params, self.image_id)
                if not _inspect_ports(db_name) or not _inspect_ports(app_name):
                    raise QualificationFailure('C1D2_PRIVATE_PORT_EXPOSED')
                checked['database_isolation'] = _inspect_network(private_net)
                relay_params = ['run', '-d', '--rm', '--name', relay_name,
                                '--network', self.images.ingress_network,
                                '--label', 'augmis.qualifier=true',
                                '--memory', '192m', '--pids-limit', '96',
                                '--security-opt', 'no-new-privileges', '--cap-drop', 'ALL',
                                '-p', '127.0.0.1::18080',
                                '-e', f'AUGMIS_RELAY_UPSTREAM={app_name}',
                                '-e', f'AUGMIS_RELAY_UPSTREAM_PORT={self.plan.service_port}',
                                '-e', f'AUGMIS_RELAY_HEALTH_PATH={self.plan.health_path}',
                                '-e', 'AUGMIS_RELAY_ROUTE_CONTRACT='+json.dumps([
                                    {'path': p, 'methods': list(m)} for p,m in route_contract(self.manifest)
                                ], separators=(',',':')), self.images.relay_image_id]
                created.append(('container', relay_name))
                docker(*relay_params)
                docker('network', 'connect', private_net, relay_name)
                port = _port(relay_name)
                address = f'http://127.0.0.1:{port}'
                while time.monotonic() - start < _LIMIT:
                    if _http(address + self.plan.health_path) == 200:
                        break
                    time.sleep(2)
                else:
                    raise QualificationFailure('C1D2_RUNTIME_HEALTH_TIMEOUT')
                checked['internal_health'] = True
                endpoint = address + self.get_path
                unsigned = _http(endpoint)
                signed = _http(endpoint, _jwt(private, tenant=tenant,
                    app=application, instance=instance, path=self.get_path))
                wrong_tenant = _http(endpoint, _jwt(private, tenant=tenant,
                    app=application, instance=instance, path=self.get_path,
                    foreign_tenant=True))
                replay = _jwt(private, tenant=tenant, app=application,
                              instance=instance, path=self.get_path)
                first, second = _http(endpoint, replay), _http(endpoint, replay)
                checked['gateway_auth'] = signed == 200 and first == 200
                checked['gateway_rejection'] = (unsigned == 401 and wrong_tenant in {401, 403}
                                                and second == 401 and _http(address+'/api/not-declared')==404)
                if not all(checked.values()):
                    raise QualificationFailure('C1D2_SIGNED_GATEWAY_SMOKE_FAILED')
                return checked
            finally:
                # Cleanup strictly scoped to unique augmis-q-* names from this invocation.
                # No external volumes, existing instance containers or DB records are touched.
                for kind, name in reversed(created):
                    try:
                        if kind == 'container':
                            _cmd('docker', 'rm', '-f', name, check=False, timeout=20)
                        else:
                            _cmd('docker', 'network', 'rm', name, check=False, timeout=20)
                    except QualificationFailure:
                        # Original diagnostic must not be masked by cleanup errors.
                        pass
