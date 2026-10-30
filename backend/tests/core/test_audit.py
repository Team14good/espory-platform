import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.core import audit, clock
from app.modules.tournaments.models import (
    Tournament,
    TournamentMode,
    TournamentStatus,
)
from tests.conftest import FrozenClock
from tests.helpers import make_account, make_game


def _tournament_id(session: Session) -> uuid.UUID:
    """直接新增一筆賽事列並回傳 id。

    audit_log.tournament_id 有外鍵（Story 2.2），紀錄要指向真的賽事；不經
    service 建立，才不會多出 tournament.created 紀錄。
    """
    game = make_game(session)
    now = clock.now()
    tournament = Tournament(
        organizer_id=make_account(session, organizer=True).id,
        game_id=game.id,
        name="稽核測試",
        status=TournamentStatus.OPEN,
        mode=TournamentMode.CAMPUS,
        capacity=2,
        registration_start=now,
        priority_end=now,
        registration_end=now,
        start_at=now,
        round_interval_minutes=1,
        forfeit_minutes=15,
        appeal_minutes=30,
        game_snapshot={},
    )
    session.add(tournament)
    session.flush()
    return tournament.id


def _record(session: Session, tournament_id: uuid.UUID | None, action: str) -> None:
    audit.record(
        session,
        actor_id=None,
        tournament_id=tournament_id,
        action=action,
        entity_type="Sample",
        entity_id=uuid.uuid4(),
        before=None,
        after={"status": "open"},
    )


def test_list_for_tournament_orders_by_time(
    session: Session, frozen_clock: FrozenClock
) -> None:
    tournament_id = _tournament_id(session)
    start = frozen_clock.now()

    frozen_clock.advance(timedelta(minutes=2))
    _record(session, tournament_id, "second")
    frozen_clock.set(start + timedelta(minutes=1))
    _record(session, tournament_id, "first")
    _record(session, _tournament_id(session), "other_tournament")
    _record(session, None, "account_action")
    session.flush()

    logs = audit.list_for_tournament(session, tournament_id)

    assert [log.action for log in logs] == ["first", "second"]
    assert logs[0].at == start + timedelta(minutes=1)
    assert logs[0].actor_id is None  # system
    assert logs[0].after == {"status": "open"}


def test_record_serializes_non_json_values(session: Session) -> None:
    tournament_id = _tournament_id(session)
    related_id = uuid.uuid4()

    audit.record(
        session,
        actor_id=None,
        tournament_id=tournament_id,
        action="sample_changed",
        entity_type="Sample",
        entity_id=uuid.uuid4(),
        before={"related_id": related_id},
        after=None,
    )
    session.flush()

    [log] = audit.list_for_tournament(session, tournament_id)
    assert log.before == {"related_id": str(related_id)}
    assert log.after is None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
def test_database_rejects_modifying_audit_log(session: Session, statement: str) -> None:
    tournament_id = _tournament_id(session)
    _record(session, tournament_id, "original")
    session.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        with session.begin_nested():
            session.execute(text(statement))

    [log] = audit.list_for_tournament(session, tournament_id)
    assert log.action == "original"


@pytest.mark.usefixtures("frozen_clock")
def test_same_time_records_keep_insertion_order(session: Session) -> None:
    tournament_id = _tournament_id(session)
    actions = [f"action_{i}" for i in range(5)]

    for action in actions:
        _record(session, tournament_id, action)
        session.flush()

    logs = audit.list_for_tournament(session, tournament_id)

    assert [log.action for log in logs] == actions
    assert len({log.at for log in logs}) == 1


@pytest.mark.parametrize("column", ["before", "after"])
def test_none_is_stored_as_sql_null(session: Session, column: str) -> None:
    # before／after 為 None 時都要存成 SQL NULL，而不是 JSON 的 null：
    # 經 ORM 讀回時兩者都是 None，只有原生 SQL 的 IS NULL 分得出來
    tournament_id = _tournament_id(session)
    audit.record(
        session,
        actor_id=None,
        tournament_id=tournament_id,
        action=f"with_null_{column}",
        entity_type="Sample",
        entity_id=uuid.uuid4(),
        before=None if column == "before" else {"status": "open"},
        after=None if column == "after" else {"status": "open"},
    )
    session.flush()

    matched = session.execute(
        text(
            "SELECT count(*) FROM audit_log"
            f" WHERE tournament_id = :tid AND {column} IS NULL"
        ),
        {"tid": tournament_id},
    ).scalar_one()

    assert matched == 1
