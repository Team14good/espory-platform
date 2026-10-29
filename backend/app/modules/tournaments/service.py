"""tournaments 的業務規則、資源層級權限、狀態轉換、操作紀錄與事件；不得 commit 或 rollback。"""

import uuid
from typing import Any

from sqlmodel import Session

from app.core import audit, clock
from app.core.errors import BusinessError
from app.modules.tournaments import repository
from app.modules.tournaments.models import (
    GameIn,
    GameRead,
    GameTitle,
    RankTier,
    RankTierRead,
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
