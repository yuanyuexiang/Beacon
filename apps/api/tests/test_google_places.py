"""Google Places 脱敏夹具：不联网，不使用真实 Key，不保存 Google 内容。"""

import json
import time
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import AuditLog
from app.integrations import google_places as google
from app.modules.leads import google_places as routes
from app.modules.leads.models import Lead
from tests.test_imports import CSV_A, create_batch, login, upload

PID = "test_place"
NAME = f"places/{PID}/photos/test_photo"
PLACE = {
    "id": PID,
    "displayName": {"text": "Synthetic Test Restaurant"},
    "formattedAddress": "1 Test Road TEST 1AA",
    "googleMapsUri": "https://maps.google.com/?cid=123",
    "priceLevel": "PRICE_LEVEL_MODERATE",
    "priceRange": {"startPrice": {"currencyCode": "GBP", "units": "20"}},
    "photos": [
        {
            "name": NAME,
            "widthPx": 1000,
            "heightPx": 1500,
            "googleMapsUri": "https://www.google.com/maps/photo/test",
            "authorAttributions": [{"displayName": "Test Author", "uri": "https://maps.google.com/contrib/test"}],
        }
    ],
    "attributions": [{"provider": "Test Provider", "providerUri": "https://provider.example/"}],
}


def adapter(handler, reserve=None):
    return google.PlacesClient("fake-secret", transport=httpx.MockTransport(handler), reserve=reserve)


def test_masks_and_key_only_sent_to_google():
    seen = []

    def handler(r):
        assert r.headers["X-Goog-Api-Key"] == "fake-secret"
        assert "fake-secret" not in str(r.url) and "fake-secret" not in r.content.decode()
        seen.append(r.headers.get("X-Goog-FieldMask"))
        if r.method == "POST":
            assert json.loads(r.content)["pageSize"] == 3
            return httpx.Response(200, json={"places": [PLACE]})
        return httpx.Response(200, json=PLACE)

    c = adapter(handler)
    assert c.search("test")[0].id == PID
    assert c.details(PID).priceRange.startPrice.units == "20"
    assert seen == [google.SEARCH_FIELDS, google.DETAIL_FIELDS]
    assert "priceRange" not in google.SEARCH_FIELDS and "*" not in google.DETAIL_FIELDS


@pytest.mark.parametrize("status,expected", [(400, 409), (404, 409), (401, 503), (403, 503), (429, 429), (500, 502)])
def test_upstream_errors_are_safe(status, expected):
    calls: list[str] = []
    with pytest.raises(google.PlacesError) as e:
        adapter(lambda r: httpx.Response(status, text="fake-secret with raw content"), calls.append).search("test")
    assert e.value.status == expected and "fake-secret" not in str(e.value)
    assert len(calls) == (2 if status == 500 else 1)


def test_timeout_bounded_retries_and_attempt_accounting():
    calls: list[str] = []

    def fail(r):
        raise httpx.ConnectTimeout("fake-secret", request=r)

    with pytest.raises(google.PlacesError) as e:
        adapter(fail, calls.append).search("test")
    assert e.value.status == 504 and len(calls) == 2 and "fake-secret" not in str(e.value)


@pytest.mark.parametrize("body", [[], {"places": [None]}, {"places": [{"id": "../bad"}]}, {"error": {}}])
def test_malformed_response_rejected(body):
    with pytest.raises(google.PlacesError):
        adapter(lambda r: httpx.Response(200, json=body)).search("test")


def test_size_limit_and_unsafe_photo_target():
    with pytest.raises(google.PlacesError, match="大小上限"):
        adapter(lambda r: httpx.Response(200, content=b"x" * (google.MAX_JSON_BYTES + 1))).search("test")
    for uri in ("http://127.0.0.1/", "https://example.com/", "https://evil.example.googleusercontent.com@127.0.0.1/"):
        with pytest.raises(google.PlacesError, match="链接异常"):
            adapter(lambda r, uri=uri: httpx.Response(200, json={"photoUri": uri})).photo(NAME)


def test_photo_does_not_forward_key_or_follow_redirects():
    calls: list[str] = []

    def handler(r):
        calls.append(str(r.url))
        if r.url.host == "places.googleapis.com":
            assert r.headers["X-Goog-Api-Key"] == "fake-secret"
            assert r.url.params["skipHttpRedirect"] == "true"
            return httpx.Response(200, json={"photoUri": "https://lh3.googleusercontent.com/test"})
        assert "X-Goog-Api-Key" not in r.headers
        return httpx.Response(200, content=b"test-image", headers={"content-type": "image/jpeg"})

    assert adapter(handler).photo(NAME) == (b"test-image", "image/jpeg")
    assert len(calls) == 2


