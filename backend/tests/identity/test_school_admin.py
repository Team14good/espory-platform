"""Story 2.1：平台管理員新增學校與修正學校名稱（I/O 矩陣的學校各列）。"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.audit import AuditLog
from app.modules.identity import repository
from app.modules.identity.models import Account, School
from tests.helpers import API, admin_headers, make_account, member_headers

ADMIN_SCHOOLS_URL = f"{API}/admin/schools"
SCHOOLS_URL = f"{API}/schools"


def _name() -> str:
    return f"測試大學-{uuid.uuid4().hex[:8]}"


def _audit_rows(session: Session, school_id: str, action: str) -> list[AuditLog]:
    return list(
        session.exec(
            select(AuditLog)
            .where(AuditLog.entity_id == uuid.UUID(school_id))
            .where(AuditLog.action == action)
        )
    )


def _create(client: TestClient, headers: dict[str, str], name: str) -> Any:
    return client.post(ADMIN_SCHOOLS_URL, json={"name": name}, headers=headers)


def _existing_school(session: Session) -> School:
    school = session.exec(select(School).order_by(School.name)).first()
    assert school is not None
    return school


@pytest.fixture
def admin(client: TestClient, session: Session) -> dict[str, str]:
    return admin_headers(client, session)


# ---------------------------------------------------------------- 新增


def test_create_school_is_listed_immediately_and_audited(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    name = _name()

    response = _create(client, admin, f"  {name} ")

    assert response.status_code == 201, response.text
    school = response.json()
    assert school == {"id": school["id"], "name": name}
    assert school in client.get(SCHOOLS_URL).json()

    [row] = _audit_rows(session, school["id"], "school.created")
    assert row.tournament_id is None
    assert row.entity_type == "school"
    assert row.before is None
    assert row.after == {"name": name}


def test_create_school_with_existing_name_is_409(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    existing = _existing_school(session)

    response = _create(client, admin, existing.name)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SCHOOL_NAME_TAKEN"


def test_concurrent_create_with_same_name_only_one_succeeds(
    client: TestClient, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 第二個請求的同名檢查在第一個 commit 前就通過了：改由 ix_school_name 擋下
    name = _name()
    assert _create(client, admin, name).status_code == 201
    monkeypatch.setattr(repository, "get_school_by_name", lambda *_a, **_k: None)

    response = _create(client, admin, name)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SCHOOL_NAME_TAKEN"


@pytest.mark.parametrize("name", ["", "   ", "字" * 256, 123])
def test_invalid_school_name_is_422(
    client: TestClient, admin: dict[str, str], name: Any
) -> None:
    response = client.post(ADMIN_SCHOOLS_URL, json={"name": name}, headers=admin)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "name"]


# ---------------------------------------------------------------- 修正名稱


def test_rename_school_keeps_account_school_id_and_is_audited(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    old_name = _name()
    school_id = _create(client, admin, old_name).json()["id"]
    account = make_account(session, school_id=uuid.UUID(school_id))
    new_name = _name()

    response = client.patch(
        f"{ADMIN_SCHOOLS_URL}/{school_id}", json={"name": new_name}, headers=admin
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"id": school_id, "name": new_name}
    session.expire_all()
    stored = session.get(Account, account.id)
    assert stored is not None
    assert stored.school_id == uuid.UUID(school_id)
    names = [school["name"] for school in client.get(SCHOOLS_URL).json()]
    assert new_name in names
    assert old_name not in names

    [row] = _audit_rows(session, school_id, "school.renamed")
    assert row.tournament_id is None
    assert row.before == {"name": old_name}
    assert row.after == {"name": new_name}


def test_rename_to_same_name_writes_no_audit(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    name = _name()
    school_id = _create(client, admin, name).json()["id"]

    response = client.patch(
        f"{ADMIN_SCHOOLS_URL}/{school_id}", json={"name": f" {name} "}, headers=admin
    )

    assert response.status_code == 200
    assert _audit_rows(session, school_id, "school.renamed") == []


def test_rename_unknown_school_is_404(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    school_id = str(uuid.uuid4())
    response = client.patch(
        f"{ADMIN_SCHOOLS_URL}/{school_id}", json={"name": _name()}, headers=admin
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SCHOOL_NOT_FOUND"
    assert _audit_rows(session, school_id, "school.renamed") == []


def test_rename_to_existing_name_is_409(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    existing = _existing_school(session)
    school_id = _create(client, admin, _name()).json()["id"]

    response = client.patch(
        f"{ADMIN_SCHOOLS_URL}/{school_id}",
        json={"name": existing.name},
        headers=admin,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SCHOOL_NAME_TAKEN"


def test_concurrent_rename_to_same_name_is_409(
    client: TestClient,
    session: Session,
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = _existing_school(session)
    school_id = _create(client, admin, _name()).json()["id"]
    monkeypatch.setattr(repository, "get_school_by_name", lambda *_a, **_k: None)

    response = client.patch(
        f"{ADMIN_SCHOOLS_URL}/{school_id}",
        json={"name": existing.name},
        headers=admin,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SCHOOL_NAME_TAKEN"
    assert _audit_rows(session, school_id, "school.renamed") == []


# ---------------------------------------------------------------- 權限


@pytest.mark.parametrize("method", ["post", "patch"])
def test_non_admin_is_403_and_anonymous_is_401(
    client: TestClient, session: Session, method: str
) -> None:
    school = _existing_school(session)
    url = ADMIN_SCHOOLS_URL if method == "post" else f"{ADMIN_SCHOOLS_URL}/{school.id}"

    forbidden = client.request(
        method, url, json={"name": _name()}, headers=member_headers(client, session)
    )
    anonymous = client.request(method, url, json={"name": _name()})

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "PLATFORM_ADMIN_REQUIRED"
    assert anonymous.status_code == 401
