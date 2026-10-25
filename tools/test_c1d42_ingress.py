"""R01: configuration, Host and session-Origin security negatives; no live services."""
from dataclasses import dataclass

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from services.api.app.core.config import validate_production_ingress_config
from services.api.app.routes import session_security as sessions


@dataclass
class IngressFixture:
    app_env: str = "production"
    frontend_base_url: str = "https://portal.customer.com"
    cors_origins: str = "https://portal.customer.com"
    session_cookie_secure: bool = True
    session_absolute_hours: int = 24
    api_trusted_hosts: str = "portal.customer.com,api.internal"

    @property
    def cors_origin_list(self):
        return [v.strip() for v in self.cors_origins.split(",") if v.strip()]

    @property
    def api_trusted_host_list(self):
        return [v.strip().lower() for v in self.api_trusted_hosts.split(",") if v.strip()]


def request(origin: str, csrf: str = "1", **headers) -> Request:
    items = {"origin": origin, "x-augmis-csrf": csrf, **headers}
    return Request({"type": "http", "method": "POST", "scheme": "https", "path": "/api/v1/auth/refresh",
                    "headers": [(k.lower().encode(), v.encode()) for k, v in items.items()]})


def test_valid_production_ingress_config():
    cfg = IngressFixture()
    assert validate_production_ingress_config(cfg) == (cfg.frontend_base_url, cfg.api_trusted_host_list)


@pytest.mark.parametrize("origin", [
    "http://portal.customer.com", "https://localhost:3000", "https://127.0.0.1",
    "https://example.localtest.me",
    "https://portal.customer.com/path", "https://portal.customer.com:8443", "https://*.customer.com",
])
def test_insecure_public_origin_rejected(origin):
    cfg = IngressFixture(frontend_base_url=origin, cors_origins=origin)
    with pytest.raises(RuntimeError, match="R01_PUBLIC_ORIGIN_INVALID"):
        validate_production_ingress_config(cfg)

def test_public_origin_must_be_listed_as_trusted_host():
    origin = "https://portal.customer.com.evil.net"

    cfg = IngressFixture(
        frontend_base_url=origin,
        cors_origins=origin,
    )

    with pytest.raises(
        RuntimeError,
        match="R01_API_TRUSTED_HOSTS_INVALID",
    ):
        validate_production_ingress_config(cfg)

@pytest.mark.parametrize("overrides,code", [
    ({"cors_origins": "https://portal.customer.com,http://localhost:3000"}, "R01_PRODUCTION_CORS_MUST_MATCH_PUBLIC_ORIGIN"),
    ({"cors_origins": "*"}, "R01_PRODUCTION_CORS_MUST_MATCH_PUBLIC_ORIGIN"),
    ({"session_cookie_secure": False}, "R01_PRODUCTION_SECURE_COOKIE_REQUIRED"),
    ({"api_trusted_hosts": ""}, "R01_API_TRUSTED_HOSTS_INVALID"),
    ({"api_trusted_hosts": "portal.customer.com,*"}, "R01_API_TRUSTED_HOSTS_INVALID"),
    ({"api_trusted_hosts": "api.internal"}, "R01_API_TRUSTED_HOSTS_INVALID"),
    ({"api_trusted_hosts": "portal.customer.com,localhost"}, "R01_API_TRUSTED_HOSTS_INVALID"),
])



def test_unsafe_production_setting_rejected(overrides, code):
    cfg = IngressFixture(**overrides)
    with pytest.raises(RuntimeError, match=code):
        validate_production_ingress_config(cfg)


def test_production_sessions_require_exact_origin_csrf_and_secure_cookie(monkeypatch):
    cfg = IngressFixture()
    monkeypatch.setattr(sessions, "settings", cfg)
    assert sessions.cookie_name() == "__Host-augmis_refresh"
    sessions.assert_origin(request(cfg.frontend_base_url))
    for origin, csrf in [("https://evil.customer.com", "1"),
                         ("http://portal.customer.com", "1"),
                         ("https://portal.customer.com/", "1"),
                         (cfg.frontend_base_url, "0")]:
        with pytest.raises(HTTPException) as error:
            sessions.assert_origin(request(origin, csrf))
        assert error.value.status_code == 403
        assert error.value.detail == "SESSION_ORIGIN_DENIED"
    # Forged client-provided proxy headers never authorize the wrong origin.
    with pytest.raises(HTTPException):
        sessions.assert_origin(request("https://evil.customer.com", "1",
                                       **{"x-forwarded-host": "portal.customer.com", "x-forwarded-proto": "https"}))
    response = Response()
    sessions.set_cookie(response, __import__("uuid").uuid4(), "placeholder-test-only")
    cookie = response.headers["set-cookie"].lower()
    assert "__host-augmis_refresh" in cookie and "secure" in cookie and "httponly" in cookie


def test_trusted_host_middleware_ignores_forged_forwarding_and_denies_foreign_host():
    # Isolate Starlette's security boundary. Actual middleware is wired in main.py
    # after the production startup gate has been independently approved.
    cfg = IngressFixture()
    app = FastAPI()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=cfg.api_trusted_host_list, www_redirect=False)

    @app.get("/probe")
    def probe():
        return {"safe": True}

    with TestClient(app) as web:
        assert web.get("/probe", headers={"Host": "portal.customer.com", "X-Forwarded-Host": "evil.example"}).status_code == 200
        assert web.get("/probe", headers={"Host": "api.internal", "X-Forwarded-Proto": "http"}).status_code == 200
        assert web.get("/probe", headers={"Host": "evil.example", "X-Forwarded-Host": "portal.customer.com"}).status_code == 400
        assert web.get("/probe", headers={"Host": "localhost"}).status_code == 400


def test_development_cors_and_cookie_are_unmodified(monkeypatch):
    cfg = IngressFixture(app_env="development", frontend_base_url="http://localhost:3000",
                         cors_origins="http://localhost:3000,http://127.0.0.1:3000",
                         session_cookie_secure=False, api_trusted_hosts="")
    monkeypatch.setattr(sessions, "settings", cfg)
    assert sessions.cookie_name() == "augmis_dev_refresh"
    sessions.assert_origin(request("http://localhost:3000"))
    sessions.assert_origin(request("http://127.0.0.1:3000"))
