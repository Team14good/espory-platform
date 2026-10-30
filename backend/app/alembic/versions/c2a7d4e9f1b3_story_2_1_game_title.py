"""Story 2.1: game settings

建立 game_title（遊戲設定：先發、替補、預設 BO、每局預估時間、比分型態）與
rank_tier（段位對照，隨遊戲刪除）。遊戲名稱以 lower(btrim(name)) 唯一：
去除前後空白、不分大小寫不可重複。

Revision ID: c2a7d4e9f1b3
Revises: 9e5b3f1a7c42
Create Date: 2026-10-29 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "c2a7d4e9f1b3"
down_revision = "9e5b3f1a7c42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "game_title",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("starters", sa.Integer(), nullable=False),
        sa.Column("substitutes", sa.Integer(), nullable=False),
        sa.Column("default_bo", sa.Integer(), nullable=False),
        sa.Column("game_minutes", sa.Integer(), nullable=False),
        sa.Column("score_type", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_game_title_lower_name",
        "game_title",
        [sa.text("lower(btrim(name))")],
        unique=True,
    )

    op.create_table(
        "rank_tier",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["game_title.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rank_tier_game_id"), "rank_tier", ["game_id"], unique=False
    )
    # 同遊戲內段位名稱去除前後空白、不分大小寫唯一
    op.create_index(
        "ix_rank_tier_game_id_lower_name",
        "rank_tier",
        ["game_id", sa.text("lower(btrim(name))")],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_rank_tier_game_id_lower_name", table_name="rank_tier")
    op.drop_index(op.f("ix_rank_tier_game_id"), table_name="rank_tier")
    op.drop_table("rank_tier")
    op.drop_index("ix_game_title_lower_name", table_name="game_title")
    op.drop_table("game_title")
