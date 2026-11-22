import json

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog


async def log(session: AsyncSession, admin_user_id, action: str, entity_type: str | None = None,
              entity_id=None, detail: dict | None = None, ip: str | None = None) -> None:
    session.add(AuditLog(admin_user_id=admin_user_id, action=action, entity_type=entity_type,
                         entity_id=str(entity_id) if entity_id is not None else None, detail=json.loads(json.dumps(detail or {}, default=str)), ip=ip))
    await session.flush()
