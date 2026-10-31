"""registration 擁有的資料表的查詢與加鎖；不做業務判斷、不碰其他模組的資料表。"""

import uuid

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.modules.registration.models import Registration, Team, TeamMember

MEMBER_UNIQUE_CONSTRAINT = "uq_team_member_tournament_id_account_id"
TEAM_NAME_UNIQUE_INDEX = "ix_team_tournament_id_lower_name"


class DuplicateMemberError(Exception):
    """新增隊員時撞到（tournament_id, account_id）唯一鍵：已在同賽事的某支隊伍。"""


class DuplicateTeamNameError(Exception):
    """新增隊伍時撞到（tournament_id, lower(name)）唯一索引：同賽事已有同名隊伍。"""


def _translate(exc: IntegrityError) -> Exception | None:
    """把撞到唯一鍵的 IntegrityError 轉成具名的例外；其他違反約束的情況回傳 None。"""
    message = str(exc.orig)
    if MEMBER_UNIQUE_CONSTRAINT in message:
        return DuplicateMemberError()
    if TEAM_NAME_UNIQUE_INDEX in message:
        return DuplicateTeamNameError()
    return None


def get_team(session: Session, team_id: uuid.UUID) -> Team | None:
    return session.get(Team, team_id)


def get_team_by_invite_token(session: Session, token: str) -> Team | None:
    return session.exec(select(Team).where(Team.invite_token == token)).first()


def get_team_by_name(
    session: Session, tournament_id: uuid.UUID, name: str
) -> Team | None:
    """同賽事內不分大小寫比對隊名（走 lower(name) 唯一索引）。"""
    statement = (
        select(Team)
        .where(Team.tournament_id == tournament_id)
        .where(func.lower(Team.name) == func.lower(name))
    )
    return session.exec(statement).first()


def get_membership(
    session: Session, tournament_id: uuid.UUID, account_id: uuid.UUID
) -> TeamMember | None:
    """帳號在某賽事的隊員資料（最多一筆）。"""
    statement = (
        select(TeamMember)
        .where(TeamMember.tournament_id == tournament_id)
        .where(TeamMember.account_id == account_id)
    )
    return session.exec(statement).first()


def get_team_member(
    session: Session, team_id: uuid.UUID, account_id: uuid.UUID
) -> TeamMember | None:
    statement = (
        select(TeamMember)
        .where(TeamMember.team_id == team_id)
        .where(TeamMember.account_id == account_id)
    )
    return session.exec(statement).first()


def list_members(session: Session, team_id: uuid.UUID) -> list[TeamMember]:
    """依加入時間排列（同時間依 id），隊長是第一個加入的人。"""
    statement = (
        select(TeamMember)
        .where(TeamMember.team_id == team_id)
        .order_by(col(TeamMember.created_at), col(TeamMember.id))
    )
    return list(session.exec(statement))


def count_members(session: Session, team_id: uuid.UUID) -> int:
    statement = select(func.count()).where(TeamMember.team_id == team_id)
    return session.exec(statement).one()


def list_memberships_of_account(
    session: Session, account_id: uuid.UUID
) -> list[TeamMember]:
    """帳號加入的所有隊伍（新加入的在前）。"""
    statement = (
        select(TeamMember)
        .where(TeamMember.account_id == account_id)
        .order_by(col(TeamMember.created_at).desc(), col(TeamMember.id))
    )
    return list(session.exec(statement))


def get_registration_by_team(
    session: Session, team_id: uuid.UUID
) -> Registration | None:
    return session.exec(
        select(Registration).where(Registration.team_id == team_id)
    ).first()


def add_team(session: Session, team: Team) -> Team:
    """新增隊伍；同賽事已有同名隊伍時拋 DuplicateTeamNameError，外層交易不受影響。"""
    try:
        with session.begin_nested():
            session.add(team)
    except IntegrityError as exc:
        translated = _translate(exc)
        if translated is None:
            raise
        raise translated from exc
    return team


def add_member(session: Session, member: TeamMember) -> TeamMember:
    """新增隊員；已在同賽事時拋 DuplicateMemberError，外層交易不受影響。"""
    try:
        with session.begin_nested():
            session.add(member)
    except IntegrityError as exc:
        translated = _translate(exc)
        if translated is None:
            raise
        raise translated from exc
    return member


def add_registration(session: Session, registration: Registration) -> Registration:
    session.add(registration)
    session.flush()
    return registration