def setup(client, db, monkeypatch):
    login(client, db)
    create_batch(client)
    upload(client, "b1", CSV_A)
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    lead.raw = {"existing": "kept"}
    db.commit()
    get_settings().google_places_api_key = "fake-secret"
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"places": [PLACE]} if r.method == "POST" else PLACE)
    )
    real = routes._client

    def factory(db, op, lead_id):
        c = real(db, op, lead_id)
        c.transport = transport
        return c

    monkeypatch.setattr(routes, "_client", factory)
    return lead.id


def search(client, lead_id):
    r = client.post(f"/api/leads/{lead_id}/google-places/search", json={})
    assert r.status_code == 200, r.text
    return r.json()["candidates"][0]["token"]


def confirm(client, lead_id, token, **changes):
    return client.post(
        f"/api/leads/{lead_id}/google-places/confirm",
        json={"token": token, "address_checked": True, "branch_checked": True, **changes},
    )


def test_auth_missing_config_and_no_store(client, db):
    r = client.get(f"/api/leads/{uuid.uuid4()}/google-places")
    assert r.status_code == 401 and "no-store" in r.headers["cache-control"]
    login(client, db)
    create_batch(client)
    upload(client, "b1", CSV_A)
    lead = db.scalar(select(Lead).where(Lead.name == "Vesper"))
    r = client.post(f"/api/leads/{lead.id}/google-places/search", json={})
    assert r.status_code == 503 and "no-store" in r.headers["cache-control"]


def test_search_and_details_never_persist_content(client, db, monkeypatch):
    lead_id = setup(client, db, monkeypatch)
    token = search(client, lead_id)
    db.expire_all()
    assert db.get(Lead, lead_id).raw == {"existing": "kept"}
    assert confirm(client, lead_id, token, branch_checked=False).status_code == 400
    result = confirm(client, lead_id, token)
    assert result.status_code == 200
    db.expire_all()
    lead = db.get(Lead, lead_id)
    assert lead.raw["existing"] == "kept" and lead.website is None
    assert set(lead.raw["google_places_link"]) == {"place_id", "version", "reviewed_by", "reviewed_at"}
    r = client.post(f"/api/leads/{lead_id}/google-places/details")
    assert r.status_code == 200 and r.json()["photos"][0]["authors"][0]["displayName"] == "Test Author"
    assert r.json()["place"]["photos"] == []
    db.expire_all()
    logs = db.scalars(select(AuditLog)).all()
    saved = json.dumps([{"before": entry.before, "after": entry.after} for entry in logs]) + json.dumps(lead.raw)
    assert "Synthetic Test Restaurant" not in saved and "Test Road" not in saved and NAME not in saved
    assert "fake-secret" not in saved
    assert [entry.after["sku"] for entry in logs if entry.action == "google_places_request"] == [
        "Text Search Pro",
        "Place Details Enterprise",
    ]


def test_stale_tampered_cross_lead_and_expired_tokens(client, db, monkeypatch):
    lead_id = setup(client, db, monkeypatch)
    token = search(client, lead_id)
    assert confirm(client, lead_id, token + "x").status_code == 409
    other = db.scalar(select(Lead).where(Lead.name != "Vesper"))
    assert confirm(client, other.id, token).status_code == 409
    future = time.time() + 1000
    monkeypatch.setattr(routes.time, "time", lambda: future)
    assert confirm(client, lead_id, token).status_code == 409


def test_link_changes_invalidate_old_search_and_photos(client, db, monkeypatch):
    lead_id = setup(client, db, monkeypatch)
    token = search(client, lead_id)
    link = confirm(client, lead_id, token).json()
    assert confirm(client, lead_id, token).status_code == 409
    details = client.post(f"/api/leads/{lead_id}/google-places/details").json()
    photo_token = details["photos"][0]["token"]
    assert (
        client.post(f"/api/leads/{lead_id}/google-places/unlink", json={"expected_version": "wrong"}).status_code == 409
    )
    assert (
        client.post(
            f"/api/leads/{lead_id}/google-places/unlink", json={"expected_version": link["version"]}
        ).status_code
        == 204
    )
    assert client.post(f"/api/leads/{lead_id}/google-places/photo", json={"token": photo_token}).status_code == 409
    assert client.post(f"/api/leads/{lead_id}/google-places/details").status_code == 400
    db.expire_all()
    assert db.get(Lead, lead_id).raw["existing"] == "kept"
    assert "google_places_link" not in db.get(Lead, lead_id).raw
    assert confirm(client, lead_id, token).status_code == 409


