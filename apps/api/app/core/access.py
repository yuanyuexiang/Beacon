"""业务成员的数据范围在请求会话中生效；后台专用会话保持现有执行规则。"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.core.models import Operator
from app.core.models_base import Base


def set_scope(db: Session, username: str) -> None:
    # 不允许 identity map 中先前未过滤的实例绕过 Session.get 的查询。
    for item in list(db.identity_map.values()):
        if not isinstance(item, Operator):
            db.expunge(item)
    db.info["member_scope"] = username


def expressions(username: str) -> dict[str, Any]:
    tables = Base.metadata.tables
    leads = select(tables["lead"].c.id).where(tables["lead"].c.assigned_to == username)
    assets = select(tables["menu_asset"].c.id).where(tables["menu_asset"].c.lead_id.in_(leads))
    tasks = select(tables["manual_task"].c.id).where(tables["manual_task"].c.lead_id.in_(leads))
    analyses = select(tables["menu_analysis"].c.id).where(tables["menu_analysis"].c.asset_id.in_(assets))
    content = select(tables["content_piece"].c.id).where(tables["content_piece"].c.lead_id.in_(leads))
    conversations = select(tables["social_conversation"].c.id).where(tables["social_conversation"].c.lead_id.in_(leads))
    return {
        "lead_id": leads,
        "asset_id": assets,
        "task_id": tasks,
        "analysis_id": analyses,
        "content_id": content,
        "conversation_id": conversations,
    }


@event.listens_for(Session, "do_orm_execute")
def scope_queries(state: ORMExecuteState) -> None:
    username = state.session.info.get("member_scope")
    if not username or not state.is_orm_statement:
        return
    from app.modules.leads.models import Lead

    options = [with_loader_criteria(Lead, Lead.assigned_to == username, include_aliases=True)]
    scopes = expressions(username)
    for mapper in Base.registry.mappers:
        cls: Any = mapper.class_
        # 拒收按联系值全局生效，不能因为别的负责人记录就漏掉。列表另做权限过滤。
        if mapper.persist_selectable.description in {"lead", "suppression"}:
            continue
        for key, identities in scopes.items():
            if key in mapper.columns:
                options.append(with_loader_criteria(cls, getattr(cls, key).in_(identities), include_aliases=True))
                break
    state.statement = state.statement.options(*options)


@event.listens_for(Session, "before_flush")
def scope_writes(db: Session, flush_context, instances) -> None:
    username = db.info.get("member_scope")
    if not username:
        return
    from app.modules.leads.models import Lead

    # 新记录也必须属于自己的门店，不能仅依赖列表查询过滤。
    for item in list(db.new) + list(db.dirty) + list(db.deleted):
        identity = getattr(item, "lead_id", None)
        if identity is not None:
            lead = db.scalar(select(Lead).where(Lead.id == identity).with_for_update())
            if lead is None:
                raise HTTPException(403, "门店未分配给当前业务成员")
        if isinstance(item, Lead) and item.assigned_to != username:
            raise HTTPException(403, "业务成员不能更改门店负责人")
