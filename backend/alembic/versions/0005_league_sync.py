"""league import/sync tables

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"; down_revision = "0004"; branch_labels = None; depends_on = None


def upgrade():
    op.create_table(
        "league_competitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("season", sa.String(20), nullable=False),
        sa.Column("group_name", sa.String(80), nullable=True),
        sa.Column("slug", sa.String(240), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("provider", "external_id", "season", name="uq_league_comp"),
    )
    op.create_table(
        "league_standings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("competition_id", sa.String(36), sa.ForeignKey("league_competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_team_id", sa.String(80), nullable=False),
        sa.Column("team_name", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("played", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("draws", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("goals_for", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("goals_against", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("yellow_cards", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("red_cards", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_league_standings_competition_id", "league_standings", ["competition_id"])
    op.create_table(
        "league_fixtures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("competition_id", sa.String(36), sa.ForeignKey("league_competitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(80), nullable=False),
        sa.Column("round_label", sa.String(40), nullable=True),
        sa.Column("match_date", sa.String(40), nullable=True),
        sa.Column("home_team", sa.String(160), nullable=False),
        sa.Column("away_team", sa.String(160), nullable=False),
        sa.Column("home_external_id", sa.String(80), nullable=True),
        sa.Column("away_external_id", sa.String(80), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default=""),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(300), nullable=True),
        sa.Column("home_match_id", sa.String(36), sa.ForeignKey("matches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("away_match_id", sa.String(36), sa.ForeignKey("matches.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("competition_id", "external_id", name="uq_league_fixture"),
    )
    op.create_index("ix_league_fixtures_competition_id", "league_fixtures", ["competition_id"])
    op.create_table(
        "external_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(120), nullable=False),
        sa.Column("internal_entity_id", sa.String(36), nullable=False),
        sa.Column("external_url", sa.String(400), nullable=True),
        sa.Column("season", sa.String(20), nullable=True),
        sa.Column("competition_id", sa.String(80), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("provider", "entity_type", "external_id", name="uq_external_identity"),
    )
    op.create_index("ix_external_identities_provider", "external_identities", ["provider"])
    op.create_index("ix_external_identities_entity_type", "external_identities", ["entity_type"])
    op.create_table(
        "official_player_stats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("player_external_id", sa.String(80), nullable=False),
        sa.Column("team_external_id", sa.String(80), nullable=False),
        sa.Column("season", sa.String(20), nullable=False, server_default=""),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("appearances", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("goals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("yellow", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("red", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("position_hint", sa.String(40), nullable=True),
        sa.Column("player_id", sa.String(36), sa.ForeignKey("players.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_official_player_stats_player_external_id", "official_player_stats", ["player_external_id"])
    op.create_index("ix_official_player_stats_team_external_id", "official_player_stats", ["team_external_id"])


def downgrade():
    for table in ("official_player_stats", "external_identities", "league_fixtures", "league_standings", "league_competitions"):
        op.drop_table(table)
