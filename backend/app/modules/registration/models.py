"""registration 的資料表、schema 與列舉。"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator
from pydantic_core import PydanticCustomError
from sqlalchemy import DateTime, Index, String, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.core import clock


class MemberRole(StrEnum):
    """隊員角色：隊長、選手。"""

    CAPTAIN = "captain"
    PLAYER = "player"


class RegistrationStatus(StrEnum):
    """報名狀態：組隊中、已送出・待分配、正取、候補、退回、撤回、已參賽、退賽、取消資格。"""

    FORMING = "forming"
    PENDING = "pending"
    ACCEPTED = "accepted"
    WAITLISTED = "waitlisted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    DRAWN = "drawn"
    RETIRED = "retired"
    DISQUALIFIED = "disqualified"


TEAM_NAME_MAX_LENGTH = 30
INVITE_TOKEN_MAX_LENGTH = 64


# ---------------------------------------------------------------- 資料表
# tournament_id 暫不加外鍵：tournament 表由 Story 2.2 建立（見 deferred-work）。


class Team(SQLModel, table=True):
    """隊伍：只屬於一個賽事。邀請 token 要能重複顯示給隊員，所以明文儲存（UNIQUE）。"""

    # 同賽事內隊名不分大小寫不可重複
    __table_args__ = (
        Index(
            "ix_team_tournament_id_lower_name",
            "tournament_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tournament_id: uuid.UUID = Field(index=True)
    name: str = Field(max_length=TEAM_NAME_MAX_LENGTH)
    invite_token: str = Field(max_length=INVITE_TOKEN_MAX_LENGTH, unique=True)
    created_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )


class TeamMember(SQLModel, table=True):
    """隊員。（tournament_id, account_id）唯一：同一帳號在同一賽事只能在一支隊伍。

    參賽資料欄位（遊戲 ID、段位、截圖）由 Story 3.2 加入。
    """

    __tablename__ = "team_member"
    __table_args__ = (
        UniqueConstraint(
            "tournament_id",
            "account_id",
            name="uq_team_member_tournament_id_account_id",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    team_id: uuid.UUID = Field(foreign_key="team.id", index=True)
    tournament_id: uuid.UUID
    account_id: uuid.UUID = Field(foreign_key="account.id", index=True)
    role: MemberRole = Field(sa_type=String(16))
    created_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )


class Registration(SQLModel, table=True):
    """報名：建立隊伍時同時產生（組隊中）；狀態只能經 `service.mark_status()` 修改。

    送出時的快照欄位（學校、平均段位積分、送出時間）由 Story 3.3 加入。
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    team_id: uuid.UUID = Field(foreign_key="team.id", unique=True)
    tournament_id: uuid.UUID = Field(index=True)
    status: RegistrationStatus = Field(sa_type=String(32))
    created_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )


# ---------------------------------------------------------------- API schema


def _require_str(value: object) -> object:
    if not isinstance(value, str):
        raise PydanticCustomError("string_required", "請輸入文字")
    return value


def _validate_team_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise PydanticCustomError("team_name_required", "請輸入隊名")
    if len(name) > TEAM_NAME_MAX_LENGTH:
        raise PydanticCustomError(
            "team_name_too_long", f"隊名最多 {TEAM_NAME_MAX_LENGTH} 個字"
        )
    return name


TeamNameField = Annotated[
    str, BeforeValidator(_require_str), AfterValidator(_validate_team_name)
]

# 邀請連結的狀態：可加入、隊伍已滿（名單鎖定由 3.3 加入）
InviteStatus = Literal["active", "full"]


class TeamCreate(BaseModel):
    """S16 建立隊伍。"""

    name: TeamNameField


class TeamMemberRead(BaseModel):
    account_id: uuid.UUID
    display_name: str
    role: MemberRole
    joined_at: datetime


class TeamDetail(BaseModel):
    """S17 隊伍頁：只有隊員看得到（含邀請 token）。"""

    id: uuid.UUID
    name: str
    tournament_id: uuid.UUID
    tournament_name: str
    game_name: str
    starters: int
    substitutes: int
    # 隊伍人數上限＝先發＋替補
    max_members: int
    members: list[TeamMemberRead]
    registration_status: RegistrationStatus
    invite_token: str
    invite_status: InviteStatus
    # 目前檢視者在這支隊伍的角色
    my_role: MemberRole


class TeamInvitePreview(BaseModel):
    """S19 加入隊伍前的公開預覽：不含隊員名單與任何個資（AD-19）。"""

    team_id: uuid.UUID
    team_name: str
    tournament_id: uuid.UUID
    tournament_name: str
    game_name: str
    member_count: int
    max_members: int
    invite_status: InviteStatus


class MyTeamCard(BaseModel):
    """S12 我的隊伍：每支隊伍一張 Registration status card。"""

    team_id: uuid.UUID
    team_name: str
    tournament_id: uuid.UUID
    tournament_name: str
    game_name: str
    registration_status: RegistrationStatus


class TeamMemberRole(BaseModel):
    account_id: uuid.UUID
    role: MemberRole


class TeamRead(BaseModel):
    """給其他模組使用的隊伍資料：隊名、隊員帳號與角色（隊長身分交給 `core.authz` 判斷）。"""

    id: uuid.UUID
    tournament_id: uuid.UUID
    name: str
    members: list[TeamMemberRole]


class RegistrationRead(BaseModel):
    """給其他模組使用的報名資料。"""

    id: uuid.UUID
    team_id: uuid.UUID
    tournament_id: uuid.UUID
    status: RegistrationStatus
    created_at: datetime
