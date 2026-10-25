"""C1-D4.2: negative environment-release gate tests. No Docker/DB/network I/O."""
from __future__ import annotations

import pytest
from services.api.app.services import security_release_gate as gate


@pytest.mark.parametrize("value", ["development", "dev", " DEVELOPMENT ", "DEV"])
def test_explicit_development_is_unchanged(monkeypatch, value):
    monkeypatch.setattr(gate.settings, "app_env", value)
    monkeypatch.delenv("AUGMIS_SESSION_STORE", raising=False)
    assert gate.require_safe_runtime_exposure() is None


@pytest.mark.parametrize("value", ["", "test", "staging", "prodution", "developement", "unknown"])
def test_unknown_environment_is_denied(monkeypatch, value):
    monkeypatch.setattr(gate.settings, "app_env", value)
    monkeypatch.setenv("AUGMIS_SESSION_STORE", "redis")
    with pytest.raises(RuntimeError, match="C1D42_APP_ENV_UNRECOGNIZED"):
        gate.require_safe_runtime_exposure()


@pytest.mark.parametrize("value", ["production", "prod", " PRODUCTION "])
def test_production_with_redis_remains_blocked(monkeypatch, value):
    monkeypatch.setattr(gate.settings, "app_env", value)
    monkeypatch.setenv("AUGMIS_SESSION_STORE", "redis")
    with pytest.raises(RuntimeError, match="Production launch blocked"):
        gate.require_safe_runtime_exposure()


@pytest.mark.parametrize("value", ["production", "prod"])
def test_production_without_redis_denied(monkeypatch, value):
    monkeypatch.setattr(gate.settings, "app_env", value)
    monkeypatch.setenv("AUGMIS_SESSION_STORE", "memory")
    with pytest.raises(RuntimeError, match="Production requires shared Redis runtime sessions"):
        gate.require_safe_runtime_exposure()
