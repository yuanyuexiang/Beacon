"""审计记录：谁在何时对什么做了什么，前后快照。"""

import uuid

from sqlalchemy.orm import Session

from app.core.models import AuditLog, Operator


def record(
    db: Session,
    operator: Operator | None,
    action: str,
    entity: str,
    entity_id: str | uuid.UUID,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            operator_id=operator.id if operator else None,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            before=before,
            after=after,
        )
    )
