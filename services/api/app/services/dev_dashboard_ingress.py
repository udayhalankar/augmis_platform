"""B4 Pass 3H-5D: development-only managed private ingress for dashboard.

No production opt-in. It does not grant access or issue tokens; the existing
AUGMIS gateway supplies a signed assertion following authorization.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable

from services.api.app.services.dashboard_runtime_mounts import DashboardPilotLaunch

_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NETWORK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}\Z")
_NAME = re.compile(r"augmis-[a-z0-9][a-z0-9-]{0,160}\Z")
_PORT = re.compile(r"127\.0\.0\.1:([0-9]{1,5})\Z")

class DevIngressError(ValueError):
    pass

@dataclass(frozen=True)
class DevRelay:
    ingress_network: str
    private_network: str
    relay_image_id: str


def relay_container_name(dashboard_name: str) -> str:
    if not _NAME.fullmatch(dashboard_name) or len(dashboard_name) > 170:
        raise DevIngressError("Invalid managed dashboard container name")
    return dashboard_name + "-ingress"


def parse_relay_port(output: str) -> int:
    # Reject any 0.0.0.0/IPv6/second binding; never trust a partial match.
    rows = output.strip().splitlines()
    if len(rows) != 1:
        raise DevIngressError("Relay must publish exactly one loopback mapping")
    match = _PORT.fullmatch(rows[0].strip())
    if not match:
        raise DevIngressError("Relay must bind only Windows IPv4 loopback")
    port = int(match[1])
    if port < 1024 or port > 65535:
        raise DevIngressError("Invalid relay host port")
    return port


def require_dev_relay(pilot: DashboardPilotLaunch,
                      *, run_docker: Callable[[list[str]], str]) -> DevRelay:
    from services.api.app.core.config import settings
    if str(settings.app_env).lower() not in {"development", "dev"}:
        raise DevIngressError("Private dashboard relay is forbidden outside development")
    if os.environ.get("AUGMIS_DASHBOARD_DEV_RELAY_ENABLED") != "1":
        raise DevIngressError("Dashboard pilot requires explicit development ingress approval")
    image = os.environ.get("AUGMIS_DASHBOARD_DEV_RELAY_IMAGE_ID", "").strip()
    ingress = os.environ.get("AUGMIS_DASHBOARD_DEV_INGRESS_NETWORK", "").strip()
    if not _IMAGE.fullmatch(image):
        raise DevIngressError("Relay image must be pinned by immutable image ID")
    if not _NETWORK.fullmatch(ingress) or ingress in {"bridge", "host", "none", pilot.private_network}:
        raise DevIngressError("Invalid dedicated ingress network")
    if run_docker(["docker", "network", "inspect", "--format", "{{.Internal}}", pilot.private_network]).strip().lower() != "true":
        raise DevIngressError("Dashboard database network must remain internal")
    if run_docker(["docker", "network", "inspect", "--format", "{{.Internal}}", ingress]).strip().lower() != "false":
        raise DevIngressError("Ingress bridge must be separate from internal DB network")
    if run_docker(["docker", "image", "inspect", "--format", "{{.Config.User}}", image]).strip() != "10002:10002":
        raise DevIngressError("Relay must run as approved non-root user")
    return DevRelay(ingress, pilot.private_network, image)


def verify_companion_relay(name: str, target: str,
                           run_docker: Callable[[list[str]], str]) -> bool:
    """Absent => False; mismatch => error, never remove foreign container."""
    from services.api.app.services.deployment_engine import DeploymentError
    try:
        output = run_docker([
            "docker", "container", "inspect", "--format",
            '{{index .Config.Labels "augmis.ingress_for"}}|{{index .Config.Labels "augmis.managed"}}', name
        ])
    except DeploymentError as exc:
        # Distinguish not-found from daemon outage without parsing a secret.
        if "no such container" in str(exc).lower() or "no such object" in str(exc).lower():
            return False
        raise
    if output.strip() != f"{target}|true":
        raise DevIngressError("Companion relay ownership verification failed")
    return True
