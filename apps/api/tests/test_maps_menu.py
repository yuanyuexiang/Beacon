import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.integrations import maps_menu_browser as browser
from app.modules.leads.models import Lead
from app.modules.menus import maps
from app.modules.menus.models import MenuAsset
from tests.test_imports import login

TOKEN = "maps-worker-test-token-0123456789abcdef"
AUTH = {"Authorization": "Bearer " + TOKEN}
VIEWER = "https://www.google.com/maps/place/College/data=!6shttps://lh3.googleusercontent.com/p/qa=w100-h100-k-no!7i100!8i100"
SOURCE = browser.photo_url(VIEWER)
_buffer = BytesIO()
Image.new("RGB", (32, 32), "white").save(_buffer, format="PNG")
IMAGE = _buffer.getvalue()


@pytest.fixture
def setup(client, db, monkeypatch):
    login(client, db)
    monkeypatch.setattr(get_settings(), "maps_worker_token", TOKEN)
    monkeypatch.setattr(maps, "HEARTBEAT", time.monotonic())
    lead = Lead(
        source_key="qa:maps",
        source_name="qa",
        name="THE COLLEGE BAR AND DELI",
        address="9 Alford Place, Aberdeen",
        postcode="AB10 1YD",
    )
    db.add(lead)
    db.commit()
    return str(lead.id)


def start_claim(client, lid):
    response = client.post(f"/api/leads/{lid}/maps-menu")
    assert response.status_code == 202, response.text
    run = response.json()
    job = client.post("/api/internal/maps-menu/claim", headers=AUTH).json()["job"]
    return run, job


def upload(client, job, **overrides):
    fields = {
        "lease": job["lease"],
        "viewer_url": VIEWER,
        "source_url": SOURCE,
        "observed_name": "College Bar",
        "observed_address": "Address: 9 Alford Place, Aberdeen AB10 1YD",
    }
    fields.update(overrides)
    return client.post(
        f"/api/internal/maps-menu/{job['lead_id']}/{job['run_id']}/images",
        headers=AUTH,
        data=fields,
        files={"file": ("menu.png", IMAGE, "image/png")},
    )


def test_start_claim_import_finish_and_deduplicate(client, db, setup):
    lid = setup
    run, job = start_claim(client, lid)
    assert job and "lease" not in run and "snapshot" not in run
    assert client.post(f"/api/leads/{lid}/maps-menu").json()["id"] == run["id"]
    assert client.post("/api/internal/maps-menu/claim", headers=AUTH).json()["job"] is None
    uploaded = upload(client, job)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["created"]
    assert upload(client, job).json()["created"] is False
    done = client.post(
        f"/api/internal/maps-menu/{lid}/{run['id']}/finish",
        headers=AUTH,
        json={"lease": job["lease"], "capture_status": "downloaded", "thumbnail_count": 1},
    )
    assert done.json()["status"] == "completed"
    assert len(done.json()["images"]) == 1 and done.json()["images"][0]["date"] is None
    assets = list(db.scalars(select(MenuAsset)))
    assert len(assets) == 1 and assets[0].sha256 == hashlib.sha256(IMAGE).hexdigest()
    assert len(assets[0].analyses) == 0
    _, next_job = start_claim(client, lid)
    assert upload(client, next_job).json()["asset_id"] == str(assets[0].id)
    assert len(list(db.scalars(select(MenuAsset)))) == 1


def test_auth_offline_and_lease_guards(client, db, setup, monkeypatch):
    lid = setup
    assert client.post("/api/internal/maps-menu/claim").status_code == 401
    assert client.post("/api/internal/maps-menu/claim", headers={"Authorization": "Bearer bad"}).status_code == 401
    monkeypatch.setattr(maps, "HEARTBEAT", 0)
    assert client.post(f"/api/leads/{lid}/maps-menu").status_code == 503
    client.post("/api/internal/maps-menu/claim", headers=AUTH)
    run, job = start_claim(client, lid)
    assert upload(client, job, lease="bad").status_code == 409
    assert "lease" not in client.get(f"/api/leads/{lid}/maps-menu").json()["run"]
    client.cookies.clear()
    assert client.get(f"/api/leads/{lid}/maps-menu").status_code == 401
    assert client.post(f"/api/leads/{lid}/maps-menu").status_code == 401


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "Other Branch"),
        ("address", "99 Other Road"),
        ("postcode", "AB1 1AA"),
        ("raw", {"google_places_revision": "new"}),
    ],
)
def test_changed_branch_blocks_import(client, db, setup, field, value):
    _, job = start_claim(client, setup)
    lead = db.get(Lead, uuid.UUID(setup))
    setattr(lead, field, {**(lead.raw or {}), **value} if field == "raw" else value)
    db.commit()
    assert upload(client, job).status_code == 409
    assert client.get(f"/api/leads/{setup}/maps-menu").json()["run"]["status"] == "conflict"
    assert not list(db.scalars(select(MenuAsset)))


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_url": "https://localhost/menu.png"},
        {"viewer_url": "https://evil.example/maps/"},
        {"observed_address": "Address: 99 Alford Place, Aberdeen AB10 1YD"},
        {"observed_name": "Another Bar"},
    ],
)
def test_sources_and_identity_rechecked_on_server(client, db, setup, overrides):
    _, job = start_claim(client, setup)
    assert upload(client, job, **overrides).status_code == 400
    assert not list(db.scalars(select(MenuAsset)))


