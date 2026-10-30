"""帳號層級的權限依賴（AD-10），給各模組的 router 以 `Depends` 套用。

core 不能 import 模組（AD-3），所以依賴由 identity 提供；其他模組的 router 直接
import 這裡的 `CurrentAccount`、`VerifiedAccount`、`PlatformAdmin`（呼叫方向
disputes → … → identity）。憑證是 `Authorization: Bearer <access token>`。
"""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.db import SessionDep
from app.core.errors import BusinessError
from app.modules.identity import service
from app.modules.identity.models import AccountRead

# auto_error=False：沒帶憑證時由我們回 401 `AUTHENTICATION_REQUIRED`（統一的錯誤格式）
_bearer = HTTPBearer(auto_error=False, description="登入 API 回傳的 access token")


def get_current_account(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AccountRead:
    """已登入：沒帶 token、token 無效或過期、帳號不存在都回 401。"""
    if credentials is None:
        raise service.authentication_required()
    return service.get_current_account(session, credentials.credentials)


CurrentAccount = Annotated[AccountRead, Depends(get_current_account)]


def require_verified(account: CurrentAccount) -> AccountRead:
    """已登入且 Email 已驗證；未驗證回 403 `EMAIL_NOT_VERIFIED`。"""
    if not account.email_verified:
        raise BusinessError(
            "EMAIL_NOT_VERIFIED",
            "完成 Email 驗證後才能使用這個功能。",
            status_code=403,
        )
    return account


VerifiedAccount = Annotated[AccountRead, Depends(require_verified)]


def require_platform_admin(account: CurrentAccount) -> AccountRead:
    """已登入的平台管理員；其他帳號回 403 `PLATFORM_ADMIN_REQUIRED`。"""
    if not account.is_platform_admin:
        raise BusinessError(
            "PLATFORM_ADMIN_REQUIRED",
            "只有平台管理員可以使用這個功能。",
            status_code=403,
        )
    return account


PlatformAdmin = Annotated[AccountRead, Depends(require_platform_admin)]


def require_organizer(account: CurrentAccount) -> AccountRead:
    """已登入的主辦方；其他帳號回 403 `ORGANIZER_REQUIRED`。"""
    if not account.is_organizer:
        raise BusinessError(
            "ORGANIZER_REQUIRED",
            "只有主辦方可以使用這個功能。",
            status_code=403,
        )
    return account


Organizer = Annotated[AccountRead, Depends(require_organizer)]
