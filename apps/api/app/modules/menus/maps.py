"""单家 Maps 菜单任务；专用浏览器执行器主动领取，不暴露浏览器控制端口。"""

import copy
import hashlib
import secrets
import time
import uuid
from datetime import UTC, datetime
from io import BytesIO

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.config import get_settings
from app.core.db import get_db, get_sessionmaker
from app.core.models import Operator
from app.integrations import fetcher
from app.integrations import maps_menu_browser as browser
from app.modules.leads.models import Lead
from app.modules.menus import service
from app.modules.menus.models import AssetKind, FetchStatus, MenuAsset

router = APIRouter(tags=["maps-menu"])
worker_router = APIRouter(prefix="/api/internal/maps-menu", tags=["maps-menu-worker"])
ACTIVE = {"queued", "running", "analyzing"}
HEARTBEAT = 0.0
LEASE_SECONDS = 900


def now() -> str:
    return datetime.now(UTC).isoformat()


def snapshot(lead: Lead) -> dict:
    return {
        "name": lead.name,
        "address": lead.address,
        "postcode": lead.postcode,
        "website": lead.website,
        "google_places_revision": (lead.raw or {}).get("google_places_revision"),
        "google_places_link": (lead.raw or {}).get("google_places_link"),
    }


def confirmed_place(run: dict) -> bool:
    link = (run.get("snapshot") or {}).get("google_places_link") or {}
    return bool(link.get("place_id") and link.get("reviewed_at"))


def locked(db: Session, lead_id: uuid.UUID) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update().execution_options(populate_existing=True))
    if not lead:
        raise HTTPException(404, "线索不存在")
    return lead


def run_of(lead: Lead) -> dict | None:
    return copy.deepcopy((lead.raw or {}).get("maps_menu_run"))


def write(lead: Lead, run: dict) -> None:
    raw = {**(lead.raw or {}), "maps_menu_run": copy.deepcopy(run)}
    if run.get("observed_name") or run.get("observed_address"):
        history = copy.deepcopy(raw.get("maps_menu_observations") or {})
        history[run["id"]] = {
            "source": "google_maps",
            "observed_at": run.get("observed_at") or run["updated_at"],
            "place_id": ((run.get("snapshot") or {}).get("google_places_link") or {}).get("place_id"),
            "name": run.get("observed_name"),
            "address": run.get("observed_address"),
            "website": run.get("observed_website"),
            "maps_url": run["maps_url"],
            "original": copy.deepcopy(run.get("snapshot")),
            "asset_ids": [item["asset_id"] for item in run["images"]],
        }
        raw["maps_menu_observations"] = history
    lead.raw = raw


def public(run: dict | None) -> dict | None:
    if not run:
        return None
    result = {k: v for k, v in run.items() if k not in {"lease", "snapshot", "operator_id"}}
    result["target"] = {key: (run.get("snapshot") or {}).get(key) for key in ("name", "address", "postcode", "website")}
    return result


def recover(lead: Lead) -> None:
    run = run_of(lead)
    if run and run["status"] in ACTIVE:
        age = (datetime.now(UTC) - datetime.fromisoformat(run["updated_at"])).total_seconds()
        if age > LEASE_SECONDS:
            run.update(status="interrupted", stage="已中断", message="执行器中断或任务超时，请重试；已入库文件会去重")
            write(lead, run)


def authorize_worker(authorization: str | None = Header(None)) -> None:
    token = get_settings().maps_worker_token
    if not token or not secrets.compare_digest(authorization or "", "Bearer " + token):
        raise HTTPException(401, "执行器认证失败")


worker_router.dependencies.append(Depends(authorize_worker))


def checked(db: Session, lead_id: uuid.UUID, run_id: str, lease: str) -> tuple[Lead, dict]:
    lead = locked(db, lead_id)
    recover(lead)
    run = run_of(lead)
    if (
        not run
        or run["id"] != run_id
        or run["status"] != "running"
        or not secrets.compare_digest(run.get("lease", ""), lease)
    ):
        db.commit()
        raise HTTPException(409, "任务已过期或被替换")
    if snapshot(lead) != run["snapshot"]:
        run.update(status="conflict", stage="门店资料已改变", message="名称、地址或 Google 关联改变，已停止导入")
        write(lead, run)
        db.commit()
        raise HTTPException(409, "门店资料已改变，请重新运行")
    return lead, run


