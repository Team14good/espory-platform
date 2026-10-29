"""tournaments 的資料表、schema 與列舉。"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator
from pydantic_core import PydanticCustomError
from sqlalchemy import DateTime, Index, String, text
from sqlmodel import Field, SQLModel

from app.core import clock


class ScoreType(StrEnum):
    """比分型態（AD-18）。"""

    WIN_LOSS = "win_loss"
    ROUNDS = "rounds"


class TournamentMode(StrEnum):
    """賽事模式（AD-20）：校園賽、自訂。"""

    CAMPUS = "campus"
    CUSTOM = "custom"


class TournamentStatus(StrEnum):
    """賽事狀態：尚未開放、開放報名、報名截止、賽程已公布、進行中、已結束、已取消。"""

    UPCOMING = "upcoming"
    OPEN = "open"
    CLOSED = "closed"
    PUBLISHED = "published"
    ONGOING = "ongoing"
    FINISHED = "finished"
    CANCELLED = "cancelled"


GAME_NAME_MAX_LENGTH = 100
RANK_TIER_NAME_MAX_LENGTH = 50
RANK_TIERS_MAX_COUNT = 100
ALLOWED_BO = (1, 3, 5, 7)
# 資料庫 INTEGER 的上限：超過時回 422，而不是寫入時才失敗
INT_MAX = 2_147_483_647


# ---------------------------------------------------------------- 資料表


class GameTitle(SQLModel, table=True):
    """遊戲設定（平台管理員維護）。建立賽事時複製進賽事的快照，之後不再讀取。"""

    __tablename__ = "game_title"
    # 名稱去除前後空白、不分大小寫唯一；同時新增同名遊戲時由這個索引擋下後到的
    __table_args__ = (
        Index("ix_game_title_lower_name", text("lower(btrim(name))"), unique=True),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=GAME_NAME_MAX_LENGTH)
    starters: int
    substitutes: int
    default_bo: int
    # 每局預估時間（分鐘）
    game_minutes: int
    score_type: ScoreType = Field(sa_type=String(16))
    created_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )


class RankTier(SQLModel, table=True):
    """遊戲的段位對照：段位名稱與積分。修改遊戲時整份替換。"""

    __tablename__ = "rank_tier"
    # 同遊戲內段位名稱去除前後空白、不分大小寫唯一（與 GameIn 的驗證同一規則）
    __table_args__ = (
        Index(
            "ix_rank_tier_game_id_lower_name",
            "game_id",
            text("lower(btrim(name))"),
            unique=True,
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    game_id: uuid.UUID = Field(
        foreign_key="game_title.id", ondelete="CASCADE", index=True
    )
    name: str = Field(max_length=RANK_TIER_NAME_MAX_LENGTH)
    score: int


# ---------------------------------------------------------------- API schema
# 欄位驗證錯誤以 PydanticCustomError 拋出，422 的 msg 直接是繁中訊息。


def _require_str(value: object) -> object:
    if not isinstance(value, str):
        raise PydanticCustomError("string_required", "請輸入文字")
    return value


def _require_int(value: object) -> object:
    # bool 是 int 的子類別，但 true／false 不是合法的人數
    if isinstance(value, bool) or not isinstance(value, int):
        raise PydanticCustomError("integer_required", "請輸入整數")
    return value


def _name_validator(label: str, max_length: int) -> AfterValidator:
    def _validate(value: str) -> str:
        name = value.strip()
        context = {"label": label, "max_length": max_length}
        if not name:
            raise PydanticCustomError("name_required", "請輸入{label}", context)
        if len(name) > max_length:
            raise PydanticCustomError(
                "name_too_long", "{label}最多 {max_length} 個字", context
            )
        return name

    return AfterValidator(_validate)


def _range_validator(label: str, minimum: int) -> AfterValidator:
    def _validate(value: int) -> int:
        context = {"label": label, "minimum": minimum}
        if value < minimum:
            raise PydanticCustomError(
                "number_too_small", "{label}不能小於 {minimum}", context
            )
        if value > INT_MAX:
            raise PydanticCustomError("number_too_large", "{label}太大", context)
        return value

    return AfterValidator(_validate)


def _validate_bo(value: int) -> int:
    if value not in ALLOWED_BO:
        raise PydanticCustomError("bo_invalid", "BO 數只能是 1、3、5 或 7")
    return value


GameNameField = Annotated[
    str,
    BeforeValidator(_require_str),
    _name_validator("遊戲名稱", GAME_NAME_MAX_LENGTH),
]
RankTierNameField = Annotated[
    str,
    BeforeValidator(_require_str),
    _name_validator("段位名稱", RANK_TIER_NAME_MAX_LENGTH),
]
StartersField = Annotated[
    int, BeforeValidator(_require_int), _range_validator("先發人數", 1)
]
SubstitutesField = Annotated[
    int, BeforeValidator(_require_int), _range_validator("替補人數", 0)
]
BoField = Annotated[int, BeforeValidator(_require_int), AfterValidator(_validate_bo)]
GameMinutesField = Annotated[
    int, BeforeValidator(_require_int), _range_validator("每局預估時間", 1)
]
ScoreField = Annotated[int, BeforeValidator(_require_int), _range_validator("積分", 0)]


class RankTierIn(BaseModel):
    name: RankTierNameField
    score: ScoreField


class RankTierRead(BaseModel):
    name: str
    score: int


def _validate_rank_tiers(tiers: list[RankTierIn]) -> list[RankTierIn]:
    if not tiers:
        raise PydanticCustomError("rank_tiers_required", "至少需要一筆段位")
    if len(tiers) > RANK_TIERS_MAX_COUNT:
        raise PydanticCustomError(
            "rank_tiers_too_many", f"段位最多 {RANK_TIERS_MAX_COUNT} 筆"
        )
    seen: set[str] = set()
    for tier in tiers:
        key = tier.name.casefold()
        if key in seen:
            raise PydanticCustomError(
                "rank_tier_name_duplicated",
                "段位名稱「{name}」重複",
                {"name": tier.name},
            )
        seen.add(key)
    return tiers


class GameIn(BaseModel):
    """新增或修改遊戲（修改為整份替換，含段位表）。"""

    name: GameNameField
    starters: StartersField
    substitutes: SubstitutesField
    default_bo: BoField
    game_minutes: GameMinutesField
    score_type: ScoreType
    rank_tiers: Annotated[list[RankTierIn], AfterValidator(_validate_rank_tiers)]


class GameRead(BaseModel):
    """遊戲設定；段位依積分由高到低（同分依名稱）排列。"""

    id: uuid.UUID
    name: str
    starters: int
    substitutes: int
    default_bo: int
    game_minutes: int
    score_type: ScoreType
    rank_tiers: list[RankTierRead]
