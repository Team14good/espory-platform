"""操作紀錄（AD-9）：與業務資料同一個交易寫入，只增不改。

資料庫 trigger 拒絕對 `audit_log` 的 UPDATE、DELETE 與 TRUNCATE；程式只能
透過 `record()` 新增、透過 `list_for_tournament()` 查詢。
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy import BigInteger, Column, DateTime, Identity, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Session, SQLModel, col, select

from app.core import clock


class AuditLogBase(SQLModel):
    # 操作者；None 代表 system（worker 自動執行）
    actor_id: uuid.UUID | None = Field(default=None, foreign_key="account.id")
    # 所屬賽事；帳號類操作為 None。外鍵在 Story 2.2 建立 tournament 表時加上
    tournament_id: uuid.UUID | None = Field(default=None, foreign_key="tournament.id")
    action: str = Field(max_length=100)
    entity_type: str = Field(max_length=100)
    entity_id: uuid.UUID
    # none_as_null：Python 的 None 存成 SQL NULL，而不是 JSON 的 null
    before: dict[str, Any] | None = Field(
        default=None, sa_type=JSONB(none_as_null=True)
    )
    after: dict[str, Any] | None = Field(default=None, sa_type=JSONB(none_as_null=True))
    at: datetime = Field(sa_type=DateTime(timezone=True))


class AuditLog(AuditLogBase, table=True):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_tournament_id_at_seq", "tournament_id", "at", "seq"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # 資料庫產生的遞增序號：同一個 at 的紀錄依寫入順序排列
    seq: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, Identity(always=True), nullable=False),
    )


class AuditLogRead(AuditLogBase):
    id: uuid.UUID


def record(
    session: Session,
    *,
    actor_id: uuid.UUID | None,
    tournament_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """在目前的交易裡新增一筆操作紀錄；不 commit。"""
    session.add(
        AuditLog(
            actor_id=actor_id,
            tournament_id=tournament_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=to_jsonable_python(before),
            after=to_jsonable_python(after),
            at=clock.now(),
        )
    )


def list_for_tournament(
    session: Session, tournament_id: uuid.UUID
) -> list[AuditLogRead]:
    """依操作時間由舊到新（同時間依寫入順序）列出某賽事的操作紀錄。"""
    statement = (
        select(AuditLog)
        .where(AuditLog.tournament_id == tournament_id)
        .order_by(col(AuditLog.at), col(AuditLog.seq))
    )
    return [AuditLogRead.model_validate(row) for row in session.exec(statement)]
