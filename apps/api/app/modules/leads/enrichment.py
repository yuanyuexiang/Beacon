"""单家持续完善：复用名单队列与业务服务，读取状态不触发外部调用。"""

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.db import get_db
from app.core.models import Operator
from app.integrations.ai_runtime import revision as ai_revision
from app.integrations.ai_runtime import workflow_scope
from app.modules.leads import policy, runs, service, website_review, workflows
from app.modules.leads.models import Batch, BatchLead, Lead
from app.modules.menus import service as menus
from app.modules.menus.models import MenuAsset

router = APIRouter(tags=["lead-enrichment"])
KEYS = ("website", "contacts", "menus", "analysis")
ACTIVE = {"pending", "running"}


class EnrichmentIn(BaseModel):
    mode: Literal["continue", "refresh"] = "continue"
    items: list[Literal["website", "contacts", "menus", "analysis"]] = Field(
        default=["website", "contacts", "menus", "analysis"], min_length=1, max_length=4
    )


def get_lead(db: Session, identity: uuid.UUID) -> Lead:
    lead = db.get(Lead, identity)
    if lead is None:
        raise HTTPException(404, "门店不存在")
    return lead


def batches(db: Session, lead: Lead) -> list[Batch]:
    return list(db.scalars(select(Batch).join(BatchLead).where(BatchLead.lead_id == lead.id).order_by(Batch.id)))


def active(db: Session, lead: Lead) -> workflows.Workflow | None:
    memberships = select(BatchLead.batch_id).where(BatchLead.lead_id == lead.id)
    tasks = db.scalars(
        select(workflows.Workflow)
        .where(workflows.Workflow.batch_id.in_(memberships), workflows.Workflow.status.in_(ACTIVE))
        .order_by(workflows.Workflow.created_at.desc())
    )
    return next((t for t in tasks if not t.params.get("lead_ids") or str(lead.id) in t.params["lead_ids"]), None)


def fresh(value: str | None, days: int) -> bool:
    try:
        return datetime.now(UTC) - datetime.fromisoformat(value or "") < timedelta(days=days)
    except (ValueError, TypeError):
        return False


def items(db: Session, lead: Lead) -> list[dict]:
    raw = lead.raw or {}
    days = policy.current(db).stale_days
    review = raw.get("website_research") or {}
    scan = raw.get("contacts_scan") or {}
    assets = list(db.scalars(select(MenuAsset).where(MenuAsset.lead_id == lead.id)))
    fetched = [a for a in assets if a.fetch_status == "fetched"]
    latest = [menus.latest_analysis(db, a.id) for a in fetched]
    pending = sum(
        not a or a.status == "failed" or a.input_sha256 != asset.sha256
        for asset, a in zip(fetched, latest, strict=True)
    )
    checks = [
        (
            "website",
            "门店与官网",
            not lead.website or website_review.needed(lead, days) or review.get("status") != "verified",
            review.get("checked_at"),
            review.get("reason") or ("已有官网，可继续核验最新资料" if lead.website else "尚未取得官网"),
        ),
        (
            "contacts",
            "联系方式",
            runs._needs_contact_scan(lead) or not fresh(scan.get("at"), days),
            scan.get("at"),
            f"已有候选 {scan.get('found', 0)} 项；页面读取失败 {scan.get('pages_failed', 0)} 页"
            if scan
            else "尚未查找联系方式",
        ),
        (
            "menus",
            "菜单获取",
            bool(raw.get("website_refresh_required", {}).get("menus"))
            or not fetched
            or any(not fresh(a.fetched_at.isoformat() if a.fetched_at else None, days) for a in fetched),
            max((a.fetched_at.isoformat() for a in fetched if a.fetched_at), default=None),
            f"已保存 {len(fetched)} 份菜单；可上传其他渠道取得的文件"
            if fetched
            else "尚无菜单；也可直接准备询问菜单的消息",
        ),
        (
            "analysis",
            "菜单 AI 分析",
            bool(pending) or not fetched,
            max((a.created_at.isoformat() for a in latest if a), default=None),
            f"待分析 {pending} 份；已核对结果保留" if fetched else "取得菜单后再分析",
        ),
    ]
    output = [
        dict(key=k, title=title, needed=need, updated_at=at, description=description)
        for k, title, need, at, description in checks
    ]
    for item in output:
        record = (raw.get("single_enrichment") or {}).get(item["key"]) or {}
        if record and record.get("snapshot") == website_review.snapshot(lead):
            item["updated_at"] = record.get("at") or item["updated_at"]
            if record.get("status") == "failed":
                item["needed"] = True
                item["description"] = record.get("message") or item["description"]
            elif item["key"] == "menus" and fetched and fresh(record.get("at"), days):
                item["needed"] = False
    return output


