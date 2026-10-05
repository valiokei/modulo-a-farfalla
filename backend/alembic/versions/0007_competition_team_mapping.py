"""competition-scoped team mapping

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("league_team_mappings"):
        return
    op.create_table(
        "league_team_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("season", sa.String(20), nullable=False),
        sa.Column("competition_external_id", sa.String(80), nullable=False),
        sa.Column("team_external_id", sa.String(80), nullable=False),
        sa.Column("local_team_id", sa.String(36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("provider", "season", "competition_external_id", "team_external_id", name="uq_league_team_mapping"),
    )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("league_team_mappings"):
        op.drop_table("league_team_mappings")
