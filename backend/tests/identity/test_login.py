"""Story 1.4：登入、目前帳號、身分清單、帳號資料與權限依賴（I/O 矩陣的後端各列）。"""

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy import Connection
from sqlmodel import Session, select

from app.core.audit import AuditLog
from app.core.config import Settings, settings
from app.core.db import get_session
from app.core.errors import register_error_handlers
from app.core.security import ALGORITHM, create_access_token, get_password_hash
from app.modules.identity import service
from app.modules.identity.deps import CurrentAccount, PlatformAdmin, VerifiedAccount
from app.modules.identity.models import Account, School
from tests.conftest import FrozenClock

API = settings.API_V1_STR
PASSWORD = "eight-ch"
INVALID_CREDENTIALS = {
    "detail": {"code": "INVALID_CREDENTIALS", "message": "Email 或密碼錯誤。"}
}
AUTHENTICATION_REQUIRED = {
    "detail": {"code": "AUTHENTICATION_REQUIRED", "message": "請先登入。"}
}


def _email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


def _make_account(
    session: Session,
    *,
    verified: bool = True,
    admin: bool = False,
    hashed_password: str | None = None,
    school_id: uuid.UUID | None = None,
) -> Account:
    account = Account(
        email=_email(),
        hashed_password=hashed_password or get_password_hash(PASSWORD),
        email_verified=verified,
        display_name="小安",
        school_id=school_id,
        is_platform_admin=admin,
    )
    session.add(account)
    session.flush()
    return account


def _login(client: TestClient, email: str, password: str = PASSWORD) -> Any:
    return client.post(
        f"{API}/access-tokens", json={"email": email, "password": password}
    )


def _token(client: TestClient, account: Account) -> str:
    response = _login(client, account.email)
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _schools(session: Session, count: int) -> list[School]:
    schools = list(session.exec(select(School).order_by(School.name).limit(count)))
    assert len(schools) == count
    return schools


def _audit_rows(session: Session, account_id: uuid.UUID) -> list[AuditLog]:
    return list(
        session.exec(
            select(AuditLog)
            .where(AuditLog.entity_id == account_id)
            .where(AuditLog.action == "account.profile_updated")
        )
    )


# ---------------------------------------------------------------- 登入


def test_login_with_normalized_email_returns_bearer_token_valid_for_7_days(
    client: TestClient, session: Session, frozen_clock: FrozenClock
) -> None:
    account = _make_account(session)

    response = _login(client, f"  {account.email.upper()} ")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_at"}
    assert body["token_type"] == "bearer"
    assert datetime.fromisoformat(body["expires_at"]) == frozen_clock.now() + (
        timedelta(days=7)
    )
    me = client.get(f"{API}/accounts/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == str(account.id)


def test_access_token_lifetime_defaults_to_7_days() -> None:
    # 檢查程式宣告的預設值（compose 會注入環境變數，settings 的值不代表預設值）
    assert Settings.model_fields["ACCESS_TOKEN_EXPIRE_MINUTES"].default == 60 * 24 * 7


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("nobody@example.com", PASSWORD),  # Email 不存在
        (None, "wrong-password"),  # 密碼錯誤（None 代表用既有帳號的 Email）
        ("not-an-email", PASSWORD),  # 格式不符
        ("", ""),
        (None, ""),
        (None, PASSWORD + "x" * 200),  # 超過密碼長度上限
        ("a" * 300 + "@example.com", PASSWORD),  # 超過 Email 長度上限
    ],
)
def test_login_failures_are_indistinguishable(
    client: TestClient, session: Session, email: str | None, password: str
) -> None:
    account = _make_account(session)

    response = _login(client, email if email is not None else account.email, password)

    assert response.status_code == 401
    assert response.json() == INVALID_CREDENTIALS


