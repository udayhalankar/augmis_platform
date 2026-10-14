"""B3 startup safety gate. Explicitly refuses an unsafe production exposure."""
from __future__ import annotations
import os
from services.api.app.core.config import settings


def require_safe_runtime_exposure() -> None:
    env = str(settings.app_env).strip().lower()
    if env not in ("production", "prod"):
        return  # Development must still remain on loopback / isolated network.
    if os.environ.get("AUGMIS_SESSION_STORE", "").strip().lower() != "redis":
        raise RuntimeError("Production requires shared Redis runtime sessions")
    # Existing Docker executor publishes host-loopback ports and lacks a
    # complete private-network gateway adapter; do not silently accept this.
    raise RuntimeError(
        "Production launch blocked: private runtime networking, origin separation, "
        "secret-provider verification and staging security approval are not yet implemented."
    )
