"""identity 的資料表、schema、事件與列舉。"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BaseModel, BeforeValidator, field_validator
from pydantic import Field as SchemaField
from pydantic_core import PydanticCustomError
from sqlalchemy import DateTime, Index, String, text
from sqlmodel import Field, SQLModel

from app.core import clock
from app.core.events import Event


class TokenPurpose(StrEnum):
    """一次性帳號 token 的用途。"""

    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class ApplicationStatus(StrEnum):
    """主辦方申請狀態：待審核、核准、退回（OrganizerApplication 由 Story 1.7 建立）。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


EMAIL_MAX_LENGTH = 255
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
DISPLAY_NAME_MAX_LENGTH = 50
REDIRECT_MAX_LENGTH = 2000


def normalize_email(email: str) -> str:
    """Email 一律去除前後空白、轉小寫後儲存與比對。"""
    return email.strip().lower()


# ---------------------------------------------------------------- 資料表


class School(SQLModel, table=True):
    """學校清單（初始資料為教育部大專校院名錄，由遷移檔載入）。"""

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, index=True, max_length=255)
    created_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )


class Account(SQLModel, table=True):
    """帳號。平台管理員與主辦方都是帳號上的旗標。"""

    # Email 以 lower(email) 唯一：即使有人繞過 normalize_email 也不會出現只差大小寫的重複帳號
    __table_args__ = (
        Index("ix_account_lower_email", text("lower(email)"), unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(max_length=EMAIL_MAX_LENGTH)
    hashed_password: str = Field(max_length=255)
    email_verified: bool = False
    display_name: str = Field(max_length=255)
    school_id: uuid.UUID | None = Field(default=None, foreign_key="school.id")
    is_platform_admin: bool = False
    is_organizer: bool = False
    # 憑證版本：access token 的 `ver` 與它不同時視為失效；重設密碼時＋1（登出其他裝置）
    credentials_version: int = Field(
        default=0, sa_column_kwargs={"server_default": "0"}
    )
    created_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )


class AccountToken(SQLModel, table=True):
    """一次性帳號 token：只存 SHA-256 雜湊；用過（`used_at`）或過期就失效。"""

    __tablename__ = "account_token"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    account_id: uuid.UUID = Field(foreign_key="account.id", index=True)
    purpose: TokenPurpose = Field(sa_type=String(32))
    token_hash: str = Field(max_length=64, unique=True, index=True)
    expires_at: datetime = Field(sa_type=DateTime(timezone=True))
    used_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )


# ---------------------------------------------------------------- 事件


class VerificationEmailRequested(Event):
    """需要寄驗證信：帶 token 明文，notifications 只建立 EmailDelivery。"""

    account_id: uuid.UUID
    token: str
    redirect: str | None = None


class PasswordResetRequested(Event):
    """需要寄重設密碼信：帶 token 明文，notifications 只建立 EmailDelivery。"""

    account_id: uuid.UUID
    token: str


# ---------------------------------------------------------------- API schema
# 欄位驗證錯誤以 PydanticCustomError 拋出，422 的 msg 直接是繁中訊息。


def _validate_email(value: str) -> str:
    email = normalize_email(value)
    if len(email) > EMAIL_MAX_LENGTH:
        raise PydanticCustomError("email_too_long", "Email 太長")
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        raise PydanticCustomError("email_invalid", "請輸入有效的 Email")
    return email


def _validate_password(value: str) -> str:
    if len(value) < PASSWORD_MIN_LENGTH:
        raise PydanticCustomError(
            "password_too_short", f"密碼至少需要 {PASSWORD_MIN_LENGTH} 個字元"
        )
    if len(value) > PASSWORD_MAX_LENGTH:
        raise PydanticCustomError(
            "password_too_long", f"密碼最多 {PASSWORD_MAX_LENGTH} 個字元"
        )
    return value


def _validate_display_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise PydanticCustomError("display_name_required", "請輸入顯示名稱")
    if len(name) > DISPLAY_NAME_MAX_LENGTH:
        raise PydanticCustomError(
            "display_name_too_long", f"顯示名稱最多 {DISPLAY_NAME_MAX_LENGTH} 個字"
        )
    return name


