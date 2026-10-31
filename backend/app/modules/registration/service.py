"""registration 的業務規則、資源層級權限、狀態轉換、操作紀錄與事件；不得 commit 或 rollback。

tournaments 的 `get_tournament`、`lock_tournament`、`ensure_accepting_registrations`
由 Story 2.2 提供（contracts/tournaments.md）。2.2 合併前照約定呼叫、測試以替身代替；
呼叫處的 `type: ignore[attr-defined]`（mypy）、`ty: ignore[unresolved-attribute]`（ty）
與本地的 `_Tournament` Protocol 在 2.2 合併後移除
（見 deferred-work）。
"""

import secrets
import uuid
from typing import Protocol

from sqlmodel import Session

from app.core import audit, clock
from app.core.errors import BusinessError
from app.modules.identity import service as identity_service
from app.modules.registration import repository
from app.modules.registration.models import (
    InviteStatus,
    MemberRole,
    MyTeamCard,
    Registration,
    RegistrationRead,
    RegistrationStatus,
    Team,
    TeamDetail,
    TeamInvitePreview,
    TeamMember,
    TeamMemberRead,
    TeamMemberRole,
    TeamRead,
)
from app.modules.tournaments import service as tournaments_service

INVITE_TOKEN_BYTES = 24


class _Tournament(Protocol):
    """本模組需要的 `TournamentRead` 欄位（contracts/tournaments.md）。"""

    @property
    def id(self) -> uuid.UUID: ...
    @property
    def organizer_id(self) -> uuid.UUID: ...
    @property
    def name(self) -> str: ...
    @property
    def game_name(self) -> str: ...
    @property
    def starters(self) -> int: ...
    @property
    def substitutes(self) -> int: ...


# ---------------------------------------------------------------- tournaments 介面


def _get_tournament(session: Session, tournament_id: uuid.UUID) -> _Tournament:
    tournament: _Tournament = tournaments_service.get_tournament(  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        session, tournament_id=tournament_id
    )
    return tournament


def _lock_tournament(session: Session, tournament_id: uuid.UUID) -> _Tournament:
    """鎖住賽事列（AD-6）：建隊、加入等改變名單的操作都先鎖，再檢查身分與人數。"""
    tournament: _Tournament = tournaments_service.lock_tournament(  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        session, tournament_id=tournament_id
    )
    return tournament


def _ensure_accepting_registrations(tournament: _Tournament) -> None:
    """賽事不是開放報名時，由 tournaments 拋 409 `REGISTRATION_CLOSED`。"""
    tournaments_service.ensure_accepting_registrations(tournament)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]


# ---------------------------------------------------------------- 錯誤


def _team_not_found() -> BusinessError:
    return BusinessError("TEAM_NOT_FOUND", "找不到這支隊伍。", status_code=404)


def _invite_not_found() -> BusinessError:
    return BusinessError("TEAM_INVITE_NOT_FOUND", "這個邀請連結無效。", status_code=404)


def _already_in_tournament() -> BusinessError:
    return BusinessError(
        "ALREADY_IN_TOURNAMENT",
        "你已經在這個賽事的隊伍中，同一個賽事只能加入一支隊伍。",
        status_code=409,
    )


def _organizer_cannot_join() -> BusinessError:
    return BusinessError(
        "ORGANIZER_CANNOT_JOIN",
        "主辦方不能在自己的賽事建立或加入隊伍。",
        status_code=403,
    )


def _team_full() -> BusinessError:
    return BusinessError("TEAM_FULL", "隊伍已滿，無法再加入。", status_code=409)


def _team_name_taken() -> BusinessError:
    return BusinessError(
        "TEAM_NAME_TAKEN", "這個賽事已經有同名的隊伍。", status_code=409
    )


def _team_member_required() -> BusinessError:
    return BusinessError(
        "TEAM_MEMBER_REQUIRED", "只有隊員可以查看這支隊伍。", status_code=403
    )


def _registration_not_found() -> BusinessError:
    return BusinessError(
        "REGISTRATION_NOT_FOUND", "找不到這支隊伍的報名。", status_code=404
    )


# ---------------------------------------------------------------- 報名狀態

# 期中文件 B 參、四（二）的報名狀態圖
_TRANSITIONS: dict[RegistrationStatus, frozenset[RegistrationStatus]] = {
    RegistrationStatus.FORMING: frozenset(
        {
            RegistrationStatus.PENDING,
            RegistrationStatus.ACCEPTED,
            RegistrationStatus.WAITLISTED,
            RegistrationStatus.WITHDRAWN,
        }
    ),
    RegistrationStatus.PENDING: frozenset(
        {
            RegistrationStatus.ACCEPTED,
            RegistrationStatus.WAITLISTED,
            RegistrationStatus.REJECTED,
            RegistrationStatus.WITHDRAWN,
            RegistrationStatus.DISQUALIFIED,
        }
    ),
    RegistrationStatus.ACCEPTED: frozenset(
        {
            RegistrationStatus.REJECTED,
            RegistrationStatus.WITHDRAWN,
            RegistrationStatus.DRAWN,
            RegistrationStatus.DISQUALIFIED,
        }
    ),
    RegistrationStatus.WAITLISTED: frozenset(
        {
            RegistrationStatus.ACCEPTED,
            RegistrationStatus.DRAWN,
            RegistrationStatus.REJECTED,
            RegistrationStatus.WITHDRAWN,
            RegistrationStatus.DISQUALIFIED,
        }
    ),
    RegistrationStatus.REJECTED: frozenset({RegistrationStatus.FORMING}),
    RegistrationStatus.WITHDRAWN: frozenset(),
    RegistrationStatus.DRAWN: frozenset(
        {RegistrationStatus.RETIRED, RegistrationStatus.DISQUALIFIED}
    ),
    RegistrationStatus.RETIRED: frozenset(),
    RegistrationStatus.DISQUALIFIED: frozenset(),
}


