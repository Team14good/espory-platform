"""registration 的 HTTP 端點：帳號層級權限、開啟並提交交易（router 才能 commit）。"""

import uuid

from fastapi import APIRouter, status

from app.core.db import SessionDep
from app.modules.identity.deps import CurrentAccount, VerifiedAccount
from app.modules.registration import service
from app.modules.registration.models import (
    MyTeamCard,
    TeamCreate,
    TeamDetail,
    TeamInvitePreview,
)

router = APIRouter(tags=["registration"])


@router.post("/tournaments/{tournament_id}/teams", status_code=status.HTTP_201_CREATED)
def create_team(
    session: SessionDep,
    account: VerifiedAccount,
    tournament_id: uuid.UUID,
    body: TeamCreate,
) -> TeamDetail:
    """S16 建立隊伍：建立者成為隊長，報名狀態為「組隊中」，並產生邀請連結。"""
    team = service.create_team(
        session, tournament_id=tournament_id, account_id=account.id, name=body.name
    )
    session.commit()
    return team


@router.get("/teams/{team_id}")
def read_team(
    session: SessionDep, account: CurrentAccount, team_id: uuid.UUID
) -> TeamDetail:
    """S17 隊伍頁；只有隊員能看，其他帳號回 403 `TEAM_MEMBER_REQUIRED`。"""
    return service.get_team_detail(session, team_id=team_id, account_id=account.id)


@router.get("/team-invites/{token}")
def preview_team_invite(session: SessionDep, token: str) -> TeamInvitePreview:
    """S19 邀請連結的公開預覽（不需登入）：賽事、遊戲、隊名與是否已滿。"""
    return service.preview_invite(session, token=token)


@router.post("/team-invites/{token}/members")
def join_team(session: SessionDep, account: VerifiedAccount, token: str) -> TeamDetail:
    """S19 以邀請連結加入隊伍，成為選手。"""
    team = service.join_team(session, token=token, account_id=account.id)
    session.commit()
    return team


@router.get("/accounts/me/teams")
def list_my_teams(session: SessionDep, account: CurrentAccount) -> list[MyTeamCard]:
    """S12 我的隊伍：目前帳號加入的每支隊伍與報名狀態。"""
    return service.list_my_teams(session, account_id=account.id)
