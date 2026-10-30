"""Story 2.2：賽事狀態轉換、可否報名／回報比分、每輪 BO 與主辦方權限判斷。"""

import uuid
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from app.core import audit, authz
from app.core.errors import BusinessError
from app.modules.tournaments import service
from app.modules.tournaments.models import (
    Tournament,
    TournamentRead,
    TournamentStatus,
)
from tests.helpers import make_account, make_tournament

S = TournamentStatus

ALLOWED = {
    (S.UPCOMING, S.OPEN),
    (S.OPEN, S.CLOSED),
    (S.OPEN, S.PUBLISHED),
    (S.CLOSED, S.PUBLISHED),
    (S.PUBLISHED, S.ONGOING),
    (S.ONGOING, S.FINISHED),
    (S.CLOSED, S.OPEN),
    *((status, S.CANCELLED) for status in S if status not in (S.FINISHED, S.CANCELLED)),
}
FORBIDDEN = [(a, b) for a in S for b in S if (a, b) not in ALLOWED]


def _tournament_in(session: Session, status: TournamentStatus) -> uuid.UUID:
    """建立賽事後直接把狀態設成指定值（測試用，略過轉換規則）。"""
    tournament_id = make_tournament(session).id
    row = session.get(Tournament, tournament_id)
    assert row is not None
    row.status = status
    session.add(row)
    session.flush()
    return tournament_id


def _read_with(status: TournamentStatus, session: Session) -> TournamentRead:
    created = make_tournament(session)
    return created.model_copy(update={"status": status})


@pytest.mark.parametrize(("source", "target"), sorted(ALLOWED))
@pytest.mark.usefixtures("frozen_clock")
def test_allowed_transition_changes_status_and_writes_audit(
    session: Session, source: TournamentStatus, target: TournamentStatus
) -> None:
    tournament_id = _tournament_in(session, source)
    actor = make_account(session)
    service.lock_tournament(session, tournament_id=tournament_id)

    result = service.transition_tournament(
        session, tournament_id=tournament_id, to=target, actor_id=actor.id
    )

    assert result.status == target
    assert service.get_tournament(session, tournament_id=tournament_id).status == target
    row = audit.list_for_tournament(session, tournament_id)[-1]
    assert row.action == "tournament.status_changed"
    assert row.actor_id == actor.id
    assert row.before == {"status": source.value}
    assert row.after == {"status": target.value}


@pytest.mark.parametrize(("source", "target"), FORBIDDEN)
@pytest.mark.usefixtures("frozen_clock")
def test_forbidden_transition_is_409_and_changes_nothing(
    session: Session, source: TournamentStatus, target: TournamentStatus
) -> None:
    tournament_id = _tournament_in(session, source)
    logs_before = audit.list_for_tournament(session, tournament_id)

    with pytest.raises(BusinessError) as excinfo:
        service.transition_tournament(
            session, tournament_id=tournament_id, to=target, actor_id=None
        )

    assert excinfo.value.code == "TOURNAMENT_INVALID_TRANSITION"
    assert excinfo.value.status_code == 409
    assert service.get_tournament(session, tournament_id=tournament_id).status == source
    assert audit.list_for_tournament(session, tournament_id) == logs_before


@pytest.mark.usefixtures("frozen_clock")
def test_upcoming_to_finished_is_409(session: Session) -> None:
    # I/O 矩陣的「非法轉換」列
    tournament_id = _tournament_in(session, S.UPCOMING)

    with pytest.raises(BusinessError) as excinfo:
        service.transition_tournament(
            session, tournament_id=tournament_id, to=S.FINISHED, actor_id=None
        )

    assert excinfo.value.code == "TOURNAMENT_INVALID_TRANSITION"
    assert excinfo.value.status_code == 409


def test_transition_of_missing_tournament_is_404(session: Session) -> None:
    with pytest.raises(BusinessError) as excinfo:
        service.transition_tournament(
            session, tournament_id=uuid.uuid4(), to=S.OPEN, actor_id=None
        )

    assert excinfo.value.code == "TOURNAMENT_NOT_FOUND"


# ---------------------------------------------------------------- ensure_*


@pytest.mark.parametrize("status", list(S))
@pytest.mark.usefixtures("frozen_clock")
def test_ensure_accepting_registrations_only_when_open(
    session: Session, status: TournamentStatus
) -> None:
    tournament = _read_with(status, session)

    if status == S.OPEN:
        service.ensure_accepting_registrations(tournament)
        return
    with pytest.raises(BusinessError) as excinfo:
        service.ensure_accepting_registrations(tournament)
    assert excinfo.value.code == "REGISTRATION_CLOSED"
    assert excinfo.value.status_code == 409


@pytest.mark.parametrize("status", list(S))
@pytest.mark.usefixtures("frozen_clock")
def test_ensure_accepting_scores_only_when_published_or_ongoing(
    session: Session, status: TournamentStatus
) -> None:
    tournament = _read_with(status, session)

    if status in (S.PUBLISHED, S.ONGOING):
        service.ensure_accepting_scores(tournament)
        return
    with pytest.raises(BusinessError) as excinfo:
        service.ensure_accepting_scores(tournament)
    assert excinfo.value.code == "TOURNAMENT_NOT_ACCEPTING_SCORES"
    assert excinfo.value.status_code == 409


# ---------------------------------------------------------------- bo_for_round


@pytest.mark.usefixtures("frozen_clock")
def test_bo_for_round_returns_tournament_bo_for_every_round(session: Session) -> None:
    tournament = make_tournament(session, bo=5, round_interval_minutes=300)

    assert [
        service.bo_for_round(session, tournament_id=tournament.id, round_no=n)
        for n in (1, 2, 7)
    ] == [5, 5, 5]


@pytest.mark.usefixtures("frozen_clock")
def test_bo_for_round_rejects_round_zero(session: Session) -> None:
    tournament = make_tournament(session)

    with pytest.raises(ValueError):
        service.bo_for_round(session, tournament_id=tournament.id, round_no=0)


# ---------------------------------------------------------------- core.authz


def test_ensure_tournament_owner_compares_loaded_organizer_id() -> None:
    owner = uuid.uuid4()
    tournament = SimpleNamespace(organizer_id=owner)

    authz.ensure_tournament_owner(tournament, owner)
    with pytest.raises(BusinessError) as excinfo:
        authz.ensure_tournament_owner(tournament, uuid.uuid4())

    assert excinfo.value.code == "TOURNAMENT_OWNER_REQUIRED"
    assert excinfo.value.status_code == 403
