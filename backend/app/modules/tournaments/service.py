"""tournaments 的業務規則、資源層級權限、狀態轉換、操作紀錄與事件；不得 commit 或 rollback。"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session

from app.core import audit, clock
from app.core.errors import BusinessError, FieldError
from app.modules.tournaments import repository
from app.modules.tournaments.models import (
    GameIn,
    GameRead,
    GameTitle,
    RankTier,
    RankTierRead,
    Tournament,
    TournamentCreate,
    TournamentMode,
    TournamentRead,
    TournamentStatus,
)

# 遊戲本身的欄位（段位表另外處理）
_GAME_FIELDS = (
    "name",
    "starters",
    "substitutes",
    "default_bo",
    "game_minutes",
    "score_type",
)


# ---------------------------------------------------------------- 遊戲設定
# 程式中不得依遊戲名稱或 id 寫分支（AD-18）：所有差異都來自設定值。


def _game_not_found() -> BusinessError:
    return BusinessError("GAME_NOT_FOUND", "找不到這款遊戲。", status_code=404)


def _game_name_taken() -> BusinessError:
    return BusinessError("GAME_NAME_TAKEN", "已經有同名的遊戲。", status_code=409)


def _sorted_tiers(tiers: list[RankTierRead]) -> list[RankTierRead]:
    """積分由高到低；同分依名稱（逐碼位）排列，與資料庫的 COLLATE "C" 一致。"""
    return sorted(tiers, key=lambda tier: (-tier.score, tier.name))


def _to_read(game: GameTitle, tiers: list[RankTier]) -> GameRead:
    return GameRead(
        id=game.id,
        name=game.name,
        starters=game.starters,
        substitutes=game.substitutes,
        default_bo=game.default_bo,
        game_minutes=game.game_minutes,
        score_type=game.score_type,
        rank_tiers=_sorted_tiers(
            [RankTierRead(name=tier.name, score=tier.score) for tier in tiers]
        ),
    )


def _new_tiers(game_id: uuid.UUID, data: GameIn) -> list[RankTier]:
    return [
        RankTier(game_id=game_id, name=tier.name, score=tier.score)
        for tier in data.rank_tiers
    ]


def _tiers_for_audit(tiers: list[RankTierRead]) -> list[dict[str, Any]]:
    return [tier.model_dump() for tier in _sorted_tiers(tiers)]


def list_games(session: Session) -> list[GameRead]:
    """所有遊戲，依名稱排序。"""
    games = repository.list_games(session)
    tiers_by_game: dict[uuid.UUID, list[RankTier]] = {game.id: [] for game in games}
    for tier in repository.list_rank_tiers(session, list(tiers_by_game)):
        tiers_by_game[tier.game_id].append(tier)
    return [_to_read(game, tiers_by_game[game.id]) for game in games]


def get_game(session: Session, *, game_id: uuid.UUID) -> GameRead:
    """讀取一款遊戲的設定（2.2 建立賽事時複製成快照）；不存在拋 404 `GAME_NOT_FOUND`。"""
    game = repository.get_game(session, game_id)
    if game is None:
        raise _game_not_found()
    return _to_read(game, repository.list_rank_tiers(session, [game.id]))


def create_game(session: Session, *, actor_id: uuid.UUID, data: GameIn) -> GameRead:
    """新增遊戲；名稱（去除前後空白、不分大小寫）重複拋 409 `GAME_NAME_TAKEN`。"""
    if repository.get_game_by_name(session, data.name) is not None:
        raise _game_name_taken()
    now = clock.now()
    game = GameTitle(
        name=data.name,
        starters=data.starters,
        substitutes=data.substitutes,
        default_bo=data.default_bo,
        game_minutes=data.game_minutes,
        score_type=data.score_type,
        created_at=now,
        updated_at=now,
    )
    tiers = _new_tiers(game.id, data)
    try:
        repository.add_game(session, game, tiers)
    except repository.DuplicateGameNameError:
        # 兩個請求同時新增同名遊戲：後到的撞到唯一索引
        raise _game_name_taken() from None

    created = _to_read(game, tiers)
    after: dict[str, Any] = {field: getattr(created, field) for field in _GAME_FIELDS}
    after["rank_tiers"] = _tiers_for_audit(created.rank_tiers)
    audit.record(
        session,
        actor_id=actor_id,
        tournament_id=None,
        action="game.created",
        entity_type="game",
        entity_id=game.id,
        before=None,
        after=after,
    )
    return created


def update_game(
    session: Session, *, actor_id: uuid.UUID, game_id: uuid.UUID, data: GameIn
) -> GameRead:
    """整份替換遊戲設定（含段位表）。

    不存在拋 404 `GAME_NOT_FOUND`；改成其他遊戲的名稱拋 409 `GAME_NAME_TAKEN`。
    有變動時寫 `game.updated`，before／after 只含有變動的欄位（段位表以整份比較）。
    """
    game = repository.get_game(session, game_id, for_update=True)
    if game is None:
        raise _game_not_found()
    current = _to_read(game, repository.list_rank_tiers(session, [game.id]))

    same_name = repository.get_game_by_name(session, data.name)
    if same_name is not None and same_name.id != game.id:
        raise _game_name_taken()

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field in _GAME_FIELDS:
        old, new = getattr(current, field), getattr(data, field)
        if old != new:
            before[field] = old
            after[field] = new
    old_tiers = _tiers_for_audit(current.rank_tiers)
    new_tiers = _tiers_for_audit(
        [RankTierRead(name=tier.name, score=tier.score) for tier in data.rank_tiers]
    )
    if old_tiers != new_tiers:
        before["rank_tiers"] = old_tiers
        after["rank_tiers"] = new_tiers

    if not after:
        return current

    changes = {field: after[field] for field in _GAME_FIELDS if field in after}
    changes["updated_at"] = clock.now()
    try:
        repository.update_game(session, game, changes)
    except repository.DuplicateGameNameError:
        # 等鎖期間另一個請求把別款遊戲改成這個名稱
        raise _game_name_taken() from None
    if "rank_tiers" in after:
        repository.replace_rank_tiers(session, game.id, _new_tiers(game.id, data))

    audit.record(
        session,
        actor_id=actor_id,
        tournament_id=None,
        action="game.updated",
        entity_type="game",
        entity_id=game.id,
        before=before,
        after=after,
    )
    return get_game(session, game_id=game.id)


# ---------------------------------------------------------------- 賽事
# 遊戲相關的值在建立時複製進 game_snapshot，之後只讀快照（AD-12）。

# 允許的狀態轉換（contracts/tournaments.md〈三〉）
_TRANSITIONS: dict[TournamentStatus, frozenset[TournamentStatus]] = {
    TournamentStatus.UPCOMING: frozenset(
        {TournamentStatus.OPEN, TournamentStatus.CANCELLED}
    ),
    TournamentStatus.OPEN: frozenset(
        {
            TournamentStatus.CLOSED,
            TournamentStatus.PUBLISHED,
            TournamentStatus.CANCELLED,
        }
    ),
    TournamentStatus.CLOSED: frozenset(
        {
            TournamentStatus.OPEN,
            TournamentStatus.PUBLISHED,
            TournamentStatus.CANCELLED,
        }
    ),
    TournamentStatus.PUBLISHED: frozenset(
        {TournamentStatus.ONGOING, TournamentStatus.CANCELLED}
    ),
    TournamentStatus.ONGOING: frozenset(
        {TournamentStatus.FINISHED, TournamentStatus.CANCELLED}
    ),
    TournamentStatus.FINISHED: frozenset(),
    TournamentStatus.CANCELLED: frozenset(),
}

_SCORING_STATUSES = frozenset({TournamentStatus.PUBLISHED, TournamentStatus.ONGOING})


def _tournament_not_found() -> BusinessError:
    return BusinessError("TOURNAMENT_NOT_FOUND", "找不到這場賽事。", status_code=404)


def _field_error(field: str, code: str, message: str) -> FieldError:
    return FieldError(code, message, loc=("body", field))


def _tournament_to_read(tournament: Tournament) -> TournamentRead:
    snapshot = tournament.game_snapshot
    return TournamentRead(
        id=tournament.id,
        organizer_id=tournament.organizer_id,
        name=tournament.name,
        status=tournament.status,
        mode=tournament.mode,
        capacity=tournament.capacity,
        registration_start=tournament.registration_start,
        priority_end=tournament.priority_end,
        registration_end=tournament.registration_end,
        start_at=tournament.start_at,
        round_interval_minutes=tournament.round_interval_minutes,
        forfeit_minutes=tournament.forfeit_minutes,
        appeal_minutes=tournament.appeal_minutes,
        livestream_url=tournament.livestream_url,
        game_id=tournament.game_id,
        game_name=snapshot["game_name"],
        starters=snapshot["starters"],
        substitutes=snapshot["substitutes"],
        bo=snapshot["bo"],
        game_minutes=snapshot["game_minutes"],
        score_type=snapshot["score_type"],
        rank_tiers=[RankTierRead.model_validate(t) for t in snapshot["rank_tiers"]],
    )


def min_round_interval(
    *, forfeit_minutes: int, bo: int, game_minutes: int, appeal_minutes: int
) -> int:
    """每輪間隔的下限：棄權時限＋BO × 每局預估時間＋申訴期（分鐘）。"""
    return forfeit_minutes + bo * game_minutes + appeal_minutes


def _validate_schedule(
    data: TournamentCreate, *, bo: int, game_minutes: int, now: datetime
) -> None:
    """要對照現在時間或遊戲設定的欄位檢查；違反時拋 422 並指向欄位。"""
    if data.start_at <= now:
        raise _field_error("start_at", "START_AT_PASSED", "開賽時間必須晚於現在")
    if data.registration_end > data.start_at:
        raise _field_error(
            "registration_end",
            "REGISTRATION_END_AFTER_START",
            "報名截止不能晚於開賽時間",
        )
    if data.registration_end <= now:
        raise _field_error(
            "registration_end", "REGISTRATION_END_PASSED", "報名截止必須晚於現在"
        )
    if data.registration_start >= data.registration_end:
        raise _field_error(
            "registration_start",
            "REGISTRATION_START_NOT_BEFORE_END",
            "報名開始必須早於報名截止",
        )
    # 以時間長度比較，避免極大的優先期在相加時溢位
    if timedelta(hours=data.priority_hours) > (
        data.registration_end - data.registration_start
    ):
        raise _field_error(
            "priority_hours",
            "PRIORITY_END_AFTER_REGISTRATION_END",
            "優先期結束（報名開始＋優先期）不能晚於報名截止",
        )
    minimum = min_round_interval(
        forfeit_minutes=data.forfeit_minutes,
        bo=bo,
        game_minutes=game_minutes,
        appeal_minutes=data.appeal_minutes,
    )
    if data.round_interval_minutes < minimum:
        raise _field_error(
            "round_interval_minutes",
            "ROUND_INTERVAL_TOO_SHORT",
            f"每輪間隔至少 {minimum} 分鐘",
        )


def create_tournament(
    session: Session, *, organizer_id: uuid.UUID, data: TournamentCreate
) -> TournamentRead:
    """建立賽事（期中一律校園賽）並複製遊戲快照；寫 `tournament.created`。

    遊戲不存在拋 404 `GAME_NOT_FOUND`；欄位不合法拋 422（`FieldError`，指向欄位）。
    報名開始已到時狀態為 `open`，否則為 `upcoming`（由 worker 到時開放）。
    """
    # 以 FOR SHARE 鎖住遊戲列：修改遊戲（FOR UPDATE）要等本交易結束，遊戲欄位與
    # 段位表因此取自同一個版本；多個主辦方同時以同一款遊戲建立賽事則不互相等待
    game_row = repository.get_game(session, data.game_id, for_share=True)
    if game_row is None:
        raise _game_not_found()
    game = _to_read(game_row, repository.list_rank_tiers(session, [game_row.id]))

    starters = data.starters if data.starters is not None else game.starters
    substitutes = data.substitutes if data.substitutes is not None else game.substitutes
    bo = data.bo if data.bo is not None else game.default_bo
    now = clock.now()
    _validate_schedule(data, bo=bo, game_minutes=game.game_minutes, now=now)

    registration_start = data.registration_start.astimezone(UTC)
    tournament = Tournament(
        organizer_id=organizer_id,
        game_id=game.id,
        name=data.name,
        status=(
            TournamentStatus.OPEN
            if registration_start <= now
            else TournamentStatus.UPCOMING
        ),
        mode=TournamentMode.CAMPUS,
        capacity=data.capacity,
        registration_start=registration_start,
        priority_end=registration_start + timedelta(hours=data.priority_hours),
        registration_end=data.registration_end.astimezone(UTC),
        start_at=data.start_at.astimezone(UTC),
        round_interval_minutes=data.round_interval_minutes,
        forfeit_minutes=data.forfeit_minutes,
        appeal_minutes=data.appeal_minutes,
        livestream_url=data.livestream_url,
        game_snapshot={
            "game_name": game.name,
            "starters": starters,
            "substitutes": substitutes,
            "bo": bo,
            "game_minutes": game.game_minutes,
            "score_type": game.score_type.value,
            "rank_tiers": [tier.model_dump() for tier in game.rank_tiers],
        },
        created_at=now,
        updated_at=now,
    )
    repository.add_tournament(session, tournament)

    created = _tournament_to_read(tournament)
    audit.record(
        session,
        actor_id=organizer_id,
        tournament_id=tournament.id,
        action="tournament.created",
        entity_type="tournament",
        entity_id=tournament.id,
        before=None,
        after=created.model_dump(exclude={"id"}),
    )
    return created


def get_tournament(session: Session, *, tournament_id: uuid.UUID) -> TournamentRead:
    """讀取賽事；不存在拋 404 `TOURNAMENT_NOT_FOUND`。"""
    tournament = repository.get_tournament(session, tournament_id)
    if tournament is None:
        raise _tournament_not_found()
    return _tournament_to_read(tournament)


def lock_tournament(session: Session, *, tournament_id: uuid.UUID) -> TournamentRead:
    """`SELECT ... FOR UPDATE` 鎖住賽事列並回傳最新值；鎖賽事的唯一入口（AD-6）。

    同時要鎖場次等其他資料時，先鎖賽事。不存在拋 404 `TOURNAMENT_NOT_FOUND`。
    """
    tournament = repository.get_tournament(session, tournament_id, for_update=True)
    if tournament is None:
        raise _tournament_not_found()
    return _tournament_to_read(tournament)


def list_organizer_tournaments(
    session: Session, *, organizer_id: uuid.UUID
) -> list[TournamentRead]:
    """某主辦方建立的賽事，新建立的在前。"""
    return [
        _tournament_to_read(tournament)
        for tournament in repository.list_tournaments_by_organizer(
            session, organizer_id
        )
    ]


def transition_tournament(
    session: Session,
    *,
    tournament_id: uuid.UUID,
    to: TournamentStatus,
    actor_id: uuid.UUID | None,
) -> TournamentRead:
    """改變賽事狀態的唯一入口（AD-11）；寫 `tournament.status_changed`。

    呼叫前應先 `lock_tournament`（這裡也會再鎖一次，同一交易內不會等待）。
    不允許的轉換拋 409 `TOURNAMENT_INVALID_TRANSITION`；`actor_id=None` 表示系統。
    """
    tournament = repository.get_tournament(session, tournament_id, for_update=True)
    if tournament is None:
        raise _tournament_not_found()
    current = TournamentStatus(tournament.status)
    if to not in _TRANSITIONS[current]:
        raise BusinessError(
            "TOURNAMENT_INVALID_TRANSITION",
            "賽事目前的狀態不能進行這個操作。",
            status_code=409,
        )
    repository.set_tournament_status(session, tournament, to, clock.now())
    audit.record(
        session,
        actor_id=actor_id,
        tournament_id=tournament.id,
        action="tournament.status_changed",
        entity_type="tournament",
        entity_id=tournament.id,
        before={"status": current.value},
        after={"status": to.value},
    )
    return _tournament_to_read(tournament)


def ensure_accepting_registrations(tournament: TournamentRead) -> None:
    """賽事開放報名中；否則拋 409 `REGISTRATION_CLOSED`。只看狀態，不碰資料庫。"""
    if tournament.status != TournamentStatus.OPEN:
        raise BusinessError(
            "REGISTRATION_CLOSED", "這場賽事目前不開放報名。", status_code=409
        )


def ensure_accepting_scores(tournament: TournamentRead) -> None:
    """賽程已公布或進行中；否則拋 409 `TOURNAMENT_NOT_ACCEPTING_SCORES`。不碰資料庫。"""
    if tournament.status not in _SCORING_STATUSES:
        raise BusinessError(
            "TOURNAMENT_NOT_ACCEPTING_SCORES",
            "這場賽事目前不接受比分回報。",
            status_code=409,
        )


def bo_for_round(session: Session, *, tournament_id: uuid.UUID, round_no: int) -> int:
    """某一輪（從 1 起算）的 BO；期中不做分輪 BO（2.3），一律回傳賽事的 BO。"""
    if round_no < 1:
        raise ValueError(f"round_no must start from 1: {round_no}")
    return get_tournament(session, tournament_id=tournament_id).bo


def open_due_registration(session: Session) -> bool:
    """worker 用：把一筆報名開始已到的 `upcoming` 賽事轉為 `open`（操作者為系統）。

    先找到候選、鎖住後重新檢查；已被其他 worker 處理過就不做任何事。
    回傳是否找到候選（找到就可能還有下一筆）。
    """
    now = clock.now()
    tournament_id = repository.find_due_upcoming_id(session, now)
    if tournament_id is None:
        return False
    tournament = lock_tournament(session, tournament_id=tournament_id)
    if (
        tournament.status == TournamentStatus.UPCOMING
        and tournament.registration_start <= now
    ):
        transition_tournament(
            session,
            tournament_id=tournament_id,
            to=TournamentStatus.OPEN,
            actor_id=None,
        )
    return True
