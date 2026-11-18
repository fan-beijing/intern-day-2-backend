"""接口回归用例：覆盖登录链路、鉴权分支与记账功能。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app

USERNAME = "demo"
PASSWORD = "test-password-123"


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    # with 语句会触发 lifespan，完成建表与练习账号创建
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str = USERNAME, password: str = PASSWORD) -> str:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_returns_token_and_me(client: TestClient) -> None:
    payload = client.post(
        "/auth/login", json={"username": USERNAME, "password": PASSWORD}
    ).json()

    assert payload["token_type"] == "bearer"
    assert len(payload["token"]) >= 32
    # 时间字段必须带时区标记，前端才不会按本地时间误读
    assert payload["expires_at"].endswith("Z")
    assert payload["user"]["username"] == USERNAME
    assert payload["user"]["created_at"].endswith("Z")
    # 响应里不能出现密码相关字段
    assert "password" not in str(payload).lower()

    me = client.get("/auth/me", headers=auth_header(payload["token"]))
    assert me.status_code == 200
    assert me.json()["username"] == USERNAME


def test_wrong_password_is_401(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": USERNAME, "password": "wrong-pass"})
    assert response.status_code == 401
    assert response.json()["detail"] == "账号或密码错误"


def test_unknown_user_uses_same_message(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": "nobody", "password": "whatever"})
    assert response.status_code == 401
    assert response.json()["detail"] == "账号或密码错误"


def test_empty_payload_is_422(client: TestClient) -> None:
    assert client.post("/auth/login", json={"username": "", "password": ""}).status_code == 422
    assert client.post("/auth/login", json={}).status_code == 422


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer forged-token-value"},
        {"Authorization": "Basic ZGVtbzp0ZXN0"},
        {"Authorization": "Bearer "},
    ],
)
def test_invalid_credentials_are_401(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.get("/ledger/entries", headers=headers).status_code == 401


def test_logout_invalidates_old_token(client: TestClient) -> None:
    token = login(client)
    assert client.post("/auth/logout", headers=auth_header(token)).status_code == 200
    # 同一个令牌第二次使用必须失败
    assert client.get("/auth/me", headers=auth_header(token)).status_code == 401
    assert client.post("/auth/logout", headers=auth_header(token)).status_code == 401


def test_entry_flow_and_summary(client: TestClient) -> None:
    token = login(client)
    headers = auth_header(token)
    month = "2026-03"

    income = client.post(
        "/ledger/entries",
        headers=headers,
        json={"kind": "income", "amount": 3000, "category": "工资", "note": "三月", "occurred_on": f"{month}-01"},
    )
    assert income.status_code == 201, income.text

    expense = client.post(
        "/ledger/entries",
        headers=headers,
        json={"kind": "expense", "amount": 25.5, "category": "餐饮", "occurred_on": f"{month}-05"},
    )
    assert expense.status_code == 201, expense.text

    summary = client.get("/ledger/summary", params={"month": month}, headers=headers).json()
    assert summary["income"] == 3000
    assert summary["expense"] == 25.5
    assert summary["balance"] == 2974.5
    assert summary["count"] == 2

    listing = client.get("/ledger/entries", params={"month": month}, headers=headers).json()
    assert listing["count"] == 2
    assert listing["items"][0]["occurred_on"] >= listing["items"][-1]["occurred_on"]

    deleted = client.delete(f"/ledger/entries/{expense.json()['id']}", headers=headers)
    assert deleted.status_code == 204

    after = client.get("/ledger/summary", params={"month": month}, headers=headers).json()
    assert after["expense"] == 0
    assert after["balance"] == 3000
    assert after["count"] == 1


def test_negative_and_zero_amount_are_422(client: TestClient) -> None:
    headers = auth_header(login(client))
    for amount in (-5, 0):
        response = client.post(
            "/ledger/entries", headers=headers, json={"kind": "expense", "amount": amount}
        )
        assert response.status_code == 422


def test_entry_defaults_to_today(client: TestClient) -> None:
    headers = auth_header(login(client))
    response = client.post("/ledger/entries", headers=headers, json={"kind": "income", "amount": 1})
    assert response.status_code == 201
    assert response.json()["occurred_on"] == date.today().isoformat()


def test_deleting_someone_elses_entry_is_404(client: TestClient) -> None:
    owner_token = login(client)
    owner_headers = auth_header(owner_token)
    entry_id = client.post(
        "/ledger/entries",
        headers=owner_headers,
        json={"kind": "income", "amount": 88, "category": "红包"},
    ).json()["id"]

    # 造一个第二个账号，用它去删别人的账目
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as db:
        if db.query(User).filter(User.username == "intruder").first() is None:
            db.add(User(username="intruder", password_hash=hash_password("intruder-pass")))
            db.commit()

    intruder_headers = auth_header(login(client, "intruder", "intruder-pass"))

    response = client.delete(f"/ledger/entries/{entry_id}", headers=intruder_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "账目不存在"

    # 原主人依然能删
    assert client.delete(f"/ledger/entries/{entry_id}", headers=owner_headers).status_code == 204


def test_month_parameter_validation(client: TestClient) -> None:
    headers = auth_header(login(client))
    assert client.get("/ledger/entries", params={"month": "2026-13"}, headers=headers).status_code == 422
    assert client.get("/ledger/summary", params={"month": "abc"}, headers=headers).status_code == 422


def test_expired_token_is_401_and_cleaned_up(client: TestClient) -> None:
    from datetime import datetime, timedelta, timezone

    from app.db import SessionLocal
    from app.models import AuthSession
    from app.security import hash_token

    token = login(client)
    token_digest = hash_token(token)

    # 直接把会话过期时间改到过去，等价于「等到凭证过期」
    with SessionLocal() as db:
        session = db.query(AuthSession).filter(AuthSession.token_hash == token_digest).one()
        session.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        db.commit()

    assert client.get("/auth/me", headers=auth_header(token)).status_code == 401
    assert client.get("/ledger/entries", headers=auth_header(token)).status_code == 401

    # 命中过期会话时顺手删行，避免会话表无限增长
    with SessionLocal() as db:
        assert db.query(AuthSession).filter(AuthSession.token_hash == token_digest).first() is None