def _validate_redirect(value: str | None) -> str | None:
    """只接受站內路徑（/ 開頭、不是 // 或 /\\），避免驗證後被導到外部網站。

    控制字元與空白一律拒絕：瀏覽器解析網址時會刪掉 tab、換行，`/\\t/evil.com`
    就會變成 `//evil.com`。
    """
    if value is None or value == "":
        return None
    if (
        len(value) > REDIRECT_MAX_LENGTH
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        # C0、DEL 與 C1（U+0080～U+009F）控制字元，以及任何空白；與前端 safeRedirect 規則一致
        or any(
            ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F or ch.isspace() for ch in value
        )
    ):
        raise PydanticCustomError("redirect_invalid", "返回頁面的網址無效")
    return value


def _require_str(value: object) -> object:
    # 非字串時給繁中訊息，而不是 pydantic 預設的英文
    if not isinstance(value, str):
        raise PydanticCustomError("string_required", "請輸入文字")
    return value


EmailField = Annotated[
    str, BeforeValidator(_require_str), AfterValidator(_validate_email)
]
PasswordField = Annotated[
    str, BeforeValidator(_require_str), AfterValidator(_validate_password)
]
DisplayNameField = Annotated[
    str, BeforeValidator(_require_str), AfterValidator(_validate_display_name)
]
RedirectField = Annotated[str | None, AfterValidator(_validate_redirect)]


class PublicSchool(BaseModel):
    id: uuid.UUID
    name: str


SCHOOL_NAME_MAX_LENGTH = 255


def _validate_school_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise PydanticCustomError("school_name_required", "請輸入學校名稱")
    if len(name) > SCHOOL_NAME_MAX_LENGTH:
        raise PydanticCustomError(
            "school_name_too_long", f"學校名稱最多 {SCHOOL_NAME_MAX_LENGTH} 個字"
        )
    return name


class SchoolIn(BaseModel):
    """平台管理員新增學校或修正學校名稱（名稱去除前後空白後儲存）。"""

    name: Annotated[
        str, BeforeValidator(_require_str), AfterValidator(_validate_school_name)
    ]


class AccountCreate(BaseModel):
    email: EmailField
    password: PasswordField
    display_name: DisplayNameField
    school_id: uuid.UUID | None = None
    # 驗證成功後「繼續」要回到的站內頁面
    redirect: RedirectField = None


class RegisteredAccount(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    school_id: uuid.UUID | None
    email_verified: bool


class EmailVerificationCreate(BaseModel):
    token: str = SchemaField(min_length=1, max_length=200)


class VerificationEmailCreate(BaseModel):
    email: EmailField
    redirect: RedirectField = None


class PasswordResetEmailCreate(BaseModel):
    """S8 申請重設信；不論 Email 是否已註冊，回應都相同。"""

    email: EmailField


class PasswordResetCheck(BaseModel):
    """S9 開啟時檢查重設連結是否仍有效（不會用掉 token）。"""

    token: str = SchemaField(min_length=1, max_length=200)


class PasswordResetCreate(BaseModel):
    """S9 以重設連結的 token 設定新密碼。"""

    token: str = SchemaField(min_length=1, max_length=200)
    new_password: PasswordField


class AccessTokenCreate(BaseModel):
    """登入。不套用註冊時的格式驗證：格式不符與帳密錯誤回應完全相同（401）。"""

    email: Annotated[str, BeforeValidator(_require_str)]
    password: Annotated[str, BeforeValidator(_require_str)]


class AccessToken(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class AccountRead(BaseModel):
    """目前登入的帳號；也是 `CurrentAccount` 等權限依賴提供給 router 的型別。"""

    id: uuid.UUID
    email: str
    display_name: str
    school_id: uuid.UUID | None
    email_verified: bool
    is_platform_admin: bool
    is_organizer: bool


class IdentityKey(StrEnum):
    """身分切換器的身分；之後的 Story 會加入我的隊伍、裁判、主辦方後台。"""

    BROWSE = "browse"
    PLATFORM_ADMIN = "platform_admin"


class Identity(BaseModel):
    key: IdentityKey
    label: str
    home_path: str


class ProfileUpdate(BaseModel):
    """S10 帳號資料：只改有送出的欄位；`school_id` 送 null 代表清除學校。"""

    display_name: DisplayNameField | None = None
    school_id: uuid.UUID | None = None

    @field_validator("display_name")
    @classmethod
    def _display_name_not_null(cls, value: str | None) -> str | None:
        # 有送出 display_name 卻是 null：顯示名稱不能清除
        if value is None:
            raise PydanticCustomError("display_name_required", "請輸入顯示名稱")
        return value
