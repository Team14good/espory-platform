"""Story 3.1：建立隊伍與邀請隊員（I/O 矩陣、唯一鍵防線、報名狀態轉換、公開函式）。

tournaments 的 `get_tournament`、`lock_tournament`、`ensure_accepting_registrations`
由 Story 2.2 提供，合併前以 monkeypatch 替身代替（見 deferred-work）。
"""

import itertools
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.errors import BusinessError
from app.core.security import create_access_token, get_password_hash
from app.modules.identity.models import Account
from app.modules.registration import repository, service
from app.modules.registration.models import (
    MemberRole,
    Registration,
    RegistrationStatus,
    TeamMember,
)
from app.modules.tournaments import service as tournaments_service
from tests.conftest import FrozenClock

API = settings.API_V1_STR


# ---------------------------------------------------------------- 替身與測試資料


@dataclass
class FakeTournament:
    """`TournamentRead` 中 registration 用到的欄位。"""

    organizer_id: uuid.UUID
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = "政大校園盃"
    game_name: str = "特戰英豪"
    starters: int = 5
    substitutes: int = 1
    status: str = "open"


class FakeTournaments:
    """tournaments.service 的替身：記錄 lock_tournament 的呼叫。"""

    def __init__(self) -> None:
        self.items: dict[uuid.UUID, FakeTournament] = {}
        self.locked: list[uuid.UUID] = []
        # 呼叫順序（測試「先鎖再檢查」時由其他替身一起寫入）
        self.events: list[str] = []
        # lock_tournament 回傳的值與 get_tournament 不同時使用（鎖住後讀到的最新值）
        self.locked_values: dict[uuid.UUID, FakeTournament] = {}

    def add(self, **kwargs: Any) -> FakeTournament:
        kwargs.setdefault("organizer_id", uuid.uuid4())
        tournament = FakeTournament(**kwargs)
        self.items[tournament.id] = tournament
        return tournament

    def get_tournament(
        self, _session: Session, *, tournament_id: uuid.UUID
    ) -> FakeTournament:
        if tournament_id not in self.items:
            raise BusinessError(
                "TOURNAMENT_NOT_FOUND", "找不到這個賽事。", status_code=404
            )
        return self.items[tournament_id]

    def lock_tournament(
        self, session: Session, *, tournament_id: uuid.UUID
    ) -> FakeTournament:
        self.locked.append(tournament_id)
        self.events.append("lock")
        if tournament_id in self.locked_values:
            return self.locked_values[tournament_id]
        return self.get_tournament(session, tournament_id=tournament_id)

    def ensure_accepting_registrations(self, tournament: FakeTournament) -> None:
        if tournament.status != "open":
            raise BusinessError(
                "REGISTRATION_CLOSED", "目前不在報名期間。", status_code=409
            )


@pytest.fixture
def tournaments(monkeypatch: pytest.MonkeyPatch) -> FakeTournaments:
    fake = FakeTournaments()
    for name in (
        "get_tournament",
        "lock_tournament",
        "ensure_accepting_registrations",
    ):
        monkeypatch.setattr(
            tournaments_service, name, getattr(fake, name), raising=False
        )
    return fake


def _make_account(
    session: Session, *, verified: bool = True, display_name: str = "小安"
) -> Account:
    account = Account(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=get_password_hash("eight-ch"),
        email_verified=verified,
        display_name=display_name,
    )
    session.add(account)
    session.flush()
    return account


def _auth(account: Account) -> dict[str, str]:
    token = create_access_token(
        account.id, timedelta(hours=1), version=account.credentials_version
    )
    return {"Authorization": f"Bearer {token}"}


def _create(
    client: TestClient, account: Account, tournament_id: uuid.UUID, name: str = "夜貓隊"
) -> Any:
    return client.post(
        f"{API}/tournaments/{tournament_id}/teams",
        json={"name": name},
        headers=_auth(account),
    )


def _create_ok(
    client: TestClient, account: Account, tournament_id: uuid.UUID, name: str = "夜貓隊"
) -> dict[str, Any]:
    response = _create(client, account, tournament_id, name)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _join(client: TestClient, account: Account, token: str) -> Any:
    return client.post(f"{API}/team-invites/{token}/members", headers=_auth(account))


