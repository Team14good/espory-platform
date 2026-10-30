"""Story 2.2：主辦方建立賽事（I/O 矩陣的建立、驗證與權限各列）。"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core import audit
from app.core.audit import AuditLog
from app.core.errors import BusinessError
from app.modules.tournaments import service
from app.modules.tournaments.models import TournamentRead
from tests.conftest import FrozenClock
from tests.helpers import (
    API,
    admin_headers,
    bearer,
    make_account,
    make_game,
    make_tournament,
    member_headers,
    organizer_headers,
    token_for,
    tournament_body,
)

TOURNAMENTS_URL = f"{API}/organizer/tournaments"

# contracts/tournaments.md〈一〉的 TournamentRead 欄位
CONTRACT_FIELDS = {
    "id",
    "organizer_id",
    "name",
    "status",
    "mode",
    "capacity",
    "registration_start",
    "priority_end",
    "registration_end",
    "start_at",
    "round_interval_minutes",
    "forfeit_minutes",
    "appeal_minutes",
    "livestream_url",
    "game_id",
    "game_name",
    "starters",
    "substitutes",
    "bo",
    "game_minutes",
    "score_type",
    "rank_tiers",
}


@pytest.fixture
def organizer(client: TestClient, session: Session) -> dict[str, str]:
    return organizer_headers(client, session)


def _create(client: TestClient, headers: dict[str, str], body: dict[str, Any]) -> Any:
    return client.post(TOURNAMENTS_URL, json=body, headers=headers)


def _single_error(response: Any) -> dict[str, Any]:
    assert response.status_code == 422, response.text
    [error] = response.json()["detail"]
    return dict(error)


def _error_locs(response: Any) -> list[list[Any]]:
    assert response.status_code == 422, response.text
    return [error["loc"] for error in response.json()["detail"]]


# ---------------------------------------------------------------- 建立


@pytest.mark.usefixtures("frozen_clock")
def test_create_with_registration_started_is_open_and_snapshots_game(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session)
    body = tournament_body(game.id, livestream_url="https://twitch.tv/flow")

    response = _create(client, organizer, body)

    assert response.status_code == 201, response.text
    tournament = response.json()
    assert set(tournament) == CONTRACT_FIELDS
    assert tournament["status"] == "open"
    assert tournament["mode"] == "campus"
    assert tournament["name"] == "期中盃"
    assert tournament["capacity"] == 16
    assert tournament["forfeit_minutes"] == 15
    assert tournament["appeal_minutes"] == 30
    assert tournament["livestream_url"] == "https://twitch.tv/flow"
    assert tournament["game_id"] == str(game.id)
    assert tournament["game_name"] == game.name
    assert tournament["starters"] == game.starters
    assert tournament["substitutes"] == game.substitutes
    assert tournament["bo"] == game.default_bo
    assert tournament["game_minutes"] == game.game_minutes
    assert tournament["score_type"] == game.score_type
    assert tournament["rank_tiers"] == [t.model_dump() for t in game.rank_tiers]

    read = TournamentRead.model_validate(tournament)
    # 預設優先期 24 小時
    assert read.priority_end == read.registration_start + timedelta(hours=24)

    [row] = audit.list_for_tournament(session, read.id)
    assert row.action == "tournament.created"
    assert row.entity_type == "tournament"
    assert row.entity_id == read.id
    assert row.actor_id == read.organizer_id
    assert row.before is None
    assert row.after is not None
    assert row.after["status"] == "open"
    assert row.after["bo"] == game.default_bo


def test_create_before_registration_start_is_upcoming(
    client: TestClient,
    session: Session,
    organizer: dict[str, str],
    frozen_clock: FrozenClock,
) -> None:
    game = make_game(session)
    now = frozen_clock.now()
    body = tournament_body(
        game.id,
        registration_start=(now + timedelta(days=1)).isoformat(),
        priority_hours=12,
    )

    response = _create(client, organizer, body)

    assert response.status_code == 201, response.text
    tournament = TournamentRead.model_validate(response.json())
    assert tournament.status == "upcoming"
    assert tournament.registration_start == now + timedelta(days=1)
    assert tournament.priority_end == now + timedelta(days=1, hours=12)


def test_registration_start_equal_to_now_is_open(
    client: TestClient,
    session: Session,
    organizer: dict[str, str],
    frozen_clock: FrozenClock,
) -> None:
    game = make_game(session)
    body = tournament_body(game.id, registration_start=frozen_clock.now().isoformat())

    response = _create(client, organizer, body)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "open"


@pytest.mark.usefixtures("frozen_clock")
def test_times_with_other_offsets_are_stored_as_utc(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    # 現在凍結在 2026-10-18 11:00 UTC = 19:00 台北時間
    game = make_game(session)
    body = tournament_body(
        game.id,
        registration_start="2026-10-18T19:00:00+08:00",  # = 現在
        registration_end="2026-10-25T19:00:00+08:00",
        start_at="2026-10-26T20:00:00+08:00",
        priority_hours=12,
    )

    response = _create(client, organizer, body)

    assert response.status_code == 201, response.text
    created = TournamentRead.model_validate(response.json())
    assert created.registration_start == datetime(2026, 10, 18, 11, tzinfo=UTC)
    assert created.registration_end == datetime(2026, 10, 25, 11, tzinfo=UTC)
    assert created.start_at == datetime(2026, 10, 26, 12, tzinfo=UTC)
    assert created.priority_end == datetime(2026, 10, 18, 23, tzinfo=UTC)
    for field in ("registration_start", "registration_end", "start_at"):
        assert response.json()[field].endswith(("Z", "+00:00"))
    # 換算後報名開始 = 現在，所以是 open
    assert created.status == "open"

    # 晚一秒（換算後在現在之後）就是 upcoming
    later = _create(
        client,
        organizer,
        {**body, "registration_start": "2026-10-18T19:00:01+08:00"},
    )
    assert later.status_code == 201, later.text
    assert later.json()["status"] == "upcoming"


@pytest.mark.usefixtures("frozen_clock")
def test_fictional_third_game_snapshot_matches_game(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    # 2.1 移來的 AC：人數、BO 與示範遊戲都不同的虛構遊戲
    game = make_game(
        session,
        starters=3,
        substitutes=0,
        default_bo=7,
        game_minutes=20,
        score_type="win_loss",
        rank_tiers=[{"name": "唯一段位", "score": 0}],
    )
    body = tournament_body(game.id, round_interval_minutes=185)

    response = _create(client, organizer, body)

    assert response.status_code == 201, response.text
    tournament = response.json()
    assert tournament["starters"] == 3
    assert tournament["substitutes"] == 0
    assert tournament["bo"] == 7
    assert tournament["game_minutes"] == 20
    assert tournament["score_type"] == "win_loss"
    assert tournament["rank_tiers"] == [{"name": "唯一段位", "score": 0}]


@pytest.mark.usefixtures("frozen_clock")
def test_changing_game_defaults_does_not_change_existing_snapshot(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    # 2.1 移來的 AC：平台管理員修改遊戲後，既有賽事的快照不變
    game = make_game(session)
    created = _create(client, organizer, tournament_body(game.id)).json()

    response = client.put(
        f"{API}/admin/games/{game.id}",
        json={
            "name": "改名後的遊戲",
            "starters": 6,
            "substitutes": 4,
            "default_bo": 1,
            "game_minutes": 15,
            "score_type": "rounds",
            "rank_tiers": [{"name": "新段位", "score": 99}],
        },
        headers=admin_headers(client, session),
    )
    assert response.status_code == 200, response.text

    after = client.get(f"{TOURNAMENTS_URL}/{created['id']}", headers=organizer)
    assert after.status_code == 200
    assert after.json() == created


@pytest.mark.usefixtures("frozen_clock")
def test_organizer_overrides_starters_and_bo(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session, starters=5, default_bo=3, game_minutes=40)
    body = tournament_body(
        game.id, starters=4, substitutes=1, bo=5, round_interval_minutes=245
    )

    response = _create(client, organizer, body)

    assert response.status_code == 201, response.text
    tournament = response.json()
    assert tournament["starters"] == 4
    assert tournament["substitutes"] == 1
    assert tournament["bo"] == 5
    stored = service.get_tournament(session, tournament_id=uuid.UUID(tournament["id"]))
    assert (stored.starters, stored.substitutes, stored.bo) == (4, 1, 5)
    # 遊戲本身不受影響
    assert service.get_game(session, game_id=game.id) == game


@pytest.mark.usefixtures("frozen_clock")
def test_mode_field_is_ignored_and_stored_as_campus(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session)

    response = _create(client, organizer, tournament_body(game.id, mode="custom"))

    assert response.status_code == 201, response.text
    assert response.json()["mode"] == "campus"


# ---------------------------------------------------------------- 驗證


@pytest.mark.usefixtures("frozen_clock")
def test_round_interval_shorter_than_minimum_shows_minimum(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session, game_minutes=40, default_bo=1)
    body = tournament_body(game.id, round_interval_minutes=80)

    error = _single_error(_create(client, organizer, body))

    assert error["loc"] == ["body", "round_interval_minutes"]
    assert error["msg"] == "每輪間隔至少 85 分鐘"


@pytest.mark.usefixtures("frozen_clock")
def test_round_interval_equal_to_minimum_is_accepted(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session, game_minutes=40, default_bo=1)
    body = tournament_body(game.id, round_interval_minutes=85)

    assert _create(client, organizer, body).status_code == 201


@pytest.mark.usefixtures("frozen_clock")
def test_round_interval_minimum_uses_overridden_bo_and_periods(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session, game_minutes=10, default_bo=1)
    # 棄權 20 + BO3 × 10 + 申訴 40 = 90
    body = tournament_body(
        game.id,
        bo=3,
        forfeit_minutes=20,
        appeal_minutes=40,
        round_interval_minutes=89,
    )

    error = _single_error(_create(client, organizer, body))

    assert error["msg"] == "每輪間隔至少 90 分鐘"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        # 報名截止晚於開賽時間
        ({"registration_end": {"days": 9}}, "registration_end"),
        # 開賽時間 ≤ 現在
        ({"start_at": {"days": 0}}, "start_at"),
        ({"start_at": {"days": -1}, "registration_end": {"days": -2}}, "start_at"),
        # 報名截止 ≤ 現在
        (
            {"registration_start": {"days": -2}, "registration_end": {"days": 0}},
            "registration_end",
        ),
        # 報名開始晚於（含等於）報名截止
        ({"registration_start": {"days": 7}}, "registration_start"),
        ({"registration_start": {"days": 7, "hours": 1}}, "registration_start"),
    ],
)
def test_date_order_errors_point_to_field(
    client: TestClient,
    session: Session,
    organizer: dict[str, str],
    frozen_clock: FrozenClock,
    overrides: dict[str, dict[str, int]],
    field: str,
) -> None:
    game = make_game(session)
    now = frozen_clock.now()
    body = tournament_body(
        game.id,
        **{
            key: (now + timedelta(**delta)).isoformat()
            for key, delta in overrides.items()
        },
    )

    error = _single_error(_create(client, organizer, body))

    assert error["loc"] == ["body", field]


def test_registration_end_equal_to_start_at_is_accepted(
    client: TestClient,
    session: Session,
    organizer: dict[str, str],
    frozen_clock: FrozenClock,
) -> None:
    game = make_game(session)
    at = (frozen_clock.now() + timedelta(days=3)).isoformat()
    body = tournament_body(game.id, registration_end=at, start_at=at)

    assert _create(client, organizer, body).status_code == 201


@pytest.mark.parametrize("priority_hours", [7 * 24 + 2, 2_147_483_647])
@pytest.mark.usefixtures("frozen_clock")
def test_priority_end_after_registration_end_is_rejected(
    client: TestClient,
    session: Session,
    organizer: dict[str, str],
    priority_hours: int,
) -> None:
    # 報名開始為 1 小時前、截止為 7 天後：優先期最多 7 天 1 小時
    game = make_game(session)
    body = tournament_body(game.id, priority_hours=priority_hours)

    error = _single_error(_create(client, organizer, body))

    assert error["loc"] == ["body", "priority_hours"]


@pytest.mark.usefixtures("frozen_clock")
def test_priority_end_equal_to_registration_end_is_accepted(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session)
    body = tournament_body(game.id, priority_hours=7 * 24 + 1)

    response = _create(client, organizer, body)

    assert response.status_code == 201, response.text
    assert response.json()["priority_end"] == response.json()["registration_end"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capacity", 1),
        ("capacity", 2_147_483_648),
        ("capacity", True),
        ("forfeit_minutes", 14),
        ("appeal_minutes", 29),
        ("bo", 2),
        ("bo", 4),
        ("starters", 0),
        ("substitutes", -1),
        ("priority_hours", -1),
        ("round_interval_minutes", 0),
        ("round_interval_minutes", 2_147_483_648),
        ("name", "   "),
        ("name", "字" * 101),
        ("livestream_url", "ftp://example.com/live"),
        ("livestream_url", "javascript:alert(1)"),
        ("livestream_url", "https://"),
        ("livestream_url", "twitch.tv/flow"),
        ("livestream_url", 123),
        ("start_at", "2026-11-01T10:00:00"),  # 沒有時區
        ("game_id", "not-a-uuid"),
    ],
)
@pytest.mark.usefixtures("frozen_clock")
def test_invalid_fields_are_rejected_with_field_loc(
    client: TestClient,
    session: Session,
    organizer: dict[str, str],
    field: str,
    value: Any,
) -> None:
    game = make_game(session)
    body = tournament_body(game.id)
    body[field] = value

    response = _create(client, organizer, body)

    assert ["body", field] in _error_locs(response)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"capacity": 1}, "名額不能小於 2"),
        ({"forfeit_minutes": 14}, "棄權時限不能小於 15"),
        ({"appeal_minutes": 29}, "申訴期不能小於 30"),
        (
            {"livestream_url": "ftp://x.tv"},
            "直播連結必須是 http:// 或 https:// 開頭的網址",
        ),
        ({"capacity": 2_147_483_648}, "名額太大"),
    ],
)
@pytest.mark.usefixtures("frozen_clock")
def test_field_error_messages_are_in_chinese(
    client: TestClient,
    session: Session,
    organizer: dict[str, str],
    overrides: dict[str, Any],
    message: str,
) -> None:
    game = make_game(session)

    error = _single_error(
        _create(client, organizer, tournament_body(game.id, **overrides))
    )

    assert error["msg"] == message


@pytest.mark.parametrize(
    "url", ["http://example.com/live", "  HTTPS://Twitch.tv/x  ", ""]
)
@pytest.mark.usefixtures("frozen_clock")
def test_valid_or_blank_livestream_url_is_accepted(
    client: TestClient, session: Session, organizer: dict[str, str], url: str
) -> None:
    game = make_game(session)

    response = _create(client, organizer, tournament_body(game.id, livestream_url=url))

    assert response.status_code == 201, response.text
    assert response.json()["livestream_url"] == (url.strip() or None)


# 128 只是第二階段畫面的提醒門檻，後端照常建立
@pytest.mark.parametrize("capacity", [2, 128, 129, 200, 2_147_483_647])
@pytest.mark.usefixtures("frozen_clock")
def test_capacity_bounds_are_accepted(
    client: TestClient, session: Session, organizer: dict[str, str], capacity: int
) -> None:
    game = make_game(session)

    response = _create(client, organizer, tournament_body(game.id, capacity=capacity))

    assert response.status_code == 201, response.text
    assert response.json()["capacity"] == capacity


@pytest.mark.usefixtures("frozen_clock")
def test_unknown_game_is_404(client: TestClient, organizer: dict[str, str]) -> None:
    response = _create(client, organizer, tournament_body(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "GAME_NOT_FOUND"


@pytest.mark.usefixtures("frozen_clock")
def test_rejected_create_writes_nothing(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session, game_minutes=40, default_bo=1)
    before = len(list(session.exec(select(AuditLog))))

    response = _create(
        client, organizer, tournament_body(game.id, round_interval_minutes=1)
    )

    assert response.status_code == 422
    listed = client.get(TOURNAMENTS_URL, headers=organizer).json()
    assert listed == []
    assert len(list(session.exec(select(AuditLog)))) == before


# ---------------------------------------------------------------- 權限與讀取


@pytest.mark.usefixtures("frozen_clock")
def test_non_organizer_cannot_create_or_list_games(
    client: TestClient, session: Session
) -> None:
    game = make_game(session)
    for headers in (member_headers(client, session), admin_headers(client, session)):
        created = _create(client, headers, tournament_body(game.id))
        games = client.get(f"{API}/games", headers=headers)
        listed = client.get(TOURNAMENTS_URL, headers=headers)

        for response in (created, games, listed):
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "ORGANIZER_REQUIRED"


def test_organizer_can_list_games(
    client: TestClient, session: Session, organizer: dict[str, str]
) -> None:
    game = make_game(session)

    response = client.get(f"{API}/games", headers=organizer)

    assert response.status_code == 200
    assert game.model_dump(mode="json") in response.json()


@pytest.mark.usefixtures("frozen_clock")
def test_organizer_cannot_read_another_organizers_tournament(
    client: TestClient, session: Session
) -> None:
    other = make_tournament(session)
    headers = organizer_headers(client, session)

    response = client.get(f"{TOURNAMENTS_URL}/{other.id}", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TOURNAMENT_OWNER_REQUIRED"


@pytest.mark.usefixtures("frozen_clock")
def test_non_organizer_cannot_read_tournament_by_id(
    client: TestClient, session: Session
) -> None:
    tournament = make_tournament(session)

    for headers in (member_headers(client, session), admin_headers(client, session)):
        response = client.get(f"{TOURNAMENTS_URL}/{tournament.id}", headers=headers)

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ORGANIZER_REQUIRED"


@pytest.mark.parametrize(
    "path",
    ["/games", "/organizer/tournaments", f"/organizer/tournaments/{uuid.uuid4()}"],
)
def test_reads_without_token_are_401(client: TestClient, path: str) -> None:
    response = client.get(f"{API}{path}")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


def test_reading_missing_tournament_is_404(
    client: TestClient, organizer: dict[str, str]
) -> None:
    response = client.get(f"{TOURNAMENTS_URL}/{uuid.uuid4()}", headers=organizer)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TOURNAMENT_NOT_FOUND"


@pytest.mark.usefixtures("frozen_clock")
def test_list_returns_only_own_tournaments_newest_first(
    client: TestClient, session: Session, frozen_clock: FrozenClock
) -> None:
    owner = make_account(session, organizer=True)
    headers = bearer(token_for(client, owner))
    game = make_game(session)
    first = make_tournament(session, organizer=owner, game=game, name="第一場")
    frozen_clock.advance(timedelta(minutes=1))
    second = make_tournament(session, organizer=owner, game=game, name="第二場")
    make_tournament(session, game=game, name="別人的")

    response = client.get(TOURNAMENTS_URL, headers=headers)

    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [str(second.id), str(first.id)]
    single = client.get(f"{TOURNAMENTS_URL}/{first.id}", headers=headers)
    assert single.status_code == 200
    assert TournamentRead.model_validate(single.json()) == first


@pytest.mark.usefixtures("frozen_clock")
def test_get_and_lock_return_contract_fields(session: Session) -> None:
    created = make_tournament(session)

    got = service.get_tournament(session, tournament_id=created.id)
    locked = service.lock_tournament(session, tournament_id=created.id)

    assert set(TournamentRead.model_fields) == CONTRACT_FIELDS
    assert got == created
    assert locked == created


@pytest.mark.parametrize("function", [service.get_tournament, service.lock_tournament])
def test_get_and_lock_missing_tournament_is_404(
    session: Session, function: Any
) -> None:
    with pytest.raises(BusinessError) as excinfo:
        function(session, tournament_id=uuid.uuid4())

    assert excinfo.value.code == "TOURNAMENT_NOT_FOUND"
    assert excinfo.value.status_code == 404


def test_audit_log_tournament_id_references_tournament(session: Session) -> None:
    with pytest.raises(IntegrityError), session.begin_nested():
        audit.record(
            session,
            actor_id=None,
            tournament_id=uuid.uuid4(),
            action="orphan",
            entity_type="Sample",
            entity_id=uuid.uuid4(),
            before=None,
            after=None,
        )
        session.flush()
