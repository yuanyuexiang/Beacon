"""汇总导入全部模型，供 Alembic 与测试使用。"""

from app.core.models import AuditLog, Operator  # noqa: F401
from app.core.models_base import Base
from app.modules.content.models import Approval, ContentPiece  # noqa: F401
from app.modules.leads.models import Batch, BatchLead, ImportRun, Lead  # noqa: F401
from app.modules.leads.runs import BatchJob, BatchRun  # noqa: F401
from app.modules.menus.models import AnalysisCorrection, MenuAnalysis, MenuAsset  # noqa: F401
from app.modules.sales.models import ChannelEligibility, CostEntry, Event, ManualTask, Suppression  # noqa: F401

__all__ = ["Base"]
