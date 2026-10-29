"""Story 2.1：平台管理員維護遊戲設定（I/O 矩陣的遊戲各列）。"""

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.audit import AuditLog
from app.core.errors import BusinessError
from app.modules.tournaments import repository, service
from app.modules.tournaments.models import GameIn, GameRead, RankTier
from tests.helpers import API, admin_headers, make_account, member_headers

GAMES_URL = f"{API}/admin/games"


def _game_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": f"遊戲-{uuid.uuid4().hex[:8]}",
        "starters": 5,
        "substitutes": 2,
        "default_bo": 3,
        "game_minutes": 40,
        "score_type": "win_loss",
        "rank_tiers": [
            {"name": "黃金", "score": 10},
            {"name": "鑽石", "score": 30},
        ],
    }
    body.update(overrides)
    return body


def _audit_rows(session: Session, game_id: str, action: str) -> list[AuditLog]:
    return list(
        session.exec(
            select(AuditLog)
            .where(AuditLog.entity_id == uuid.UUID(game_id))
            .where(AuditLog.action == action)
        )
    )


def _error_locs(response: Any) -> list[list[Any]]:
    return [error["loc"] for error in response.json()["detail"]]


@pytest.fixture
def admin(client: TestClient, session: Session) -> dict[str, str]:
    return admin_headers(client, session)


# ---------------------------------------------------------------- 新增


def test_create_game_returns_tiers_by_score_desc_and_writes_audit(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    body = _game_body(name="  英雄聯盟測試  ")

    response = client.post(GAMES_URL, json=body, headers=admin)

    assert response.status_code == 201, response.text
    game = response.json()
    assert game["name"] == "英雄聯盟測試"
    assert game["starters"] == 5
    assert game["substitutes"] == 2
    assert game["default_bo"] == 3
    assert game["game_minutes"] == 40
    assert game["score_type"] == "win_loss"
    assert game["rank_tiers"] == [
        {"name": "鑽石", "score": 30},
        {"name": "黃金", "score": 10},
    ]

    [row] = _audit_rows(session, game["id"], "game.created")
    assert row.tournament_id is None
    assert row.entity_type == "game"
    assert row.before is None
    assert row.after == {
        "name": "英雄聯盟測試",
        "starters": 5,
        "substitutes": 2,
        "default_bo": 3,
        "game_minutes": 40,
        "score_type": "win_loss",
        "rank_tiers": [{"name": "鑽石", "score": 30}, {"name": "黃金", "score": 10}],
    }


def test_fictional_third_game_values_match_input(
    client: TestClient, admin: dict[str, str]
) -> None:
    body = _game_body(
        name="虛構對戰",
        starters=3,
        substitutes=0,
        default_bo=7,
        score_type="win_loss",
        rank_tiers=[{"name": "唯一段位", "score": 0}],
    )

    response = client.post(GAMES_URL, json=body, headers=admin)

    assert response.status_code == 201, response.text
    game = response.json()
    assert {key: game[key] for key in body} == body


def test_new_game_is_listed_immediately(
    client: TestClient, admin: dict[str, str]
) -> None:
    created = client.post(GAMES_URL, json=_game_body(), headers=admin).json()

    listed = client.get(GAMES_URL, headers=admin)
    single = client.get(f"{GAMES_URL}/{created['id']}", headers=admin)

    assert listed.status_code == 200
    assert created in listed.json()
    assert single.status_code == 200
    assert single.json() == created


@pytest.mark.parametrize("bo", [0, 2, 4, 6, 8, -1])
def test_invalid_bo_is_rejected(
    client: TestClient, admin: dict[str, str], bo: int
) -> None:
    response = client.post(GAMES_URL, json=_game_body(default_bo=bo), headers=admin)

    assert response.status_code == 422
    assert ["body", "default_bo"] in _error_locs(response)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("starters", 0),
        ("substitutes", -1),
        ("game_minutes", 0),
        ("starters", True),
        ("starters", 2_147_483_648),
        ("score_type", "points"),
        ("name", "   "),
        ("name", 123),
        ("name", "字" * 101),
        ("rank_tiers", [{"name": f"段位{i}", "score": i} for i in range(101)]),
    ],
)
def test_invalid_game_fields_are_rejected(
    client: TestClient, admin: dict[str, str], field: str, value: Any
) -> None:
    response = client.post(GAMES_URL, json=_game_body(**{field: value}), headers=admin)

    assert response.status_code == 422
    assert ["body", field] in _error_locs(response)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"starters": 0}, "先發人數不能小於 1"),
        ({"default_bo": 2}, "BO 數只能是 1、3、5 或 7"),
        ({"name": ""}, "請輸入遊戲名稱"),
        ({"rank_tiers": []}, "至少需要一筆段位"),
        (
            {
                "rank_tiers": [
                    {"name": "鑽石", "score": 1},
                    {"name": "鑽石", "score": 2},
                ]
            },
            "段位名稱「鑽石」重複",
        ),
    ],
)
def test_field_error_messages_are_in_chinese(
    client: TestClient, admin: dict[str, str], overrides: dict[str, Any], message: str
) -> None:
    response = client.post(GAMES_URL, json=_game_body(**overrides), headers=admin)

    assert response.status_code == 422
    assert [error["msg"] for error in response.json()["detail"]] == [message]


