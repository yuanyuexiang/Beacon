"""D7：局部样稿与短文案生成、版本、审批。
- 样稿只填入已审核分析中的菜名与价格，不改写。
- 文案只引用已确认（confirmed=true）的问题事实；必须包含发送身份与退出方式；禁止新增成分/过敏原/利润/到店等事实。
- 审批绑定 content_hash 与 source_hash；内容或源数据改变后审批失效。"""

import hashlib
import html
import json
import re
import subprocess
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.files import resolve_within, store_bytes
from app.modules.content.models import Approval, ApprovalDecision, ContentKind, ContentPiece, ContentStatus
from app.modules.leads.models import Lead
from app.modules.menus import review as menu_review
from app.modules.menus.models import MenuAnalysis
from app.modules.menus.service import latest_analysis

TEMPLATE_NAME = "partial_menu.html"
MESSAGE_TEMPLATE = "message_short_v1"
BANNED_CLAIMS = [
    "allerg",
    "vegan",
    "vegetarian",
    "gluten",
    "profit",
    "margin",
    "we visited",
    "our client",
    "案例",
    "到店",
    "过敏",
    "素食",
    "利润",
]


class ContentError(ValueError):
    pass


def _sha(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def source_hash(a: MenuAnalysis) -> str:
    return _sha({"items": a.items, "issues": a.issues, "version": a.version, "asset": str(a.asset_id)})


def _require_reviewed_latest(db: Session, a: MenuAnalysis) -> None:
    latest = latest_analysis(db, a.asset_id)
    if latest is None or latest.id != a.id:
        raise ContentError("只能基于最新分析版本生成内容")
    if a.review_state != "reviewed":
        raise ContentError("分析尚未完成人工审核，不能生成对外内容")


def _next_version(db: Session, lead_id: uuid.UUID, kind: ContentKind) -> int:
    v = db.scalar(
        select(ContentPiece.version)
        .where(ContentPiece.lead_id == lead_id, ContentPiece.kind == kind)
        .order_by(ContentPiece.version.desc())
        .limit(1)
    )
    return (v or 0) + 1


def _template_bytes() -> bytes:
    p = get_settings().templates_dir / TEMPLATE_NAME
    if not p.exists():
        raise ContentError(f"模板不存在：{p}")
    return p.read_bytes()


def render_html(spec: dict, template: bytes) -> str:
    rows = []
    for it in spec["items"]:
        rows.append(
            f'<div class="item"><span class="name">{html.escape(it["name"])}</span><span class="dots"></span>'
            f'<span class="price">{html.escape(it["price_text"])}</span></div>'
        )
    page = template.decode("utf-8")
    fills = {
        "restaurant": html.escape(spec["restaurant"]),
        "section": html.escape(spec["section"]),
        "source": html.escape(spec.get("source", "")),
        "generated": html.escape(spec.get("generated", "")),
        "items": "\n".join(rows),
    }
    for k, v in fills.items():
        page = page.replace("{{" + k + "}}", v)
    return page


def _png(html_path, png_path, n_items: int) -> bool:
    chrome = get_settings().chrome_path
    if not chrome or not chrome.exists():
        return False
    h = 160 + 56 * max(n_items, 1)
    cmd = [
        str(chrome),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size=375,{h}",
        f"--screenshot={png_path}",
        f"file://{html_path}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0 and png_path.exists()
    except Exception:
        return False


def create_sample(
    db: Session, lead: Lead, a: MenuAnalysis, section: str, item_indexes: list[int] | None, by: str
) -> ContentPiece:
    _require_reviewed_latest(db, a)
    items = menu_review.active_items(a)
    if item_indexes is not None:
        try:
            items = [items[i] for i in item_indexes]
        except IndexError as e:
            raise ContentError("item_indexes 越界") from e
    if not items:
        raise ContentError("没有可用的菜品条目")
    template = _template_bytes()
    spec = {
        "restaurant": lead.name,
        "section": section,
        "items": [{"name": it["name"], "price_text": it["price_text"]} for it in items],
        "source": f"analysis v{a.version}",
        "generated": datetime.now(UTC).isoformat(timespec="minutes"),
    }
    piece = ContentPiece(
        lead_id=lead.id,
        analysis_id=a.id,
        kind=ContentKind.sample_partial,
        version=_next_version(db, lead.id, ContentKind.sample_partial),
        template_name=TEMPLATE_NAME,
        template_version=hashlib.sha256(template).hexdigest()[:12],
        engine="template",
        spec=spec,
        content_hash=_sha(
            {
                "spec": {k: v for k, v in spec.items() if k != "generated"},
                "template": hashlib.sha256(template).hexdigest(),
            }
        ),
        source_hash=source_hash(a),
        status=ContentStatus.draft,
        created_by=by,
    )
    db.add(piece)
    db.flush()
    page = render_html(spec, template)
    rel_html = f"content/{lead.id}/{piece.id}.html"
    store_bytes(rel_html, page.encode())
    piece.storage_path_html = rel_html
    rel_png = f"content/{lead.id}/{piece.id}.png"
    if _png(resolve_within(rel_html), resolve_within(rel_png), len(items)):
        piece.storage_path_png = rel_png
    db.commit()
    db.refresh(piece)
    return piece


def compose_message(
    lead: Lead, a: MenuAnalysis, sender_identity: str, opt_out_text: str, website: str | None
) -> tuple[str, list[int]]:
    facts = [
        (i, iss["fact"])
        for i, iss in enumerate(a.issues or [])
        if iss.get("confirmed") is True and not iss.get("deleted")
    ]
    if not facts:
        raise ContentError("没有已确认的菜单问题，不生成对外文案")
    src = f"the menu on your website ({website})" if website else "the menu you published"
    lines = [f"Hello {lead.name},", "", f"We looked at {src} and noticed:"]
    lines += [f"- {f}" for _, f in facts]
    lines += [
        "",
        "We prepared a small sample layout of one section, using your own dish names and prices, "
        "so you can see the difference.",
        "Would you like us to send it over?",
        "",
        sender_identity.strip(),
        "",
        opt_out_text.strip(),
    ]
    return "\n".join(lines), [i for i, _ in facts]


def check_claims(body: str, a: MenuAnalysis) -> None:
    allowed = " ".join(iss.get("fact", "") for iss in (a.issues or [])).lower()
    low = body.lower()
    for term in BANNED_CLAIMS:
        if term in low and term not in allowed:
            raise ContentError(f"文案包含未经证据支持的表述：{term!r}")


def create_message(
    db: Session, lead: Lead, a: MenuAnalysis, sender_identity: str, opt_out_text: str, website: str | None, by: str
) -> ContentPiece:
    _require_reviewed_latest(db, a)
    if not sender_identity.strip() or not opt_out_text.strip():
        raise ContentError("必须提供发送身份与退出方式")
    body, cited = compose_message(lead, a, sender_identity, opt_out_text, website)
    check_claims(body, a)
    spec = {
        "template": MESSAGE_TEMPLATE,
        "cited_issue_indexes": cited,
        "sender_identity": sender_identity,
        "opt_out_text": opt_out_text,
        "website": website,
    }
    piece = ContentPiece(
        lead_id=lead.id,
        analysis_id=a.id,
        kind=ContentKind.message_short,
        version=_next_version(db, lead.id, ContentKind.message_short),
        template_name=MESSAGE_TEMPLATE,
        template_version="1",
        engine="template",
        spec=spec,
        body_text=body,
        content_hash=_sha({"body": body, "spec": spec}),
        source_hash=source_hash(a),
        status=ContentStatus.draft,
        created_by=by,
    )
    db.add(piece)
    db.commit()
    db.refresh(piece)
    return piece


def revise_message(db: Session, piece: ContentPiece, body_text: str, by: str) -> ContentPiece:
    if piece.kind != ContentKind.message_short:
        raise ContentError("只有文案可以直接编辑；样稿请重新生成")
    a = db.get(MenuAnalysis, piece.analysis_id) if piece.analysis_id else None
    if a is None:
        raise ContentError("内容缺少来源分析")
    check_claims(body_text, a)
    spec = dict(piece.spec or {})
    if spec.get("sender_identity") and spec["sender_identity"].strip() not in body_text:
        raise ContentError("编辑后的文案缺少发送身份")
    if spec.get("opt_out_text") and spec["opt_out_text"].strip() not in body_text:
        raise ContentError("编辑后的文案缺少退出方式")
    nv = ContentPiece(
        lead_id=piece.lead_id,
        analysis_id=piece.analysis_id,
        kind=piece.kind,
        version=_next_version(db, piece.lead_id, piece.kind),
        template_name=piece.template_name,
        template_version=piece.template_version,
        engine="human",
        spec=spec,
        body_text=body_text,
        content_hash=_sha({"body": body_text, "spec": spec}),
        source_hash=piece.source_hash,
        status=ContentStatus.draft,
        created_by=by,
    )
    db.add(nv)
    db.commit()
    db.refresh(nv)
    return nv


def source_still_valid(db: Session, piece: ContentPiece) -> tuple[bool, str | None]:
    if piece.analysis_id is None:
        return False, "内容缺少来源分析"
    a = db.get(MenuAnalysis, piece.analysis_id)
    if a is None:
        return False, "来源分析不存在"
    latest = latest_analysis(db, a.asset_id)
    if latest is None or latest.id != a.id:
        return False, f"来源分析已更新到 v{latest.version if latest else '?'}，内容基于 v{a.version}"
    if source_hash(a) != piece.source_hash:
        return False, "来源分析内容已变化"
    return True, None


def decide(db: Session, piece: ContentPiece, decision: ApprovalDecision, by: str, note: str | None) -> ContentPiece:
    ok, why = source_still_valid(db, piece)
    if decision == ApprovalDecision.approved and not ok:
        raise ContentError(f"源数据已变更，不能审批：{why}")
    db.add(
        Approval(
            content_id=piece.id,
            content_hash=piece.content_hash,
            decision=decision,
            decided_by=by,
            decided_at=datetime.now(UTC),
            note=note,
        )
    )
    piece.status = ContentStatus.approved if decision == ApprovalDecision.approved else ContentStatus.rejected
    db.commit()
    db.refresh(piece)
    return piece


def approval_valid(db: Session, piece: ContentPiece) -> tuple[bool, str | None]:
    """D8 用：审批是否仍然有效（状态、hash、源数据、是否最新版本）。"""
    if piece.status != ContentStatus.approved:
        return False, f"内容状态为 {piece.status}"
    last = db.scalar(
        select(Approval).where(Approval.content_id == piece.id).order_by(Approval.decided_at.desc()).limit(1)
    )
    if last is None or last.decision != ApprovalDecision.approved or last.content_hash != piece.content_hash:
        return False, "审批记录与当前内容不一致"
    newer = db.scalar(
        select(ContentPiece.id)
        .where(
            ContentPiece.lead_id == piece.lead_id, ContentPiece.kind == piece.kind, ContentPiece.version > piece.version
        )
        .limit(1)
    )
    if newer is not None:
        return False, "已有更新版本的内容"
    return source_still_valid(db, piece)


def latest_content(db: Session, lead_id: uuid.UUID, kind: ContentKind) -> ContentPiece | None:
    return db.scalar(
        select(ContentPiece)
        .where(ContentPiece.lead_id == lead_id, ContentPiece.kind == kind)
        .order_by(ContentPiece.version.desc())
        .limit(1)
    )


_ = re  # 保留 re 供未来文案校验扩展
