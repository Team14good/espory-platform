"""identity 的業務規則、資源層級權限、狀態轉換、操作紀錄與事件；不得 commit 或 rollback。"""

import hashlib
import secrets
import uuid
from datetime import timedelta
from functools import cache
from typing import Any

from pydantic import BaseModel
from sqlmodel import Session

from app.core import audit, clock, events
from app.core.config import settings
from app.core.errors import BusinessError, FieldError
from app.core.security import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.modules.identity import repository
from app.modules.identity.models import (
    EMAIL_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    AccessToken,
    Account,
    AccountRead,
    AccountToken,
    Identity,
    IdentityKey,
    PasswordResetRequested,
    ProfileUpdate,
    PublicSchool,
    RegisteredAccount,
    TokenPurpose,
    VerificationEmailRequested,
    normalize_email,
)

FIRST_ADMIN_DISPLAY_NAME = "平台管理員"
VERIFY_EMAIL_TOKEN_TTL = timedelta(hours=24)
RESET_PASSWORD_TOKEN_TTL = timedelta(hours=1)


class AccountContact(BaseModel):
    """給其他模組（notifications 寄信）使用的帳號聯絡資料。"""

    id: uuid.UUID
    email: str
    display_name: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_first_admin(session: Session, *, email: str, password: str) -> bool:
    """建立第一個平台管理員；同 Email 已存在就略過、不覆寫任何欄位。

    回傳是否新建了帳號。交易由呼叫端（`app.initial_data`）提交。
    """
    email = normalize_email(email)
    if repository.get_account_by_email(session, email) is not None:
        return False
    repository.add_account(
        session,
        Account(
            email=email,
            hashed_password=get_password_hash(password),
            email_verified=True,
            display_name=FIRST_ADMIN_DISPLAY_NAME,
            is_platform_admin=True,
        ),
    )
    return True


def list_schools(session: Session) -> list[PublicSchool]:
    """公開的學校清單，依名稱排序。"""
    return [
        PublicSchool.model_validate(school, from_attributes=True)
        for school in repository.list_schools(session)
    ]


def get_account_contact(
    session: Session, account_id: uuid.UUID
) -> AccountContact | None:
    account = repository.get_account(session, account_id)
    if account is None:
        return None
    return AccountContact.model_validate(account, from_attributes=True)


def _school_not_found() -> FieldError:
    return FieldError("SCHOOL_NOT_FOUND", "找不到這間學校", loc=("body", "school_id"))


def _email_already_registered() -> BusinessError:
    return BusinessError(
        "EMAIL_ALREADY_REGISTERED", "這個 Email 已經註冊過。", status_code=409
    )


def _issue_verification_token(
    session: Session, account: Account, *, redirect: str | None
) -> None:
    """作廢舊的驗證 token、產生新的，並發出 VerificationEmailRequested。"""
    repository.delete_unused_tokens(session, account.id, TokenPurpose.VERIFY_EMAIL)
    token = secrets.token_urlsafe(32)
    repository.add_token(
        session,
        AccountToken(
            account_id=account.id,
            purpose=TokenPurpose.VERIFY_EMAIL,
            token_hash=hash_token(token),
            expires_at=clock.now() + VERIFY_EMAIL_TOKEN_TTL,
            created_at=clock.now(),
        ),
    )
    events.publish(
        session,
        VerificationEmailRequested(
            account_id=account.id, token=token, redirect=redirect
        ),
    )