def test_empty_rank_tiers_are_rejected(
    client: TestClient, admin: dict[str, str]
) -> None:
    response = client.post(GAMES_URL, json=_game_body(rank_tiers=[]), headers=admin)

    assert response.status_code == 422
    assert ["body", "rank_tiers"] in _error_locs(response)


def test_duplicate_rank_tier_names_are_rejected(
    client: TestClient, admin: dict[str, str]
) -> None:
    tiers = [{"name": "鑽石", "score": 30}, {"name": " 鑽石 ", "score": 20}]

    response = client.post(GAMES_URL, json=_game_body(rank_tiers=tiers), headers=admin)

    assert response.status_code == 422
    assert ["body", "rank_tiers"] in _error_locs(response)


def test_negative_rank_tier_score_is_rejected(
    client: TestClient, admin: dict[str, str]
) -> None:
    tiers = [{"name": "鑽石", "score": -1}]

    response = client.post(GAMES_URL, json=_game_body(rank_tiers=tiers), headers=admin)

    assert response.status_code == 422
    assert ["body", "rank_tiers", 0, "score"] in _error_locs(response)


@pytest.mark.parametrize("duplicate", ["英雄聯盟 ", "英雄聯盟", " 英雄聯盟"])
def test_duplicate_game_name_is_409(
    client: TestClient, admin: dict[str, str], duplicate: str
) -> None:
    assert (
        client.post(GAMES_URL, json=_game_body(name="英雄聯盟"), headers=admin)
    ).status_code == 201

    response = client.post(GAMES_URL, json=_game_body(name=duplicate), headers=admin)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "GAME_NAME_TAKEN"


def test_game_name_is_case_insensitive(
    client: TestClient, admin: dict[str, str]
) -> None:
    client.post(GAMES_URL, json=_game_body(name="Valorant"), headers=admin)

    response = client.post(GAMES_URL, json=_game_body(name="VALORANT"), headers=admin)

    assert response.status_code == 409


