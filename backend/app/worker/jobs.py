"""worker 每一輪要執行的工作清單（依序執行）。

每個工作接收一個 session、一次只處理一筆，回傳是否處理了一筆；只呼叫 core 與
各模組 service，不得 commit 或 rollback（交易由 `app.worker.run_once` 負責）。
"""

from sqlmodel import Session

from app.core import events
from app.modules.notifications import service as notifications_service
from app.modules.notifications.email import EmailSender, SmtpEmailSender
from app.modules.tournaments import service as tournaments_service
from app.worker import Job


def dispatch_outbox(session: Session) -> bool:
    """取一則未處理的事件交給 notifications 分派，再標為已處理。"""
    event = events.next_unprocessed(session)
    if event is None:
        return False
    notifications_service.dispatch_event(session, event)
    events.mark_processed(session, event)
    return True


def make_send_email_job(sender: EmailSender) -> Job:
    def send_pending_email(session: Session) -> bool:
        """寄出一封待寄的 Email。"""
        return notifications_service.send_next_email(session, sender=sender)

    return send_pending_email


def open_registrations(session: Session) -> bool:
    """把一筆報名開始已到的「尚未開放」賽事轉為開放報名（操作者為系統）。"""
    return tournaments_service.open_due_registration(session)


JOBS: list[Job] = [
    open_registrations,
    dispatch_outbox,
    make_send_email_job(SmtpEmailSender()),
]
