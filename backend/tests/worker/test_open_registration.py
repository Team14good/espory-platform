"""Story 2.2：worker 在報名開始時間到時，把「尚未開放」的賽事轉為開放報名。"""

from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlmodel import Session

from app.core import audit
from app.modules.tournaments import repository, service
from app.modules.tournaments.models import TournamentStatus
from app.worker import run_once
from app.worker.jobs import JOBS, open_registrations
from tests.conftest import FrozenClock
from tests.helpers import make_tournament


def test_open_registrations_is_registered() -> None:
    assert open_registrations in JOBS


def test_worker_opens_registration_when_start_arrives_and_is_idempotent(
    session: Session,
    session_factory: Callable[[], Session],
    frozen_clock: FrozenClock,
) -> None:
    due_soon = make_tournament(
        session,
        registration_start=(frozen_clock.now() + timedelta(hours=1)).isoformat(),
        priority_hours=1,
    )
    later = make_tournament(
        session,
        registration_start=(frozen_clock.now() + timedelta(hours=3)).isoformat(),
        priority_hours=1,
    )
    session.commit()

    # 還沒到：不變
    run_once([open_registrations], session_factory=session_factory)
    assert service.get_tournament(session, tournament_id=due_soon.id).status == (
        TournamentStatus.UPCOMING
    )

    frozen_clock.advance(timedelta(hours=1))
    run_once([open_registrations], session_factory=session_factory)
    session.expire_all()

    assert service.get_tournament(session, tournament_id=due_soon.id).status == (
        TournamentStatus.OPEN
    )
    assert service.get_tournament(session, tournament_id=later.id).status == (
        TournamentStatus.UPCOMING
    )
    logs = audit.list_for_tournament(session, due_soon.id)
    assert [log.action for log in logs] == [
        "tournament.created",
        "tournament.status_changed",
    ]
    changed = logs[-1]
    assert changed.actor_id is None  # system
    assert changed.before == {"status": "upcoming"}
    assert changed.after == {"status": "open"}

    # 再執行一次：不變、不重複寫紀錄
    run_once([open_registrations], session_factory=session_factory)
    session.expire_all()
    assert service.get_tournament(session, tournament_id=due_soon.id).status == (
        TournamentStatus.OPEN
    )
    assert len(audit.list_for_tournament(session, due_soon.id)) == 2


def test_worker_opens_every_due_tournament_in_one_round(
    session: Session,
    session_factory: Callable[[], Session],
    frozen_clock: FrozenClock,
) -> None:
    ids = [
        make_tournament(
            session,
            registration_start=(frozen_clock.now() + timedelta(minutes=m)).isoformat(),
            priority_hours=1,
        ).id
        for m in (10, 20)
    ]
    session.commit()

    frozen_clock.advance(timedelta(minutes=30))
    run_once([open_registrations], session_factory=session_factory)
    session.expire_all()

    assert [service.get_tournament(session, tournament_id=i).status for i in ids] == [
        TournamentStatus.OPEN,
        TournamentStatus.OPEN,
    ]


def test_candidate_already_opened_after_lock_is_left_unchanged(
    session: Session,
    frozen_clock: FrozenClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 找到候選後、鎖住前，另一個 worker 已經把它轉為 open：重新檢查後不做任何事
    tournament = make_tournament(
        session,
        registration_start=(frozen_clock.now() + timedelta(hours=1)).isoformat(),
        priority_hours=1,
    )
    frozen_clock.advance(timedelta(hours=2))
    service.transition_tournament(
        session, tournament_id=tournament.id, to=TournamentStatus.OPEN, actor_id=None
    )
    logs_before = len(audit.list_for_tournament(session, tournament.id))
    candidates = iter([tournament.id])
    monkeypatch.setattr(
        repository,
        "find_due_upcoming_id",
        lambda _session, _now: next(candidates, None),
    )

    assert open_registrations(session) is True

    assert service.get_tournament(session, tournament_id=tournament.id).status == (
        TournamentStatus.OPEN
    )
    assert len(audit.list_for_tournament(session, tournament.id)) == logs_before
    assert open_registrations(session) is False


def test_job_returns_false_when_nothing_is_due(session: Session) -> None:
    assert open_registrations(session) is False
