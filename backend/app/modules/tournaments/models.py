"""tournaments 的資料表、schema 與列舉。"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator
from pydantic_core import PydanticCustomError
from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
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
TOURNAMENT_NAME_MAX_LENGTH = 100
LIVESTREAM_URL_MAX_LENGTH = 2048
# 建立賽事的預設值與下限
DEFAULT_FORFEIT_MINUTES = 15
MIN_FORFEIT_MINUTES = 15
DEFAULT_APPEAL_MINUTES = 30
MIN_APPEAL_MINUTES = 30
DEFAULT_PRIORITY_HOURS = 24
# 名額不設上限（128 只是第二階段畫面的提醒門檻），只檢查 ≥ 2 與資料庫整數上限
MIN_CAPACITY = 2


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


class Tournament(SQLModel, table=True):
    """賽事。遊戲的設定在建立時複製進 `game_snapshot`，之後只讀快照（AD-12）。

    `game_snapshot` 的鍵：`game_name`、`starters`、`substitutes`、`bo`、
    `game_minutes`、`score_type`、`rank_tiers`（`[{name, score}]`，積分由高到低）。
    狀態只能經 `service.transition_tournament` 修改（AD-11）。
    """

    __tablename__ = "tournament"
    # worker 依狀態與報名開始時間找出到期的賽事
    __table_args__ = (
        Index(
            "ix_tournament_status_registration_start", "status", "registration_start"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organizer_id: uuid.UUID = Field(foreign_key="account.id", index=True)
    game_id: uuid.UUID = Field(foreign_key="game_title.id")
    name: str = Field(max_length=TOURNAMENT_NAME_MAX_LENGTH)
    status: TournamentStatus = Field(sa_type=String(16))
    mode: TournamentMode = Field(sa_type=String(16))
    # 正取名額
    capacity: int
    registration_start: datetime = Field(sa_type=DateTime(timezone=True))
    priority_end: datetime = Field(sa_type=DateTime(timezone=True))
    registration_end: datetime = Field(sa_type=DateTime(timezone=True))
    start_at: datetime = Field(sa_type=DateTime(timezone=True))
    round_interval_minutes: int
    forfeit_minutes: int
    appeal_minutes: int
    livestream_url: str | None = Field(
        default=None, max_length=LIVESTREAM_URL_MAX_LENGTH
    )
    game_snapshot: dict[str, Any] = Field(sa_type=JSONB)
    created_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=clock.now, sa_type=DateTime(timezone=True)
    )


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


# ---------------------------------------------------------------- 賽事


def _optional_str(value: object) -> object:
    return value if value is None else _require_str(value)


def _validate_livestream_url(value: str | None) -> str | None:
    """選填；空白視為未填。只接受 http／https 且有主機名稱的網址。"""
    if value is None:
        return None
    url = value.strip()
    if not url:
        return None
    if len(url) > LIVESTREAM_URL_MAX_LENGTH:
        raise PydanticCustomError(
            "url_too_long",
            "直播連結最多 {max_length} 個字",
            {"max_length": LIVESTREAM_URL_MAX_LENGTH},
        )
    try:
        parts = urlsplit(url)
        valid = parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
    except ValueError:
        valid = False
    if not valid:
        raise PydanticCustomError(
            "url_scheme_invalid", "直播連結必須是 http:// 或 https:// 開頭的網址"
        )
    return url


TournamentNameField = Annotated[
    str,
    BeforeValidator(_require_str),
    _name_validator("賽事名稱", TOURNAMENT_NAME_MAX_LENGTH),
]
CapacityField = Annotated[
    int, BeforeValidator(_require_int), _range_validator("名額", MIN_CAPACITY)
]
PriorityHoursField = Annotated[
    int, BeforeValidator(_require_int), _range_validator("優先期", 0)
]
RoundIntervalField = Annotated[
    int, BeforeValidator(_require_int), _range_validator("每輪間隔", 1)
]
ForfeitMinutesField = Annotated[
    int,
    BeforeValidator(_require_int),
    _range_validator("棄權時限", MIN_FORFEIT_MINUTES),
]
AppealMinutesField = Annotated[
    int,
    BeforeValidator(_require_int),
    _range_validator("申訴期", MIN_APPEAL_MINUTES),
]
LivestreamUrlField = Annotated[
    str | None,
    BeforeValidator(_optional_str),
    AfterValidator(_validate_livestream_url),
]


class TournamentCreate(BaseModel):
    """建立賽事。時間必須帶時區；先發、替補、BO 未填時帶入遊戲的值。

    期中一律為校園賽，不接受模式欄位。要對照遊戲或現在時間的檢查（日期順序、
    優先期、每輪間隔）由 service 進行，錯誤同樣是 422 並指向欄位。
    """

    name: TournamentNameField
    game_id: uuid.UUID
    capacity: CapacityField
    registration_start: AwareDatetime
    registration_end: AwareDatetime
    # 優先期長度（小時）：優先期結束 = 報名開始 + 優先期
    priority_hours: PriorityHoursField = DEFAULT_PRIORITY_HOURS
    start_at: AwareDatetime
    round_interval_minutes: RoundIntervalField
    forfeit_minutes: ForfeitMinutesField = DEFAULT_FORFEIT_MINUTES
    appeal_minutes: AppealMinutesField = DEFAULT_APPEAL_MINUTES
    starters: StartersField | None = None
    substitutes: SubstitutesField | None = None
    bo: BoField | None = None
    livestream_url: LivestreamUrlField = None


class TournamentRead(BaseModel):
    """賽事；遊戲相關欄位（`game_name` 以下）來自建立時的快照（AD-12）。"""

    id: uuid.UUID
    organizer_id: uuid.UUID
    name: str
    status: TournamentStatus
    # 期中一律 campus
    mode: TournamentMode
    # 正取名額
    capacity: int
    registration_start: datetime
    # 優先期結束 = registration_start + 優先期時數
    priority_end: datetime
    registration_end: datetime
    # 開賽時間（第 1 輪）
    start_at: datetime
    round_interval_minutes: int
    forfeit_minutes: int
    appeal_minutes: int
    livestream_url: str | None
    game_id: uuid.UUID
    game_name: str
    starters: int
    substitutes: int
    bo: int
    game_minutes: int
    score_type: ScoreType
    # 段位對照表快照，積分由高到低
    rank_tiers: list[RankTierRead]
