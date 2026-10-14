"""B4 3H-2: opt-in, immutable-image-pinned secure dashboard launch contract.

This module does not create credentials, set permissions, or activate the pilot.
Host-managed files must be provisioned separately outside all repositories.
Only trusted AUGMIS instance/application/tenant model IDs may reach this API.
"""
from __future__ import annotations

import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

APP_ENV = "AUGMIS_DASHBOARD_ASSERTION_APPLICATION_ID"
TENANT_ENV = "AUGMIS_DASHBOARD_ASSERTION_TENANT_ID"
SIGNING_FILE_ENV = "AUGMIS_DASHBOARD_ASSERTION_PRIVATE_KEY_FILE"
ROOT_ENV = "AUGMIS_DASHBOARD_SECRET_ROOT"
IMAGE_ENV = "AUGMIS_DASHBOARD_APPROVED_IMAGE_ID"
NETWORK_ENV = "AUGMIS_DASHBOARD_PRIVATE_NETWORK"
DB_HOST_ENV = "AUGMIS_DASHBOARD_DB_HOST"
DB_PORT_ENV = "AUGMIS_DASHBOARD_DB_PORT"

PASSWORD_FILE = "db_password"
PUBLIC_KEY_FILE = "assertion_public.pem"
CONTAINER_PASSWORD = "/run/secrets/augmis-dashboard-db-password"
CONTAINER_PUBLIC_KEY = "/run/secrets/augmis-dashboard-public-key.pem"

_IMAGE_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_NETWORK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_DB_HOST_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.-]{0,252}$")

class PilotLaunchError(ValueError):
    """Safe configuration failure; never include secret values in messages."""

@dataclass(frozen=True)
class DashboardPilotLaunch:
    environment: dict[str, str]
    secret_mounts: tuple[tuple[Path, str], ...]
    private_network: str


def _exact_uuid(value: str | uuid.UUID) -> uuid.UUID:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PilotLaunchError("Invalid trusted runtime identity") from exc
    if str(parsed) != str(value):
        raise PilotLaunchError("Noncanonical runtime identity")
    return parsed


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise PilotLaunchError("Required dashboard pilot configuration is missing")
    return value