def test_interrupted_worker_can_retry_and_reject_old_upload(client, db, setup):
    run, job = start_claim(client, setup)
    lead = db.get(Lead, uuid.UUID(setup))
    raw = dict(lead.raw)
    raw["maps_menu_run"] = {
        **raw["maps_menu_run"],
        "updated_at": (datetime.now(UTC) - timedelta(minutes=20)).isoformat(),
    }
    lead.raw = raw
    db.commit()
    assert client.get(f"/api/leads/{setup}/maps-menu").json()["run"]["status"] == "interrupted"
    newer, _ = start_claim(client, setup)
    assert newer["id"] != run["id"]
    assert upload(client, job).status_code == 409


def test_capture_failure_is_visible(client, db, setup):
    run, job = start_claim(client, setup)
    response = client.post(
        f"/api/internal/maps-menu/{setup}/{run['id']}/finish",
        headers=AUTH,
        json={"lease": job["lease"], "capture_status": "limited_view"},
    )
    assert response.json()["status"] == "needs_review"
    assert "不一定需要登录" in response.json()["message"]
    assert response.json()["images"] == []


def test_identity_and_source_helpers():
    assert browser.identity_matches(
        "THE COLLEGE BAR AND DELI",
        "9 Alford Place, Aberdeen",
        "AB10 1YD",
        "College Bar",
        "9 Alford Place, Aberdeen AB10 1YD",
    )
    assert not browser.identity_matches(
        "College", "9 Alford Place", "AB10 1YD", "College", "9 Alford Place, Glasgow G1 1AA"
    )
    assert browser.photo_url(VIEWER) == SOURCE
    assert "query_place_id=qa" in browser.maps_url("College Bar", "Aberdeen", "qa")
    with pytest.raises(ValueError):
        browser.maps_url("College Bar", "Aberdeen", "bad!id")


def test_street_abbreviation_matches_but_house_number_does_not():
    assert browser.identity_matches(
        "College Bar", "9 Alford Place", "AB10 1YD", "College Bar", "Address: 9 Alford Pl, Aberdeen AB10 1YD"
    )
    assert not browser.identity_matches(
        "College Bar", "9 Alford Place", "AB10 1YD", "College Bar", "Address: 99 Alford Pl, Aberdeen AB10 1YD"
    )


def test_real_provider_path_transcribes_but_never_reviews(client, db, setup, monkeypatch):
    from app.integrations.llm import FakeProvider
    from app.modules.menus import service
    from app.modules.menus.models import MenuAnalysis

    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-key")
    monkeypatch.setattr(service, "get_provider", lambda: FakeProvider())
    run, job = start_claim(client, setup)
    assert upload(client, job).status_code == 200
    client.post(
        f"/api/internal/maps-menu/{setup}/{run['id']}/finish",
        headers=AUTH,
        json={"lease": job["lease"], "capture_status": "downloaded"},
    )
    state = client.get(f"/api/leads/{setup}/maps-menu").json()["run"]
    assert state["status"] == "needs_review" and state["images"][0]["analysis_status"] == "needs_review"
    analysis = db.scalar(select(MenuAnalysis))
    assert analysis.review_state is None
    analysis.review_state = "reviewed"
    analysis.reviewed_by = "qa"
    db.commit()
    second, next_job = start_claim(client, setup)
    assert upload(client, next_job).json()["created"] is False
    client.post(
        f"/api/internal/maps-menu/{setup}/{second['id']}/finish",
        headers=AUTH,
        json={"lease": next_job["lease"], "capture_status": "downloaded"},
    )
    db.expire_all()
    assert len(list(db.scalars(select(MenuAnalysis)))) == 1
    assert db.get(MenuAnalysis, analysis.id).review_state == "reviewed"


def test_partial_capture_keeps_timeout_reason_after_transcription(client, db, setup, monkeypatch):
    from app.integrations.llm import FakeProvider
    from app.modules.menus import service

    monkeypatch.setattr(get_settings(), "llm_provider", "deepseek")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-key")
    monkeypatch.setattr(service, "get_provider", lambda: FakeProvider())
    run, job = start_claim(client, setup)
    assert upload(client, job).status_code == 200
    client.post(
        f"/api/internal/maps-menu/{setup}/{run['id']}/finish",
        headers=AUTH,
        json={"lease": job["lease"], "capture_status": "timeout"},
    )
    result = client.get(f"/api/leads/{setup}/maps-menu").json()["run"]
    assert len(result["images"]) == 1
    assert "超时" in result["message"] and "已保留部分" in result["message"]