def can_transition(frm: RegistrationStatus, to: RegistrationStatus) -> bool:
    return to in _TRANSITIONS[frm]


def mark_status(
    session: Session,
    *,
    registration: Registration,
    to: RegistrationStatus,
    actor_id: uuid.UUID | None,
) -> None:
    """唯一修改報名狀態的入口；非法轉換拋 409 `REGISTRATION_INVALID_TRANSITION`。

    寫操作紀錄 `registration.status_changed`；`actor_id=None` 表示系統（worker）。
    呼叫前要先 `lock_tournament`（會改變名額的操作）。
    """
    current = registration.status
    if not can_transition(current, to):
        raise BusinessError(
            "REGISTRATION_INVALID_TRANSITION",
            "報名目前的狀態不能進行這個操作。",
            status_code=409,
        )
    registration.status = to
    session.add(registration)
    audit.record(
        session,
        actor_id=actor_id,
        tournament_id=registration.tournament_id,
        action="registration.status_changed",
        entity_type="registration",
        entity_id=registration.id,
        before={"status": current},
        after={"status": to},
    )
    session.flush()


# ---------------------------------------------------------------- 內部共用


def _max_members(tournament: _Tournament) -> int:
    return tournament.starters + tournament.substitutes


def _invite_status(member_count: int, max_members: int) -> InviteStatus:
    return "full" if member_count >= max_members else "active"


def _registration_of(session: Session, team: Team) -> Registration:
    registration = repository.get_registration_by_team(session, team.id)
    assert registration is not None  # 建立隊伍時同時建立
    return registration


def _ensure_can_join(
    session: Session, tournament: _Tournament, account_id: uuid.UUID
) -> None:
    """鎖住賽事後檢查：開放報名、不是主辦方、不在該賽事的任何隊伍。"""
    _ensure_accepting_registrations(tournament)
    if tournament.organizer_id == account_id:
        raise _organizer_cannot_join()
    if repository.get_membership(session, tournament.id, account_id) is not None:
        raise _already_in_tournament()


def _build_detail(
    session: Session, team: Team, tournament: _Tournament, viewer: TeamMember
) -> TeamDetail:
    members = repository.list_members(session, team.id)
    member_reads: list[TeamMemberRead] = []
    for member in members:
        contact = identity_service.get_account_contact(session, member.account_id)
        assert contact is not None  # 外鍵保證帳號存在
        member_reads.append(
            TeamMemberRead(
                account_id=member.account_id,
                display_name=contact.display_name,
                role=member.role,
                joined_at=member.created_at,
            )
        )
    max_members = _max_members(tournament)
    return TeamDetail(
        id=team.id,
        name=team.name,
        tournament_id=team.tournament_id,
        tournament_name=tournament.name,
        game_name=tournament.game_name,
        starters=tournament.starters,
        substitutes=tournament.substitutes,
        max_members=max_members,
        members=member_reads,
        registration_status=_registration_of(session, team).status,
        invite_token=team.invite_token,
        invite_status=_invite_status(len(members), max_members),
        my_role=viewer.role,
    )


# ---------------------------------------------------------------- 使用案例


def create_team(
    session: Session, *, tournament_id: uuid.UUID, account_id: uuid.UUID, name: str
) -> TeamDetail:
    """S16 建立隊伍：建立者成為隊長，同時建立「組隊中」的報名與邀請 token。"""
    tournament = _lock_tournament(session, tournament_id)
    _ensure_can_join(session, tournament, account_id)
    if repository.get_team_by_name(session, tournament.id, name) is not None:
        raise _team_name_taken()

    now = clock.now()
    team = Team(
        tournament_id=tournament.id,
        name=name,
        invite_token=secrets.token_urlsafe(INVITE_TOKEN_BYTES),
        created_at=now,
    )
    try:
        repository.add_team(session, team)
    except repository.DuplicateTeamNameError:
        raise _team_name_taken()
    captain = TeamMember(
        team_id=team.id,
        tournament_id=tournament.id,
        account_id=account_id,
        role=MemberRole.CAPTAIN,
        created_at=now,
    )
    try:
        repository.add_member(session, captain)
    except repository.DuplicateMemberError:
        raise _already_in_tournament()
    repository.add_registration(
        session,
        Registration(
            team_id=team.id,
            tournament_id=tournament.id,
            status=RegistrationStatus.FORMING,
            created_at=now,
        ),
    )
    audit.record(
        session,
        actor_id=account_id,
        tournament_id=tournament.id,
        action="team.created",
        entity_type="team",
        entity_id=team.id,
        before=None,
        after={"name": team.name, "captain_id": account_id},
    )
    session.flush()
    return _build_detail(session, team, tournament, captain)