def task_view(task: workflows.Workflow | None, lead: Lead) -> dict | None:
    if task is None:
        return None
    single = task.kind == "single" and task.params.get("lead_ids") == [str(lead.id)]
    return {
        "id": str(task.id),
        "status": task.status,
        "step": task.step,
        "steps": task.steps,
        "single": single,
        "results": task.results if single else [],
        "error": task.error if single else None,
        "updated_at": task.updated_at.isoformat(),
        "message": "正在完善这家门店" if single else "已有名单任务包含这家门店，沿用该任务进度",
    }


@router.get("/leads/{lead_id}/enrichment")
def state(lead_id: uuid.UUID, db: Session = Depends(get_db)):
    lead = get_lead(db, lead_id)
    task = active(db, lead)
    if task is None:
        task = db.scalar(
            select(workflows.Workflow)
            .where(workflows.Workflow.kind == "single", workflows.Workflow.params["lead_ids"].contains([str(lead.id)]))
            .order_by(workflows.Workflow.created_at.desc())
            .limit(1)
        )
    return {"items": items(db, lead), "task": task_view(task, lead)}


@router.post("/leads/{lead_id}/enrichment", status_code=202)
def start(
    lead_id: uuid.UUID, body: EnrichmentIn, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    lead = get_lead(db, lead_id)
    owners = batches(db, lead)
    if not owners:
        raise HTTPException(409, "门店尚未加入名单，请先加入名单")
    with ExitStack() as stack:
        for batch in owners:
            stack.enter_context(workflows.lock(db, batch))
        existing = active(db, lead)
        if existing:
            return {"task": task_view(existing, lead), "reused": True}
        from app.modules.leads import auto_research

        research = auto_research.run_of(lead)
        if research and research.get("status") in auto_research.ACTIVE:
            raise HTTPException(409, "菜单自动研究正在执行，请在菜单资料中查看进度")
        selected = [
            x["key"] for x in items(db, lead) if x["key"] in body.items and (body.mode == "refresh" or x["needed"])
        ]
        if not selected:
            return {"task": None, "reused": True, "message": "所选资料已齐全且未过期，可使用重新完善主动更新"}
        task = workflows.Workflow(
            batch_id=owners[0].id,
            kind="single",
            status="pending",
            step=0,
            steps=selected,
            params={
                "ai_revision": ai_revision(db),
                "lead_ids": [str(lead.id)],
                "mode": body.mode,
                "background": True,
                "policy": policy.current(db).model_dump(),
            },
            results=[],
            started_by=op.username,
        )
        db.add(task)
        db.flush()
        audit.record(
            db,
            op,
            "start_lead_enrichment",
            "lead",
            lead.id,
            after={"task_id": str(task.id), "mode": body.mode, "items": selected},
        )
        db.commit()
        return {"task": task_view(task, lead), "reused": False}


@router.post("/leads/{lead_id}/enrichment/{task_id}/cancel")
def cancel(
    lead_id: uuid.UUID, task_id: uuid.UUID, db: Session = Depends(get_db), op: Operator = Depends(current_operator)
):
    lead = get_lead(db, lead_id)
    task = db.get(workflows.Workflow, task_id)
    if not task or task.kind != "single" or task.params.get("lead_ids") != [str(lead.id)]:
        raise HTTPException(404, "单家完善任务不存在；名单任务请在名单页面管理")
    db.execute(
        update(workflows.Workflow)
        .where(workflows.Workflow.id == task.id, workflows.Workflow.status.in_(ACTIVE))
        .values(status="cancelled")
    )
    audit.record(db, op, "cancel_lead_enrichment", "lead", lead.id, after={"task_id": str(task.id)})
    db.commit()
    db.refresh(task)
    return task_view(task, lead)


def execute_item(db: Session, batch: Batch, task: workflows.Workflow, lead: Lead, op: Operator, key: str) -> str:
    from app.modules.leads import auto_research, places_enrichment, source_sync
    from app.modules.sales import contacts

    refresh = task.params.get("mode") == "refresh"
    if key == "website":
        # Overture 只补当前门店，不改同名单的其他门店；人工官网保护由共用服务执行。
        try:
            service.enrich_overture(db, batch, lead_ids=[str(lead.id)])
        except Exception:
            db.rollback()  # 来源故障不阻断 Google／既有官网核验。
            db.refresh(lead)
        selected = policy.Policy.model_validate(task.params["policy"])
        if refresh and selected.google_mode != "off":
            from app.core.config import get_settings

            if get_settings().google_places_api_key:
                source_sync.sync_one(db, lead, op, str(task.id))
        outcome = places_enrichment.review_one(db, lead, op, selected, str(task.id), force=refresh)
        db.commit()
        if outcome != "verified":
            raise ValueError(
                ((lead.raw or {}).get("website_research") or {}).get("reason") or "官网核验未完成，可查看来源与历史"
            )
        return "已更新门店与官网；人工确认资料保留"
    if key == "contacts":
        result = contacts.collect(db, lead)
        db.commit()
        if result["pages_failed"] or (lead.website and not result["pages_ok"]) or result["ai_status"] != "completed":
            raise ValueError(result.get("ai_reason") or "部分官网页面未读取，已取得的候选保留")
        return f"已查找 {result['found']} 项候选，新增记录 {result['recorded']} 项"
    if key == "menus":
        run = auto_research.start(lead.id, BackgroundTasks(), db, op)
        auto_research.execute(lead.id, run["id"], op.id)
        db.expire_all()
        result = auto_research.run_of(get_lead(db, lead.id)) or {}
        if result.get("status") != "completed":
            raise ValueError(
                result.get("message") or result.get("error") or "菜单获取未完成，可上传菜单或准备无菜单询问"
            )
        return "菜单已获取并分析，价格与事实仍待核对"
    assets = list(
        db.scalars(select(MenuAsset).where(MenuAsset.lead_id == lead.id, MenuAsset.fetch_status == "fetched"))
    )
    if not assets:
        raise ValueError("尚无可分析菜单；请上传菜单，或直接准备询问菜单的消息")
    failed = 0
    for asset in assets:
        if workflows.cancelled(db, task.id):
            break
        previous = menus.latest_analysis(db, asset.id)
        # 继续完善不重做已有同内容的成功版本；主动重分析创建新版本，原审核不被覆盖。
        if (
            not refresh
            and previous
            and previous.input_sha256 == asset.sha256
            and previous.status in {"succeeded", "needs_review"}
        ):
            continue
        analysed, _ = menus.run_analysis(db, asset, engine="auto", force=refresh)
        failed += analysed.status == "failed"
    if failed:
        raise ValueError(f"{failed} 份菜单分析未完成，已完成结果保留")
    return "菜单分析已准备，请核对新版本；历史分析与沟通记录保留"


@workflow_scope
def advance(db: Session, batch: Batch, task: workflows.Workflow, op: Operator) -> None:
    from app.integrations.page_cache import fresh_read

    if task.status not in ACTIVE:
        return
    lead = get_lead(db, uuid.UUID(task.params["lead_ids"][0]))
    key = task.steps[task.step]
    task.status = "running"
    workflows.save_progress(db, task)
    if task.status == "cancelled":
        return
    try:
        with fresh_read(task.params.get("mode") == "refresh"):
            message = execute_item(db, batch, task, lead, op, key)
        result = {"key": key, "status": "completed", "message": message}
    except Exception as exc:
        db.rollback()
        result = {
            "key": key,
            "status": "failed",
            "message": str(exc)[:400]
            if isinstance(exc, (ValueError, HTTPException))
            else f"处理未完成（{type(exc).__name__}），可重试此项",
        }
    db.refresh(task)
    if task.status == "cancelled":
        return
    result["at"] = datetime.now(UTC).isoformat()
    current = db.scalar(
        select(Lead).where(Lead.id == lead.id).with_for_update().execution_options(populate_existing=True)
    )
    if current is not None:
        raw = dict(current.raw or {})
        raw["single_enrichment"] = {
            **raw.get("single_enrichment", {}),
            key: {**result, "snapshot": website_review.snapshot(current)},
        }
        if result["status"] == "completed" and key in {"menus", "contacts"}:
            raw["website_refresh_required"] = {**raw.get("website_refresh_required", {}), key: False}
        current.raw = raw
    task.results = task.results[: task.step] + [result]
    task.step += 1
    task.status = (
        "pending"
        if task.step < len(task.steps)
        else "failed"
        if any(r["status"] == "failed" for r in task.results)
        else "completed"
    )
    task.error = "部分资料未补齐，已有结果可继续使用；可逐项重试" if task.status == "failed" else None
    workflows.save_progress(db, task)
