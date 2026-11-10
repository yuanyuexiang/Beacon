"""Device result and screenshot roundtrip; no real phones or sends."""

import base64
import io

from PIL import Image
from sqlalchemy import select

from app.modules.mobile.models import Execution
from tests.test_assignment import person
from tests.test_mobile import enqueue, setup
from tests.test_users import session


def test_unregistered_result_and_private_screenshot_roundtrip(client, db):
    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    claim = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    picture = io.BytesIO()
    Image.new("RGB", (40, 80), "white").save(picture, "PNG")
    args = {
        "lease": claim["lease"],
        "attempt": claim["attempt"],
        "status": "unavailable",
        "detail": "此号码没有 WhatsApp 账户",
        "reason_code": "not_registered",
        "screenshot": base64.b64encode(picture.getvalue()).decode(),
    }
    url = f"/api/mobile/device/jobs/{job['id']}/result"
    for _ in range(2):
        response = client.post(url, headers=headers, json=args)
        assert response.status_code == 200, response.text
    result = client.get(f"/api/mobile/tasks/{tid}").json()
    assert result["reason_code"] == "not_registered"
    assert "screenshot" not in result and result["status"] == "unavailable"
    image = client.get(result["screenshot_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert {v.strip() for v in image.headers["cache-control"].split(",")} == {"private", "no-store"}
    outsider = session(person(db, "other-sales", "member"))
    assert outsider.get(result["screenshot_url"]).status_code == 404
    assert Image.open(io.BytesIO(image.content)).size == (40, 80)
    # Read-only operators without a session cannot fetch evidence.
    client.cookies.clear()
    assert client.get(result["screenshot_url"]).status_code == 401


def test_bad_screenshot_does_not_commit_a_result(client, db):
    tid, device, headers, _ = setup(client, db)
    job, _ = enqueue(client, tid, device)
    claim = client.post("/api/mobile/device/claim", headers=headers).json()["job"]
    args = {"lease": claim["lease"], "attempt": claim["attempt"], "status": "failed", "screenshot": "not-an-image"}
    assert client.post(f"/api/mobile/device/jobs/{job['id']}/result", headers=headers, json=args).status_code == 422
    db.expire_all()
    assert db.scalar(select(Execution)).status == "claimed"
    args.pop("screenshot")
    assert client.post(f"/api/mobile/device/jobs/{job['id']}/result", headers=headers, json=args).status_code == 200
    assert client.get(f"/api/mobile/tasks/{tid}/screenshot").status_code == 404