@router.get("/leads/{lead_id}/maps-menu")
def state(lead_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    lead = locked(db, lead_id)
    recover(lead)
    result = {
        "configured": bool(get_settings().maps_worker_token),
        "worker_online": time.monotonic() - HEARTBEAT < 90,
        "run": public(run_of(lead)),
        "observations": list(((lead.raw or {}).get("maps_menu_observations") or {}).values()),
    }
    db.commit()
    return result


class StartIn(BaseModel):
    show_browser: bool = False


@router.post("/leads/{lead_id}/maps-menu", status_code=202)
def start(
    lead_id: uuid.UUID,
    body: StartIn = StartIn(),
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> dict:
    if not get_settings().maps_worker_token or time.monotonic() - HEARTBEAT >= 90:
        raise HTTPException(503, "Maps 浏览器执行器未连接，请启动执行器后重试")
    lead = locked(db, lead_id)
    recover(lead)
    old = run_of(lead)
    if old and old["status"] in ACTIVE:
        db.commit()
        return public(old) or {}
    if not confirmed_place({"snapshot": snapshot(lead)}) and (not lead.address or not lead.postcode):
        raise HTTPException(400, "请先补充门店地址和邮编，避免获取同名异店的菜单")
    place_id = ((lead.raw or {}).get("google_places_link") or {}).get("place_id")
    try:
        url = browser.maps_url(lead.name, f"{lead.address} {lead.postcode}", place_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    run: dict = {
        "id": uuid.uuid4().hex,
        "status": "queued",
        "stage": "等待浏览器执行器",
        "started_at": now(),
        "updated_at": now(),
        "snapshot": snapshot(lead),
        "operator_id": str(op.id),
        "by": op.username,
        "maps_url": url,
        "images": [],
        "capture_status": None,
        "headless": not body.show_browser,
    }
    write(lead, run)
    audit.record(db, op, "start_maps_menu", "lead", lead.id, after={"run_id": run["id"], "maps_url": url})
    db.commit()
    return public(run) or {}


@worker_router.post("/claim")
def claim(db: Session = Depends(get_db)) -> dict:
    global HEARTBEAT
    HEARTBEAT = time.monotonic()
    # 多执行器也只允许一项浏览器任务；锁覆盖检查和领取。
    db.execute(text("select pg_advisory_xact_lock(466001)"))
    active = list(
        db.scalars(select(Lead).where(Lead.raw["maps_menu_run"]["status"].astext.in_(ACTIVE)).with_for_update())
    )
    for item in active:
        recover(item)
    if any((run_of(lead) or {}).get("status") in {"running", "analyzing"} for lead in active):
        db.commit()
        return {"job": None}
    lead = next((item for item in active if (run_of(item) or {}).get("status") == "queued"), None)
    if not lead:
        db.commit()
        return {"job": None}
    run = run_of(lead)
    assert run is not None
    if snapshot(lead) != run["snapshot"]:
        run.update(status="conflict", stage="门店资料已改变", message="门店资料改变，请重新运行")
        write(lead, run)
        db.commit()
        return {"job": None}
    run.update(status="running", stage="启动专用浏览器", updated_at=now(), lease=secrets.token_urlsafe(32))
    write(lead, run)
    db.commit()
    return {
        "job": {
            "lead_id": str(lead.id),
            "run_id": run["id"],
            "lease": run["lease"],
            "maps_url": run["maps_url"],
            "name": lead.name,
            "address": lead.address,
            "postcode": lead.postcode,
            "confirmed_place": confirmed_place(run),
            "headless": run.get("headless", True),
        }
    }


class ProgressIn(BaseModel):
    lease: str = Field(max_length=128)
    stage: str = Field(max_length=100)


@worker_router.post("/{lead_id}/{run_id}/progress")
def progress(lead_id: uuid.UUID, run_id: str, body: ProgressIn, db: Session = Depends(get_db)) -> dict:
    global HEARTBEAT
    HEARTBEAT = time.monotonic()
    lead, run = checked(db, lead_id, run_id, body.lease)
    run.update(stage=body.stage, updated_at=now())
    write(lead, run)
    db.commit()
    return {"ok": True}


@worker_router.post("/{lead_id}/{run_id}/images")
async def import_image(
    lead_id: uuid.UUID,
    run_id: str,
    file: UploadFile = File(...),
    lease: str = Form(...),
    viewer_url: str = Form(...),
    source_url: str = Form(...),
    observed_name: str = Form(...),
    observed_address: str = Form(...),
    observed_website: str | None = Form(None, max_length=2048),
    db: Session = Depends(get_db),
) -> dict:
    # 限制读取量，并在服务端再次校验来源和门店。浏览器运行不持有数据库锁。
    body = await file.read(browser.MAX_BYTES + 1)
    if len(body) > browser.MAX_BYTES or fetcher.sniff_kind(body, file.content_type) != "image":
        raise HTTPException(400, "图片无效或超过 15 MB")
    try:
        with Image.open(BytesIO(body)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as e:
        raise HTTPException(400, "无法解码菜单图片") from e
    try:
        extracted = browser.photo_url(viewer_url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not extracted or source_url != extracted or len(source_url) > 1024 or len(viewer_url) > 8000:
        raise HTTPException(400, "菜单图片来源不一致")
    lead, run = checked(db, lead_id, run_id, lease)
    if not confirmed_place(run) and not browser.identity_matches(
        lead.name, lead.address or "", lead.postcode or "", observed_name, observed_address
    ):
        raise HTTPException(400, "菜单所在页面与门店不匹配")
    sha = hashlib.sha256(body).hexdigest()
    if len(run["images"]) >= 5 and not any(item["sha256"] == sha for item in run["images"]):
        raise HTTPException(400, "单次最多获取 5 张菜单图片")
    asset = db.scalar(select(MenuAsset).where(MenuAsset.lead_id == lead_id, MenuAsset.sha256 == sha))
    created = asset is None
    if created:
        asset = MenuAsset(
            lead_id=lead_id,
            kind=AssetKind.image,
            source_url=source_url,
            final_url=source_url,
            original_filename="Google Maps 菜单图片",
            content_type=file.content_type,
            fetch_status=FetchStatus.fetched,
            fetch_attempts=1,
            fetched_at=datetime.now(UTC),
            added_by=run["by"],
        )
        db.add(asset)
        db.flush()
        service._store(asset, body, "image")
    assert asset is not None
    result = {
        "asset_id": str(asset.id),
        "file_url": f"/api/files/{asset.storage_path}",
        "sha256": sha,
        "viewer_url": viewer_url,
        "created": created,
        "date": None,
    }
    if not any(item["sha256"] == sha for item in run["images"]):
        run["images"].append(result)
    run.update(
        stage="菜单图片入库",
        updated_at=now(),
        observed_name=observed_name,
        observed_address=observed_address,
        observed_website=observed_website,
    )
    run.setdefault("observed_at", now())
    write(lead, run)
    audit.record(
        db,
        db.get(Operator, uuid.UUID(run["operator_id"])),
        "import_maps_menu",
        "menu_asset",
        asset.id,
        after={"run_id": run_id, "viewer_url": viewer_url, "sha256": sha, "created": created, "date": None},
    )
    db.commit()
    return result


class FinishIn(BaseModel):
    lease: str = Field(max_length=128)
    capture_status: str = Field(max_length=64)
    thumbnail_count: int = Field(default=0, ge=0, le=10000)
    observed_name: str | None = Field(default=None, max_length=256)
    observed_address: str | None = Field(default=None, max_length=2048)
    observed_website: str | None = Field(default=None, max_length=2048)


@worker_router.post("/{lead_id}/{run_id}/finish")
def finish(
    lead_id: uuid.UUID,
    run_id: str,
    body: FinishIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    lead, run = checked(db, lead_id, run_id, body.lease)
    capture_status = body.capture_status if body.capture_status in browser.MESSAGES else "failed"
    settings = get_settings()
    can_analyze = settings.llm_provider == "deepseek" and bool(settings.deepseek_api_key)
    analyze = can_analyze and any(item["created"] for item in run["images"])
    run.update(
        status="analyzing"
        if analyze
        else "completed"
        if run["images"] and capture_status == "downloaded"
        else "needs_review",
        stage="AI 转录菜单图片" if analyze else "获取结束",
        updated_at=now(),
        capture_status=capture_status,
        thumbnail_count=body.thumbnail_count,
        message=browser.MESSAGES[capture_status],
    )
    if body.observed_name or body.observed_address:
        run.update(
            observed_name=body.observed_name,
            observed_address=body.observed_address,
            observed_website=body.observed_website,
        )
        run.setdefault("observed_at", now())
        run["identity_check"] = browser.identity_check(
            lead.name,
            lead.address or "",
            lead.postcode or "",
            body.observed_name or "",
            body.observed_address or "",
        )
        if confirmed_place(run):
            run["source_notice"] = "按已关联的 Google 门店获取；各来源资料分别保留，不因名称、地址或邮编差异阻止导入"
        if capture_status == "place_mismatch":
            differences = [
                label
                for key, label in (
                    ("name_matches", "名称不同"),
                    ("street_matches", "门牌号或街道不同"),
                    ("postcode_matches", "邮编不同"),
                )
                if not run["identity_check"][key]
            ]
            run["message"] = (
                "、".join(differences) + "，未导入图片。请查看下方门店资料对照；可能存在更名、搬迁或关联错店"
            )
    if run["images"] and not can_analyze:
        run["message"] += "；未配置真实模型，可在菜单文件中手动分析"
    write(lead, run)
    audit.record(
        db,
        db.get(Operator, uuid.UUID(run["operator_id"])),
        "finish_maps_capture",
        "lead",
        lead_id,
        after={"run_id": run_id, "status": capture_status, "images": len(run["images"])},
    )
    db.commit()
    if analyze:
        background.add_task(analyze_images, lead_id, run_id)
    return public(run) or {}


def analyze_images(lead_id: uuid.UUID, run_id: str) -> None:
    with get_sessionmaker()() as db:
        lead = locked(db, lead_id)
        run = run_of(lead)
        if not run or run["id"] != run_id or run["status"] != "analyzing":
            return
        images = copy.deepcopy(run["images"])
        db.commit()
        for item in images:
            # 已有资产及人工审核保持原样，不强制重跑。
            if not item["created"]:
                continue
            asset = db.get(MenuAsset, uuid.UUID(item["asset_id"]))
            if not asset:
                continue
            try:
                analysis, _ = service.run_analysis(db, asset, engine="provider")
                item.update(analysis_id=str(analysis.id), analysis_status=analysis.status.value)
            except Exception:
                db.rollback()
                item["analysis_status"] = "failed"
            lead = locked(db, lead_id)
            latest = run_of(lead)
            if not latest or latest["id"] != run_id or latest["status"] != "analyzing":
                db.commit()
                return
            for entry in latest["images"]:
                if entry["asset_id"] == item["asset_id"]:
                    entry.update(item)
            latest.update(updated_at=now())
            write(lead, latest)
            db.commit()
        lead = locked(db, lead_id)
        latest = run_of(lead)
        if latest and latest["id"] == run_id and latest["status"] == "analyzing":
            failed = any(item.get("analysis_status") == "failed" for item in latest["images"])
            capture_note = ""
            if latest.get("capture_status") != "downloaded":
                capture_note = (
                    "已保留部分菜单图片；"
                    + browser.MESSAGES.get(str(latest.get("capture_status") or "failed"), "获取未完成")
                    + "；"
                )
            latest.update(
                status="needs_review",
                stage="获取与分析结束",
                updated_at=now(),
                message=capture_note
                + (
                    "菜单已入库；部分分析失败，可在菜单文件中重试"
                    if failed
                    else "菜单已入库并完成转录；名称、价格与日期仍待审核"
                ),
            )
            write(lead, latest)
            db.commit()
