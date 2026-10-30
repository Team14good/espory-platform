"""端到端（不含瀏覽器）：註冊 → worker 分派並寄出驗證信 → 以信中連結完成驗證。"""

import uuid
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.events import OutboxEvent
from app.modules.identity.models import Account
from app.modules.notifications.models import DeliveryStatus, EmailDelivery
from app.worker import run_once
from app.worker.jobs import JOBS, dispatch_outbox, make_send_email_job
from tests.conftest import FakeEmailSender

API = settings.API_V1_STR


def _link_from(html: str) -> str:
    start = html.index(f"{settings.FRONTEND_HOST}/verify-email?")
    end = html.index('"', start)
    return html[start:end].replace("&amp;", "&")


def test_jobs_are_registered_in_order() -> None:
    names = [getattr(job, "__name__", "") for job in JOBS]

    assert names == ["open_registrations", "dispatch_outbox", "send_pending_email"]


def test_signup_email_is_sent_by_the_next_round_and_link_verifies(
    client: TestClient,
    session: Session,
    session_factory: Callable[[], Session],
    fake_email_sender: FakeEmailSender,
) -> None:
    email = "Pipeline.User@Example.com"
    response = client.post(
        f"{API}/accounts",
        json={
            "email": email,
            "password": "pipeline-pass",
            "display_name": "管線",
            "redirect": "/tournaments/1",
        },
    )
    assert response.status_code == 201
    jobs = [dispatch_outbox, make_send_email_job(fake_email_sender)]

    run_once(jobs, session_factory=session_factory)
    run_once(jobs, session_factory=session_factory)  # 再跑一輪也不會重寄

    [message] = fake_email_sender.sent
    assert message.to == "pipeline.user@example.com"
    assert message.subject == "完成 FLOW 的 Email 驗證"
    events = list(session.exec(select(OutboxEvent)))
    assert events and all(e.processed_at is not None for e in events)
    [delivery] = list(session.exec(select(EmailDelivery)))
    assert delivery.status == DeliveryStatus.SENT

    link = _link_from(message.html)
    query = parse_qs(urlsplit(link).query)
    assert query["redirect"] == ["/tournaments/1"]
    verified = client.post(
        f"{API}/email-verifications", json={"token": query["token"][0]}
    )
    assert verified.status_code == 204
    account = session.exec(
        select(Account).where(Account.email == "pipeline.user@example.com")
    ).one()
    session.refresh(account)
    assert account.email_verified is True


def test_smtp_failure_does_not_block_other_events(
    client: TestClient,
    session: Session,
    session_factory: Callable[[], Session],
    fake_email_sender: FakeEmailSender,
) -> None:
    for name in ("first", "second"):
        response = client.post(
            f"{API}/accounts",
            json={
                "email": f"{name}-{uuid.uuid4().hex}@example.com",
                "password": "pipeline-pass",
                "display_name": name,
            },
        )
        assert response.status_code == 201, response.text
    fake_email_sender.fail_with = ConnectionRefusedError("SMTP down")

    run_once(
        [dispatch_outbox, make_send_email_job(fake_email_sender)],
        session_factory=session_factory,
    )

    deliveries = list(session.exec(select(EmailDelivery)))
    assert len(deliveries) == 2
    assert {d.attempts for d in deliveries} == {1}
    assert all(d.status == DeliveryStatus.PENDING for d in deliveries)
    assert all(d.last_error and "SMTP down" in d.last_error for d in deliveries)
    # 兩則事件都已處理，失敗只影響寄送
    assert all(e.processed_at is not None for e in session.exec(select(OutboxEvent)))
