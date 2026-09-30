"""team coaching platform

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="0002";down_revision="0001";branch_labels=None;depends_on=None


def upgrade():
    # Revision 0001 intentionally bootstraps a fresh database from current
    # metadata. Existing installations need the additive migration below;
    # fresh installations already contain it.
    columns={column["name"] for column in sa.inspect(op.get_bind()).get_columns("teams")}
    if "logo_path" in columns:
        return
    op.add_column("teams",sa.Column("logo_path",sa.String(),nullable=True))
    op.add_column("teams",sa.Column("season",sa.String(40),nullable=True))
    op.add_column("teams",sa.Column("notes",sa.Text(),nullable=False,server_default=""))
    op.add_column("players",sa.Column("notes",sa.Text(),nullable=False,server_default=""))
    op.add_column("players",sa.Column("active",sa.Boolean(),nullable=False,server_default=sa.true()))
    for name,type_ in [("home_team_id",sa.String(36)),("away_team_id",sa.String(36)),("primary_team_id",sa.String(36)),("template_id",sa.String(36))]:
        op.add_column("matches",sa.Column(name,type_,nullable=True))
    op.add_column("matches",sa.Column("season",sa.String(40),nullable=False,server_default=""))
    op.add_column("matches",sa.Column("venue",sa.String(160),nullable=False,server_default=""))
    op.add_column("matches",sa.Column("location_type",sa.String(20),nullable=False,server_default="home"))
    op.add_column("matches",sa.Column("home_score",sa.Integer(),nullable=True))
    op.add_column("matches",sa.Column("away_score",sa.Integer(),nullable=True))
    op.create_foreign_key("fk_matches_home_team","matches","teams",["home_team_id"],["id"],ondelete="SET NULL")
    op.create_foreign_key("fk_matches_away_team","matches","teams",["away_team_id"],["id"],ondelete="SET NULL")
    op.create_foreign_key("fk_matches_primary_team","matches","teams",["primary_team_id"],["id"],ondelete="SET NULL")
    op.create_foreign_key("fk_matches_template","matches","templates",["template_id"],["id"],ondelete="SET NULL")
    op.create_index("ix_matches_home_team_id","matches",["home_team_id"]);op.create_index("ix_matches_away_team_id","matches",["away_team_id"])
    op.add_column("events",sa.Column("team_id",sa.String(36),nullable=True))
    op.create_foreign_key("fk_events_team","events","teams",["team_id"],["id"],ondelete="SET NULL");op.create_index("ix_events_team_id","events",["team_id"])
    op.add_column("annotations",sa.Column("coordinate_mode",sa.String(20),nullable=False,server_default="screen"))
    op.add_column("annotations",sa.Column("start",sa.Float(),nullable=True));op.add_column("annotations",sa.Column("end",sa.Float(),nullable=True))
    op.add_column("ai_suggestions",sa.Column("end",sa.Float(),nullable=True))
    op.add_column("ai_suggestions",sa.Column("proposed_team_id",sa.String(36),nullable=True))
    op.add_column("ai_suggestions",sa.Column("proposed_players",sa.JSON(),nullable=False,server_default="[]"))
    op.add_column("ai_suggestions",sa.Column("pitch_position",sa.JSON(),nullable=True))
    op.add_column("ai_suggestions",sa.Column("corrected_data",sa.JSON(),nullable=False,server_default="{}"))
    op.create_foreign_key("fk_ai_suggestion_team","ai_suggestions","teams",["proposed_team_id"],["id"],ondelete="SET NULL")
    op.create_table("match_players",sa.Column("id",sa.String(36),primary_key=True),sa.Column("match_id",sa.String(36),sa.ForeignKey("matches.id",ondelete="CASCADE"),nullable=False),sa.Column("player_id",sa.String(36),sa.ForeignKey("players.id",ondelete="CASCADE"),nullable=False),sa.Column("role",sa.String(40)),sa.Column("starter",sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column("squad_status",sa.String(20),nullable=False,server_default="available"),sa.UniqueConstraint("match_id","player_id",name="uq_match_player"))
    op.create_index("ix_match_players_match_id","match_players",["match_id"]);op.create_index("ix_match_players_player_id","match_players",["player_id"])
    op.create_table("event_players",sa.Column("id",sa.String(36),primary_key=True),sa.Column("event_id",sa.String(36),sa.ForeignKey("events.id",ondelete="CASCADE"),nullable=False),sa.Column("player_id",sa.String(36),sa.ForeignKey("players.id",ondelete="CASCADE"),nullable=False),sa.Column("role",sa.String(40),nullable=False,server_default="actor"),sa.UniqueConstraint("event_id","player_id","role",name="uq_event_player_role"))
    op.create_index("ix_event_players_event_id","event_players",["event_id"]);op.create_index("ix_event_players_player_id","event_players",["player_id"])
    op.create_table("presentations",sa.Column("id",sa.String(36),primary_key=True),sa.Column("name",sa.String(160),nullable=False),sa.Column("notes",sa.Text(),nullable=False,server_default=""),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("presentation_items",sa.Column("id",sa.String(36),primary_key=True),sa.Column("presentation_id",sa.String(36),sa.ForeignKey("presentations.id",ondelete="CASCADE"),nullable=False),sa.Column("event_id",sa.String(36),sa.ForeignKey("events.id",ondelete="SET NULL")),sa.Column("order",sa.Integer(),nullable=False,server_default="0"),sa.Column("kind",sa.String(20),nullable=False,server_default="clip"),sa.Column("title",sa.String(200),nullable=False,server_default=""),sa.Column("notes",sa.Text(),nullable=False,server_default=""),sa.Column("start",sa.Float()),sa.Column("end",sa.Float()))
    op.create_index("ix_presentation_items_presentation_id","presentation_items",["presentation_id"])
    status_type=postgresql.ENUM("queued","running","completed","failed",name="jobstatus",create_type=False)
    op.create_table("tracking_jobs",sa.Column("id",sa.String(36),primary_key=True),sa.Column("video_id",sa.String(36),sa.ForeignKey("videos.id",ondelete="CASCADE"),nullable=False),sa.Column("status",status_type,nullable=False),sa.Column("progress",sa.Integer(),nullable=False,server_default="0"),sa.Column("start",sa.Float(),nullable=False,server_default="0"),sa.Column("end",sa.Float()),sa.Column("config",sa.JSON(),nullable=False,server_default="{}"),sa.Column("error",sa.Text()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_tracking_jobs_video_id","tracking_jobs",["video_id"])
    op.create_table("player_tracks",sa.Column("id",sa.String(36),primary_key=True),sa.Column("tracking_job_id",sa.String(36),sa.ForeignKey("tracking_jobs.id",ondelete="CASCADE"),nullable=False),sa.Column("player_id",sa.String(36),sa.ForeignKey("players.id",ondelete="SET NULL")),sa.Column("anonymous_id",sa.String(80),nullable=False),sa.Column("team_id",sa.String(36),sa.ForeignKey("teams.id",ondelete="SET NULL")),sa.Column("confidence",sa.Float(),nullable=False,server_default="0"),sa.Column("keyframes",sa.JSON(),nullable=False,server_default="[]"),sa.Column("lost_ranges",sa.JSON(),nullable=False,server_default="[]"))
    op.create_index("ix_player_tracks_tracking_job_id","player_tracks",["tracking_job_id"])
    op.create_table("pitch_calibrations",sa.Column("id",sa.String(36),primary_key=True),sa.Column("video_id",sa.String(36),sa.ForeignKey("videos.id",ondelete="CASCADE"),nullable=False),sa.Column("timestamp",sa.Float(),nullable=False,server_default="0"),sa.Column("method",sa.String(20),nullable=False,server_default="manual"),sa.Column("confidence",sa.Float()),sa.Column("image_points",sa.JSON(),nullable=False,server_default="[]"),sa.Column("pitch_points",sa.JSON(),nullable=False,server_default="[]"),sa.Column("homography",sa.JSON()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_pitch_calibrations_video_id","pitch_calibrations",["video_id"])


def downgrade():
    for table in ["pitch_calibrations","player_tracks","tracking_jobs","presentation_items","presentations","event_players","match_players"]:op.drop_table(table)
    for col in ["corrected_data","pitch_position","proposed_players","proposed_team_id","end"]:op.drop_column("ai_suggestions",col)
    for col in ["end","start","coordinate_mode"]:op.drop_column("annotations",col)
    op.drop_column("events","team_id")
    for col in ["away_score","home_score","location_type","venue","season","template_id","primary_team_id","away_team_id","home_team_id"]:op.drop_column("matches",col)
    op.drop_column("players","active");op.drop_column("players","notes")
    op.drop_column("teams","notes");op.drop_column("teams","season");op.drop_column("teams","logo_path")