def _no_reparse(path: Path) -> None:
    """Reject symlinks and Windows junctions/reparse points along configured path."""
    for part in (path, *path.parents):
        try:
            st = part.lstat()
        except OSError as exc:
            raise PilotLaunchError("Dashboard secret path is unavailable") from exc
        if stat.S_ISLNK(st.st_mode) or (
            getattr(st, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise PilotLaunchError("Dashboard secret path must not contain links")


def _safe_secret_files(root_value: str, tenant_id: uuid.UUID, instance_id: uuid.UUID) -> tuple[Path, Path]:
    root = Path(root_value)
    if not root.is_absolute() or "," in root_value or "\n" in root_value or "\r" in root_value:
        raise PilotLaunchError("Invalid dashboard secret root")
    folder = root / str(tenant_id) / str(instance_id)
    files = (folder / PASSWORD_FILE, folder / PUBLIC_KEY_FILE)
    for path in (root, folder, *files):
        if not path.exists():
            raise PilotLaunchError("Dashboard secret file/directory is missing")
        _no_reparse(path)
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise PilotLaunchError("Dashboard secret file/directory is unavailable") from exc
        if resolved != path.absolute():
            raise PilotLaunchError("Dashboard secret path resolved unexpectedly")
    if not root.is_dir() or not folder.is_dir() or any(not f.is_file() for f in files):
        raise PilotLaunchError("Dashboard secret layout is invalid")
    return files


def _validate_material(password_path: Path, public_path: Path, signing_path: str) -> None:
    try:
        password = password_path.read_bytes()
        public_bytes = public_path.read_bytes()
        private_bytes = Path(signing_path).read_bytes()
        public_key = serialization.load_pem_public_key(public_bytes)
        private_key = serialization.load_pem_private_key(private_bytes, password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise PilotLaunchError("Dashboard signing or database secret is unavailable") from exc
    # Password is never logged or returned, including on error.
    stripped = password.rstrip(b"\r\n")
    if not stripped or len(stripped) > 4096 or b"\n" in stripped or b"\r" in stripped or b"\x00" in stripped:
        raise PilotLaunchError("Dashboard database secret format is invalid")
    if not isinstance(public_key, Ed25519PublicKey) or not isinstance(private_key, Ed25519PrivateKey):
        raise PilotLaunchError("Dashboard runtime key algorithms do not match the contract")
    actual = public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    expected = private_key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    if actual != expected:
        raise PilotLaunchError("Dashboard runtime verifier differs from AUGMIS signing key")


def build_dashboard_pilot_launch(
    *, tenant_id: str | uuid.UUID, application_id: str | uuid.UUID,
    instance_id: str | uuid.UUID, image_id: str,
    inspect_docker: Callable[[list[str]], str] | None = None,
) -> DashboardPilotLaunch | None:
    """Return None for all other apps; fail closed for configured pilot.

    The Docker network must be pre-created with Internal=true and a reachable
    approved database service. A host-OS database is NOT reachable by design.
    """
    configured_app = os.environ.get(APP_ENV, "").strip()
    if not configured_app:
        return None
    application = _exact_uuid(application_id)
    if _exact_uuid(configured_app) != application:
        return None
    tenant = _exact_uuid(tenant_id)
    instance = _exact_uuid(instance_id)
    if _exact_uuid(_required(TENANT_ENV)) != tenant:
        raise PilotLaunchError("Dashboard pilot tenant scope mismatch")
    approved_image = _required(IMAGE_ENV)
    if not _IMAGE_RE.fullmatch(image_id) or approved_image != image_id:
        raise PilotLaunchError("Dashboard pilot image is not explicitly approved")

    name = _required(NETWORK_ENV)
    if not _NETWORK_RE.fullmatch(name) or name in ("bridge", "host", "none"):
        raise PilotLaunchError("Invalid dashboard private network configuration")
    host = _required(DB_HOST_ENV)
    if not _DB_HOST_RE.fullmatch(host) or host.lower() in (
        "localhost", "host.docker.internal", "gateway.docker.internal", "host-gateway"
    ) or host.lower().endswith(".internal") or host.lower().startswith("127."):
        raise PilotLaunchError("Dashboard database must be a private service on the approved Docker network")
    try:
        port = int(os.environ.get(DB_PORT_ENV, "5432"))
    except ValueError as exc:
        raise PilotLaunchError("Invalid dashboard database port") from exc
    if not 1 <= port <= 65535:
        raise PilotLaunchError("Invalid dashboard database port")

    password_path, public_path = _safe_secret_files(_required(ROOT_ENV), tenant, instance)
    _validate_material(password_path, public_path, _required(SIGNING_FILE_ENV))

    if inspect_docker is None:
        from services.api.app.services.deployment_engine import run_docker
        inspect_docker = lambda args: run_docker(args, timeout=30)
    try:
        network_internal = inspect_docker([
            "docker", "network", "inspect", "--format", "{{.Internal}}", name
        ]).strip().lower()
        image_user = inspect_docker([
            "docker", "image", "inspect", "--format", "{{.Config.User}}", image_id
        ]).strip()
    except Exception as exc:
        raise PilotLaunchError("Approved dashboard network or image cannot be inspected") from exc
    if network_internal != "true":
        raise PilotLaunchError("Dashboard pilot network must be internal")
    if image_user != "10001:10001":
        raise PilotLaunchError("Dashboard pilot image user is not the approved non-root identity")

    return DashboardPilotLaunch(
        environment={
            "AUGMIS_RUNTIME_TENANT_ID": str(tenant),
            "AUGMIS_RUNTIME_APPLICATION_ID": str(application),
            "AUGMIS_RUNTIME_INSTANCE_ID": str(instance),
            "AUGMIS_RUNTIME_ASSERTION_PUBLIC_KEY_FILE": CONTAINER_PUBLIC_KEY,
            "AUGMIS_DASHBOARD_DB_PASSWORD_FILE": CONTAINER_PASSWORD,
            "AUGMIS_DASHBOARD_DB_HOST": host,
            "AUGMIS_DASHBOARD_DB_PORT": str(port),
        },
        secret_mounts=((password_path, CONTAINER_PASSWORD), (public_path, CONTAINER_PUBLIC_KEY)),
        private_network=name,
    )