def test_login_rejects_correct_password_followed_by_extra_characters(
    client: TestClient, session: Session
) -> None:
    # 密碼正好 128 字元：截斷到 128 字元後雜湊會吻合，只靠長度檢查擋下
    password = "p" * 128
    account = _make_account(session, hashed_password=get_password_hash(password))

    assert _login(client, account.email, password).status_code == 200
    response = _login(client, account.email, password + "x")

    assert response.status_code == 401
    assert response.json() == INVALID_CREDENTIALS
    assert "www-authenticate" not in response.headers


def test_unknown_email_still_runs_a_password_hash_check(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = service.verify_password

    def _spy(plain: str, hashed: str) -> tuple[bool, str | None]:
        calls.append(hashed)
        return original(plain, hashed)

    monkeypatch.setattr(service, "verify_password", _spy)

    response = _login(client, "nobody@example.com")

    assert response.status_code == 401
    assert len(calls) == 1


def test_unverified_account_can_log_in(client: TestClient, session: Session) -> None:
    account = _make_account(session, verified=False)

    token = _token(client, account)

    me = client.get(f"{API}/accounts/me", headers=_bearer(token))
    assert me.status_code == 200
    assert me.json()["email_verified"] is False


def test_login_upgrades_outdated_password_hash_without_audit(
    client: TestClient, session: Session
) -> None:
    account = _make_account(session, hashed_password=BcryptHasher().hash(PASSWORD))

    assert _login(client, account.email).status_code == 200

    session.expire_all()
    refreshed = session.get(Account, account.id)
    assert refreshed is not None
    assert refreshed.hashed_password.startswith("$argon2")
    assert not list(
        session.exec(select(AuditLog).where(AuditLog.entity_id == account.id))
    )


def test_login_requires_both_fields(client: TestClient) -> None:
    response = client.post(f"{API}/access-tokens", json={"email": "a@example.com"})

    assert response.status_code == 422


# ---------------------------------------------------------------- 目前帳號與 token


def test_current_account_returns_profile_without_password(
    client: TestClient, session: Session
) -> None:
    [school] = _schools(session, 1)
    account = _make_account(session, school_id=school.id)

    response = client.get(
        f"{API}/accounts/me", headers=_bearer(_token(client, account))
    )

    assert response.json() == {
        "id": str(account.id),
        "email": account.email,
        "display_name": "小安",
        "school_id": str(school.id),
        "email_verified": True,
        "is_platform_admin": False,
        "is_organizer": False,
    }


def _assert_authentication_required(response: Any) -> None:
    assert response.status_code == 401
    assert response.json() == AUTHENTICATION_REQUIRED
    assert response.headers["www-authenticate"] == "Bearer"


def test_current_account_without_token_is_401(client: TestClient) -> None:
    _assert_authentication_required(client.get(f"{API}/accounts/me"))


def test_expired_token_is_401(
    client: TestClient, session: Session, frozen_clock: FrozenClock
) -> None:
    account = _make_account(session)
    token = _token(client, account)

    frozen_clock.advance(timedelta(days=7) - timedelta(seconds=1))
    assert client.get(f"{API}/accounts/me", headers=_bearer(token)).status_code == 200

    frozen_clock.advance(timedelta(seconds=1))
    _assert_authentication_required(
        client.get(f"{API}/accounts/me", headers=_bearer(token))
    )


def test_token_with_wrong_signature_is_401(
    client: TestClient, session: Session, frozen_clock: FrozenClock
) -> None:
    account = _make_account(session)
    forged = jwt.encode(
        {"sub": str(account.id), "exp": frozen_clock.now() + timedelta(days=1)},
        "another-secret-key-0123456789",
        algorithm=ALGORITHM,
    )

    _assert_authentication_required(
        client.get(f"{API}/accounts/me", headers=_bearer(forged))
    )


@pytest.mark.parametrize("subject", [str(uuid.uuid4()), "not-a-uuid"])
def test_token_for_missing_account_is_401(client: TestClient, subject: str) -> None:
    token = create_access_token(subject, timedelta(days=1), version=0)

    _assert_authentication_required(
        client.get(f"{API}/accounts/me", headers=_bearer(token))
    )


@pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer not.a.jwt", "x"])
def test_malformed_authorization_header_is_401(client: TestClient, header: str) -> None:
    _assert_authentication_required(
        client.get(f"{API}/accounts/me", headers={"Authorization": header})
    )


# ---------------------------------------------------------------- 身分清單


def test_regular_account_has_browse_and_my_teams_identities(
    client: TestClient, session: Session
) -> None:
    account = _make_account(session)

    response = client.get(
        f"{API}/accounts/me/identities", headers=_bearer(_token(client, account))
    )

    assert response.status_code == 200
    assert response.json() == [
        {"key": "browse", "label": "瀏覽賽事", "home_path": "/"},
        {"key": "my_teams", "label": "我的隊伍", "home_path": "/me/teams"},
    ]


def test_platform_admin_also_has_platform_admin_identity(
    client: TestClient, session: Session
) -> None:
    account = _make_account(session, admin=True)

    response = client.get(
        f"{API}/accounts/me/identities", headers=_bearer(_token(client, account))
    )

    assert response.json() == [
        {"key": "browse", "label": "瀏覽賽事", "home_path": "/"},
        {"key": "my_teams", "label": "我的隊伍", "home_path": "/me/teams"},
        {
            "key": "platform_admin",
            "label": "平台管理",
            "home_path": "/admin/applications",
        },
    ]


def test_identities_require_login(client: TestClient) -> None:
    _assert_authentication_required(client.get(f"{API}/accounts/me/identities"))


# ---------------------------------------------------------------- 帳號資料


def _patch_me(client: TestClient, token: str, body: dict[str, Any]) -> Any:
    return client.patch(f"{API}/accounts/me", headers=_bearer(token), json=body)


def test_update_display_name_and_school_writes_audit_with_changed_fields_only(
    client: TestClient, session: Session
) -> None:
    old_school, new_school = _schools(session, 2)
    account = _make_account(session, school_id=old_school.id)
    token = _token(client, account)

    response = _patch_me(
        client,
        token,
        {"display_name": "  阿明 ", "school_id": str(new_school.id)},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "阿明"
    assert response.json()["school_id"] == str(new_school.id)
    [row] = _audit_rows(session, account.id)
    assert row.actor_id == account.id
    assert row.tournament_id is None
    assert row.entity_type == "account"
    assert row.before == {"display_name": "小安", "school_id": str(old_school.id)}
    assert row.after == {"display_name": "阿明", "school_id": str(new_school.id)}


def test_update_only_display_name_keeps_school(
    client: TestClient, session: Session
) -> None:
    [school] = _schools(session, 1)
    account = _make_account(session, school_id=school.id)

    response = _patch_me(client, _token(client, account), {"display_name": "阿明"})

    assert response.json()["school_id"] == str(school.id)
    [row] = _audit_rows(session, account.id)
    assert row.before == {"display_name": "小安"}
    assert row.after == {"display_name": "阿明"}


def test_school_can_be_cleared_with_null(client: TestClient, session: Session) -> None:
    [school] = _schools(session, 1)
    account = _make_account(session, school_id=school.id)

    response = _patch_me(client, _token(client, account), {"school_id": None})

    assert response.status_code == 200
    assert response.json()["school_id"] is None
    [row] = _audit_rows(session, account.id)
    assert row.before == {"school_id": str(school.id)}
    assert row.after == {"school_id": None}


def test_unchanged_profile_writes_no_audit(
    client: TestClient, session: Session
) -> None:
    account = _make_account(session)

    response = _patch_me(
        client, _token(client, account), {"display_name": "小安", "school_id": None}
    )

    assert response.status_code == 200
    assert _audit_rows(session, account.id) == []


def test_email_cannot_be_changed_through_profile(
    client: TestClient, session: Session
) -> None:
    account = _make_account(session)

    response = _patch_me(
        client, _token(client, account), {"email": "other@example.com"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == account.email
    assert _audit_rows(session, account.id) == []


def test_unknown_school_is_rejected_on_the_school_field(
    client: TestClient, session: Session
) -> None:
    account = _make_account(session)

    response = _patch_me(
        client, _token(client, account), {"school_id": str(uuid.uuid4())}
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "SCHOOL_NOT_FOUND",
                "loc": ["body", "school_id"],
                "msg": "找不到這間學校",
            }
        ]
    }


@pytest.mark.parametrize(
    ("display_name", "message"),
    [
        ("   ", "請輸入顯示名稱"),
        (None, "請輸入顯示名稱"),
        ("名" * 51, "顯示名稱最多 50 個字"),
        (123, "請輸入文字"),
    ],
)
def test_invalid_display_name_is_rejected_like_signup(
    client: TestClient, session: Session, display_name: object, message: str
) -> None:
    account = _make_account(session)

    response = _patch_me(
        client, _token(client, account), {"display_name": display_name}
    )

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", "display_name"]
    assert error["msg"] == message


def test_display_name_of_50_characters_is_accepted(
    client: TestClient, session: Session
) -> None:
    account = _make_account(session)

    response = _patch_me(client, _token(client, account), {"display_name": "名" * 50})

    assert response.status_code == 200


# ---------------------------------------------------------------- 權限依賴


@pytest.fixture
def probe_client(db_connection: Connection) -> Iterator[TestClient]:
    """套用 VerifiedAccount／PlatformAdmin 的測試用 app（正式 router 到 1.7、1.8 才會用到）。"""
    probe = FastAPI()
    register_error_handlers(probe)

    @probe.get("/current")
    def _current(account: CurrentAccount) -> str:
        return str(account.id)

    @probe.get("/verified")
    def _verified(account: VerifiedAccount) -> str:
        return str(account.id)

    @probe.get("/admin")
    def _admin(account: PlatformAdmin) -> str:
        return str(account.id)

    def _override_get_session() -> Iterator[Session]:
        with Session(
            bind=db_connection, join_transaction_mode="create_savepoint"
        ) as db_session:
            yield db_session

    probe.dependency_overrides[get_session] = _override_get_session
    with TestClient(probe) as test_client:
        yield test_client


def test_require_verified_rejects_unverified_account(
    client: TestClient, probe_client: TestClient, session: Session
) -> None:
    unverified = _make_account(session, verified=False)
    verified = _make_account(session)

    rejected = probe_client.get(
        "/verified", headers=_bearer(_token(client, unverified))
    )
    accepted = probe_client.get("/verified", headers=_bearer(_token(client, verified)))

    assert rejected.status_code == 403
    assert rejected.json() == {
        "detail": {
            "code": "EMAIL_NOT_VERIFIED",
            "message": "完成 Email 驗證後才能使用這個功能。",
        }
    }
    assert accepted.status_code == 200
    assert accepted.json() == str(verified.id)
    # 未驗證帳號仍然是已登入
    current = probe_client.get("/current", headers=_bearer(_token(client, unverified)))
    assert current.status_code == 200


def test_require_platform_admin_rejects_other_accounts(
    client: TestClient, probe_client: TestClient, session: Session
) -> None:
    regular = _make_account(session)
    admin = _make_account(session, admin=True)

    rejected = probe_client.get("/admin", headers=_bearer(_token(client, regular)))
    accepted = probe_client.get("/admin", headers=_bearer(_token(client, admin)))

    assert rejected.status_code == 403
    assert rejected.json() == {
        "detail": {
            "code": "PLATFORM_ADMIN_REQUIRED",
            "message": "只有平台管理員可以使用這個功能。",
        }
    }
    assert accepted.status_code == 200


@pytest.mark.parametrize("path", ["/current", "/verified", "/admin"])
def test_dependencies_require_login_first(probe_client: TestClient, path: str) -> None:
    _assert_authentication_required(probe_client.get(path))
