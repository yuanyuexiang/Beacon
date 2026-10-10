"""单家后台研究：有界证据、自动采用、异常复核。运行状态保存在 lead.raw，单进程部署。"""

import copy
import hashlib
import re
import uuid
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import urljoin, urlsplit

import pdfplumber
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import current_operator
from app.core.config import get_settings
from app.core.db import get_db, get_sessionmaker
from app.core.models import Operator
from app.integrations import fetcher, research_judge, website_menus
from app.modules.leads import google_places
from app.modules.leads.models import Lead
from app.modules.menus import analysis, service
from app.modules.menus.models import AnalysisStatus, MenuAsset

router = APIRouter(tags=["auto-research"])
PROCESS = uuid.uuid4().hex
ACTIVE = {"queued", "running"}
MAX_SECONDS = 1200


def now() -> str:
    return datetime.now(UTC).isoformat()


def snapshot(lead: Lead) -> dict:
    return {
        "website": lead.website,
        "name": lead.name,
        "address": lead.address,
        "postcode": lead.postcode,
        "revision": (lead.raw or {}).get("google_places_revision"),
        "link": (lead.raw or {}).get("google_places_link"),
    }


def locked(db: Session, lead_id: uuid.UUID) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.id == lead_id).with_for_update().execution_options(populate_existing=True))
    if not lead:
        raise HTTPException(404, "线索不存在")
    return lead


def run_of(lead: Lead) -> dict | None:
    return (lead.raw or {}).get("auto_research")


def write(db: Session, lead: Lead, run: dict) -> None:
    raw = dict(lead.raw or {})
    raw["auto_research"] = copy.deepcopy(run)
    lead.raw = raw


def recover(lead: Lead) -> None:
    run = run_of(lead)
    if (
        run
        and run["status"] in ACTIVE
        and (
            run.get("process") != PROCESS
            or (datetime.now(UTC) - datetime.fromisoformat(run["started_at"])).total_seconds() > MAX_SECONDS
        )
    ):
        run = copy.deepcopy(run)
        run.update(status="interrupted", stage="中断", error="服务重启或运行超时，请重试；已成功资产会去重复用")
        write_dummy = dict(lead.raw or {})
        write_dummy["auto_research"] = run
        lead.raw = write_dummy


