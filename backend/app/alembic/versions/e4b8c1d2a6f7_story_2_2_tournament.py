"""Story 2.2: tournament

建立 tournament（賽事；遊戲設定在建立時複製進 game_snapshot），並為
audit_log.tournament_id 加上外鍵到 tournament.id。

Revision ID: e4b8c1d2a6f7
Revises: c2a7d4e9f1b3
Create Date: 2026-10-30 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e4b8c1d2a6f7"
down_revision = "c2a7d4e9f1b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tournament",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organizer_id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("registration_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priority_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registration_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("round_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("forfeit_minutes", sa.Integer(), nullable=False),
        sa.Column("appeal_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "livestream_url",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column(
            "game_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["game_title.id"]),
        sa.ForeignKeyConstraint(["organizer_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tournament_organizer_id"),
        "tournament",
        ["organizer_id"],
        unique=False,
    )
    # worker 依狀態與報名開始時間找出到期的賽事
    op.create_index(
        "ix_tournament_status_registration_start",
        "tournament",
        ["status", "registration_start"],
        unique=False,
    )
    op.create_foreign_key(
        "audit_log_tournament_id_fkey",
        "audit_log",
        "tournament",
        ["tournament_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(
        "audit_log_tournament_id_fkey", "audit_log", type_="foreignkey"
    )
    op.drop_index("ix_tournament_status_registration_start", table_name="tournament")
    op.drop_index(op.f("ix_tournament_organizer_id"), table_name="tournament")
    op.drop_table("tournament")