def test_legal_suffix_and_shop_prefix_match_without_ignoring_other_brand():
    assert browser.identity_matches(
        "SECOND HOME STUDIO + CAFE CIC",
        "Shop, 1 Gaelic Lane, Aberdeen",
        "AB10 1JF",
        "Second Home Studio + Cafe",
        "Address: 1 Gaelic Ln, Aberdeen AB10 1JF",
    )
    renamed = browser.identity_check(
        "SECOND HOME STUDIO + CAFE CIC",
        "Shop, 1 Gaelic Lane, Aberdeen",
        "AB10 1JF",
        "Gaelic Lane Cafe + Bar",
        "Address: 1 Gaelic Ln, Aberdeen AB10 1JF",
    )
    assert renamed == {"name_matches": False, "street_matches": True, "postcode_matches": True}
    moved = browser.identity_check(
        "YOUR LOVE RARA COMMUNITY INTEREST COMPANY",
        "25 Castle Street, Castlegate, Aberdeen",
        "AB11 5BG",
        "Your Love Rara",
        "Address: 12-14 Justice St, Aberdeen AB11 5HR",
    )
    assert moved == {"name_matches": True, "street_matches": False, "postcode_matches": False}


def test_mismatch_finish_records_comparison_and_specific_reason(client, db, setup):
    run, job = start_claim(client, setup)
    client.post(
        f"/api/internal/maps-menu/{setup}/{run['id']}/finish",
        headers=AUTH,
        json={
            "lease": job["lease"],
            "capture_status": "place_mismatch",
            "observed_name": "College Bar",
            "observed_address": "99 Alford Pl, Aberdeen AB10 1YD",
        },
    )
    result = client.get(f"/api/leads/{setup}/maps-menu").json()["run"]
    assert result["target"]["name"] == "THE COLLEGE BAR AND DELI"
    assert result["observed_name"] == "College Bar"
    assert result["identity_check"] == {"name_matches": True, "street_matches": False, "postcode_matches": True}
    assert "门牌号或街道不同" in result["message"] and "名称不同" not in result["message"]
    assert not result["images"]


def test_confirmed_place_keeps_different_source_data_and_history(client, db, setup):
    lead = db.get(Lead, uuid.UUID(setup))
    original = (lead.name, lead.address, lead.postcode)
    lead.raw = {"google_places_link": {"place_id": "ChIJtest", "reviewed_at": datetime.now(UTC).isoformat()}}
    db.commit()
    for index in range(2):
        run, job = start_claim(client, setup)
        assert job["confirmed_place"] is True
        result = upload(client, job, observed_name="New Brand", observed_address="12 Justice St AB11 5HR")
        assert result.status_code == 200, result.text
        response = client.post(
            f"/api/internal/maps-menu/{setup}/{run['id']}/finish",
            headers=AUTH,
            json={
                "lease": job["lease"],
                "capture_status": "downloaded",
                "observed_name": "New Brand",
                "observed_address": "12 Justice St AB11 5HR",
                "observed_website": "https://example.com/menu",
            },
        )
        assert response.status_code == 200
        assert response.json()["source_notice"]
        state = client.get(f"/api/leads/{setup}/maps-menu").json()
        assert len(state["observations"]) == index + 1
        assert state["observations"][-1]["asset_ids"] == [result.json()["asset_id"]]
        assert state["observations"][-1]["website"] == "https://example.com/menu"
    db.refresh(lead)
    assert (lead.name, lead.address, lead.postcode) == original


def test_confirmed_place_does_not_require_old_address(client, db, setup):
    lead = db.get(Lead, uuid.UUID(setup))
    lead.address = None
    lead.postcode = None
    lead.raw = {"google_places_link": {"place_id": "ChIJtest", "reviewed_at": datetime.now(UTC).isoformat()}}
    db.commit()
    _, job = start_claim(client, setup)
    assert job["confirmed_place"]


@pytest.mark.parametrize(
    "body,headless", [(None, True), ({}, True), ({"show_browser": True}, False), ({"show_browser": False}, True)]
)
def test_browser_mode_is_saved_and_delivered(client, setup, body, headless):
    response = client.post(f"/api/leads/{setup}/maps-menu", **({"json": body} if body is not None else {}))
    assert response.status_code == 202, response.text
    assert response.json()["headless"] is headless
    # 活跃任务复用原模式，开关不改变已经启动的浏览器。
    repeated = client.post(f"/api/leads/{setup}/maps-menu", json={"show_browser": headless})
    assert repeated.json()["headless"] is headless
    job = client.post("/api/internal/maps-menu/claim", headers=AUTH).json()["job"]
    assert job["headless"] is headless
