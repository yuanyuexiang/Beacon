"""官网读取仅对临时故障有限重试，保持 TLS 和公网限制。"""

import httpx
import pytest

from app.core.config import get_settings
from app.integrations import fetcher
from app.modules.leads import entity


@pytest.mark.parametrize("failure", ["tls_eof", "timeout", "502", "429"])
def test_transient_site_failure_recovers(monkeypatch, failure):
    monkeypatch.setattr(get_settings(), "fetch_ip_check", False)
    monkeypatch.setattr(entity.time, "sleep", lambda _: None)
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            if failure == "tls_eof":
                raise httpx.ConnectError("SSL: UNEXPECTED_EOF_WHILE_READING")
            if failure == "timeout":
                raise httpx.ReadTimeout("timed out")
            return httpx.Response(int(failure))
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>Contact</html>")

    result = entity.site_fetch(httpx.MockTransport(respond))("https://restaurant.example/")
    assert result.status == 200
    assert len(calls) == 2


@pytest.mark.parametrize("status", [403, 404, 410, 200])
def test_permanent_or_success_response_is_not_retried(monkeypatch, status):
    monkeypatch.setattr(get_settings(), "fetch_ip_check", False)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status)

    assert entity.site_fetch(httpx.MockTransport(respond))("https://restaurant.example/").status == status
    assert len(calls) == 1


def test_retry_bound_and_security(monkeypatch):
    monkeypatch.setattr(get_settings(), "fetch_ip_check", False)
    monkeypatch.setattr(entity.time, "sleep", lambda _: None)
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ConnectError("SSL EOF")

    read = entity.site_fetch(httpx.MockTransport(respond))
    with pytest.raises(httpx.ConnectError):
        read("https://restaurant.example/")
    assert len(calls) == 3
    with pytest.raises(fetcher.FetchBlocked):
        read("http://127.0.0.1/")
    assert len(calls) == 3


def test_certificate_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(get_settings(), "fetch_ip_check", False)
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ConnectError("CERTIFICATE_VERIFY_FAILED")

    with pytest.raises(httpx.ConnectError):
        entity.site_fetch(httpx.MockTransport(respond))("https://restaurant.example/")
    assert len(calls) == 1


def test_long_retry_after_defers_without_hammering(monkeypatch):
    monkeypatch.setattr(get_settings(), "fetch_ip_check", False)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    assert entity.site_fetch(httpx.MockTransport(respond))("https://restaurant.example/").status == 429
    assert len(calls) == 1
