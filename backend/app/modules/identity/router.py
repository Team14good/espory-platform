"""identity 的 HTTP 端點：帳號層級權限、開啟並提交交易（router 才能 commit）。

未登入可以呼叫的寫入端點只有 `PUBLIC_WRITE_ROUTES` 列出的這些；其他寫入端點一律
套用 `CurrentAccount`（或更嚴格的依賴），未登入回 401（tests 會逐一檢查）。
"""

import uuid

from fastapi import APIRouter, status

from app.core.db import SessionDep
from app.modules.identity import service
from app.modules.identity.deps import CurrentAccount, PlatformAdmin
from app.modules.identity.models import (
    AccessToken,
    AccessTokenCreate,
    AccountCreate,
    AccountRead,
    EmailVerificationCreate,
    Identity,
    PasswordResetCheck,
    PasswordResetCreate,
    PasswordResetEmailCreate,
    ProfileUpdate,
    PublicSchool,
    RegisteredAccount,
    SchoolIn,
    VerificationEmailCreate,
)

# (方法, 路徑)：未登入也能呼叫的寫入端點
PUBLIC_WRITE_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/accounts"),
        ("POST", "/email-verifications"),
        ("POST", "/verification-emails"),
        ("POST", "/access-tokens"),
        ("POST", "/password-reset-emails"),
        ("POST", "/password-reset-checks"),
        ("POST", "/password-resets"),
    }
)

router = APIRouter(tags=["identity"])


@router.get("/schools")
def list_schools(session: SessionDep) -> list[PublicSchool]:
    """公開的學校清單（依名稱排序）。"""
    return service.list_schools(session)


@router.post("/admin/schools", status_code=status.HTTP_201_CREATED)
def create_school(
    session: SessionDep, admin: PlatformAdmin, body: SchoolIn
) -> PublicSchool:
    """平台管理員新增學校；名稱重複回 409 `SCHOOL_NAME_TAKEN`。"""
    school = service.create_school(session, actor_id=admin.id, name=body.name)
    session.commit()
    return school


@router.patch("/admin/schools/{school_id}")
def rename_school(
    session: SessionDep, admin: PlatformAdmin, school_id: uuid.UUID, body: SchoolIn
) -> PublicSchool:
    """平台管理員修正學校名稱；不存在回 404 `SCHOOL_NOT_FOUND`，重名回 409。"""
    school = service.rename_school(
        session, actor_id=admin.id, school_id=school_id, name=body.name
    )
    session.commit()
    return school


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def register(session: SessionDep, body: AccountCreate) -> RegisteredAccount:
    """以 Email 註冊；之後要收驗證信完成驗證。不會自動登入。"""
    account = service.register(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        school_id=body.school_id,
        redirect=body.redirect,
    )
    session.commit()
    return account


@router.post("/email-verifications", status_code=status.HTTP_204_NO_CONTENT)
def verify_email(session: SessionDep, body: EmailVerificationCreate) -> None:
    """以驗證信連結中的 token 完成 Email 驗證。"""
    service.verify_email(session, token=body.token)
    session.commit()


@router.post("/verification-emails", status_code=status.HTTP_202_ACCEPTED)
def resend_verification_email(
    session: SessionDep, body: VerificationEmailCreate
) -> None:
    """重寄驗證信；不論 Email 是否已註冊或已驗證，回應都相同。"""
    service.resend_verification(session, email=body.email, redirect=body.redirect)
    session.commit()


@router.post("/password-reset-emails", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset_email(
    session: SessionDep, body: PasswordResetEmailCreate
) -> None:
    """申請重設密碼信；不論 Email 是否已註冊，回應都相同。"""
    service.request_password_reset(session, email=body.email)
    session.commit()


@router.post("/password-reset-checks", status_code=status.HTTP_204_NO_CONTENT)
def check_password_reset_link(session: SessionDep, body: PasswordResetCheck) -> None:
    """檢查重設連結是否仍有效（不會用掉 token）；失效回 400 `RESET_LINK_INVALID`。

    用 POST 是為了不讓 token 出現在存取紀錄的網址裡。
    """
    service.check_reset_token(session, token=body.token)


@router.post("/password-resets", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(session: SessionDep, body: PasswordResetCreate) -> None:
    """以重設連結的 token 設定新密碼；之前簽發的 access token 一律失效，不會自動登入。"""
    service.reset_password(session, token=body.token, new_password=body.new_password)
    session.commit()


@router.post("/access-tokens", status_code=status.HTTP_200_OK)
def login(session: SessionDep, body: AccessTokenCreate) -> AccessToken:
    """以 Email 與密碼登入，回傳 access token（之後以 `Authorization: Bearer` 帶上）。

    Email 不存在、密碼錯誤或格式不符都回 401 `INVALID_CREDENTIALS`，回應完全相同。
    """
    token = service.authenticate(session, email=body.email, password=body.password)
    # 只有雜湊需要更新時才有寫入
    session.commit()
    return token


@router.get("/accounts/me")
def read_current_account(account: CurrentAccount) -> AccountRead:
    """目前登入的帳號。"""
    return account


@router.patch("/accounts/me")
def update_current_account(
    session: SessionDep, account: CurrentAccount, body: ProfileUpdate
) -> AccountRead:
    """修改顯示名稱與學校（`school_id: null` 清除學校）；Email 與密碼不能在這裡改。"""
    updated = service.update_profile(session, account_id=account.id, changes=body)
    session.commit()
    return updated


@router.get("/accounts/me/identities")
def list_current_identities(
    session: SessionDep, account: CurrentAccount
) -> list[Identity]:
    """目前帳號擁有的身分（身分切換器用），只由後端依帳號資料產生。"""
    return service.list_identities(session, account)
