from dataclasses import dataclass, field

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .errors import DomainError, forbidden
from .models import AdminUser, Permission, RolePermission, User
from .security import read_token

bearer = HTTPBearer(auto_error=False)

PERMISSIONS = ["dashboard.view", "products.manage", "rates.manage", "orders.view", "orders.manage", "rentals.manage",
               "payments.view", "payments.review", "promo.manage", "channels.manage", "vip.manage", "settings.manage",
               "users.view", "users.manage", "balance.adjust", "market.moderate", "disputes.manage", "gifts.review",
               "support.manage", "content.manage", "roles.manage", "audit.view"]
ROLE_PERMS = {
    "superadmin": ["*"],
    "admin": [p for p in PERMISSIONS if p != "roles.manage"],
    "moderator": ["users.view", "market.moderate", "disputes.manage", "support.manage", "content.manage"],
    "support": ["users.view", "support.manage", "orders.view"],
    "finance-view": ["dashboard.view", "payments.view", "orders.view"],
}


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                       session: AsyncSession = Depends(get_session)) -> User:
    if creds is None:
        raise DomainError("auth_required", "Kirish talab qilinadi", 401)
    data = read_token(creds.credentials)
    user = await session.get(User, int(data["uid"]))
    if user is None or user.kind != "user":
        raise DomainError("auth_failed", "Foydalanuvchi topilmadi", 401)
    if user.is_banned:
        raise DomainError("banned", "Akkaunt cheklangan", 403)
    return user


@dataclass
class AdminCtx:
    user: User
    admin: AdminUser
    perms: set = field(default_factory=set)
    ip: str | None = None

    def can(self, code: str) -> bool:
        return "*" in self.perms or code in self.perms


async def admin_ctx(request: Request, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)) -> AdminCtx:
    """Har so'rovda DB'dan rol/ruxsatlar qayta o'qiladi - tokenga ishonilmaydi."""
    admin = (await session.execute(select(AdminUser).where(AdminUser.user_id == user.id, AdminUser.active.is_(True)))).scalar_one_or_none()
    if admin is None:
        raise forbidden("Admin huquqi yo'q")
    codes = (await session.execute(select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id)
                                   .where(RolePermission.role_id == admin.role_id))).scalars().all()
    perms = {"*"} if admin.role.name == "superadmin" else set(codes)
    return AdminCtx(user=user, admin=admin, perms=perms, ip=request.client.host if request.client else None)


def require_perm(code: str):
    async def dep(ctx: AdminCtx = Depends(admin_ctx)) -> AdminCtx:
        if not ctx.can(code):
            raise forbidden(f"Ruxsat yetarli emas ({code})")
        return ctx
    return dep
