"""B3 startup safety gate. Explicitly refuses an unsafe production exposure."""
from __future__ import annotations
import os
from services.api.app.core.config import settings


def require_safe_runtime_exposure() -> None:
    env = str(settings.app_env).strip().lower()
    # Never interpret a typo or unexpected APP_ENV as an authorized dev environment.
    # Future environments (for example staging) require explicit review and approval.
    if env not in ("development", "dev", "production", "prod"):
        raise RuntimeError("C1D42_APP_ENV_UNRECOGNIZED")
    if env in ("development", "dev"):
        return  # Existing dev runtime behavior is preserved.
    if os.environ.get("AUGMIS_SESSION_STORE", "").strip().lower() != "redis":
        raise RuntimeError("Production requires shared Redis runtime sessions")
    # Existing Docker executor publishes host-loopback ports and lacks a
    # complete private-network gateway adapter; do not silently accept this.
    raise RuntimeError(
        "Production launch blocked: private runtime networking, origin separation, "
        "secret-provider verification and staging security approval are not yet implemented."
    )
