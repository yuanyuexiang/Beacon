"""菜单文件接入：URL 抓取或上传；受控存储；失败保留原因并可重试。"""

import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.files import resolve_within, store_bytes
from app.integrations import fetcher
from app.integrations.llm import get_provider
from app.modules.menus import analysis as rules
from app.modules.menus.models import AnalysisStatus, AssetKind, FetchStatus, MenuAnalysis, MenuAsset

EXT = {"pdf": "pdf", "image": "img", "html": "html", "unknown": "bin"}


def _store(asset: MenuAsset, body: bytes, kind: str) -> None:
    rel = f"evidence/{asset.lead_id}/{asset.id}.{EXT[kind]}"
    _, sha = store_bytes(rel, body)
    asset.storage_path = rel
    asset.sha256 = sha
    asset.bytes = len(body)
    asset.kind = AssetKind(kind)


def add_upload(
    db: Session, lead_id: uuid.UUID, filename: str | None, content_type: str | None, body: bytes, by: str
) -> MenuAsset:
    s = get_settings()
    if len(body) > s.max_asset_bytes:
        raise ValueError(f"文件超过大小上限 {s.max_asset_bytes} 字节")
    kind = fetcher.sniff_kind(body, content_type)
    if kind == "unknown":
        raise ValueError("无法识别文件类型（支持 PDF、图片、HTML）")
    asset = MenuAsset(
        lead_id=lead_id,
        original_filename=filename,
        content_type=content_type,
        fetch_status=FetchStatus.fetched,
        fetch_attempts=1,
        fetched_at=datetime.now(UTC),
        added_by=by,
    )
    db.add(asset)
    db.flush()
    _store(asset, body, kind)
    db.commit()
    db.refresh(asset)
    return asset


def add_url(
    db: Session, lead_id: uuid.UUID, url: str, by: str, transport: httpx.BaseTransport | None = None
) -> MenuAsset:
    asset = MenuAsset(lead_id=lead_id, source_url=url, fetch_status=FetchStatus.pending, fetch_attempts=0, added_by=by)
    db.add(asset)
    db.flush()
    return fetch_asset(db, asset, transport=transport)


def fetch_asset(db: Session, asset: MenuAsset, transport: httpx.BaseTransport | None = None) -> MenuAsset:
    """执行/重试抓取。任何失败都写 fetch_error 并置 failed，不抛出。"""
    s = get_settings()
    asset.fetch_attempts += 1
    asset.user_agent = s.fetch_user_agent
    try:
        r = fetcher.fetch(
            asset.source_url or "",
            max_bytes=s.max_asset_bytes,
            timeout=s.fetch_timeout_seconds,
            user_agent=s.fetch_user_agent,
            transport=transport,
            resolve_check=s.fetch_ip_check,
        )
        asset.final_url, asset.http_status, asset.content_type = r.final_url, r.status, r.content_type
        if r.status != 200:
            raise fetcher.FetchBlocked(f"HTTP {r.status}")
        if r.kind == "unknown":
            raise fetcher.FetchBlocked("无法识别内容类型（支持 PDF、图片、HTML）")
        _store(asset, r.body, r.kind)
        asset.fetch_status, asset.fetch_error, asset.fetched_at = FetchStatus.fetched, None, datetime.now(UTC)
    except fetcher.FetchBlocked as e:
        asset.fetch_status, asset.fetch_error = FetchStatus.failed, str(e)
    except httpx.TimeoutException:
        asset.fetch_status, asset.fetch_error = FetchStatus.failed, f"超时（{s.fetch_timeout_seconds}s）"
    except httpx.HTTPError as e:
        asset.fetch_status, asset.fetch_error = FetchStatus.failed, f"网络错误：{e.__class__.__name__}: {e}"
    db.commit()
    db.refresh(asset)
    return asset


# ---------- 分析 ----------


def latest_analysis(db: Session, asset_id: uuid.UUID) -> MenuAnalysis | None:
    return db.scalar(
        select(MenuAnalysis).where(MenuAnalysis.asset_id == asset_id).order_by(MenuAnalysis.version.desc()).limit(1)
    )


def run_analysis(
    db: Session, asset: MenuAsset, engine: str = "rules", force: bool = False
) -> tuple[MenuAnalysis, bool]:
    """创建新分析版本。返回 (analysis, created)。同引擎、同版本、同输入 hash 且状态非 failed 时复用，不重复创建。"""
    if asset.fetch_status != FetchStatus.fetched or not asset.storage_path:
        raise ValueError("文件尚未成功获取，不能分析")
    engine_version = rules.RULES_VERSION if engine == "rules" else None
    if engine != "rules":
        provider = get_provider()
        engine, engine_version = provider.name, "0"
    latest = latest_analysis(db, asset.id)
    if (
        latest is not None
        and not force
        and latest.engine == engine
        and latest.engine_version == engine_version
        and latest.input_sha256 == asset.sha256
        and latest.status != AnalysisStatus.failed
    ):
        return latest, False
    version = (latest.version + 1) if latest else 1
    a = MenuAnalysis(
        asset_id=asset.id,
        version=version,
        status=AnalysisStatus.running,
        engine=engine,
        engine_version=engine_version,
        input_sha256=asset.sha256,
    )
    db.add(a)
    db.flush()
    try:
        data = resolve_within(asset.storage_path).read_bytes()
        if engine == "rules":
            r = rules.analyze(asset.kind.value, data, asset.final_url or asset.source_url)
            a.items, a.measurements, a.issues = r.items, r.measurements, r.issues
            a.status = AnalysisStatus(r.status)
            a.error = r.note
        else:
            pr = (
                provider.analyze_image(data, {})
                if asset.kind == AssetKind.image
                else provider.analyze_text(data.decode("utf-8", "ignore"), {})
            )
            a.items, a.issues, a.measurements = (
                pr.items,
                pr.issues,
                {"kind": asset.kind.value, "provider_notes": pr.notes},
            )
            a.status = AnalysisStatus.needs_review  # 模型结果一律需人工核对
            a.error = pr.notes
    except Exception as e:  # 解析异常：明确失败，不伪装成功
        a.status, a.error = AnalysisStatus.failed, f"{e.__class__.__name__}: {e}"
    db.commit()
    db.refresh(a)
    return a, True
