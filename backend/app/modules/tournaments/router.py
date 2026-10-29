"""tournaments 的 HTTP 端點：帳號層級權限、開啟並提交交易（router 才能 commit）。"""

import uuid

from fastapi import APIRouter, status

from app.core.db import SessionDep
from app.modules.identity.deps import PlatformAdmin
from app.modules.tournaments import service
from app.modules.tournaments.models import GameIn, GameRead

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