def test_lead_change_during_search_cannot_issue_stale_token(client, db, monkeypatch):
    lead_id = setup(client, db, monkeypatch)
    old_search = google.PlacesClient.search

    def change(c, query):
        lead = db.get(Lead, lead_id)
        lead.postcode = "DIFFERENT"
        db.commit()
        return old_search(c, query)

    monkeypatch.setattr(google.PlacesClient, "search", change)
    assert client.post(f"/api/leads/{lead_id}/google-places/search", json={}).status_code == 409


def test_project_limit_counts_failed_requests(client, db, monkeypatch):
    lead_id = setup(client, db, monkeypatch)
    get_settings().google_places_daily_limit = 2
    real = routes._client

    def factory(db, op, lid):
        c = real(db, op, lid)
        c.transport = httpx.MockTransport(lambda r: httpx.Response(500))
        return c

    monkeypatch.setattr(routes, "_client", factory)
    assert client.post(f"/api/leads/{lead_id}/google-places/search", json={}).status_code == 502
    assert client.post(f"/api/leads/{lead_id}/google-places/search", json={}).status_code == 429
    db.expire_all()
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "google_places_request")).all()) == 2


def test_photo_bytes_no_store_and_no_disk(client, db, monkeypatch, tmp_path):
    lead_id = setup(client, db, monkeypatch)
    token = search(client, lead_id)
    confirm(client, lead_id, token)
    details = client.post(f"/api/leads/{lead_id}/google-places/details").json()
    get_settings().data_dir = tmp_path
    monkeypatch.setattr(google.PlacesClient, "photo", lambda c, name: (b"synthetic-image", "image/jpeg"))
    r = client.post(f"/api/leads/{lead_id}/google-places/photo", json={"token": details["photos"][0]["token"]})
    assert r.status_code == 200 and r.content == b"synthetic-image"
    assert "no-store" in r.headers["cache-control"] and "image/jpeg" in r.headers["content-type"]
    assert not list(tmp_path.iterdir())


def test_google_website_requires_review_and_preserves_history(client, db, monkeypatch):
    monkeypatch.setitem(PLACE, "websiteUri", "https://new-restaurant.example/menu")
    lead_id = setup(client, db, monkeypatch)
    client.patch(f"/api/leads/{lead_id}", json={"website": "https://old.example", "website_source": "Overture"})
    lead = db.get(Lead, lead_id)
    lead.raw = {**lead.raw, "contacts_scan": {"website": "https://old.example"}}
    db.commit()
    assert confirm(client, lead_id, search(client, lead_id)).status_code == 200
    token = client.post(f"/api/leads/{lead_id}/google-places/details").json()["website_token"]
    db.expire_all()
    assert db.get(Lead, lead_id).website == "https://old.example"
    body = {
        "token": token,
        "address_checked": True,
        "official_checked": True,
        "evidence": "Address and operator checked",
    }
    url = f"/api/leads/{lead_id}/google-places/website-confirm"
    assert client.post(url, json={**body, "official_checked": False}).status_code == 400
    assert client.post(url, json={**body, "evidence": " "}).status_code == 400
    assert client.post(url, json={**body, "token": token + "x"}).status_code == 409
    r = client.post(url, json=body)
    assert r.status_code == 200 and r.json()["refresh_required"] == ["menus", "contacts"]
    db.expire_all()
    lead = db.get(Lead, lead_id)
    assert lead.website == "https://new-restaurant.example/menu"
    assert lead.raw["website_confirmation"]["old_website"] == "https://old.example"
    assert lead.raw["existing"] == "kept" and "contacts_scan" not in lead.raw
    assert client.post(url, json=body).status_code == 409


@pytest.mark.parametrize("change", ["website", "expiry", "unlink"])
def test_google_website_rejects_stale_state(client, db, monkeypatch, change):
    monkeypatch.setitem(PLACE, "websiteUri", "https://new.example")
    lead_id = setup(client, db, monkeypatch)
    link = confirm(client, lead_id, search(client, lead_id)).json()
    token = client.post(f"/api/leads/{lead_id}/google-places/details").json()["website_token"]
    if change == "website":
        client.patch(f"/api/leads/{lead_id}", json={"website": "https://edited.example"})
    elif change == "expiry":
        future = time.time() + 1000
        monkeypatch.setattr(routes.time, "time", lambda: future)
    else:
        client.post(f"/api/leads/{lead_id}/google-places/unlink", json={"expected_version": link["version"]})
    r = client.post(
        f"/api/leads/{lead_id}/google-places/website-confirm",
        json={"token": token, "address_checked": True, "official_checked": True, "evidence": "checked"},
    )
    assert r.status_code == 409


@pytest.mark.parametrize("url", ["http://127.0.0.1", "javascript:alert(1)", "https://user:password@restaurant.example"])
def test_google_website_disallows_private_and_credentials(url):
    assert google.Place.model_validate({**PLACE, "websiteUri": url}).websiteUri is None
