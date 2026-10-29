"""測試共用的帳號與登入工具（原本在 tests/identity/test_login.py）。"""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.modules.identity.models import Account

API = settings.API_V1_STR
PASSWORD = "eight-ch"


def random_email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


def make_account(
    session: Session,
    *,
    verified: bool = True,
    admin: bool = False,
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