def preview_invite(session: Session, *, token: str) -> TeamInvitePreview:
    """S19 公開預覽：賽事名、遊戲、隊名與是否已滿；不需登入。"""
    team = repository.get_team_by_invite_token(session, token)
    if team is None:
        raise _invite_not_found()
    tournament = _get_tournament(session, team.tournament_id)
    member_count = repository.count_members(session, team.id)
    max_members = _max_members(tournament)
    return TeamInvitePreview(
        team_id=team.id,
        team_name=team.name,
        tournament_id=team.tournament_id,
        tournament_name=tournament.name,
        game_name=tournament.game_name,
        member_count=member_count,
        max_members=max_members,
        invite_status=_invite_status(member_count, max_members),
    )


def join_team(session: Session, *, token: str, account_id: uuid.UUID) -> TeamDetail:
    """S19 以邀請連結加入隊伍，成為選手。"""
    team = repository.get_team_by_invite_token(session, token)
    if team is None:
        raise _invite_not_found()
    tournament = _lock_tournament(session, team.tournament_id)
    _ensure_can_join(session, tournament, account_id)
    if repository.count_members(session, team.id) >= _max_members(tournament):
        raise _team_full()

    member = TeamMember(
        team_id=team.id,
        tournament_id=team.tournament_id,
        account_id=account_id,
        role=MemberRole.PLAYER,
        created_at=clock.now(),
    )
    try:
        repository.add_member(session, member)
    except repository.DuplicateMemberError:
        # 最後防線：鎖之外的併發寫入撞到（tournament_id, account_id）唯一鍵
        raise _already_in_tournament()
    audit.record(
        session,
        actor_id=account_id,
        tournament_id=team.tournament_id,
        action="team.member_joined",
        entity_type="team",
        entity_id=team.id,
        before=None,
        after={"account_id": account_id, "role": MemberRole.PLAYER},
    )
    session.flush()
    return _build_detail(session, team, tournament, member)


def get_team_detail(
    session: Session, *, team_id: uuid.UUID, account_id: uuid.UUID
) -> TeamDetail:
    """S17 隊伍頁：只有隊員能看（含邀請 token）。"""
    team = repository.get_team(session, team_id)
    if team is None:
        raise _team_not_found()
    viewer = repository.get_team_member(session, team.id, account_id)
    if viewer is None:
        raise _team_member_required()
    tournament = _get_tournament(session, team.tournament_id)
    return _build_detail(session, team, tournament, viewer)


def list_my_teams(session: Session, *, account_id: uuid.UUID) -> list[MyTeamCard]:
    """S12 我的隊伍：帳號加入的每支隊伍與其報名狀態（新加入的在前）。"""
    cards: list[MyTeamCard] = []
    for membership in repository.list_memberships_of_account(session, account_id):
        team = repository.get_team(session, membership.team_id)
        assert team is not None  # 外鍵保證隊伍存在
        tournament = _get_tournament(session, team.tournament_id)
        cards.append(
            MyTeamCard(
                team_id=team.id,
                team_name=team.name,
                tournament_id=team.tournament_id,
                tournament_name=tournament.name,
                game_name=tournament.game_name,
                registration_status=_registration_of(session, team).status,
            )
        )
    return cards


# ---------------------------------------------------------------- 公開函式（給其他模組）


def get_team(session: Session, *, team_id: uuid.UUID) -> TeamRead:
    """不存在拋 404 `TEAM_NOT_FOUND`。"""
    team = repository.get_team(session, team_id)
    if team is None:
        raise _team_not_found()
    return TeamRead(
        id=team.id,
        tournament_id=team.tournament_id,
        name=team.name,
        members=[
            TeamMemberRole(account_id=member.account_id, role=member.role)
            for member in repository.list_members(session, team.id)
        ],
    )


def get_registration(session: Session, *, team_id: uuid.UUID) -> RegistrationRead:
    """隊伍的報名（與隊伍一對一）；不存在拋 404 `REGISTRATION_NOT_FOUND`。"""
    registration = repository.get_registration_by_team(session, team_id)
    if registration is None:
        raise _registration_not_found()
    return RegistrationRead.model_validate(registration, from_attributes=True)


def is_member(session: Session, *, team_id: uuid.UUID, account_id: uuid.UUID) -> bool:
    return repository.get_team_member(session, team_id, account_id) is not None


def is_captain(session: Session, *, team_id: uuid.UUID, account_id: uuid.UUID) -> bool:
    member = repository.get_team_member(session, team_id, account_id)
    return member is not None and member.role == MemberRole.CAPTAIN