def register(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    school_id: uuid.UUID | None,
    redirect: str | None = None,
) -> RegisteredAccount:
    """以 Email 註冊：帳號、驗證 token 與事件在同一個交易寫入；不自動登入。"""
    email = normalize_email(email)
    if school_id is not None and repository.get_school(session, school_id) is None:
        raise _school_not_found()
    if repository.get_account_by_email(session, email) is not None:
        raise _email_already_registered()

    account = Account(
        email=email,
        hashed_password=get_password_hash(password),
        email_verified=False,
        display_name=display_name.strip(),
        school_id=school_id,
        created_at=clock.now(),
    )
    try:
        repository.add_account(session, account)
    except repository.DuplicateEmailError:
        # 兩個請求同時註冊同一個 Email：後到的撞到唯一索引
        raise _email_already_registered()

    audit.record(
        session,
        actor_id=account.id,
        tournament_id=None,
        action="account.registered",
        entity_type="account",
        entity_id=account.id,
        before=None,
        after={
            "email": account.email,
            "display_name": account.display_name,
            "school_id": account.school_id,
        },
    )
    _issue_verification_token(session, account, redirect=redirect)
    return RegisteredAccount.model_validate(account, from_attributes=True)


def verify_email(session: Session, *, token: str) -> None:
    """以驗證連結的 token 完成 Email 驗證；token 用過、過期或已作廢都會被拒絕。"""
    record = repository.get_token_by_hash(
        session, hash_token(token), TokenPurpose.VERIFY_EMAIL, for_update=True
    )
    now = clock.now()
    if record is None or record.used_at is not None or record.expires_at <= now:
        raise BusinessError(
            "VERIFICATION_LINK_INVALID", "此驗證連結已失效。", status_code=400
        )
    account = repository.get_account(session, record.account_id)
    assert account is not None  # 外鍵保證帳號存在

    record.used_at = now
    session.add(record)
    if not account.email_verified:
        account.email_verified = True
        session.add(account)
        audit.record(
            session,
            actor_id=account.id,
            tournament_id=None,
            action="account.email_verified",
            entity_type="account",
            entity_id=account.id,
            before={"email_verified": False},
            after={"email_verified": True},
        )
    session.flush()


def is_verification_token_active(session: Session, token: str) -> bool:
    """驗證 token 是否仍可使用：存在（沒被重寄作廢）、沒用過、沒過期，且帳號尚未驗證。

    notifications 寄驗證信前呼叫，避免寄出連結已失效的信。
    """
    record = repository.get_token_by_hash(
        session, hash_token(token), TokenPurpose.VERIFY_EMAIL
    )
    if record is None or record.used_at is not None:
        return False
    if record.expires_at <= clock.now():
        return False
    account = repository.get_account(session, record.account_id)
    return account is not None and not account.email_verified


def resend_verification(
    session: Session, *, email: str, redirect: str | None = None
) -> None:
    """重寄驗證信。不論 Email 是否存在、是否已驗證，呼叫端的回應都相同；
    只有存在且未驗證的帳號會產生新 token 與事件。"""
    account = repository.get_account_by_email(
        session, normalize_email(email), for_update=True
    )
    if account is None or account.email_verified:
        return
    _issue_verification_token(session, account, redirect=redirect)


# ---------------------------------------------------------------- 忘記與重設密碼


def _reset_link_invalid() -> BusinessError:
    return BusinessError("RESET_LINK_INVALID", "此重設連結已失效。", status_code=400)


def _issue_reset_token(session: Session, account: Account) -> None:
    """作廢舊的重設 token、產生新的，並發出 PasswordResetRequested。"""
    repository.delete_unused_tokens(session, account.id, TokenPurpose.RESET_PASSWORD)
    token = secrets.token_urlsafe(32)
    now = clock.now()
    repository.add_token(
        session,
        AccountToken(
            account_id=account.id,
            purpose=TokenPurpose.RESET_PASSWORD,
            token_hash=hash_token(token),
            expires_at=now + RESET_PASSWORD_TOKEN_TTL,
            created_at=now,
        ),
    )
    events.publish(session, PasswordResetRequested(account_id=account.id, token=token))