@router.get("/leads/{lead_id}/auto-research")
def state(lead_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    lead = locked(db, lead_id)
    recover(lead)
    result = {
        "configured": get_settings().llm_provider == "deepseek" and bool(get_settings().deepseek_api_key),
        "run": run_of(lead),
    }
    db.commit()
    return result


@router.post("/leads/{lead_id}/auto-research", status_code=202)
def start(
    lead_id: uuid.UUID,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    op: Operator = Depends(current_operator),
) -> dict:
    # 初始化时检查真实模型配置，不发送模型请求，也不允许 Fake 自动通过。
    try:
        research_judge.ResearchJudge()
    except Exception as e:
        raise HTTPException(503, str(e)) from e
    lead = locked(db, lead_id)
    recover(lead)
    previous = run_of(lead)
    if previous and previous["status"] in ACTIVE:
        db.commit()
        return previous
    if not lead.website and not google_places._link(lead):
        raise HTTPException(400, "请先补充官网或关联 Google 门店")
    run: dict = {
        "id": uuid.uuid4().hex,
        "process": PROCESS,
        "status": "queued",
        "stage": "等待开始",
        "started_at": now(),
        "updated_at": now(),
        "by": op.username,
        "operator_id": str(op.id),
        "snapshot": snapshot(lead),
        "websites": [],
        "menus": [],
        "usage": [],
        "model": None,
        "prompt_version": research_judge.PROMPT_VERSION,
    }
    write(db, lead, run)
    audit.record(db, op, "start_auto_research", "lead", lead.id, after={"run_id": run["id"]})
    db.commit()
    background.add_task(execute, lead_id, run["id"], op.id)
    return run


class Changed(RuntimeError):
    pass


def checkpoint(db: Session, lead_id: uuid.UUID, run: dict, stage: str) -> Lead:
    lead = locked(db, lead_id)
    current = run_of(lead)
    if not current or current["id"] != run["id"] or current["status"] not in ACTIVE:
        raise Changed("运行已被中断或替换")
    if snapshot(lead) != run["snapshot"]:
        raise Changed("官网、门店资料或 Google 关联已改变，停止自动采用")
    if (datetime.now(UTC) - datetime.fromisoformat(run["started_at"])).total_seconds() > MAX_SECONDS:
        raise Changed("运行达到 20 分钟上限，请重试")
    run.update(stage=stage, updated_at=now(), status="running")
    write(db, lead, run)
    db.commit()
    return lead


def fetch(url: str, document: bool = False):
    s = get_settings()
    u = urlsplit(url)
    if u.username or u.password:
        raise ValueError("不接受含凭证的 URL")
    return fetcher.fetch(
        url,
        max_bytes=s.max_asset_bytes if document else 2 * 1024 * 1024,
        timeout=min(s.fetch_timeout_seconds, 15),
        user_agent=s.fetch_user_agent,
        resolve_check=s.fetch_ip_check,
    )


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def identity_match(info: dict, docs: list[dict]) -> bool:
    # 同一页面必须同时包含邮编和完整门牌/街道；不能拼接不同分店页面凑匹配。
    postcode = norm(info.get("postcode") or "")
    street = norm((info.get("address") or "").split(",")[0])
    return (
        len(postcode) >= 5
        and len(street) >= 5
        and any(postcode in norm(d["text"]) and street in norm(d["text"]) for d in docs)
    )


def pages(url: str) -> list[dict]:
    out: list[dict] = []
    homepage = fetch(url)
    if homepage.status != 200 or homepage.kind != "html":
        raise ValueError(f"官网 HTTP {homepage.status} / {homepage.kind}")
    parser = website_menus.Page()
    parser.feed(homepage.body.decode("utf-8", errors="replace"))
    targets = [homepage.final_url]
    for href, label in parser.links:
        target = urljoin(homepage.final_url, href)
        if (
            urlsplit(target).hostname == urlsplit(homepage.final_url).hostname
            and re.search(r"contact|about|location|venue|find.us", target + label, re.I)
            and target not in targets
        ):
            targets.append(target)
    for index, target in enumerate(targets[:3]):
        r = homepage if index == 0 else fetch(target)
        if r.status == 200 and r.kind == "html":
            page_parser = website_menus.Page()
            page_parser.feed(r.body.decode("utf-8", errors="replace"))
            out.append(
                {
                    "id": f"web{index}",
                    "url": r.final_url,
                    "text": analysis.html_visible_text(r.body)[:14000],
                    "links": [{"url": urljoin(r.final_url, href), "label": label} for href, label in page_parser.links][
                        :100
                    ],
                }
            )
    return out


def text_of(result) -> str:
    if result.kind == "pdf":
        with pdfplumber.open(BytesIO(result.body)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages[:12])[:18000]
    if result.kind == "html":
        return analysis.html_visible_text(result.body)[:18000]
    return ""


def execute(lead_id: uuid.UUID, run_id: str, operator_id: uuid.UUID) -> None:
    with get_sessionmaker()() as db:
        lead = db.get(Lead, lead_id)
        if not lead:
            return
        stored = run_of(lead)
        if not stored or stored["id"] != run_id:
            return
        run: dict = copy.deepcopy(stored)
        try:
            judge = research_judge.ResearchJudge()
            run["model"] = judge.model
            op = db.get(Operator, operator_id)
            if op is None:
                raise ValueError("操作者不存在")
            lead = checkpoint(db, lead_id, run, "获取官网候选")
            options = [lead.website] if lead.website else []
            link = google_places._link(lead)
            # 不持久化详情，也不把 Google 价格、照片或响应送模型。
            db.commit()
            if link:
                try:
                    place = google_places._client(db, op, lead_id).details(link["place_id"])
                    if place.websiteUri and place.websiteUri not in options:
                        options.insert(0, place.websiteUri)
                except Exception as e:
                    run["websites"].append({"status": "failed", "reason": f"Google 官网候选不可用：{type(e).__name__}"})
                    db.rollback()
            selected = None
            selected_docs: list[dict] = []
            info = run["snapshot"]
            for url in options:
                checkpoint(db, lead_id, run, "AI 核对官网")
                report: dict = {"url": url}
                try:
                    documents = pages(url)
                    # 集团页面的真实外链可作为新候选，仍须读取并校验分店地址，不能仅凭标签采用。
                    name_words = {
                        w
                        for w in re.findall(r"[a-z]+", info["name"].lower())
                        if len(w) >= 4
                        and w not in {"restaurant", "restaurants", "deli", "cafe", "coffee", "kitchen", "hotel"}
                    }
                    discovered_branch = False
                    for d in documents:
                        for item in d.get("links", []):
                            target = item["url"]
                            if (
                                len(options) < 3
                                and target not in options
                                and urlsplit(target).hostname != urlsplit(d["url"]).hostname
                                and not re.search(
                                    r"instagram\.com|facebook\.com|linkedin\.com|youtube\.com|x\.com|twitter\.com|wa\.me|google\.",
                                    urlsplit(target).hostname or "",
                                    re.I,
                                )
                                and any(word in norm(item["label"] + target) for word in name_words)
                            ):
                                try:
                                    fetcher.check_url(target, resolve=False)
                                    options.append(target)
                                    discovered_branch = True
                                except (ValueError, fetcher.FetchBlocked):
                                    pass
                    verdict = judge.judge(
                        {
                            "kind": "website",
                            "restaurant": {k: info[k] for k in ("name", "address", "postcode")},
                            "candidate_url": url,
                        },
                        documents,
                    )
                    accepted = (
                        verdict.decision == "accept"
                        and research_judge.grounded(verdict, documents, "identity")
                        and identity_match(info, documents)
                        and not any(c.kind == "conflict" for c in verdict.citations)
                    )
                    if not accepted and verdict.decision == "accept":
                        report["validation_note"] = "程序校验未通过：引用或分店地址证据不足"
                    report.update(
                        status="accepted" if accepted else "review",
                        judgment=verdict.model_dump(),
                        reason=verdict.reason if accepted else "证据不足或存在冲突：" + verdict.reason,
                        sources=[{"id": d["id"], "url": d["url"]} for d in documents],
                    )
                    if accepted:
                        selected, selected_docs = url, documents
                    elif discovered_branch:
                        report.update(
                            status="reference", reason="发现门店专属官网，优先继续验证该候选；" + verdict.reason
                        )
                except Exception as e:
                    report.update(status="failed", reason=f"官网读取/AI 判断失败：{type(e).__name__}")
                run["websites"].append(report)
                run["usage"] = judge.usage
                if selected:
                    break
            if not selected:
                finish(db, lead_id, run, "needs_review", "没有可自动确认的官网，请查看依据并人工核对")
                return
            lead = checkpoint(db, lead_id, run, "采用官网")
            # 短事务内重新锁定检查，不能在 checkpoint 提交与实际写入之间覆盖并发编辑。
            lead = locked(db, lead_id)
            if snapshot(lead) != run["snapshot"]:
                raise Changed("采用前官网或门店已改变")
            before = {"website": lead.website, "website_source": lead.website_source}
            if lead.website != selected:
                lead.website, lead.website_source = selected, "AI 证据核对 + 程序校验"
                raw = dict(lead.raw or {})
                raw.pop("contacts_scan", None)
                raw["website_confirmation"] = {
                    "method": "ai_evidence",
                    "old_website": before["website"],
                    "candidate_url": selected,
                    "run_id": run_id,
                    "initiated_by": run["by"],
                    "confirmed_at": now(),
                    "model": judge.model,
                    "evidence": run["websites"][-1],
                }
                lead.raw = raw
                audit.record(
                    db,
                    op,
                    "auto_adopt_website",
                    "lead",
                    lead_id,
                    before=before,
                    after={"website": selected, "run_id": run_id, "method": "ai_evidence"},
                )
            run["snapshot"] = snapshot(lead)
            run["selected_website"] = selected
            write(db, lead, run)
            db.commit()
            checkpoint(db, lead_id, run, "发现官网菜单")
            lookup = website_menus.discover(selected, fetch)
            run["pages"] = lookup["pages"]
            candidates = lookup["candidates"][:6]
            run["candidate_count"] = len(lookup["candidates"])
            for candidate in candidates:
                checkpoint(db, lead_id, run, "AI 核对并获取菜单")
                report = dict(candidate)
                try:
                    r = fetch(candidate["url"], document=True)
                    if r.status != 200 or r.kind not in {"pdf", "image", "html"}:
                        raise ValueError("候选文件不可读取")
                    content = text_of(r)
                    # 扫描件/图片暂存于内存，由现有视觉接口转录；不自动作为事实批准。
                    if len(content.strip()) < 50 and r.kind in {"pdf", "image"}:
                        transcription = judge.provider.analyze_image(r.body, {"media_type": r.content_type})
                        content = "\n".join(
                            str(i.get("name", "")) + " " + str(i.get("price_text", i.get("price", "")))
                            for i in transcription.items
                        )[:18000]
                        run["usage"].append({**(transcription.usage or {}), "visual": True, "kind": "visual_evidence"})
                        if len(content.strip()) < 50:
                            raise ValueError("图像转录证据不足")
                    docs = [{"id": "menu", "url": r.final_url, "text": content}, *selected_docs]
                    verdict = judge.judge(
                        {
                            "kind": "menu",
                            "restaurant": {k: info[k] for k in ("name", "address", "postcode")},
                            "verified_website": selected,
                            "link": candidate,
                            "today": datetime.now(UTC).date().isoformat(),
                        },
                        docs,
                    )
                    is_offer = bool(
                        re.search(r"offer|promo|deal", candidate["label"] + urlsplit(candidate["url"]).path, re.I)
                    )
                    if is_offer:
                        verdict.category = "offer"
                    accepted = (
                        verdict.decision == "accept"
                        and research_judge.grounded(verdict, docs, "menu")
                        and any(c.kind == "menu" and c.document_id == "menu" for c in verdict.citations)
                        and verdict.category in {"food", "drinks", "buffet", "offer"}
                        and len(re.findall(r"[£€$]\s*\d+(?:[.,]\d{2})?", content)) >= 2
                        and (verdict.category != "offer" or bool(verdict.date))
                        and not any(c.kind == "conflict" for c in verdict.citations)
                    )
                    report.update(
                        status="accepted"
                        if accepted
                        else verdict.decision
                        if verdict.decision != "accept"
                        else "review",
                        judgment=verdict.model_dump(),
                        reason=verdict.reason
                        if accepted or verdict.decision != "accept"
                        else "程序校验未通过：引用须存在于菜单原文、至少两处价格，优惠日期须明确；" + verdict.reason,
                    )
                    if accepted:
                        import_asset(db, lead_id, run, report, r, op)
                except Changed:
                    raise
                except Exception as e:
                    db.rollback()
                    report.update(status="failed", reason=f"菜单处理失败：{type(e).__name__}: {str(e)[:150]}")
                run["menus"].append(report)
                run["usage"] = [*judge.usage, *[u for u in run["usage"] if u.get("visual")]]
            review = any(m["status"] in {"review", "failed"} for m in run["menus"])
            finish(
                db,
                lead_id,
                run,
                "needs_review" if review or not any(m["status"] == "accepted" for m in run["menus"]) else "completed",
                "处理完成，菜单价格与问题仍需审核" if run["menus"] else "未发现菜单，需要人工补充",
            )
        except Exception as e:
            db.rollback()
            finish(
                db,
                lead_id,
                run,
                "conflict" if isinstance(e, Changed) else "failed",
                str(e)[:250] if isinstance(e, Changed) else f"自动研究失败：{type(e).__name__}",
                check=False,
            )


def import_asset(db: Session, lead_id: uuid.UUID, run: dict, report: dict, result, op: Operator | None) -> None:
    checkpoint(db, lead_id, run, "导入已确认菜单")
    lead = locked(db, lead_id)
    if snapshot(lead) != run["snapshot"]:
        raise Changed("菜单导入前官网已改变")
    sha = hashlib.sha256(result.body).hexdigest()
    asset = db.scalar(select(MenuAsset).where(MenuAsset.lead_id == lead_id, MenuAsset.sha256 == sha))
    if asset is None:
        asset = MenuAsset(
            lead_id=lead_id,
            source_url=report["url"],
            final_url=result.final_url,
            content_type=result.content_type,
            fetch_status="fetched",
            fetch_attempts=1,
            fetched_at=datetime.now(UTC),
            http_status=result.status,
            added_by=run["by"],
        )
        db.add(asset)
        db.flush()
        service._store(asset, result.body, result.kind)
        audit.record(
            db,
            op,
            "auto_import_menu",
            "menu_asset",
            asset.id,
            after={"run_id": run["id"], "url": report["url"], "judgment": report["judgment"]},
        )
    report.update(asset_id=str(asset.id), sha256=sha)
    # 导入与运行结果一起提交，重试可按内容 hash 恢复。
    write(db, lead, run)
    db.commit()
    engine = (
        "model" if result.kind == "image" or (result.kind == "pdf" and len(text_of(result).strip()) < 50) else "rules"
    )
    a, created = service.run_analysis(db, asset, engine=engine)
    if created and engine != "rules" and (a.measurements or {}).get("usage"):
        run["usage"].append({**(a.measurements or {})["usage"], "visual": True, "kind": "menu_analysis"})
    if created and a.status != AnalysisStatus.failed:
        a.status = AnalysisStatus.needs_review
        db.commit()
    report.update(analysis_id=str(a.id), analysis_status=a.status.value)
    if a.status == AnalysisStatus.failed:
        report.update(status="failed", reason="菜单已导入，但分析失败，可在菜单文件中重试")


def finish(db: Session, lead_id: uuid.UUID, run: dict, status: str, message: str, check: bool = True) -> None:
    if check:
        checkpoint(db, lead_id, run, "整理结果")
    lead = locked(db, lead_id)
    current = run_of(lead)
    if not current or current["id"] != run["id"] or current["status"] not in ACTIVE:
        db.rollback()
        return
    if check and snapshot(lead) != run["snapshot"]:
        status, message = "conflict", "整理结果时门店资料已改变，请重新运行"
    run.update(
        status=status,
        stage="完成" if status == "completed" else "需要处理",
        message=message,
        updated_at=now(),
        finished_at=now(),
    )
    write(db, lead, run)
    audit.record(
        db,
        db.get(Operator, uuid.UUID(str(current.get("operator_id")))) if current.get("operator_id") else None,
        "finish_auto_research",
        "lead",
        lead_id,
        after={"run_id": run["id"], "status": status},
    )
    db.commit()
