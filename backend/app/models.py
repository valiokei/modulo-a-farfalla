import enum
import uuid
from datetime import date, datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def uid() -> str: return str(uuid.uuid4())
def now() -> datetime: return datetime.now(timezone.utc)


class Role(str, enum.Enum): admin = "admin"; coach = "coach"; player = "player"
class JobStatus(str, enum.Enum): queued = "queued"; running = "running"; completed = "completed"; failed = "failed"
class SuggestionStatus(str, enum.Enum): pending = "pending"; accepted = "accepted"; rejected = "rejected"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str]
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.coach)
    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), nullable=True, index=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    team: Mapped["Team | None"] = relationship()
    player: Mapped["Player | None"] = relationship()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    logo_path: Mapped[str | None] = mapped_column(nullable=True)
    season: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    players: Mapped[list["Player"]] = relationship(cascade="all, delete-orphan")


class Player(Base):
    __tablename__ = "players"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    shirt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[str | None] = mapped_column(String(40), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    date: Mapped[date]
    home_team: Mapped[str] = mapped_column(String(120))
    away_team: Mapped[str] = mapped_column(String(120))
    home_team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    away_team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    primary_team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    competition: Mapped[str] = mapped_column(String(120), default="")
    season: Mapped[str] = mapped_column(String(40), default="")
    venue: Mapped[str] = mapped_column(String(160), default="")
    location_type: Mapped[str] = mapped_column(String(20), default="home")
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_id: Mapped[str | None] = mapped_column(ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    attacking_direction: Mapped[str] = mapped_column(String(20), default="left-to-right")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    videos: Mapped[list["Video"]] = relationship(cascade="all, delete-orphan")


class MatchPlayer(Base):
    __tablename__ = "match_players"
    __table_args__ = (UniqueConstraint("match_id","player_id",name="uq_match_player"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    starter: Mapped[bool] = mapped_column(Boolean, default=False)
    squad_status: Mapped[str] = mapped_column(String(20), default="available")
    player: Mapped[Player] = relationship()


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(100), default="Main camera")
    original_name: Mapped[str]
    original_path: Mapped[str]
    proxy_path: Mapped[str | None] = mapped_column(nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(nullable=True)
    mime_type: Mapped[str] = mapped_column(default="video/mp4")
    duration: Mapped[float] = mapped_column(Float, default=0)
    time_offset: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(default="ready")
    processing_progress: Mapped[int] = mapped_column(Integer, default=0)
    analyze_after_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    icon: Mapped[str] = mapped_column(default="•")
    shortcut: Mapped[str | None] = mapped_column(String(16), nullable=True, unique=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pre_roll: Mapped[float] = mapped_column(Float, default=5)
    post_roll: Mapped[float] = mapped_column(Float, default=5)
    metadata_schema: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), index=True)
    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), nullable=True)
    team: Mapped[str | None] = mapped_column(String(120), nullable=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    timestamp: Mapped[float] = mapped_column(Float)
    start: Mapped[float | None] = mapped_column(Float, nullable=True)
    end: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    pitch_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    pitch_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    creator_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    category: Mapped[Category] = relationship()
    player: Mapped[Player | None] = relationship()
    event_players: Mapped[list["EventPlayer"]] = relationship(cascade="all, delete-orphan")


class EventPlayer(Base):
    __tablename__ = "event_players"
    __table_args__ = (UniqueConstraint("event_id","player_id","role",name="uq_event_player_role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40), default="actor")
    player: Mapped[Player] = relationship()


class Annotation(Base):
    __tablename__ = "annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[float]
    shapes: Mapped[list] = mapped_column(JSON, default=list)
    coordinate_mode: Mapped[str] = mapped_column(String(20), default="screen")
    start: Mapped[float | None] = mapped_column(Float, nullable=True)
    end: Mapped[float | None] = mapped_column(Float, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Playlist(Base):
    __tablename__ = "playlists"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    name: Mapped[str]
    event_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Presentation(Base):
    __tablename__ = "presentations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    items: Mapped[list["PresentationItem"]] = relationship(cascade="all, delete-orphan", order_by="PresentationItem.order")


class PresentationItem(Base):
    __tablename__ = "presentation_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    presentation_id: Mapped[str] = mapped_column(ForeignKey("presentations.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(20), default="clip")
    title: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    start: Mapped[float | None] = mapped_column(Float, nullable=True)
    end: Mapped[float | None] = mapped_column(Float, nullable=True)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(unique=True)
    definition: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str]
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AIJob(Base):
    __tablename__ = "ai_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TrackingJob(Base):
    __tablename__ = "tracking_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    start: Mapped[float] = mapped_column(Float, default=0)
    end: Mapped[float | None] = mapped_column(Float, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlayerTrack(Base):
    __tablename__ = "player_tracks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tracking_job_id: Mapped[str] = mapped_column(ForeignKey("tracking_jobs.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), nullable=True)
    anonymous_id: Mapped[str] = mapped_column(String(80))
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    keyframes: Mapped[list] = mapped_column(JSON, default=list)
    lost_ranges: Mapped[list] = mapped_column(JSON, default=list)


class PitchCalibration(Base):
    __tablename__ = "pitch_calibrations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[float] = mapped_column(Float, default=0)
    method: Mapped[str] = mapped_column(String(20), default="manual")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_points: Mapped[list] = mapped_column(JSON, default=list)
    pitch_points: Mapped[list] = mapped_column(JSON, default=list)
    homography: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LeagueCompetition(Base):
    __tablename__ = "league_competitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(240))
    season: Mapped[str] = mapped_column(String(20))
    group_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(240), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("provider", "external_id", "season", name="uq_league_comp"),)


class LeagueStanding(Base):
    __tablename__ = "league_standings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    competition_id: Mapped[str] = mapped_column(ForeignKey("league_competitions.id", ondelete="CASCADE"), index=True)
    external_team_id: Mapped[str] = mapped_column(String(80), index=True)
    team_name: Mapped[str]
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    played: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    goals_for: Mapped[int] = mapped_column(Integer, default=0)
    goals_against: Mapped[int] = mapped_column(Integer, default=0)
    points: Mapped[int] = mapped_column(Integer, default=0)
    yellow_cards: Mapped[int] = mapped_column(Integer, default=0)
    red_cards: Mapped[int] = mapped_column(Integer, default=0)


class LeagueFixture(Base):
    __tablename__ = "league_fixtures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    competition_id: Mapped[str] = mapped_column(ForeignKey("league_competitions.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(80), index=True)
    round_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    match_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    home_team: Mapped[str] = mapped_column(String(160))
    away_team: Mapped[str] = mapped_column(String(160))
    home_external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    away_external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="")
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    home_match_id: Mapped[str | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"), nullable=True)
    away_match_id: Mapped[str | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"), nullable=True)
    __table_args__ = (UniqueConstraint("competition_id", "external_id", name="uq_league_fixture"),)


class ExternalIdentity(Base):
    """Generic external-id -> internal-entity mapping with provenance."""
    __tablename__ = "external_identities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(120), index=True)
    internal_entity_id: Mapped[str] = mapped_column(String(36), index=True)
    external_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    season: Mapped[str | None] = mapped_column(String(20), nullable=True)
    competition_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("provider", "entity_type", "external_id", name="uq_external_identity"),)


class OfficialPlayerStat(Base):
    __tablename__ = "official_player_stats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(40))
    player_external_id: Mapped[str] = mapped_column(String(80), index=True)
    team_external_id: Mapped[str] = mapped_column(String(80), index=True)
    season: Mapped[str] = mapped_column(String(20), default="")
    name: Mapped[str]
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    appearances: Mapped[int] = mapped_column(Integer, default=0)
    minutes: Mapped[int] = mapped_column(Integer, default=0)
    goals: Mapped[int] = mapped_column(Integer, default=0)
    yellow: Mapped[int] = mapped_column(Integer, default=0)
    red: Mapped[int] = mapped_column(Integer, default=0)
    position_hint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    player_id: Mapped[str | None] = mapped_column(ForeignKey("players.id", ondelete="SET NULL"), nullable=True, index=True)


class AISuggestion(Base):
    __tablename__ = "ai_suggestions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ai_job_id: Mapped[str] = mapped_column(ForeignKey("ai_jobs.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[float]
    end: Mapped[float | None] = mapped_column(Float, nullable=True)
    proposed_category: Mapped[str]
    proposed_team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    proposed_players: Mapped[list] = mapped_column(JSON, default=list)
    pitch_position: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float]
    status: Mapped[SuggestionStatus] = mapped_column(Enum(SuggestionStatus), default=SuggestionStatus.pending)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    corrected_data: Mapped[dict] = mapped_column(JSON, default=dict)
    accepted_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)


class Detection(Base):
    __tablename__ = "detections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ai_job_id: Mapped[str] = mapped_column(ForeignKey("ai_jobs.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[float]
    kind: Mapped[str]
    track_id: Mapped[str | None] = mapped_column(nullable=True)
    confidence: Mapped[float]
    bbox: Mapped[list] = mapped_column(JSON)
    pitch_position: Mapped[list | None] = mapped_column(JSON, nullable=True)