def request_password_reset(session: Session, *, email: str) -> None:
    """S8 申請重設信。不論 Email 是否存在，呼叫端的回應都相同；
    只有已註冊的帳號（未驗證 Email 的也可以）會產生新 token 與事件。"""
    account = repository.get_account_by_email(
        session, normalize_email(email), for_update=True
    )
    if account is None:
        return
    _issue_reset_token(session, account)


def _active_reset_token(
    session: Session, token: str, *, for_update: bool = False
) -> AccountToken | None:
    """存在（沒被重新申請作廢）、沒用過、沒過期的重設 token；否則回傳 None。"""
    record = repository.get_token_by_hash(
        session, hash_token(token), TokenPurpose.RESET_PASSWORD, for_update=for_update
    )
    if record is None or record.used_at is not None:
        return None
    if record.expires_at <= clock.now():
        return None
    return record


def is_reset_token_active(session: Session, token: str) -> bool:
    """重設 token 是否仍可使用；notifications 寄重設信前呼叫，避免寄出已失效的連結。"""
    return _active_reset_token(session, token) is not None


def check_reset_token(session: Session, *, token: str) -> None:
    """S9 開啟時檢查重設連結；失效拋 `RESET_LINK_INVALID`。不會用掉 token。"""
    if not is_reset_token_active(session, token):
        raise _reset_link_invalid()


def reset_password(session: Session, *, token: str, new_password: str) -> None:
    """以重設連結的 token 設定新密碼；token 用過、過期或已作廢都拋 `RESET_LINK_INVALID`。

    成功時：更新密碼雜湊、`credentials_version`＋1（之前簽發的 access token 全部失效）、
    token 寫入 `used_at`；未驗證 Email 的帳號一併視為已驗證。不自動登入。
    """
    # 加鎖順序與申請重設（先帳號、再 token）一致，避免兩者同時進行時互相等待
    found = repository.get_token_by_hash(
        session, hash_token(token), TokenPurpose.RESET_PASSWORD
    )
    if found is None:
        raise _reset_link_invalid()
    account = repository.get_account(session, found.account_id, for_update=True)
    if account is None:
        raise _reset_link_invalid()
    # 鎖住後再判斷一次：等鎖期間 token 可能已被用掉或被重新申請作廢
    record = _active_reset_token(session, token, for_update=True)
    if record is None:
        raise _reset_link_invalid()

    now = clock.now()
    record.used_at = now
    session.add(record)
    account.hashed_password = get_password_hash(new_password)
    account.credentials_version += 1
    session.add(account)
    audit.record(
        session,
        actor_id=account.id,
        tournament_id=None,
        action="account.password_reset",
        entity_type="account",
        entity_id=account.id,
        # 不記錄任何密碼或雜湊，只記錄憑證版本的變化
        before={"credentials_version": account.credentials_version - 1},
        after={"credentials_version": account.credentials_version},
    )
    if not account.email_verified:
        # 能收到重設信就代表擁有這個 Email
        account.email_verified = True
        audit.record(
            session,
            actor_id=account.id,
            tournament_id=None,
            action="account.email_verified",
            entity_type="account",
            entity_id=account.id,
            before={"email_verified": False},
            after={"email_verified": True},
        )
    session.flush()


# ---------------------------------------------------------------- 登入與目前帳號


def invalid_credentials() -> BusinessError:
    return BusinessError("INVALID_CREDENTIALS", "Email 或密碼錯誤。", status_code=401)


