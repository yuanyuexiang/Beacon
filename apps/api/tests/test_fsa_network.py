import httpx
import pytest

from app.integrations import fsa


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(fsa, "_sleep", lambda _: None)


def test_retry_tls_error_then_return_authorities():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING]", request=request)
        return httpx.Response(
            200, json={"authorities": [{"LocalAuthorityId": 277, "Name": "Adur", "EstablishmentCount": 464}]}
        )

    assert fsa.list_authorities(transport=httpx.MockTransport(handler))[0]["count"] == 464
    assert calls == 3


def test_retry_only_failed_page_without_duplicate_rows():
    calls = []

    def handler(request):
        page = int(request.url.params["pageNumber"])
        calls.append(page)
        if calls == [1, 2]:
            raise httpx.ReadError("connection interrupted", request=request)
        return httpx.Response(
            200, json={"meta": {"totalCount": 2, "totalPages": 2}, "establishments": [{"FHRSID": page}]}
        )

    result = fsa.fetch_establishments(277, transport=httpx.MockTransport(handler), page_size=1)
    assert calls == [1, 2, 2]
    assert [row["FHRSID"] for row in result.establishments] == [1, 2]


@pytest.mark.parametrize("status,calls", [(503, 3), (429, 3), (404, 1), (401, 1)])
def test_http_retries_are_bounded_and_permanent_errors_are_not_retried(status, calls):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status)

    error = fsa.FsaConnectionError if calls == 3 else httpx.HTTPStatusError
    with pytest.raises(error):
        fsa.list_authorities(transport=httpx.MockTransport(handler))
    assert len(seen) == calls


def test_network_exhaustion_does_not_expose_low_level_connection_details():
    seen = []

    def handler(request):
        seen.append(request)
        raise httpx.ConnectError("internal-connection-details", request=request)

    with pytest.raises(fsa.FsaConnectionError, match="3 次") as error:
        fsa.list_authorities(transport=httpx.MockTransport(handler))
    assert len(seen) == 3 and "internal-connection-details" not in str(error.value)


def test_malformed_success_response_is_not_treated_as_an_empty_directory():
    import pytest

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"error": "temporary issue"}))
    with pytest.raises(fsa.FsaConnectionError, match="分页格式不完整"):
        fsa.fetch_establishments(277, transport=transport)
