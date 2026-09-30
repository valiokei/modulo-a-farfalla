"""admin/coach/player roles and user-player binding

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"; down_revision = "0003"; branch_labels = None; depends_on = None


def upgrade():
    bind = op.get_bind()
    users = sa.table("users", sa.column("role", sa.String), sa.column("player_id", sa.String))
    existing = [c["name"] for c in sa.inspect(bind).get_columns("users")]
    if "player_id" not in existing:
        op.add_column("users", sa.Column("player_id", sa.String(36), nullable=True))
        op.create_foreign_key("fk_users_player", "users", "players", ["player_id"], ["id"], ondelete="SET NULL")
        op.create_index("ix_users_player_id", "users", ["player_id"])
    if "team_id" not in existing:
        op.add_column("users", sa.Column("team_id", sa.String(36), nullable=True))
        op.create_foreign_key("fk_users_team", "users", "teams", ["team_id"], ["id"], ondelete="SET NULL")
        op.create_index("ix_users_team_id", "users", ["team_id"])
    # Sync legacy 'user' rows to the new 'coach' role (coach is the analysis role).
    bind.execute(sa.text("UPDATE users SET role='coach' WHERE role='user'"))


def downgrade():
    bind = op.get_bind()
    existing = [c["name"] for c in sa.inspect(bind).get_columns("users")]
    if "player_id" in existing:
        op.drop_index("ix_users_player_id", table_name="users")
        op.drop_constraint("fk_users_player", "users", type_="foreignkey")
        op.drop_column("users", "player_id")
    if "team_id" in existing:
        op.drop_index("ix_users_team_id", table_name="users")
        op.drop_constraint("fk_users_team", "users", type_="foreignkey")
        op.drop_column("users", "team_id")
    bind.execute(sa.text("UPDATE users SET role='user' WHERE role='coach'"))