def authentication_required() -> BusinessError:
    return BusinessError(
        "AUTHENTICATION_REQUIRED",
        "請先登入。",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


@cache
def _dummy_password_hash() -> str:
    """帳號不存在時拿來比對的雜湊：讓回應時間不透露帳號是否存在。"""
    return get_password_hash(secrets.token_urlsafe(16))


def authenticate(session: Session, *, email: str, password: str) -> AccessToken:
    """以 Email 與密碼登入，回傳 access token；未驗證 Email 的帳號也可以登入。

    Email 不存在、密碼錯誤或格式不符都拋同一個 `INVALID_CREDENTIALS`；
    Email 不存在時也跑一次雜湊比對。登入不寫操作紀錄。
    """
    email = normalize_email(email)
    account = None
    if len(email) <= EMAIL_MAX_LENGTH:
        account = repository.get_account_by_email(session, email)
    # 超過長度上限的密碼不可能是正確的密碼；截斷後再比對，避免拿超長字串做雜湊
    candidate = password[:PASSWORD_MAX_LENGTH]
    if account is None:
        verify_password(candidate, _dummy_password_hash())
        raise invalid_credentials()
    verified, updated_hash = verify_password(candidate, account.hashed_password)
    if not verified or len(password) > PASSWORD_MAX_LENGTH:
        raise invalid_credentials()
    if updated_hash is not None:
        # 雜湊演算法或參數已更新：順手換成新的雜湊（不是業務資料的變更，不寫操作紀錄）
        account.hashed_password = updated_hash
        session.add(account)
        session.flush()

    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return AccessToken(
        access_token=create_access_token(
            account.id, lifetime, version=account.credentials_version
        ),
        expires_at=clock.now() + lifetime,
    )


def get_current_account(session: Session, token: str) -> AccountRead:
    """以 access token 取得目前帳號；token 無效、過期、帳號不存在，或憑證版本與帳號
    目前的不同（簽發後重設過密碼）都拋 401。"""
    claims = decode_access_token(token)
    if claims is None:
        raise authentication_required()
    try:
        account_id = uuid.UUID(claims.subject)
    except ValueError:
        raise authentication_required() from None
    account = repository.get_account(session, account_id)
    if account is None or account.credentials_version != claims.version:
        raise authentication_required()
    return AccountRead.model_validate(account, from_attributes=True)


def list_identities(session: Session, account: AccountRead) -> list[Identity]:  # noqa: ARG001
    """身分切換器的身分清單，只依帳號資料產生；切換身分不改變權限。

    之後的 Story 在這裡加入「我的隊伍」「裁判」「主辦方後台」（會用到 session 查詢）。
    """
    identities = [
        Identity(key=IdentityKey.BROWSE, label="瀏覽賽事", home_path="/"),
        # Story 3.1：所有登入帳號都顯示（沒有隊伍時 S12 顯示空狀態）
        Identity(key=IdentityKey.MY_TEAMS, label="我的隊伍", home_path="/me/teams"),
    ]
    if account.is_platform_admin:
        identities.append(
            Identity(
                key=IdentityKey.PLATFORM_ADMIN,
                label="平台管理",
                home_path="/admin/applications",
            )
        )
    return identities


def update_profile(
    session: Session, *, account_id: uuid.UUID, changes: ProfileUpdate
) -> AccountRead:
    """修改顯示名稱與學校（`school_id` 為 None 代表清除）；Email 不能在這裡修改。

    只處理有送出的欄位；有變動時寫操作紀錄 `account.profile_updated`，
    before／after 只含有變動的欄位。
    """
    account = repository.get_account(session, account_id)
    if account is None:
        raise authentication_required()

    requested: dict[str, Any] = {}
    if "display_name" in changes.model_fields_set and changes.display_name is not None:
        requested["display_name"] = changes.display_name
    if "school_id" in changes.model_fields_set:
        if (
            changes.school_id is not None
            and repository.get_school(session, changes.school_id) is None
        ):
            raise _school_not_found()
        requested["school_id"] = changes.school_id

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in requested.items():
        current = getattr(account, field)
        if current != value:
            before[field] = current
            after[field] = value
            setattr(account, field, value)

    if after:
        session.add(account)
        audit.record(
            session,
            actor_id=account.id,
            tournament_id=None,
            action="account.profile_updated",
            entity_type="account",
            entity_id=account.id,
            before=before,
            after=after,
        )
        session.flush()
    return AccountRead.model_validate(account, from_attributes=True)
