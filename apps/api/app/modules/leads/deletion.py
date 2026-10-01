"""删除批次：不论是否处理过都可删除。只属于该批次的门店连同其菜单文件、分析、内容、联系方式、任务与事件一并删除；
同时属于其他批次的门店保留。有拒收/退订抑制记录的门店一律保留（脱离批次），否则同一门店日后重新导入会丢掉抑制。"""

import shutil
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.files import resolve_within
from app.modules.content.models import ContentPiece
from app.modules.leads.models import Batch, BatchLead, ImportRun, Lead
from app.modules.leads.runs import BatchRun
from app.modules.menus.models import MenuAnalysis, MenuAsset
from app.modules.sales.models import ChannelEligibility, CostEntry, Event, ManualTask, Suppression, TaskStatus


def _split(db: Session, batch: Batch) -> tuple[list[uuid.UUID], int, int]:
    """（将删除的门店，因属于其他批次而保留的数量，因有抑制记录而保留的数量）"""
    members = set(db.scalars(select(BatchLead.lead_id).where(BatchLead.batch_id == batch.id)).all())
    if not members:
        return [], 0, 0
    shared = set(
        db.scalars(
            select(BatchLead.lead_id).where(BatchLead.lead_id.in_(members), BatchLead.batch_id != batch.id)
        ).all()
    )
    suppressed = set(db.scalars(select(Suppression.lead_id).where(Suppression.lead_id.in_(members - shared))).all())
    return sorted(members - shared - suppressed), len(shared), len(suppressed)


def preview(db: Session, batch: Batch) -> dict[str, Any]:
    """删除前的影响范围；与 delete_batch 用同一套划分规则。"""
    doomed, kept_shared, kept_suppressed = _split(db, batch)

    def n(model: Any, *where: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)

    assets = select(MenuAsset.id).where(MenuAsset.lead_id.in_(doomed))
    return {
        "batch_key": batch.batch_key,
        "leads_in_batch": len(doomed) + kept_shared + kept_suppressed,
        "leads_deleted": len(doomed),
        "leads_kept_other_batches": kept_shared,
        "leads_kept_suppressed": kept_suppressed,
        "menu_assets": n(MenuAsset, MenuAsset.lead_id.in_(doomed)),
        "analyses": n(MenuAnalysis, MenuAnalysis.asset_id.in_(assets)),
        "content_pieces": n(ContentPiece, ContentPiece.lead_id.in_(doomed)),
        "contacts": n(ChannelEligibility, ChannelEligibility.lead_id.in_(doomed)),
        "tasks": n(ManualTask, ManualTask.lead_id.in_(doomed)),
        "tasks_sent": n(ManualTask, ManualTask.lead_id.in_(doomed), ManualTask.status == TaskStatus.sent_manual),
        "events": n(Event, Event.lead_id.in_(doomed)),
        "import_runs": n(ImportRun, ImportRun.batch_id == batch.id),
        "batch_runs": n(BatchRun, BatchRun.batch_id == batch.id),
        "cost_entries": n(CostEntry, CostEntry.batch_id == batch.id),
    }


def delete_batch(db: Session, batch: Batch) -> dict[str, Any]:
    """删除批次及只属于它的门店数据。调用方负责审计与提交；提交后再调用 remove_files 清理文件。"""
    result = preview(db, batch)
    doomed, _, _ = _split(db, batch)
    db.execute(delete(CostEntry).where(CostEntry.batch_id == batch.id))
    db.execute(delete(ImportRun).where(ImportRun.batch_id == batch.id))
    if doomed:
        # 数据库级联删除菜单文件记录、分析与修正、内容与审批、渠道准入、任务、事件、批次成员、运行 job
        db.execute(delete(Lead).where(Lead.id.in_(doomed)))
    db.execute(delete(Batch).where(Batch.id == batch.id))  # 级联删除批次成员与运行记录
    db.expire_all()
    result["deleted_lead_ids"] = [str(i) for i in doomed]
    return result


def remove_files(lead_ids: list[str]) -> int:
    """删除已删门店的受控文件（菜单证据与样稿）。数据库提交成功后才调用；单个目录失败不影响其余。"""
    removed = 0
    for lead_id in lead_ids:
        for top in ("evidence", "content"):
            path = resolve_within(f"{top}/{lead_id}")
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
    return removed
