"""測試共用的帳號、登入、遊戲與賽事工具（帳號部分原本在 tests/identity/test_login.py）。"""

import uuid
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core import clock
from app.core.config import settings
from app.core.security import get_password_hash
from app.modules.identity.models import Account
from app.modules.tournaments import service as tournaments_service
from app.modules.tournaments.models import (
    GameIn,
    GameRead,
    TournamentCreate,
    TournamentRead,
)

API = settings.API_V1_STR
PASSWORD = "eight-ch"


def random_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


def make_account(
    session: Session,
    *,
    verified: bool = True,
    admin: bool = False,
    organizer: bool = False,
    hashed_password: str | None = None,
    school_id: uuid.UUID | None = None,
) -> Account:
    account = Account(
        email=random_email(),
        hashed_password=hashed_password or get_password_hash(PASSWORD),
        email_verified=verified,
        display_name="小安",
        school_id=school_id,
        is_platform_admin=admin,
        is_organizer=organizer,
    )
    session.add(account)
    session.flush()
    return account


def login(client: TestClient, email: str, password: str = PASSWORD) -> Any:
    return client.post(
        f"{API}/access-tokens", json={"email": email, "password": password}
    )


def token_for(client: TestClient, account: Account) -> str:
    response = login(client, account.email)
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def admin_headers(client: TestClient, session: Session) -> dict[str, str]:
    """新建一個平台管理員並登入，回傳 Authorization 標頭。"""
    return bearer(token_for(client, make_account(session, admin=True)))


def member_headers(client: TestClient, session: Session) -> dict[str, str]:
    """新建一個已驗證的一般帳號並登入，回傳 Authorization 標頭。"""
    return bearer(token_for(client, make_account(session)))


def organizer_headers(client: TestClient, session: Session) -> dict[str, str]:
    """新建一個主辦方並登入，回傳 Authorization 標頭。"""
    return bearer(token_for(client, make_account(session, organizer=True)))


def make_game(session: Session, **overrides: Any) -> GameRead:
    """經 service 新增一款遊戲（預設：先發 5、替補 2、BO3、每局 40 分鐘）。"""
    data: dict[str, Any] = {
        "name": f"遊戲-{uuid.uuid4().hex[:8]}",
        "starters": 5,
        "substitutes": 2,
        "default_bo": 3,
        "game_minutes": 40,
        "score_type": "win_loss",
        "rank_tiers": [{"name": "鑽石", "score": 30}, {"name": "黃金", "score": 10}],
    }
    data.update(overrides)
    admin = make_account(session, admin=True)
    return tournaments_service.create_game(
        session, actor_id=admin.id, data=GameIn.model_validate(data)
    )


def tournament_body(game_id: uuid.UUID | str, **overrides: Any) -> dict[str, Any]:
    """建立賽事的合法表單（相對於目前時間：報名已開始、7 天後截止、8 天後開賽）。"""
    now = clock.now()
    body: dict[str, Any] = {
        "name": "期中盃",
        "game_id": str(game_id),
        "capacity": 16,
        "registration_start": (now - timedelta(hours=1)).isoformat(),
        "registration_end": (now + timedelta(days=7)).isoformat(),
        "start_at": (now + timedelta(days=8)).isoformat(),
        "round_interval_minutes": 180,
    }
    body.update(overrides)
    return body


def make_tournament(
    session: Session,
    *,
    organizer: Account | None = None,
    game: GameRead | None = None,
    **overrides: Any,
) -> TournamentRead:
    """經 service 建立一場賽事（預設報名已開始，狀態為 open）。"""
    organizer = organizer or make_account(session, organizer=True)
    game = game or make_game(session)
    return tournaments_service.create_tournament(
        session,
        organizer_id=organizer.id,
        data=TournamentCreate.model_validate(tournament_body(game.id, **overrides)),
    )
