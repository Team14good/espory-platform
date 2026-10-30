"""tournaments 的 HTTP 端點：帳號層級權限、開啟並提交交易（router 才能 commit）。"""

import uuid

from fastapi import APIRouter, status

from app.core import authz
from app.core.db import SessionDep
from app.modules.identity.deps import Organizer, PlatformAdmin
from app.modules.tournaments import service
from app.modules.tournaments.models import (
    GameIn,
    GameRead,
    TournamentCreate,
    TournamentRead,
)

router = APIRouter(tags=["tournaments"])


@router.get("/admin/games")
def list_games(session: SessionDep, _admin: PlatformAdmin) -> list[GameRead]:
    """所有遊戲設定（依名稱排序）；只限平台管理員。"""
    return service.list_games(session)


@router.post("/admin/games", status_code=status.HTTP_201_CREATED)
def create_game(session: SessionDep, admin: PlatformAdmin, body: GameIn) -> GameRead:
    """新增遊戲；名稱重複回 409 `GAME_NAME_TAKEN`。"""
    game = service.create_game(session, actor_id=admin.id, data=body)
    session.commit()
    return game


@router.get("/admin/games/{game_id}")
def read_game(
    session: SessionDep, _admin: PlatformAdmin, game_id: uuid.UUID
) -> GameRead:
    """一款遊戲的設定；不存在回 404 `GAME_NOT_FOUND`。"""
    return service.get_game(session, game_id=game_id)


@router.put("/admin/games/{game_id}")
def update_game(
    session: SessionDep, admin: PlatformAdmin, game_id: uuid.UUID, body: GameIn
) -> GameRead:
    """整份替換遊戲設定（含段位表）；不存在回 404，名稱重複回 409。"""
    game = service.update_game(session, actor_id=admin.id, game_id=game_id, data=body)
    session.commit()
    return game


# ---------------------------------------------------------------- 主辦方


@router.get("/games")
def list_games_for_organizer(
    session: SessionDep, _organizer: Organizer
) -> list[GameRead]:
    """主辦方建立賽事時可選的遊戲（依名稱排序）；只限主辦方。"""
    return service.list_games(session)


@router.post("/organizer/tournaments", status_code=status.HTTP_201_CREATED)
def create_tournament(
    session: SessionDep, organizer: Organizer, body: TournamentCreate
) -> TournamentRead:
    """建立賽事；遊戲不存在回 404 `GAME_NOT_FOUND`，欄位不合法回 422。"""
    tournament = service.create_tournament(
        session, organizer_id=organizer.id, data=body
    )
    session.commit()
    return tournament


@router.get("/organizer/tournaments")
def list_my_tournaments(
    session: SessionDep, organizer: Organizer
) -> list[TournamentRead]:
    """目前主辦方建立的賽事，新建立的在前。"""
    return service.list_organizer_tournaments(session, organizer_id=organizer.id)


@router.get("/organizer/tournaments/{tournament_id}")
def read_my_tournament(
    session: SessionDep, organizer: Organizer, tournament_id: uuid.UUID
) -> TournamentRead:
    """主辦方自己的賽事；不存在回 404，別人的賽事回 403 `TOURNAMENT_OWNER_REQUIRED`。"""
    tournament = service.get_tournament(session, tournament_id=tournament_id)
    authz.ensure_tournament_owner(tournament, organizer.id)
    return tournament
