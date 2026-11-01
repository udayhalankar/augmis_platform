"""Fail-closed R10 guard tests. No real DB, Docker or Git mutations."""
from __future__ import annotations

import pytest
from tools import r10_ci_checks as ci


def test_db_guard_fails_without_github(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("AUGMIS_R10_DISPOSABLE_DB", "1")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://augmis_ci:x@127.0.0.1:5432/augmis_r10_ci")
    with pytest.raises(ci.R10CheckError, match="R10_DB_CI_ONLY"):
        ci.disposable_db_preflight()


@pytest.mark.parametrize("bad", [
    "postgresql+psycopg://augmis_ci:x@localhost:5432/augmis_r10_ci",
    "postgresql+psycopg://augmis_ci:x@127.0.0.1:5432/augmis_platform",
    "postgresql+psycopg://postgres:x@127.0.0.1:5432/augmis_r10_ci",
    "postgresql+psycopg://augmis_ci:x@192.168.1.1:5432/augmis_r10_ci",
    "postgresql+psycopg://augmis_ci:x@127.0.0.1:6543/augmis_r10_ci",
])
def test_db_guard_rejects_other_database_hosts_and_names(monkeypatch, bad):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AUGMIS_R10_DISPOSABLE_DB", "1")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", bad)
    with pytest.raises(ci.R10CheckError, match="R10_DB_NON_DISPOSABLE_TARGET_DENIED"):
        ci.disposable_db_preflight()


def test_ci_preflight_accepts_disposable_identity(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AUGMIS_R10_DISPOSABLE_DB", "1")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://augmis_ci:x@127.0.0.1:5432/augmis_r10_ci")
    assert ci.disposable_db_preflight().startswith("postgresql+psycopg://")


def test_ci_preflight_rejects_production(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AUGMIS_R10_DISPOSABLE_DB", "1")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://augmis_ci:x@127.0.0.1:5432/augmis_r10_ci")
    with pytest.raises(ci.R10CheckError, match="R10_DB_ENV_DENIED"):
        ci.disposable_db_preflight()