def _error_code(response: Any) -> str:
    return str(response.json()["detail"]["code"])


def _audit(session: Session, action: str) -> list[AuditLog]:
    return list(session.exec(select(AuditLog).where(AuditLog.action == action)))


# ---------------------------------------------------------------- 建立隊伍


def test_create_team_makes_captain_forming_registration_and_invite_token(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()
    captain = _make_account(session, display_name="阿哲")

    body = _create_ok(client, captain, tournament.id, "  夜貓隊  ")

    assert body["name"] == "夜貓隊"
    assert body["tournament_id"] == str(tournament.id)
    assert body["tournament_name"] == "政大校園盃"
    assert body["game_name"] == "特戰英豪"
    assert (body["starters"], body["substitutes"], body["max_members"]) == (5, 1, 6)
    assert body["registration_status"] == "forming"
    assert body["my_role"] == "captain"
    assert body["invite_status"] == "active"
    assert len(body["invite_token"]) >= 32
    assert [(m["display_name"], m["role"]) for m in body["members"]] == [
        ("阿哲", "captain")
    ]
    assert tournaments.locked == [tournament.id]

    team_id = uuid.UUID(body["id"])
    registration = repository.get_registration_by_team(session, team_id)
    assert registration is not None
    assert registration.status == RegistrationStatus.FORMING
    assert registration.tournament_id == tournament.id

    [log] = _audit(session, "team.created")
    assert log.actor_id == captain.id
    assert log.tournament_id == tournament.id
    assert log.entity_type == "team"
    assert log.entity_id == team_id
    assert log.after == {"name": "夜貓隊", "captain_id": str(captain.id)}


@pytest.mark.parametrize("name", ["", "   ", "隊" * 31, 123])
def test_create_team_rejects_invalid_names(
    client: TestClient, session: Session, tournaments: FakeTournaments, name: Any
) -> None:
    tournament = tournaments.add()
    captain = _make_account(session)

    response = client.post(
        f"{API}/tournaments/{tournament.id}/teams",
        json={"name": name},
        headers=_auth(captain),
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "name"]


def test_create_team_accepts_30_character_name(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()

    body = _create_ok(client, _make_account(session), tournament.id, " " + "隊" * 30)

    assert body["name"] == "隊" * 30


def test_team_name_is_unique_per_tournament_ignoring_case(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()
    other = tournaments.add()
    _create_ok(client, _make_account(session), tournament.id, "Night Owls")

    response = _create(client, _make_account(session), tournament.id, "night owls")

    assert response.status_code == 409
    assert _error_code(response) == "TEAM_NAME_TAKEN"
    # 不同賽事可以同名
    _create_ok(client, _make_account(session), other.id, "night owls")


def test_team_name_unique_index_is_the_last_line_of_defense(
    client: TestClient,
    session: Session,
    tournaments: FakeTournaments,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournaments.add()
    _create_ok(client, _make_account(session), tournament.id, "Night Owls")
    # 模擬兩個請求同時通過檢查：查詢看不到對方，只剩唯一索引擋下
    monkeypatch.setattr(repository, "get_team_by_name", lambda *_args: None)

    response = _create(client, _make_account(session), tournament.id, "NIGHT OWLS")

    assert response.status_code == 409
    assert _error_code(response) == "TEAM_NAME_TAKEN"


def test_create_team_requires_verified_email(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()

    response = _create(client, _make_account(session, verified=False), tournament.id)

    assert response.status_code == 403
    assert _error_code(response) == "EMAIL_NOT_VERIFIED"


def test_organizer_cannot_create_team(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    organizer = _make_account(session)
    tournament = tournaments.add(organizer_id=organizer.id)

    response = _create(client, organizer, tournament.id)

    assert response.status_code == 403
    assert _error_code(response) == "ORGANIZER_CANNOT_JOIN"


@pytest.mark.parametrize("status", ["upcoming", "closed", "published"])
def test_create_team_rejected_when_tournament_not_open(
    client: TestClient, session: Session, tournaments: FakeTournaments, status: str
) -> None:
    tournament = tournaments.add(status=status)

    response = _create(client, _make_account(session), tournament.id)

    assert response.status_code == 409
    assert _error_code(response) == "REGISTRATION_CLOSED"
    assert tournaments.locked == [tournament.id]


def test_create_team_for_unknown_tournament_is_404(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    del tournaments  # 沒有任何賽事

    response = _create(client, _make_account(session), uuid.uuid4())

    assert response.status_code == 404
    assert _error_code(response) == "TOURNAMENT_NOT_FOUND"


def test_cannot_create_second_team_in_same_tournament(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()
    captain = _make_account(session)
    _create_ok(client, captain, tournament.id, "A 隊")

    response = _create(client, captain, tournament.id, "B 隊")

    assert response.status_code == 409
    assert _error_code(response) == "ALREADY_IN_TOURNAMENT"
    # 其他賽事可以
    _create_ok(client, captain, tournaments.add().id, "B 隊")


# ---------------------------------------------------------------- 邀請預覽與加入


def test_preview_invite_is_public_and_has_no_member_details(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()
    team = _create_ok(client, _make_account(session), tournament.id)

    response = client.get(f"{API}/team-invites/{team['invite_token']}")

    assert response.status_code == 200
    assert response.json() == {
        "team_id": team["id"],
        "team_name": "夜貓隊",
        "tournament_id": str(tournament.id),
        "tournament_name": "政大校園盃",
        "game_name": "特戰英豪",
        "member_count": 1,
        "max_members": 6,
        "invite_status": "active",
    }


def test_unknown_invite_token_is_404(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    del tournaments

    preview = client.get(f"{API}/team-invites/no-such-token")
    join = _join(client, _make_account(session), "no-such-token")

    for response in (preview, join):
        assert response.status_code == 404
        assert _error_code(response) == "TEAM_INVITE_NOT_FOUND"


def test_join_team_as_player(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()
    team = _create_ok(
        client, _make_account(session, display_name="阿哲"), tournament.id
    )
    player = _make_account(session, display_name="小芸")
    tournaments.locked.clear()

    response = _join(client, player, team["invite_token"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == team["id"]
    assert body["my_role"] == "player"
    assert [(m["display_name"], m["role"]) for m in body["members"]] == [
        ("阿哲", "captain"),
        ("小芸", "player"),
    ]
    assert tournaments.locked == [tournament.id]
    [log] = _audit(session, "team.member_joined")
    assert log.actor_id == player.id
    assert log.tournament_id == tournament.id
    assert log.entity_id == uuid.UUID(team["id"])
    assert log.after == {"account_id": str(player.id), "role": "player"}


def test_join_requires_verified_email(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    team = _create_ok(client, _make_account(session), tournaments.add().id)

    response = _join(
        client, _make_account(session, verified=False), team["invite_token"]
    )

    assert response.status_code == 403
    assert _error_code(response) == "EMAIL_NOT_VERIFIED"


def test_organizer_cannot_join(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    organizer = _make_account(session)
    team = _create_ok(
        client, _make_account(session), tournaments.add(organizer_id=organizer.id).id
    )

    response = _join(client, organizer, team["invite_token"])

    assert response.status_code == 403
    assert _error_code(response) == "ORGANIZER_CANNOT_JOIN"


def test_join_rejected_when_tournament_not_open(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()
    team = _create_ok(client, _make_account(session), tournament.id)
    tournament.status = "closed"

    response = _join(client, _make_account(session), team["invite_token"])

    assert response.status_code == 409
    assert _error_code(response) == "REGISTRATION_CLOSED"


def test_cannot_join_when_already_in_tournament(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()
    team_a = _create_ok(client, _make_account(session), tournament.id, "A 隊")
    other_captain = _make_account(session)
    _create_ok(client, other_captain, tournament.id, "B 隊")

    # 已是另一隊的隊長
    response = _join(client, other_captain, team_a["invite_token"])
    assert response.status_code == 409
    assert _error_code(response) == "ALREADY_IN_TOURNAMENT"

    # 已在同一隊
    player = _make_account(session)
    assert _join(client, player, team_a["invite_token"]).status_code == 200
    again = _join(client, player, team_a["invite_token"])
    assert again.status_code == 409
    assert _error_code(again) == "ALREADY_IN_TOURNAMENT"


def test_team_full_invalidates_invite(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add(starters=1, substitutes=1)
    team = _create_ok(client, _make_account(session), tournament.id)
    token = team["invite_token"]
    assert _join(client, _make_account(session), token).status_code == 200

    preview = client.get(f"{API}/team-invites/{token}").json()
    detail = client.get(f"{API}/teams/{team['id']}", headers=_auth_of(session, team))
    response = _join(client, _make_account(session), token)

    assert (preview["member_count"], preview["max_members"]) == (2, 2)
    assert preview["invite_status"] == "full"
    assert detail.json()["invite_status"] == "full"
    assert response.status_code == 409
    assert _error_code(response) == "TEAM_FULL"


def _auth_of(session: Session, team: dict[str, Any]) -> dict[str, str]:
    """隊伍隊長的 Authorization 標頭。"""
    captain_id = next(
        m["account_id"] for m in team["members"] if m["role"] == "captain"
    )
    account = session.get(Account, uuid.UUID(captain_id))
    assert account is not None
    return _auth(account)


def test_create_team_converts_member_unique_key_conflict_to_409(
    client: TestClient,
    session: Session,
    tournaments: FakeTournaments,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournaments.add()
    captain = _make_account(session)
    _create_ok(client, captain, tournament.id, "A 隊")
    monkeypatch.setattr(repository, "get_membership", lambda *_args: None)

    response = _create(client, captain, tournament.id, "B 隊")

    assert response.status_code == 409
    assert _error_code(response) == "ALREADY_IN_TOURNAMENT"
    # 整個請求回滾：B 隊沒有被建立
    assert repository.get_team_by_name(session, tournament.id, "B 隊") is None


def test_member_unique_key_is_the_last_line_of_defense(
    client: TestClient,
    session: Session,
    tournaments: FakeTournaments,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournaments.add()
    team_a = _create_ok(client, _make_account(session), tournament.id, "A 隊")
    team_b = _create_ok(client, _make_account(session), tournament.id, "B 隊")
    player = _make_account(session)
    assert _join(client, player, team_a["invite_token"]).status_code == 200

    # 直接新增重複的（tournament_id, account_id）：資料庫拒絕
    with pytest.raises(repository.DuplicateMemberError):
        repository.add_member(
            session,
            TeamMember(
                team_id=uuid.UUID(team_b["id"]),
                tournament_id=tournament.id,
                account_id=player.id,
                role=MemberRole.PLAYER,
            ),
        )

    # 模擬兩個請求同時通過檢查：service 把唯一鍵衝突轉成 409
    monkeypatch.setattr(repository, "get_membership", lambda *_args: None)
    response = _join(client, player, team_b["invite_token"])

    assert response.status_code == 409
    assert _error_code(response) == "ALREADY_IN_TOURNAMENT"
    assert (
        service.is_member(
            session, team_id=uuid.UUID(team_b["id"]), account_id=player.id
        )
        is False
    )


# ---------------------------------------------------------------- 隊伍頁與我的隊伍


def test_team_page_is_members_only(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    captain = _make_account(session)
    team = _create_ok(client, captain, tournaments.add().id)
    player = _make_account(session)
    _join(client, player, team["invite_token"])
    url = f"{API}/teams/{team['id']}"

    as_captain = client.get(url, headers=_auth(captain))
    as_player = client.get(url, headers=_auth(player))
    as_stranger = client.get(url, headers=_auth(_make_account(session)))
    anonymous = client.get(url)

    assert as_captain.status_code == 200
    assert as_captain.json()["my_role"] == "captain"
    assert as_player.status_code == 200
    assert as_player.json()["my_role"] == "player"
    assert as_player.json()["invite_token"] == team["invite_token"]
    assert as_stranger.status_code == 403
    assert _error_code(as_stranger) == "TEAM_MEMBER_REQUIRED"
    assert anonymous.status_code == 401


def test_unknown_team_is_404(client: TestClient, session: Session) -> None:
    response = client.get(
        f"{API}/teams/{uuid.uuid4()}", headers=_auth(_make_account(session))
    )

    assert response.status_code == 404
    assert _error_code(response) == "TEAM_NOT_FOUND"


def test_my_teams_lists_every_team_with_status(
    client: TestClient,
    session: Session,
    tournaments: FakeTournaments,
    frozen_clock: FrozenClock,
) -> None:
    account = _make_account(session)
    url = f"{API}/accounts/me/teams"
    assert client.get(url, headers=_auth(account)).json() == []

    first = tournaments.add(name="政大校園盃", game_name="特戰英豪")
    second = tournaments.add(name="清大盃", game_name="英雄聯盟")
    team_a = _create_ok(client, account, first.id, "A 隊")
    team_b = _create_ok(client, _make_account(session), second.id, "B 隊")
    frozen_clock.advance(timedelta(minutes=1))
    _join(client, account, team_b["invite_token"])

    response = client.get(url, headers=_auth(account))

    assert response.status_code == 200
    # 新加入的在前
    assert response.json() == [
        {
            "team_id": team_b["id"],
            "team_name": "B 隊",
            "tournament_id": str(second.id),
            "tournament_name": "清大盃",
            "game_name": "英雄聯盟",
            "registration_status": "forming",
        },
        {
            "team_id": team_a["id"],
            "team_name": "A 隊",
            "tournament_id": str(first.id),
            "tournament_name": "政大校園盃",
            "game_name": "特戰英豪",
            "registration_status": "forming",
        },
    ]
    assert client.get(url).status_code == 401


# ---------------------------------------------------------------- 報名狀態轉換

S = RegistrationStatus
ALLOWED = {
    (S.FORMING, S.PENDING),
    (S.FORMING, S.ACCEPTED),
    (S.FORMING, S.WAITLISTED),
    (S.FORMING, S.WITHDRAWN),
    (S.PENDING, S.ACCEPTED),
    (S.PENDING, S.WAITLISTED),
    (S.PENDING, S.REJECTED),
    (S.PENDING, S.WITHDRAWN),
    (S.PENDING, S.DISQUALIFIED),
    (S.ACCEPTED, S.REJECTED),
    (S.ACCEPTED, S.WITHDRAWN),
    (S.ACCEPTED, S.DRAWN),
    (S.ACCEPTED, S.DISQUALIFIED),
    (S.WAITLISTED, S.ACCEPTED),
    (S.WAITLISTED, S.DRAWN),
    (S.WAITLISTED, S.REJECTED),
    (S.WAITLISTED, S.WITHDRAWN),
    (S.WAITLISTED, S.DISQUALIFIED),
    (S.REJECTED, S.FORMING),
    (S.DRAWN, S.RETIRED),
    (S.DRAWN, S.DISQUALIFIED),
}


def _registration(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> Registration:
    team = _create_ok(client, _make_account(session), tournaments.add().id)
    registration = repository.get_registration_by_team(session, uuid.UUID(team["id"]))
    assert registration is not None
    return registration


@pytest.mark.parametrize(("frm", "to"), list(itertools.product(S, S)))
def test_mark_status_follows_the_state_diagram(
    client: TestClient,
    session: Session,
    tournaments: FakeTournaments,
    frm: RegistrationStatus,
    to: RegistrationStatus,
) -> None:
    registration = _registration(client, session, tournaments)
    registration.status = frm  # 直接設定起始狀態（測試用）
    session.add(registration)
    session.flush()
    actor = _make_account(session)

    if (frm, to) in ALLOWED:
        service.mark_status(
            session, registration=registration, to=to, actor_id=actor.id
        )
        session.refresh(registration)
        assert registration.status == to
        [log] = _audit(session, "registration.status_changed")
        assert log.actor_id == actor.id
        assert log.tournament_id == registration.tournament_id
        assert log.entity_id == registration.id
        assert (log.before, log.after) == ({"status": frm}, {"status": to})
    else:
        with pytest.raises(BusinessError) as exc_info:
            service.mark_status(
                session, registration=registration, to=to, actor_id=actor.id
            )
        assert exc_info.value.code == "REGISTRATION_INVALID_TRANSITION"
        assert exc_info.value.status_code == 409
        assert _audit(session, "registration.status_changed") == []


def test_mark_status_by_system_records_no_actor(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    registration = _registration(client, session, tournaments)

    service.mark_status(session, registration=registration, to=S.PENDING, actor_id=None)

    [log] = _audit(session, "registration.status_changed")
    assert log.actor_id is None
    assert (log.before, log.after) == ({"status": "forming"}, {"status": "pending"})


# ---------------------------------------------------------------- 先鎖再檢查


def _record_checks(
    monkeypatch: pytest.MonkeyPatch, tournaments: FakeTournaments
) -> None:
    """包住 repository 的檢查查詢，把呼叫順序與 lock 寫進同一個清單。"""
    for name in ("get_membership", "count_members"):
        original = getattr(repository, name)

        def wrapped(*args: Any, _name: str = name, _original: Any = original) -> Any:
            tournaments.events.append(_name)
            return _original(*args)

        monkeypatch.setattr(repository, name, wrapped)


def test_create_and_join_lock_the_tournament_before_checking(
    client: TestClient,
    session: Session,
    tournaments: FakeTournaments,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tournament = tournaments.add()
    _record_checks(monkeypatch, tournaments)

    team = _create_ok(client, _make_account(session), tournament.id)
    create_events = list(tournaments.events)
    tournaments.events.clear()
    assert (
        _join(client, _make_account(session), team["invite_token"]).status_code == 200
    )
    join_events = list(tournaments.events)

    assert create_events[:2] == ["lock", "get_membership"]
    assert join_events[:3] == ["lock", "get_membership", "count_members"]


def test_join_uses_the_value_returned_by_lock_tournament(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add(starters=1, substitutes=1)
    team = _create_ok(client, _make_account(session), tournament.id)
    # 鎖住後讀到的最新值：替補已改成 0，隊伍（1 人）已滿
    tournaments.locked_values[tournament.id] = FakeTournament(
        organizer_id=tournament.organizer_id,
        id=tournament.id,
        starters=1,
        substitutes=0,
    )

    response = _join(client, _make_account(session), team["invite_token"])

    assert response.status_code == 409
    assert _error_code(response) == "TEAM_FULL"


# ---------------------------------------------------------------- 公開函式


def test_public_functions(
    client: TestClient, session: Session, tournaments: FakeTournaments
) -> None:
    tournament = tournaments.add()
    captain = _make_account(session)
    team = _create_ok(client, captain, tournament.id)
    player = _make_account(session)
    _join(client, player, team["invite_token"])
    stranger = _make_account(session)
    team_id = uuid.UUID(team["id"])

    read = service.get_team(session, team_id=team_id)
    assert (read.id, read.tournament_id, read.name) == (
        team_id,
        tournament.id,
        "夜貓隊",
    )
    assert [(m.account_id, m.role) for m in read.members] == [
        (captain.id, MemberRole.CAPTAIN),
        (player.id, MemberRole.PLAYER),
    ]

    registration = service.get_registration(session, team_id=team_id)
    assert registration.team_id == team_id
    assert registration.tournament_id == tournament.id
    assert registration.status == RegistrationStatus.FORMING

    assert service.is_member(session, team_id=team_id, account_id=captain.id)
    assert service.is_member(session, team_id=team_id, account_id=player.id)
    assert not service.is_member(session, team_id=team_id, account_id=stranger.id)
    assert service.is_captain(session, team_id=team_id, account_id=captain.id)
    assert not service.is_captain(session, team_id=team_id, account_id=player.id)
    assert not service.is_captain(session, team_id=team_id, account_id=stranger.id)


def test_public_functions_raise_for_unknown_team(session: Session) -> None:
    with pytest.raises(BusinessError) as team_error:
        service.get_team(session, team_id=uuid.uuid4())
    with pytest.raises(BusinessError) as registration_error:
        service.get_registration(session, team_id=uuid.uuid4())

    assert (team_error.value.code, team_error.value.status_code) == (
        "TEAM_NOT_FOUND",
        404,
    )
    assert (registration_error.value.code, registration_error.value.status_code) == (
        "REGISTRATION_NOT_FOUND",
        404,
    )
