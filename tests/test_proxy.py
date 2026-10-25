"""Exercise the deployment's actual Uvicorn proxy middleware and login limiter."""
import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from backend.main import app
from backend.server import trusted_proxy_ips


def test_render_clients_have_separate_limits_and_spoofed_prefix_is_ignored(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    # The bootstrap must override broad hosting environment defaults.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=trusted_proxy_ips())
    with TestClient(wrapped, client=("10.29.8.12", 1234)) as client:
        for n in range(10):
            headers = {"X-Forwarded-For": f"192.0.2.{n+1}, 198.51.100.10, 172.64.1.1, 10.29.58.213"}
            assert client.post("/api/session", json={"password": "wrong"}, headers=headers).status_code == 401
        headers = {"X-Forwarded-For": "192.0.2.200, 198.51.100.10, 172.64.1.1, 10.29.58.213"}
        assert client.post("/api/session", json={"password": "wrong"}, headers=headers).status_code == 429
        headers = {"X-Forwarded-For": "198.51.100.20, 172.64.1.1, 10.29.58.213"}
        assert client.post("/api/session", json={"password": "refundpilot-local"}, headers=headers).status_code == 200


def test_direct_untrusted_client_cannot_change_rate_limit_identity(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=trusted_proxy_ips())
    with TestClient(wrapped, client=("198.51.100.30", 1234)) as client:
        for n in range(10):
            headers = {"X-Forwarded-For": f"192.0.2.{n+1}"}
            assert client.post("/api/session", json={"password": "wrong"}, headers=headers).status_code == 401
        assert client.post("/api/session", json={"password": "wrong"}, headers={"X-Forwarded-For": "192.0.2.200"}).status_code == 429


def test_local_proxy_defaults_and_explicit_override(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    assert trusted_proxy_ips() == "127.0.0.1,::1"
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.1, 10.29.0.0/16")
    assert trusted_proxy_ips() == "127.0.0.1,10.29.0.0/16"


@pytest.mark.parametrize("value", ["*", "0.0.0.0/0", "::/0", "invalid"])
def test_trust_all_and_invalid_proxy_overrides_fail_closed(monkeypatch, value):
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", value)
    with pytest.raises(ValueError):
        trusted_proxy_ips()