def test_concurrent_create_with_same_name_only_one_succeeds(
    client: TestClient,
    session: Session,
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 第二個請求的同名檢查在第一個 commit 前就通過了：改由唯一索引擋下
    assert (
        client.post(GAMES_URL, json=_game_body(name="同時送出"), headers=admin)
    ).status_code == 201
    monkeypatch.setattr(repository, "get_game_by_name", lambda *_a, **_k: None)

    response = client.post(GAMES_URL, json=_game_body(name="同時送出 "), headers=admin)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "GAME_NAME_TAKEN"
    assert len(_audit_rows_by_action(session, "game.created", "同時送出")) == 1


def _audit_rows_by_action(session: Session, action: str, name: str) -> list[AuditLog]:
    return [
        row
        for row in session.exec(select(AuditLog).where(AuditLog.action == action))
        if row.after is not None and row.after.get("name") == name
    ]


# ---------------------------------------------------------------- 修改


def test_update_replaces_bo_and_rank_tiers_and_audits_only_changes(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    created = client.post(GAMES_URL, json=_game_body(), headers=admin).json()
    new_tiers = [{"name": "大師", "score": 50}, {"name": "鑽石", "score": 30}]
    body = _game_body(name=created["name"], default_bo=5, rank_tiers=new_tiers)

    response = client.put(f"{GAMES_URL}/{created['id']}", json=body, headers=admin)

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["default_bo"] == 5
    assert updated["rank_tiers"] == new_tiers
    # 段位整份替換：舊的「黃金」不再存在
    stored = session.exec(
        select(RankTier).where(RankTier.game_id == uuid.UUID(created["id"]))
    ).all()
    assert sorted(tier.name for tier in stored) == ["大師", "鑽石"]

    [row] = _audit_rows(session, created["id"], "game.updated")
    assert row.tournament_id is None
    assert row.before == {
        "default_bo": 3,
        "rank_tiers": [{"name": "鑽石", "score": 30}, {"name": "黃金", "score": 10}],
    }
    assert row.after == {"default_bo": 5, "rank_tiers": new_tiers}
    # 立即反映在列表
    assert updated in client.get(GAMES_URL, headers=admin).json()


def test_update_without_changes_writes_no_audit(
    client: TestClient, session: Session, admin: dict[str, str]
) -> None:
    body = _game_body()
    created = client.post(GAMES_URL, json=body, headers=admin).json()
    # 段位順序不同但內容相同，視為沒有變動
    body["rank_tiers"] = list(reversed(body["rank_tiers"]))

    response = client.put(f"{GAMES_URL}/{created['id']}", json=body, headers=admin)

    assert response.status_code == 200
    assert response.json() == created
    assert _audit_rows(session, created["id"], "game.updated") == []


def test_update_can_change_name_case_of_itself(
    client: TestClient, admin: dict[str, str]
) -> None:
    created = client.post(GAMES_URL, json=_game_body(name="dota"), headers=admin).json()

    response = client.put(
        f"{GAMES_URL}/{created['id']}", json=_game_body(name="DOTA"), headers=admin
    )

    assert response.status_code == 200
    assert response.json()["name"] == "DOTA"


def test_update_to_another_games_name_is_409(
    client: TestClient, admin: dict[str, str]
) -> None:
    client.post(GAMES_URL, json=_game_body(name="甲遊戲"), headers=admin)
    other = client.post(GAMES_URL, json=_game_body(name="乙遊戲"), headers=admin)

    response = client.put(
        f"{GAMES_URL}/{other.json()['id']}",
        json=_game_body(name="甲遊戲 "),
        headers=admin,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "GAME_NAME_TAKEN"


def test_concurrent_rename_to_same_name_is_409(
    client: TestClient,
    session: Session,
    admin: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.post(GAMES_URL, json=_game_body(name="丙遊戲"), headers=admin)
    other = client.post(GAMES_URL, json=_game_body(name="丁遊戲"), headers=admin)
    monkeypatch.setattr(repository, "get_game_by_name", lambda *_a, **_k: None)

    response = client.put(
        f"{GAMES_URL}/{other.json()['id']}",
        json=_game_body(name="丙遊戲"),
        headers=admin,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "GAME_NAME_TAKEN"
    assert _audit_rows(session, other.json()["id"], "game.updated") == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"default_bo": 2},
        {"rank_tiers": []},
        {
            "rank_tiers": [
                {"name": "Diamond", "score": 30},
                {"name": "diamond", "score": 20},
            ]
        },
    ],
)
def test_update_with_invalid_body_is_422_and_leaves_game_unchanged(
    client: TestClient,
    session: Session,
    admin: dict[str, str],
    overrides: dict[str, Any],
) -> None:
    created = client.post(GAMES_URL, json=_game_body(), headers=admin).json()

    response = client.put(
        f"{GAMES_URL}/{created['id']}",
        json=_game_body(name=created["name"], **overrides),
        headers=admin,
    )

    assert response.status_code == 422
    assert client.get(f"{GAMES_URL}/{created['id']}", headers=admin).json() == created
    stored = session.exec(
        select(RankTier).where(RankTier.game_id == uuid.UUID(created["id"]))
    ).all()
    assert sorted((tier.name, tier.score) for tier in stored) == [
        ("鑽石", 30),
        ("黃金", 10),
    ]
    assert _audit_rows(session, created["id"], "game.updated") == []


def test_case_only_duplicate_rank_tier_names_are_rejected(
    client: TestClient, admin: dict[str, str]
) -> None:
    tiers = [{"name": "Diamond", "score": 30}, {"name": "diamond", "score": 20}]

    response = client.post(GAMES_URL, json=_game_body(rank_tiers=tiers), headers=admin)

    assert response.status_code == 422
    assert ["body", "rank_tiers"] in _error_locs(response)


@pytest.mark.parametrize("method", ["get", "put"])
def test_unknown_game_is_404(
    client: TestClient, session: Session, admin: dict[str, str], method: str
) -> None:
    game_id = str(uuid.uuid4())
    response = client.request(
        method,
        f"{GAMES_URL}/{game_id}",
        json=_game_body() if method == "put" else None,
        headers=admin,
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "GAME_NOT_FOUND"
    assert _audit_rows(session, game_id, "game.updated") == []


# ---------------------------------------------------------------- 權限


@pytest.mark.parametrize(
    ("method", "path", "send_body"),
    [
        ("get", "", False),
        ("post", "", True),
        ("get", "/{id}", False),
        ("put", "/{id}", True),
    ],
)
def test_non_admin_is_403_and_anonymous_is_401(
    client: TestClient,
    session: Session,
    admin: dict[str, str],
    method: str,
    path: str,
    send_body: bool,
) -> None:
    created = client.post(GAMES_URL, json=_game_body(), headers=admin).json()
    url = GAMES_URL + path.replace("{id}", created["id"])
    body = _game_body() if send_body else None

    forbidden = client.request(
        method, url, json=body, headers=member_headers(client, session)
    )
    anonymous = client.request(method, url, json=body)

    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "PLATFORM_ADMIN_REQUIRED"
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


# ---------------------------------------------------------------- 公開函式


def test_get_game_public_function_returns_game_read(session: Session) -> None:
    actor = make_account(session, admin=True)
    created = service.create_game(
        session, actor_id=actor.id, data=GameIn.model_validate(_game_body())
    )

    game = service.get_game(session, game_id=created.id)

    assert isinstance(game, GameRead)
    assert game == created
    with pytest.raises(BusinessError) as excinfo:
        service.get_game(session, game_id=uuid.uuid4())
    assert excinfo.value.code == "GAME_NOT_FOUND"
    assert excinfo.value.status_code == 404
