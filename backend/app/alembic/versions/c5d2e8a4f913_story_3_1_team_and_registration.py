"""Story 3.1: team and registration

建立 team（隊伍；邀請 token 明文、UNIQUE；同賽事隊名不分大小寫唯一）、team_member
（隊員；（tournament_id, account_id）唯一）與 registration（報名；建立隊伍時為 forming）。
tournament_id 暫不加外鍵：tournament 表由 Story 2.2 建立，合併後另以遷移補上。
參賽資料欄位（3.2）與送出快照欄位（3.3）由之後的 Story 加入。

Revision ID: c5d2e8a4f913
Revises: 9e5b3f1a7c42
Create Date: 2026-10-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "c5d2e8a4f913"
down_revision = "9e5b3f1a7c42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "team",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=False),
        sa.Column(
            "invite_token", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invite_token"),
    )
    op.create_index(
        op.f("ix_team_tournament_id"), "team", ["tournament_id"], unique=False
    )
    op.create_index(
        "ix_team_tournament_id_lower_name",
        "team",
        ["tournament_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "team_member",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id",
            "account_id",
            name="uq_team_member_tournament_id_account_id",
        ),
    )
    op.create_index(
        op.f("ix_team_member_account_id"), "team_member", ["account_id"], unique=False
    )
    op.create_index(
        op.f("ix_team_member_team_id"), "team_member", ["team_id"], unique=False
    )

    op.create_table(
        "registration",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("tournament_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id"),
    )
    op.create_index(
        op.f("ix_registration_tournament_id"),
        "registration",
        ["tournament_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_registration_tournament_id"), table_name="registration")
    op.drop_table("registration")
    op.drop_index(op.f("ix_team_member_team_id"), table_name="team_member")
    op.drop_index(op.f("ix_team_member_account_id"), table_name="team_member")
    op.drop_table("team_member")
    op.drop_index("ix_team_tournament_id_lower_name", table_name="team")
    op.drop_index(op.f("ix_team_tournament_id"), table_name="team")
    op.drop_table("team")
