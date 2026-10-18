"""C1-D1: deterministic, bounded, non-mutating runtime-host readiness checks.

Never exposes private key bytes, environment contents, or raw Docker stderr.
Readiness is rechecked before new generic database provisioning so recovery
from a transient Docker outage does not require an API restart.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from services.api.app.core.config import settings
from services.api.app.core.runtime_host import active_profile


@dataclass(frozen=True)
class RuntimeHostStatus:
    state: str
    code: str

    @property
    def ready(self) -> bool:
        return self.state == 'ready'


def _docker(*args: str) -> str:
    try:
        result = subprocess.run(['docker', *args], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('C1D_DOCKER_UNAVAILABLE') from exc
    if result.returncode:
        raise RuntimeError('C1D_DOCKER_CHECK_FAILED')
    return result.stdout.strip()


def check_runtime_host() -> RuntimeHostStatus:
    """Pure host inspection (never creates, stops or modifies Docker resources)."""
    profile = active_profile()
    if profile is None:
        return RuntimeHostStatus('not_configured', 'C1D_PROFILE_NOT_CONFIGURED')
    if str(settings.app_env).lower() not in ('development', 'dev'):
        return RuntimeHostStatus('unready', 'C1D_DEVELOPMENT_ONLY')
    try:
        env = profile.environment
        # A runtime environment modified after initialization is an error,
        # not an opportunity to silently switch capabilities or keys.
        for key, required in env.items():
            if os.environ.get(key) != required:
                raise RuntimeError('C1D_RUNTIME_ENV_DRIFT')
        from services.api.app.services.private_crud_runtime import signing_material
        signing_material()  # validates matching Ed25519 keys
        if _docker('info','--format','{{.ServerVersion}}') == '':
            raise RuntimeError('C1D_DOCKER_UNAVAILABLE')
        for name in ('AUGMIS_C1B_POSTGRES_IMAGE_ID', 'AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID'):
            image = env[name]
            if _docker('image', 'inspect', '--format', '{{.Id}}', image) != image:
                raise RuntimeError('C1D_IMAGE_DRIFT')
        if _docker('image', 'inspect', '--format', '{{.Config.User}}',
                   env['AUGMIS_C1C_GENERIC_RELAY_IMAGE_ID']) != '10002:10002':
            raise RuntimeError('C1D_RELAY_NOT_NONROOT')
        ingress = env['AUGMIS_C1B_CRUD_INGRESS_NETWORK']
        if _docker('network', 'inspect', '--format', '{{.Internal}}', ingress).lower() != 'false':
            raise RuntimeError('C1D_INGRESS_TOPOLOGY_INVALID')
        if _docker('network', 'inspect', '--format', '{{.Driver}}', ingress) != 'bridge':
            raise RuntimeError('C1D_INGRESS_DRIVER_INVALID')
        return RuntimeHostStatus('ready', 'C1D_RUNTIME_READY')
    except RuntimeError as exc:
        # Retain only stable, known, non-sensitive machine-readable error codes.
        code = str(exc)
        if not code.startswith('C1D_'):
            code = 'C1D_HOST_CHECK_FAILED'
        return RuntimeHostStatus('unready', code)
    except Exception:
        return RuntimeHostStatus('unready', 'C1D_HOST_CHECK_FAILED')


def require_generic_host_ready() -> None:
    from services.api.app.core.runtime_host import RuntimeProfileError
    state = check_runtime_host()
    if not state.ready:
        raise RuntimeProfileError(state.code)
