import csv
import io
import json
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .jobs import analyze, export_clip, export_highlight, launch, transcode
from .media import disk_has_space, initialize_storage, remove_video_files, request_encode_cancel, safe_path
from .models import AIJob, AISuggestion, Annotation, Category, Event, EventPlayer, ExternalIdentity, Job, JobStatus, LeagueCompetition, LeagueFixture, LeagueStanding, LeagueTeamMapping, Match, MatchPlayer, OfficialPlayerStat, PitchCalibration, Player, PlayerTrack, Playlist, Presentation, PresentationItem, Role, SuggestionStatus, Team, Template, TrackingJob, User, Video
from .security import admin_user, coach_user, current_user, hash_password, make_token, verify_password
from .action_spotting import CATEGORIES as SPOTTING_CATEGORIES
from .league import pfs as pfs_module
from .league.sync import import_competition, list_competitions, sync_competition_fixtures, sync_fixtures, sync_pibfal, sync_results

DEFAULTS = [
    ("Goal","⚽","g"),("Shot","◎","s"),("Save","🧤","v"),("GK Error","!","e"),("Defensive Error","⚠",None),("Pass","→","p"),("Cross","↗","c"),("1v1","◆","1"),("Set Piece","◈",None),("Corner","⌜","k"),("Free Kick","◉","f"),("Penalty","●",None),("Distribution","⇢","d"),("High Ball","↑","h"),("Note","✎","n")
]
COACH_CATEGORIES = [
    "Possession","Attacking Phase","Defensive Phase","Build-up","Progression","Final Third","Sustained Attack","Defensive Block","High Press","Mid Block","Low Block","Counterattack","Attacking Transition","Defensive Transition","Counterpress","Restart","Stoppage",
    "Forward Pass","Backward Pass","Lateral Pass","Progressive Pass","Through Ball","Line-breaking Pass","Key Pass","Long Pass","Switch of Play","Cutback","Assist","Carry","Progressive Carry","Dribble","Final Third Entry","Penalty Area Entry","Box Entry",
    "Shot on Target","Big Chance","Chance Creation","Header","Post/Bar","Blocked Shot","Off Target",
    "Pressure","Press","Tackle","Interception","Recovery","Turnover Forced","Clearance","Block","Defensive Duel","Aerial Duel","Ground Duel","Second Ball","Error",
    "Ball Recovery","Ball Loss","Miscontrol","Dispossessed","Forced Turnover","Unforced Turnover",
    "Throw-in","Kick-off","Foul","Yellow Card","Red Card","Offside","Substitution","Injury","VAR Decision",
    "Goal Conceded","Catch","Parry","Deflection","Reflex Save","Cross Claim","Punch","Sweeper Action","Short Distribution","Long Distribution","Throw","Goal Kick","Pass Received","Pass Under Pressure"
]
SCHEMAS = {
    "Pass":{"result":["successful","unsuccessful"],"direction":["forward","backward","lateral"],"body_part":["right-foot","left-foot","head","other"],"under_pressure":["yes","no"]},
    "Shot":{"outcome":["goal","saved","blocked","off-target","woodwork"],"body_part":["right-foot","left-foot","head","other"],"assisted":["yes","no"]},
    "Save":{"type":["catch","parry","deflection","1v1","high-ball","reflex"]},
    "Distribution":{"method":["short","long","throw","goal-kick"],"outcome":["success","failure"]},
    "Tackle":{"result":["successful","unsuccessful"]},"Cross":{"result":["successful","unsuccessful"],"delivery_zone":["near-post","central","far-post","edge"]},
    "Corner":{"phase":["attacking","defending"],"delivery":["short","direct"],"outcome":["first-contact","shot","goal","cleared"]},
}
TEMPLATE_CATEGORIES={
    "Quick Match":["Goal","Shot","Save","Pass","Cross","Tackle","Interception","Foul","Corner","Note"],
    "Full Match":["Possession","Build-up","Progression","Final Third","Pass","Progressive Pass","Long Pass","Cross","Carry","Dribble","Shot","Shot on Target","Goal","Pressure","Tackle","Interception","Recovery","Ball Loss","Counterattack","Attacking Transition","Defensive Transition","Corner","Free Kick","Foul","Offside","Note"],
    "Tactical":["Possession","Attacking Phase","Defensive Phase","Build-up","Progression","Final Third","Defensive Block","High Press","Mid Block","Low Block","Counterattack","Attacking Transition","Defensive Transition","Counterpress","Final Third Entry","Penalty Area Entry","Note"],
    "Attacking":["Pass","Progressive Pass","Through Ball","Key Pass","Long Pass","Switch of Play","Cross","Cutback","Carry","Progressive Carry","Dribble","Final Third Entry","Penalty Area Entry","Shot","Shot on Target","Goal","Big Chance","Chance Creation","Note"],
    "Defensive":["Pressure","Press","Counterpress","Tackle","Interception","Recovery","Clearance","Block","Defensive Duel","Aerial Duel","Second Ball","Ball Recovery","Forced Turnover","Defensive Error","Note"],
    "Set Pieces":["Corner","Free Kick","Penalty","Throw-in","Goal Kick","Kick-off","Cross","Shot","Goal","Note"],
    "Goalkeeper":["Save","Goal Conceded","GK Error","1v1","Catch","Parry","Deflection","Reflex Save","High Ball","Cross Claim","Punch","Sweeper Action","Short Distribution","Long Distribution","Throw","Goal Kick","Pass Received","Pass Under Pressure","Note"],
    "Custom":[],
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_storage(); Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == settings.bootstrap_admin_email)):
            db.add(User(email=settings.bootstrap_admin_email.lower(), password_hash=hash_password(settings.bootstrap_admin_password), role=Role.admin))
        existing={c.name for c in db.scalars(select(Category)).all()}
        for i,(name,icon,key) in enumerate(DEFAULTS):
            if name not in existing:db.add(Category(name=name,icon=icon,shortcut=key,order=i,metadata_schema=SCHEMAS.get(name,{})))
            existing.add(name)
        for i,name in enumerate(list(dict.fromkeys(COACH_CATEGORIES + list(SPOTTING_CATEGORIES.values()))),start=len(DEFAULTS)):
            if name not in existing:db.add(Category(name=name,icon="•",shortcut=None,order=i,metadata_schema=SCHEMAS.get(name,{})))
        for name,names in TEMPLATE_CATEGORIES.items():
            if not db.scalar(select(Template).where(Template.name==name)):
                db.add(Template(name=name,definition={"categories":names,"qualifiers":{n:SCHEMAS.get(n,{}) for n in names},"statistics":["overview","passing","attacking","defensive","goalkeeping"]}))
        db.query(Job).filter(Job.status == JobStatus.running).update({Job.status: JobStatus.failed, Job.error: "Server restarted"})
        db.query(AIJob).filter(AIJob.status == JobStatus.running).update({AIJob.status: JobStatus.failed, AIJob.error: "Server restarted"})
        db.commit()
    yield


app = FastAPI(title="Modulo a Farfalla API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=True, allow_methods=["GET","POST","PUT","PATCH","DELETE"], allow_headers=["Content-Type"])


class InModel(BaseModel): model_config = ConfigDict(extra="forbid")
class Login(InModel): email: str; password: str
class UserIn(InModel): email: str | None = None; password: str | None = Field(default=None,min_length=8,max_length=128); role: Role | None = None; player_id: str | None = None; name: str | None = None; team_id: str | None = None
class TeamIn(InModel): name: str = Field(min_length=1,max_length=120); season: str | None = None; notes: str = ""
class PlayerIn(InModel): name: str; shirt_number: int | None = None; position: str | None = None; notes: str = ""; active: bool = True
class MatchPlayerIn(InModel): player_id: str; role: str | None = None; starter: bool = False; squad_status: str = "available"
class MatchIn(InModel):
    date: date; home_team: str = ""; away_team: str = ""; home_team_id: str | None = None; away_team_id: str | None = None; primary_team_id: str | None = None
    competition: str = ""; season: str = ""; venue: str = ""; location_type: str = "home"; home_score: int | None = None; away_score: int | None = None
    template_id: str | None = None; notes: str = ""; attacking_direction: str = "left-to-right"; squad: list[MatchPlayerIn] = []
class CategoryIn(InModel): name: str; icon: str = "•"; shortcut: str | None = None; order: int = 0; enabled: bool = True; pre_roll: float = 5; post_roll: float = 5; metadata_schema: dict = {}
class EventPlayerIn(InModel): player_id: str; role: str = "actor"
class EventIn(InModel): video_id: str; category_id: str; timestamp: float = Field(ge=0); start: float | None = Field(None,ge=0); end: float | None = Field(None,ge=0); player_id: str | None = None; players: list[EventPlayerIn] = []; team: str | None = None; team_id: str | None = None; note: str = ""; tags: list[str] = []; metadata: dict = {}; pitch_x: float | None = Field(None,ge=0,le=1); pitch_y: float | None = Field(None,ge=0,le=1)
class EventPatch(InModel): note: str | None = None; tags: list[str] | None = None; player_id: str | None = None; players: list[EventPlayerIn] | None = None; team: str | None = None; team_id: str | None = None; metadata: dict | None = None; pitch_x: float | None = Field(None,ge=0,le=1); pitch_y: float | None = Field(None,ge=0,le=1); start: float | None = Field(None,ge=0); end: float | None = Field(None,ge=0)
class AnnotationIn(InModel): timestamp: float; shapes: list[dict]; coordinate_mode: str = "screen"; start: float | None = None; end: float | None = None
class PlaylistIn(InModel): name: str; event_ids: list[str]
class ClipOverlay(InModel): header: str = ""; minute: str = ""; team: str = ""; player: str = ""; note: str = ""; pitch_x: float | None = None; pitch_y: float | None = None
class ExportIn(InModel): video_id: str; start: float = Field(allow_inf_nan=False); end: float = Field(allow_inf_nan=False); overlay: ClipOverlay | str | None = None; event_id: str | None = None; include_annotations: bool = True; freeze_seconds: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)
class AIIn(InModel): video_id: str; config: dict = {}
class SuggestionAction(InModel): action: str; category_id: str | None = None; team_id: str | None = None; players: list[EventPlayerIn] = []; timestamp: float | None = None; metadata: dict = {}; note: str = ""
class TemplateIn(InModel): name: str; definition: dict
class CalibrationIn(InModel): timestamp: float = 0; image_points: list[list[float]]; pitch_points: list[list[float]]; homography: list | None = None
class TrackIn(InModel): player_id: str | None = None; anonymous_id: str; team_id: str | None = None; confidence: float = 1; keyframes: list[dict]; lost_ranges: list = []
class TrackingIn(InModel): video_id: str; start: float = 0; end: float | None = None; config: dict = {}; tracks: list[TrackIn] = []
class PresentationItemIn(InModel): event_id: str | None = None; order: int = 0; kind: str = "clip"; title: str = ""; notes: str = ""; start: float | None = None; end: float | None = None
class PresentationIn(InModel): name: str; notes: str = ""; items: list[PresentationItemIn]


def obj(x, **extra):
    private={"password_hash","original_path","proxy_path","thumbnail_path","screenshot_path","logo_path"}
    data = {c.name: getattr(x, c.key) for c in x.__table__.columns if c.name not in private}
    for k,v in list(data.items()):
        if hasattr(v,"value"): data[k]=v.value
        elif hasattr(v,"isoformat"): data[k]=v.isoformat()
        elif k=="result" and isinstance(v,dict): data[k]={key:value for key,value in v.items() if key!="path"}
    data.update(extra); return data


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    # FastAPI's default 422 body has detail as a list of objects, which the SPA
    # rendered as "[object Object]" (e.g. password shorter than 8 chars on user
    # edit). Flatten to a single human-readable string so every client can show it.
    def describe(err: dict) -> str:
        loc = [str(part) for part in err.get("loc", ()) if part != "body"]
        field = " · ".join(loc) if loc else "request"
        return f"{field}: {err.get('msg', 'invalid value')}"
    return JSONResponse(status_code=422, content={"detail": "; ".join(describe(err) for err in exc.errors())})


@app.get("/api/health")
async def health(): return {"status":"ok"}

@app.post("/api/auth/login")
async def login(data: Login, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if not user or not verify_password(data.password, user.password_hash): raise HTTPException(401,"Invalid email or password")
    response.set_cookie("access_token", make_token(user), httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=604800, path="/")
    return obj(user)

@app.post("/api/auth/logout", status_code=204)
async def logout(response: Response): response.delete_cookie("access_token", path="/")

@app.get("/api/auth/me")
async def me(user: User = Depends(current_user)): return obj(user)

@app.post("/api/users")
async def create_user(data: UserIn, db: Session=Depends(get_db), _=Depends(admin_user)):
    email=(data.email or "").strip().lower()
    if "@" not in email: raise HTTPException(422,"Valid email required")
    if not data.password or len(data.password)<8: raise HTTPException(422,"Password must be at least 8 characters")
    if db.scalar(select(User).where(User.email==email)): raise HTTPException(409,"Email already exists")
    if data.player_id and not db.get(Player,data.player_id): raise HTTPException(400,"Invalid player binding")
    if data.team_id and not db.get(Team,data.team_id): raise HTTPException(400,"Invalid team binding")
    user=User(email=email,password_hash=hash_password(data.password),role=data.role or Role.coach,name=(data.name or "").strip() or None,player_id=data.player_id,team_id=data.team_id)
    db.add(user);db.commit();db.refresh(user)
    return obj(user,player=obj(user.player) if user.player else None, team=obj(user.team) if user.team else None)

@app.get("/api/users")
async def list_users(db: Session=Depends(get_db), _=Depends(admin_user)):
    users=db.scalars(select(User).order_by(User.created_at)).all()
    return [obj(u, player=obj(u.player) if u.player else None, team=obj(u.team) if u.team else None) for u in users]

@app.patch("/api/users/{user_id}")
async def update_user(user_id:str,data:UserIn,db:Session=Depends(get_db),me:User=Depends(admin_user)):
    user=db.get(User,user_id)
    if not user: raise HTTPException(404,"User not found")
    fields=data.model_fields_set
    if "email" in fields:
        email=(data.email or "").strip().lower()
        if "@" not in email: raise HTTPException(422,"Valid email required")
        if email!=user.email and db.scalar(select(User).where(User.email==email,User.id!=user.id)): raise HTTPException(409,"Email already exists")
        user.email=email
    if "name" in fields: user.name=(data.name or "").strip() or None
    if "role" in fields and data.role:
        if user.id==me.id and data.role!=Role.admin: raise HTTPException(400,"You cannot remove your own admin role")
        user.role=data.role
    if "player_id" in fields:
        if data.player_id and not db.get(Player,data.player_id): raise HTTPException(400,"Invalid player binding")
        user.player_id=data.player_id
    if "team_id" in fields:
        if data.team_id and not db.get(Team,data.team_id): raise HTTPException(400,"Invalid team binding")
        user.team_id=data.team_id or None
    if data.password:
        if len(data.password)<8: raise HTTPException(422,"Password must be at least 8 characters")
        user.password_hash=hash_password(data.password)
    db.commit();db.refresh(user)
    return obj(user,player=obj(user.player) if user.player else None, team=obj(user.team) if user.team else None)

@app.delete("/api/users/{user_id}",status_code=204)
async def delete_user(user_id:str,db:Session=Depends(get_db),me:User=Depends(admin_user)):
    user=db.get(User,user_id)
    if not user: raise HTTPException(404,"User not found")
    if user.id==me.id: raise HTTPException(400,"You cannot delete your own account")
    if user.role==Role.admin and db.scalar(select(func.count()).select_from(User).where(User.role==Role.admin))<2: raise HTTPException(409,"At least one admin must remain")
    db.execute(update(Event).where(Event.creator_id==user_id).values(creator_id=None))
    db.delete(user);db.commit()

@app.get("/api/teams")
async def teams(db: Session=Depends(get_db), _=Depends(current_user)):
    return [obj(t, players=[obj(p) for p in t.players], has_logo=bool(t.logo_path)) for t in db.scalars(select(Team).order_by(Team.name)).all()]

@app.post("/api/teams")
async def create_team(data: TeamIn, db: Session=Depends(get_db), _=Depends(coach_user)):
    values=data.model_dump();values["name"]=values["name"].strip()
    if db.scalar(select(Team).where(func.lower(Team.name)==values["name"].lower())):
        raise HTTPException(409,f"A team named '{values['name']}' already exists")
    team=Team(**values); db.add(team)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,f"A team named '{values['name']}' already exists") from None
    return obj(team,players=[],has_logo=bool(team.logo_path))

TEAM_CSV_MAX_BYTES=5*1024*1024
TEAM_CSV_MAX_ROWS=2000
TEAM_CSV_REQUIRED={"team_name","player_name"}
TEAM_CSV_OPTIONAL={"season","shirt_number","position","player_notes","team_notes"}

@app.post("/api/teams/import-csv")
async def import_teams_csv(file:UploadFile=File(...),db:Session=Depends(get_db),_=Depends(coach_user)):
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400,"Upload a .csv file")
    raw=await file.read(TEAM_CSV_MAX_BYTES+1)
    if len(raw)>TEAM_CSV_MAX_BYTES:
        raise HTTPException(413,"CSV exceeds the 5 MiB limit")
    try:
        text=raw.decode("utf-8-sig")
        reader=csv.DictReader(io.StringIO(text,newline=""))
        headers={str(h or "").strip().lower() for h in (reader.fieldnames or [])}
        if len(headers) != len(reader.fieldnames or []):
            raise HTTPException(422,"CSV contains duplicate or empty column names")
        missing=TEAM_CSV_REQUIRED-headers
        unknown=headers-(TEAM_CSV_REQUIRED|TEAM_CSV_OPTIONAL)
        if missing or unknown:
            raise HTTPException(422,"CSV headers invalid; required: team_name, player_name; optional: season, shirt_number, position, player_notes, team_notes")
        rows=[]
        for line,row in enumerate(reader,start=2):
            if len(rows)>=TEAM_CSV_MAX_ROWS:
                raise HTTPException(413,"CSV exceeds the 2,000 row limit")
            if row is None or None in row or any(value is None for key,value in row.items() if key is not None):
                raise HTTPException(422,f"CSV row {line}: column count does not match the header")
            value={str(k or "").strip().lower():str(v or "").strip() for k,v in row.items()}
            team_name=value.get("team_name","")
            player_name=value.get("player_name","")
            if not team_name or not player_name:
                raise HTTPException(422,f"CSV row {line}: team_name and player_name are required")
            if len(team_name)>120 or len(player_name)>120:
                raise HTTPException(422,f"CSV row {line}: team/player name exceeds 120 characters")
            if len(value.get("season", ""))>40 or len(value.get("position", ""))>80:
                raise HTTPException(422,f"CSV row {line}: season or position is too long")
            shirt=value.get("shirt_number") or None
            if shirt is not None and (not shirt.isdigit() or int(shirt)>999):
                raise HTTPException(422,f"CSV row {line}: shirt_number must be an integer from 0 to 999")
            rows.append({"team_name":team_name,"season":value.get("season") or None,
                         "player_name":player_name,"shirt_number":int(shirt) if shirt else None,
                         "position":value.get("position") or None,
                         "player_notes":value.get("player_notes","")[:4000],
                         "team_notes":value.get("team_notes","")[:4000],"line":line})
    except UnicodeDecodeError as exc:
        raise HTTPException(400,"CSV must use UTF-8 encoding") from exc
    except csv.Error as exc:
        raise HTTPException(422,"CSV is malformed or contains a field that is too large") from exc
    if not rows:
        raise HTTPException(422,"CSV contains no player rows")
    teams_created=players_created=players_skipped=0
    try:
        team_cache={t.name.strip().casefold():t for t in db.scalars(select(Team)).all()}
        player_keys={(p.team_id,p.name.strip().casefold(),p.shirt_number)
                     for p in db.scalars(select(Player)).all()}
        for row in rows:
            key=row["team_name"].casefold()
            team=team_cache.get(key)
            if not team:
                team=Team(name=row["team_name"],season=row["season"],notes=row["team_notes"])
                db.add(team);db.flush();team_cache[key]=team;teams_created+=1
            elif row["season"] and not team.season:
                team.season=row["season"]
            player_key=(team.id,row["player_name"].casefold(),row["shirt_number"])
            if player_key in player_keys:
                players_skipped+=1;continue
            db.add(Player(team_id=team.id,name=row["player_name"],shirt_number=row["shirt_number"],
                          position=row["position"],notes=row["player_notes"],active=True))
            player_keys.add(player_key);players_created+=1
        db.commit()
    except Exception:
        db.rollback();raise
    return {"ok":True,"teams_created":teams_created,"players_created":players_created,
            "players_skipped":players_skipped,"rows_read":len(rows)}

@app.put("/api/teams/{team_id}")
async def update_team(team_id:str,data:TeamIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    team=db.get(Team,team_id)
    if not team:raise HTTPException(404,"Team not found")
    values=data.model_dump();values["name"]=values["name"].strip()
    if db.scalar(select(Team).where(Team.id!=team.id,func.lower(Team.name)==values["name"].lower())):
        raise HTTPException(409,f"A team named '{values['name']}' already exists")
    for key,value in values.items():setattr(team,key,value)
    try: db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,f"A team named '{values['name']}' already exists") from None
    return obj(team,players=[obj(p) for p in team.players],has_logo=bool(team.logo_path))

TEAM_LOGO_TYPES={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}
TEAM_LOGO_MAX_BYTES=2_000_000

def _team_logo_response(team:Team):
    path=Path(team.logo_path) if team.logo_path else None
    if not path or not path.is_file(): raise HTTPException(404,"Logo not found")
    media={"png":"image/png","jpg":"image/jpeg","webp":"image/webp"}.get(path.suffix.lstrip(".").lower(),"application/octet-stream")
    return FileResponse(path,media_type=media,headers={"Cache-Control":"no-cache"})

def _drop_team_logo(team:Team):
    if team.logo_path: Path(team.logo_path).unlink(missing_ok=True)
    team.logo_path=None

@app.post("/api/teams/{team_id}/logo")
async def upload_team_logo(team_id:str,file:UploadFile=File(...),db:Session=Depends(get_db),_=Depends(coach_user)):
    team=db.get(Team,team_id)
    if not team: raise HTTPException(404,"Team not found")
    ext=TEAM_LOGO_TYPES.get(file.content_type or "")
    if not ext: raise HTTPException(400,"Only PNG, JPEG or WebP images are supported")
    data=await file.read()
    if not data: raise HTTPException(400,"Empty file")
    if len(data)>TEAM_LOGO_MAX_BYTES: raise HTTPException(413,"Logo too large (max 2 MB)")
    _drop_team_logo(team)  # remove a previous file that may carry a different extension
    path=safe_path("logos",f"{team.id}.{ext}")
    path.write_bytes(data)
    team.logo_path=str(path);db.commit()
    return obj(team,players=[obj(p) for p in team.players],has_logo=True)

@app.get("/api/teams/{team_id}/logo")
async def get_team_logo(team_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    team=db.get(Team,team_id)
    if not team: raise HTTPException(404,"Team not found")
    return _team_logo_response(team)

@app.delete("/api/teams/{team_id}/logo",status_code=204)
async def remove_team_logo(team_id:str,db:Session=Depends(get_db),_=Depends(coach_user)):
    team=db.get(Team,team_id)
    if not team: raise HTTPException(404,"Team not found")
    _drop_team_logo(team);db.commit()

@app.delete("/api/teams/{team_id}",status_code=204)
async def delete_team(team_id:str,db:Session=Depends(get_db),_=Depends(coach_user)):
    team=db.get(Team,team_id)
    if not team:raise HTTPException(404,"Team not found")
    _drop_team_logo(team)
    db.delete(team);db.commit()

@app.post("/api/teams/{team_id}/players")
async def create_player(team_id:str,data:PlayerIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    if not db.get(Team,team_id): raise HTTPException(404,"Team not found")
    player=Player(team_id=team_id,**data.model_dump()); db.add(player); db.commit(); return obj(player)

@app.put("/api/players/{player_id}")
async def update_player(player_id:str,data:PlayerIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    player=db.get(Player,player_id)
    if not player:raise HTTPException(404,"Player not found")
    for key,value in data.model_dump().items():setattr(player,key,value)
    db.commit();return obj(player)

@app.delete("/api/players/{player_id}",status_code=204)
async def delete_player(player_id:str,db:Session=Depends(get_db),_=Depends(coach_user)):
    player=db.get(Player,player_id)
    if not player:raise HTTPException(404,"Player not found")
    db.delete(player);db.commit()

@app.get("/api/matches")
async def matches(db:Session=Depends(get_db),user:User=Depends(current_user)):
    rows=db.scalars(select(Match).order_by(Match.date.desc())).unique().all()
    if user.role.value == "coach" and user.team_id:
        rows=[m for m in rows if (m.home_team_id==user.team_id) or (m.away_team_id==user.team_id)]
    return [obj(m,videos=[video_obj(v,db) for v in m.videos]) for m in rows]

@app.get("/api/me/player-stats")
async def my_player_stats(db:Session=Depends(get_db), user:User=Depends(current_user)):
    """Read-only summary for a bound player account."""
    if user.role.value != "player" or not user.player_id:
        raise HTTPException(403,"Player account with a bound player required")
    player=db.get(Player,user.player_id)
    if not player: raise HTTPException(404,"Bound player not found")
    team=db.get(Team,player.team_id) if player.team_id else None
    matches_rows=db.scalars(select(Match).where((Match.home_team_id==team.id)|(Match.away_team_id==team.id))).all() if team else []
    stats=db.scalars(select(Event).where(Event.player_id==player.id)).all()
    via_roles=db.scalars(select(Event).join(EventPlayer,EventPlayer.event_id==Event.id).where(EventPlayer.player_id==player.id)).all()
    stats={e.id:e for e in [*stats,*via_roles]}.values()
    per_category={}
    for e in stats:
        if e.category.name in per_category: per_category[e.category.name]+=1
        else: per_category[e.category.name]=1
    return {
        "player":obj(player),
        "team":obj(team) if team else None,
        "matches":len(matches_rows),
        "events":len(stats),
        "by_category":per_category,
    }


# ---- League / Official data (coach+ role) ----

@app.get("/api/league/competitions")
async def league_competitions(season:str="2026",_=Depends(coach_user)):
    try:
        return [{"id": c.id, "name": c.name, "season": c.season, "slug": c.slug} for c in list_competitions("pfs", season)]
    except Exception as exc:
        raise HTTPException(502, f"Provider not available: {exc}")

@app.get("/api/league/teams")
async def league_teams(competition_id:str,season:str="2026",_=Depends(coach_user)):
    try:
        prov = pfs_module.PragueFootballAssociationProvider(season=season)
        return [t.__dict__ for t in prov.get_teams(competition_id)]
    except Exception as exc:
        raise HTTPException(502, f"Provider not available: {exc}")

@app.get("/api/league/roster")
async def league_roster(team_id:str,season:str="2026",competition_id:str|None=None,_=Depends(coach_user)):
    try:
        prov = pfs_module.PragueFootballAssociationProvider(season=season)
        return [r.__dict__ for r in prov.get_roster(team_id, competition_id=competition_id)]
    except Exception as exc:
        raise HTTPException(502, f"Provider not available: {exc}")

@app.post("/api/league/import")
async def league_import(competition_id:str,season:str="2026",map_team:str="{}",import_rosters:bool=False,_=Depends(coach_user)):
    try:
        import json
        mapping = json.loads(map_team) if map_team else {}
        if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
            raise HTTPException(422, "Invalid team mapping")
        result = import_competition("pfs", season, competition_id, map_team=mapping,
                                    import_rosters=import_rosters)
        return {"ok": True, "competition": {"id": result.id, "name": result.name,
                                            "teams": len(result.teams)}}
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Provider not available: {exc}")

@app.get("/api/league/mappings")
async def league_mappings(competition_id:str,season:str="2026",_=Depends(coach_user),db:Session=Depends(get_db)):
    rows=db.scalars(select(LeagueTeamMapping).where(
        LeagueTeamMapping.provider=="pfs", LeagueTeamMapping.season==season,
        LeagueTeamMapping.competition_external_id==competition_id)).all()
    return {row.team_external_id:row.local_team_id for row in rows}

@app.get("/api/league/legacy-mappings")
async def league_legacy_mappings(_=Depends(coach_user),db:Session=Depends(get_db)):
    rows=db.scalars(select(ExternalIdentity).where(
        ExternalIdentity.provider=="pfs",ExternalIdentity.entity_type=="team")).all()
    return [row.external_id for row in rows]

@app.get("/api/league/synced")
async def league_synced(_=Depends(coach_user)):
    db = SessionLocal()
    try:
        comps = db.scalars(select(LeagueCompetition)).all()
        return [
            obj(c, standings=[obj(s) for s in db.scalars(select(LeagueStanding).where(
                LeagueStanding.competition_id == c.id)).all()])
            for c in comps
        ]
    finally:
        db.close()


@app.post("/api/league/results/sync")
async def league_results_sync(team_external_id: str, season: str = "2026",
                              competition_id: str | None = None,
                              _=Depends(coach_user)):
    try:
        result = sync_results("pfs", season, team_external_id=team_external_id,
                              competition_id=competition_id)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(502, f"Provider not available: {exc}")


@app.get("/api/league/results")
async def league_results(season: str = "2026", _=Depends(coach_user)):
    db = SessionLocal()
    try:
        rows = db.scalars(select(LeagueFixture)
                          .join(LeagueCompetition, LeagueCompetition.id == LeagueFixture.competition_id)
                          .where(LeagueCompetition.season == season)
                          .order_by(LeagueFixture.match_date.desc())).all()
        return [obj(r) for r in rows]
    finally:
        db.close()


@app.post("/api/league/fixtures/sync")
async def league_fixtures_sync(competition_slug: str, season: str = "2026",
                               competition_id: str | None = None,
                               _=Depends(coach_user)):
    try:
        result = sync_fixtures("pfs", season, competition_slug=competition_slug,
                               competition_id=competition_id)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(502, f"Provider not available: {exc}")


@app.get("/api/league/fixtures")
async def league_fixtures(season: str = "2026", status: str | None = None,
                          competition: str | None = None, _=Depends(coach_user)):
    db = SessionLocal()
    try:
        stmt = select(LeagueFixture).join(LeagueCompetition, LeagueCompetition.id == LeagueFixture.competition_id)
        if season:
            stmt = stmt.where(LeagueCompetition.season == season)
        if status:
            stmt = stmt.where(LeagueFixture.status == status)
        if competition:
            stmt = stmt.where(LeagueCompetition.external_id == competition)
        rows = db.scalars(stmt.order_by(LeagueFixture.match_date.desc())).all()
        return [obj(r) for r in rows]
    finally:
        db.close()


@app.post("/api/league/pibfal/sync")
async def league_pibfal_sync(season_label: str = "2026/27 Championship",
                             season_tag: str = "2026/27",
                             _=Depends(coach_user)):
    try:
        result = sync_pibfal(season_label=season_label, season_tag=season_tag)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(502, f"Provider not available: {exc}")



@app.post("/api/league/competition/sync")
async def league_competition_fixtures_sync(competition_external: str, slug: str = "",
                                           season: str = "2026", replace_existing: bool = False,
                                           rounds: str = "", _=Depends(coach_user)):
    try:
        rounds_list = [int(x) for x in rounds.split(",") if x.strip().isdigit()] if rounds else None
        if slug:
            result = sync_competition_fixtures("pfs", season, competition_external=competition_external,
                                               competition_slug=slug, replace_existing=replace_existing,
                                               rounds=rounds_list)
        else:
            # derive slug from known mappings
            slug_by_id = {"752": "752-9-liga-a5b-3-trida-skupina-b-muzu",
                          "753": "753-9-liga-a5c-3-trida-skupina-c-muzu"}
            result = sync_competition_fixtures("pfs", season, competition_external=competition_external,
                                               competition_slug=slug_by_id.get(competition_external, competition_external),
                                               replace_existing=replace_existing, rounds=rounds_list)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(502, f"Provider not available: {exc}")

@app.get("/api/league/pibfal/fixtures")
async def league_pibfal_fixtures(season_tag: str = "2026/27", _=Depends(coach_user)):
    db = SessionLocal()
    try:
        rows = db.scalars(select(LeagueFixture)
                          .join(LeagueCompetition, LeagueCompetition.id == LeagueFixture.competition_id)
                          .where(LeagueCompetition.provider == "pibfal",
                                 LeagueCompetition.season == season_tag)
                          .order_by(LeagueFixture.match_date)).all()
        return [obj(r) for r in rows]
    finally:
        db.close()


@app.get("/api/league/standings/top")
async def league_standings_top(competition_id: str, _=Depends(coach_user)):
    db = SessionLocal()
    try:
        # Accept either the internal Competition row id or the provider external id
        comp = db.get(LeagueCompetition, competition_id)
        if not comp:
            comp = db.scalar(select(LeagueCompetition).where(
                LeagueCompetition.external_id == competition_id))
        if not comp:
            return []
        rows = db.scalars(select(LeagueStanding)
                          .where(LeagueStanding.competition_id == comp.id)
                          .order_by(LeagueStanding.position)).all()
        return [obj(r) for r in rows]
    finally:
        db.close()

@app.post("/api/matches")
async def create_match(data:MatchIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    values=data.model_dump();squad=values.pop("squad")
    home=db.get(Team,values.get("home_team_id")) if values.get("home_team_id") else None;away=db.get(Team,values.get("away_team_id")) if values.get("away_team_id") else None
    if home:values["home_team"]=home.name
    if away:values["away_team"]=away.name
    if not values["home_team"] or not values["away_team"]:raise HTTPException(400,"Home and away teams are required")
    if not values.get("template_id"):
        template=db.scalar(select(Template).where(Template.name=="Full Match"));values["template_id"]=template.id if template else None
    m=Match(**values);db.add(m);db.flush()
    for entry in squad:db.add(MatchPlayer(match_id=m.id,**entry))
    db.commit();return match_obj(m,db)

def video_obj(video:Video,db:Session):
    ai_job=db.scalar(select(AIJob).where(AIJob.video_id==video.id).order_by(AIJob.created_at.desc()))
    return obj(video,ai_job_id=ai_job.id if ai_job else None,ai_status=ai_job.status.value if ai_job else None,ai_progress=ai_job.progress if ai_job else 0,ai_error=ai_job.error if ai_job else None)


def match_obj(m:Match,db:Session):
    squad=db.scalars(select(MatchPlayer).options(joinedload(MatchPlayer.player)).where(MatchPlayer.match_id==m.id)).all()
    template=db.get(Template,m.template_id) if m.template_id else None
    return obj(m,videos=[video_obj(v,db) for v in m.videos],squad=[obj(x,player=obj(x.player)) for x in squad],template=obj(template) if template else None)

@app.get("/api/matches/{match_id}")
async def get_match(match_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    m=db.get(Match,match_id)
    if not m: raise HTTPException(404,"Match not found")
    return match_obj(m,db)

@app.put("/api/matches/{match_id}")
async def update_match(match_id:str,data:MatchIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    m=db.get(Match,match_id)
    if not m: raise HTTPException(404,"Match not found")
    values=data.model_dump();squad=values.pop("squad")
    for k,v in values.items(): setattr(m,k,v)
    home=db.get(Team,m.home_team_id) if m.home_team_id else None;away=db.get(Team,m.away_team_id) if m.away_team_id else None
    if home:m.home_team=home.name
    if away:m.away_team=away.name
    db.query(MatchPlayer).filter(MatchPlayer.match_id==m.id).delete()
    for entry in squad:db.add(MatchPlayer(match_id=m.id,**entry))
    db.commit(); return match_obj(m,db)

@app.delete("/api/matches/{match_id}",status_code=204)
async def delete_match(match_id:str,db:Session=Depends(get_db),_=Depends(coach_user)):
    m=db.get(Match,match_id)
    if not m: raise HTTPException(404,"Match not found")
    # Stop any in-flight FFmpeg encode for these videos before their rows go
    # away; otherwise the worker would commit onto deleted rows and leave an
    # orphan FFmpeg process running.
    for v in m.videos:
        request_encode_cancel(v.id)
        remove_video_files(v.original_path,v.proxy_path,v.thumbnail_path)
    db.delete(m); db.commit()

ALLOWED_TYPES={"video/mp4","video/quicktime","video/x-matroska","video/webm","application/octet-stream"}
@app.post("/api/matches/{match_id}/videos")
async def upload_video(match_id:str,file:UploadFile=File(...),label:str=Form("Main camera"),time_offset:float=Form(0),analyze_ai:bool=Form(False),db:Session=Depends(get_db),_=Depends(coach_user)):
    if analyze_ai and not settings.ai_enabled:
        raise HTTPException(503, "AI runtime is not included in this desktop build; disable automatic AI analysis")
    if not db.get(Match,match_id): raise HTTPException(404,"Match not found")
    if file.content_type not in ALLOWED_TYPES: raise HTTPException(415,"Unsupported video type")
    video=Video(match_id=match_id,label=label[:100],time_offset=time_offset,original_name=Path(file.filename or "video").name[:255],original_path="",mime_type=file.content_type or "video/mp4",status="uploading",processing_progress=0,analyze_after_processing=analyze_ai)
    db.add(video); db.flush(); target=safe_path("originals",f"{video.id}{Path(video.original_name).suffix.lower()[:8]}"); video.original_path=str(target)
    size=0
    try:
        with target.open("xb") as out:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>settings.max_upload_gb*1024**3: raise HTTPException(413,"Upload too large")
                if not disk_has_space(len(chunk)): raise HTTPException(507,"Not enough disk space")
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True); db.rollback(); raise
    video.status="queued"; db.commit(); launch(transcode,video.id)
    return obj(video)

def ranged_file(path:Path,request:Request,media_type:str):
    if not path.exists(): raise HTTPException(404,"Media missing")
    size=path.stat().st_size; header=request.headers.get("range")
    match=re.match(r"bytes=(\d*)-(\d*)",header) if header else None
    if header and not match: raise HTTPException(416,"Invalid range")
    start=int(match.group(1) or 0) if match else 0; end=min(int(match.group(2) or size-1),size-1) if match else size-1
    if start>=size or end<start: raise HTTPException(416,"Range not satisfiable")
    async def body():
        with path.open("rb") as f:
            f.seek(start); left=end-start+1
            while left:
                chunk=f.read(min(1024*1024,left))
                if not chunk: break
                left-=len(chunk); yield chunk
    headers={"Content-Length":str(end-start+1),"Accept-Ranges":"bytes"}
    if match: headers["Content-Range"]=f"bytes {start}-{end}/{size}"
    return StreamingResponse(body(),status_code=206 if match else 200,media_type=media_type,headers=headers)

@app.get("/api/videos/{video_id}/stream")
async def stream_video(video_id:str,request:Request,db:Session=Depends(get_db),_=Depends(current_user)):
    v=db.get(Video,video_id)
    if not v or v.status!="ready": raise HTTPException(404,"Video not ready")
    return ranged_file(Path(v.proxy_path or v.original_path),request,"video/mp4")

@app.patch("/api/videos/{video_id}")
async def update_video(video_id:str,label:str|None=None,time_offset:float|None=None,db:Session=Depends(get_db),_=Depends(coach_user)):
    v=db.get(Video,video_id)
    if not v: raise HTTPException(404,"Video not found")
    if label is not None: v.label=label[:100]
    if time_offset is not None: v.time_offset=time_offset
    db.commit(); return obj(v)

@app.get("/api/categories")
async def categories(db:Session=Depends(get_db),_=Depends(current_user)): return [obj(c) for c in db.scalars(select(Category).order_by(Category.order)).all()]

@app.post("/api/categories")
async def create_category(data:CategoryIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    c=Category(**data.model_dump()); db.add(c); db.commit(); return obj(c)

@app.put("/api/categories/{category_id}")
async def update_category(category_id:str,data:CategoryIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    c=db.get(Category,category_id)
    if not c: raise HTTPException(404,"Category not found")
    for k,v in data.model_dump().items(): setattr(c,k,v)
    db.commit(); return obj(c)

def event_obj(e:Event):
    participants=[{"id":ep.id,"role":ep.role,"player":obj(ep.player)} for ep in e.event_players]
    return obj(e,metadata=e.metadata_,category=obj(e.category),player=obj(e.player) if e.player else None,players=participants)

@app.get("/api/matches/{match_id}/events")
async def events(match_id:str,category:str|None=None,player:str|None=None,team:str|None=None,tag:str|None=None,q:str|None=None,include_suggestions:bool=False,ai_only:bool=False,db:Session=Depends(get_db),_=Depends(current_user)):
    stmt=select(Event).options(joinedload(Event.category),joinedload(Event.player),joinedload(Event.event_players).joinedload(EventPlayer.player)).where(Event.match_id==match_id)
    if category: stmt=stmt.where(Event.category_id==category)
    if player: stmt=stmt.where(Event.player_id==player)
    if team: stmt=stmt.where(Event.team==team)
    if q: stmt=stmt.where(Event.note.ilike(f"%{q[:100]}%"))
    rows=db.scalars(stmt.order_by(Event.timestamp)).unique().all()
    if tag: rows=[e for e in rows if tag in e.tags]
    result=[event_obj(e) for e in rows]
    if include_suggestions or ai_only:
        suggestions=[suggestion_obj(s, db) for s in timeline_suggestions(db, match_id)]
        if not ai_only:
            result += suggestions
            result.sort(key=lambda x: x.get("timestamp") or 0)
        else:
            return suggestions
    return result


def timeline_suggestions(db:Session, match_id:str, cap:int = 300) -> list[AISuggestion]:
    """Best subset of AI proposals for the timeline so huge model output stays responsive.

    Accepted proposals are always included; the remaining slots go to the most
    confident pending candidates (confidence is low across the whole video, so
    the user still sees representative actions plus every confirmed one).
    """
    all_rows=match_suggestions(db, match_id)
    if len(all_rows) <= cap:
        return all_rows
    accepted=[s for s in all_rows if s.status == SuggestionStatus.accepted]
    pending=[s for s in all_rows if s.status != SuggestionStatus.accepted]
    pending.sort(key=lambda s: s.confidence, reverse=True)
    keep=pending[: max(0, cap - len(accepted))] + accepted
    keep.sort(key=lambda s: s.timestamp)
    return keep

def match_suggestions(db:Session, match_id:str) -> list[AISuggestion]:
    video_ids=db.scalars(select(Video.id).where(Video.match_id==match_id)).all()
    if not video_ids: return []
    job=db.scalar(select(AIJob).where(AIJob.video_id.in_(video_ids)).order_by(AIJob.created_at.desc()).limit(1))
    if not job: return []
    return list(db.scalars(select(AISuggestion).where(AISuggestion.ai_job_id==job.id,AISuggestion.status.in_([SuggestionStatus.pending,SuggestionStatus.accepted])).order_by(AISuggestion.timestamp)))

def suggestion_obj(s:AISuggestion, db:Session):
    proposed_players=s.proposed_players or []
    players=[]
    for participant in proposed_players:
        if isinstance(participant,dict) and participant.get("player_id"):
            p=db.get(Player,participant["player_id"])
            if p: players.append({"id":participant.get("id"),"role":participant.get("role","actor"),"player":obj(p)})
    corrected=s.corrected_data or {}
    category=None
    category_id=corrected.get("category_id")
    if category_id: category=db.get(Category,category_id)
    if not category: category=db.scalar(select(Category).where(Category.name==s.proposed_category))
    pitch=s.pitch_position
    timestamp=s.timestamp
    if corrected.get("timestamp") is not None: timestamp=corrected["timestamp"]
    job=db.get(AIJob,s.ai_job_id)
    video=db.get(Video,job.video_id) if job else None
    return {
        "id":s.id,
        "match_id":video.match_id if video else None,
        "video_id":video.id if video else None,
        "category_id":category.id if category else None,
        "category":obj(category) if category else {"id":"","name":s.proposed_category,"icon":"✨"},
        "timestamp":timestamp,
        "start":s.end or (timestamp-(category.pre_roll if category else 5)),
        "end":s.end or (timestamp+(category.post_roll if category else 5)),
        "note":(corrected.get("note") or s.proposed_category),
        "tags":["ai-assistant"],
        "team_id":corrected.get("team_id",s.proposed_team_id),
        "team":None,
        "player":None,
        "players":players,
        "pitch_x":pitch[0] if pitch and len(pitch)>0 else None,
        "pitch_y":pitch[1] if pitch and len(pitch)>1 else None,
        "metadata":{"confidence":s.confidence,**(corrected.get("metadata") or {})},
        "ai":True,
        "suggestion_status":s.status.value,
        "accepted_event_id":s.accepted_event_id,
    }

@app.post("/api/matches/{match_id}/events")
async def create_event(match_id:str,data:EventIn,db:Session=Depends(get_db),user:User=Depends(coach_user)):
    video=db.get(Video,data.video_id); category=db.get(Category,data.category_id)
    if not video or video.match_id!=match_id or not category: raise HTTPException(400,"Invalid video or category")
    active_ai=db.scalar(select(AIJob.id).where(AIJob.video_id==video.id,AIJob.status.in_([JobStatus.queued,JobStatus.running])).limit(1))
    if active_ai:raise HTTPException(409,"AI analysis is running; event creation is locked until it completes")
    values=data.model_dump(); metadata=values.pop("metadata");players=values.pop("players")
    if values.get("start") is not None and values.get("end") is not None and values["end"]<=values["start"]: raise HTTPException(400,"Invalid event window: end must be greater than start")
    if values.get("team_id"):
        team=db.get(Team,values["team_id"])
        if not team:raise HTTPException(400,"Invalid team")
        values["team"]=team.name
    e=Event(match_id=match_id,creator_id=user.id,metadata_=metadata,**values)
    if e.start is None: e.start=max(video.time_offset,e.timestamp-category.pre_roll)
    if e.end is None: e.end=min(video.time_offset+video.duration if video.duration else e.timestamp+category.post_roll,e.timestamp+category.post_roll)
    db.add(e);db.flush()
    for participant in players:
        if db.get(Player,participant["player_id"]):db.add(EventPlayer(event_id=e.id,**participant))
    db.commit();return event_obj(e)

@app.patch("/api/events/{event_id}")
async def update_event(event_id:str,data:EventPatch,db:Session=Depends(get_db),_=Depends(coach_user)):
    e=db.get(Event,event_id)
    if not e: raise HTTPException(404,"Event not found")
    values=data.model_dump(exclude_unset=True);players=values.pop("players",None)
    new_start=values.get("start",e.start);new_end=values.get("end",e.end)
    if new_start is not None and new_end is not None and new_end<=new_start: raise HTTPException(400,"Invalid event window: end must be greater than start")
    if "metadata" in values: e.metadata_=values.pop("metadata")
    for k,v in values.items(): setattr(e,k,v)
    if e.team_id:
        team=db.get(Team,e.team_id);e.team=team.name if team else e.team
    if players is not None:
        db.query(EventPlayer).filter(EventPlayer.event_id==e.id).delete()
        for participant in players:
            if db.get(Player,participant["player_id"]):db.add(EventPlayer(event_id=e.id,**participant))
    db.commit(); return event_obj(e)

@app.delete("/api/events/{event_id}",status_code=204)
async def delete_event(event_id:str,db:Session=Depends(get_db),_=Depends(coach_user)):
    e=db.get(Event,event_id)
    if not e: raise HTTPException(404,"Event not found")
    db.delete(e); db.commit()

@app.get("/api/events/{event_id}/annotations")
async def annotations(event_id:str,db:Session=Depends(get_db),_=Depends(current_user)): return [obj(a) for a in db.scalars(select(Annotation).where(Annotation.event_id==event_id).order_by(Annotation.created_at.desc(),Annotation.id.desc())).all()]

@app.post("/api/events/{event_id}/annotations")
async def add_annotation(event_id:str,data:AnnotationIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    if not db.get(Event,event_id): raise HTTPException(404,"Event not found")
    a=Annotation(event_id=event_id,**data.model_dump()); db.add(a); db.commit(); return obj(a)

@app.put("/api/annotations/{annotation_id}")
async def update_annotation(annotation_id:str,data:AnnotationIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    a=db.get(Annotation,annotation_id)
    if not a: raise HTTPException(404,"Annotation not found")
    a.timestamp=data.timestamp;a.shapes=data.shapes;a.start=data.start;a.end=data.end;a.coordinate_mode=data.coordinate_mode;db.commit();return obj(a)

@app.get("/api/matches/{match_id}/playlists")
async def playlists(match_id:str,db:Session=Depends(get_db),_=Depends(current_user)): return [obj(p) for p in db.scalars(select(Playlist).where(Playlist.match_id==match_id)).all()]

@app.post("/api/matches/{match_id}/playlists")
async def add_playlist(match_id:str,data:PlaylistIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    valid=set(db.scalars(select(Event.id).where(Event.match_id==match_id)).all())
    if not set(data.event_ids)<=valid: raise HTTPException(400,"Playlist contains invalid event")
    p=Playlist(match_id=match_id,**data.model_dump());db.add(p);db.commit();return obj(p)

@app.post("/api/playlists/{playlist_id}/export")
async def export_playlist(playlist_id:str,db:Session=Depends(get_db),_=Depends(coach_user)):
    playlist=db.get(Playlist,playlist_id)
    if not playlist:raise HTTPException(404,"Playlist not found")
    job=Job(kind="highlight",payload={"event_ids":playlist.event_ids,"name":playlist.name});db.add(job);db.commit();launch(export_highlight,job.id);return obj(job)

@app.post("/api/exports/clip")
async def clip(data:ExportIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    if not db.get(Video,data.video_id): raise HTTPException(404,"Video not found")
    if data.event_id:
        event=db.get(Event,data.event_id)
        if not event or event.video_id!=data.video_id: raise HTTPException(400,"Event does not belong to this video")
        # Event clips always cover the window saved on the event (start-end): the
        # coach-set interval is authoritative over any ad-hoc client seconds.
        if event.start is not None and event.end is not None:
            data.start,data.end=event.start,event.end
    if data.end <= data.start or (data.start < 0 and not data.event_id): raise HTTPException(400,"Invalid clip range")
    j=Job(kind="clip",payload=data.model_dump());db.add(j);db.commit();launch(export_clip,j.id);return obj(j)

@app.get("/api/jobs/{job_id}")
async def get_job(job_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    j=db.get(Job,job_id)
    if not j: raise HTTPException(404,"Job not found")
    return obj(j)

@app.get("/api/jobs/{job_id}/download")
async def download_job(job_id:str,request:Request,db:Session=Depends(get_db),_=Depends(current_user)):
    j=db.get(Job,job_id)
    if not j or j.status!=JobStatus.completed: raise HTTPException(404,"Export not ready")
    path=Path(j.result["path"])
    if not path.exists() or path.parent not in [settings.storage_root/"clips",settings.storage_root/"exports"]: raise HTTPException(404,"Export missing")
    return ranged_file(path,request,"video/mp4")

@app.get("/api/matches/{match_id}/export.csv")
async def export_csv(match_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    rows=db.scalars(select(Event).options(joinedload(Event.category),joinedload(Event.player)).where(Event.match_id==match_id).order_by(Event.timestamp)).all()
    out=io.StringIO();writer=csv.writer(out);writer.writerow(["id","timestamp","start","end","category","player","team","note","tags","pitch_x","pitch_y"])
    for e in rows: writer.writerow([e.id,e.timestamp,e.start,e.end,e.category.name,e.player.name if e.player else "",e.team or "",e.note,"|".join(e.tags),e.pitch_x,e.pitch_y])
    return Response(out.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="events-{match_id}.csv"'})

@app.get("/api/matches/{match_id}/export.json")
async def export_json(match_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    match=db.get(Match,match_id)
    if not match: raise HTTPException(404,"Match not found")
    ev=db.scalars(select(Event).options(joinedload(Event.category),joinedload(Event.player)).where(Event.match_id==match_id)).all()
    anns=db.scalars(select(Annotation).join(Event).where(Event.match_id==match_id)).all()
    return {"version":1,"match":obj(match),"videos":[obj(v) for v in match.videos],"events":[event_obj(e) for e in ev],"annotations":[obj(a) for a in anns]}


@app.post("/api/matches/{match_id}/export.highlight")
async def export_match_highlight(match_id:str,db:Session=Depends(get_db),_=Depends(coach_user)):
    if not db.get(Match,match_id): raise HTTPException(404,"Match not found")
    event_ids=[e.id for e in db.scalars(select(Event).where(Event.match_id==match_id).order_by(Event.timestamp)).all()]
    if not event_ids: raise HTTPException(400,"Match has no events to compile")
    job=Job(kind="highlight",payload={"event_ids":event_ids,"name":"match-highlight","overlay":True});db.add(job);db.commit();launch(export_highlight,job.id);return obj(job)

def calculate_stats(events:list[Event]):
    groups:dict[str,list[Event]]={}
    for event in events:groups.setdefault(event.category.name,[]).append(event)
    ids=lambda *names:[e.id for name in names for e in groups.get(name,[])]
    count=lambda *names:len(ids(*names))
    successful=lambda names:[e.id for name in names for e in groups.get(name,[]) if e.metadata_.get("result") in ("successful","success","won") or e.metadata_.get("outcome") in ("successful","success")]
    saves=count("Save");conceded=count("Goal Conceded");faced=saves+conceded
    passes=ids("Pass","Forward Pass","Backward Pass","Lateral Pass","Progressive Pass","Through Ball","Line-breaking Pass","Key Pass","Long Pass","Switch of Play")
    pass_success=successful(["Pass","Forward Pass","Backward Pass","Lateral Pass","Progressive Pass","Through Ball","Line-breaking Pass","Key Pass","Long Pass","Switch of Play"])
    shots=ids("Shot","Shot on Target","Goal","Blocked Shot","Off Target","Post/Bar")
    on_target=ids("Shot on Target","Goal")+[e.id for e in groups.get("Shot",[]) if e.metadata_.get("outcome") in ("goal","saved")]
    possessions=groups.get("Possession",[]);duration=sum(max(0,(e.end or e.timestamp)-(e.start or e.timestamp)) for e in possessions)
    rows=[
        ("goalkeeping","shots faced",faced,ids("Save","Goal Conceded"),"manual"),("goalkeeping","saves",saves,ids("Save"),"manual"),("goalkeeping","goals conceded",conceded,ids("Goal Conceded"),"manual"),("goalkeeping","save %",round(saves/faced*100,1) if faced else 0,ids("Save","Goal Conceded"),"calculated"),
        ("overview","goals",count("Goal"),ids("Goal"),"manual"),("overview","shots",len(set(shots)),list(dict.fromkeys(shots)),"manual"),("overview","shots on target",len(set(on_target)),list(dict.fromkeys(on_target)),"calculated"),("overview","corners",count("Corner"),ids("Corner"),"manual"),("overview","free kicks",count("Free Kick"),ids("Free Kick"),"manual"),("overview","fouls",count("Foul"),ids("Foul"),"manual"),("overview","offsides",count("Offside"),ids("Offside"),"manual"),("overview","cards",count("Yellow Card","Red Card"),ids("Yellow Card","Red Card"),"manual"),
        ("passing","passes",len(passes),passes,"manual"),("passing","completed passes",len(pass_success),pass_success,"manual"),("passing","pass completion %",round(len(pass_success)/len(passes)*100,1) if passes else 0,passes,"calculated"),("passing","progressive passes",count("Progressive Pass"),ids("Progressive Pass"),"manual"),("passing","long passes",count("Long Pass"),ids("Long Pass"),"manual"),("passing","key passes",count("Key Pass"),ids("Key Pass"),"manual"),("passing","crosses",count("Cross"),ids("Cross"),"manual"),
        ("attacking","conversion rate",round(count("Goal")/len(set(shots))*100,1) if shots else 0,list(dict.fromkeys(shots)),"calculated"),("attacking","final-third entries",count("Final Third Entry"),ids("Final Third Entry"),"manual"),("attacking","penalty-area entries",count("Penalty Area Entry","Box Entry"),ids("Penalty Area Entry","Box Entry"),"manual"),
        ("defensive","tackles",count("Tackle"),ids("Tackle"),"manual"),("defensive","interceptions",count("Interception"),ids("Interception"),"manual"),("defensive","recoveries",count("Recovery","Ball Recovery"),ids("Recovery","Ball Recovery"),"manual"),("defensive","clearances",count("Clearance"),ids("Clearance"),"manual"),("defensive","blocks",count("Block"),ids("Block"),"manual"),("transition","counterpresses",count("Counterpress"),ids("Counterpress"),"manual"),("transition","turnovers",count("Ball Loss","Forced Turnover","Unforced Turnover"),ids("Ball Loss","Forced Turnover","Unforced Turnover"),"manual"),
        ("possession","possessions",len(possessions),[e.id for e in possessions],"manual"),("possession","average possession duration",round(duration/len(possessions),1) if possessions else 0,[e.id for e in possessions],"calculated"),
        ("goalkeeping","1v1",count("1v1"),ids("1v1"),"manual"),("goalkeeping","high balls",count("High Ball","Catch","Cross Claim","Punch"),ids("High Ball","Catch","Cross Claim","Punch"),"manual"),("goalkeeping","distributions",count("Distribution","Short Distribution","Long Distribution","Throw","Goal Kick"),ids("Distribution","Short Distribution","Long Distribution","Throw","Goal Kick"),"manual"),("goalkeeping","tagged errors",count("GK Error","Defensive Error","Error"),ids("GK Error","Defensive Error","Error"),"manual")]
    return [{"group":group,"name":name,"value":value,"event_ids":event_ids,"source":source} for group,name,value,event_ids,source in rows]

@app.get("/api/matches/{match_id}/stats")
async def stats(match_id:str,team_id:str|None=None,player_id:str|None=None,db:Session=Depends(get_db),_=Depends(current_user)):
    stmt=select(Event).options(joinedload(Event.category)).where(Event.match_id==match_id)
    if team_id:stmt=stmt.where(Event.team_id==team_id)
    events=db.scalars(stmt).all()
    if player_id:
        related=set(db.scalars(select(EventPlayer.event_id).where(EventPlayer.player_id==player_id)).all());events=[e for e in events if e.player_id==player_id or e.id in related]
    return calculate_stats(events)

@app.get("/api/matches/{match_id}/statistics.csv")
async def export_statistics(match_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    events=db.scalars(select(Event).options(joinedload(Event.category)).where(Event.match_id==match_id)).all();out=io.StringIO();writer=csv.writer(out);writer.writerow(["group","statistic","value","source","event_ids"])
    for row in calculate_stats(events):writer.writerow([row["group"],row["name"],row["value"],row["source"],"|".join(row["event_ids"])])
    return Response(out.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="statistics-{match_id}.csv"'})

@app.get("/api/templates")
async def templates(db:Session=Depends(get_db),_=Depends(current_user)): return [obj(t) for t in db.scalars(select(Template)).all()]
@app.post("/api/templates")
async def add_template(data:TemplateIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    t=Template(**data.model_dump());db.add(t);db.commit();return obj(t)
@app.get("/api/templates/{template_id}/export")
async def export_template(template_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    t=db.get(Template,template_id)
    if not t:raise HTTPException(404,"Template not found")
    return {"version":1,"name":t.name,"definition":t.definition}

@app.get("/api/presentations")
async def presentations(db:Session=Depends(get_db),_=Depends(current_user)):
    return [obj(p,items=[obj(i) for i in p.items]) for p in db.scalars(select(Presentation).order_by(Presentation.created_at.desc())).unique().all()]

@app.post("/api/presentations")
async def add_presentation(data:PresentationIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    presentation=Presentation(name=data.name,notes=data.notes);db.add(presentation);db.flush()
    for item in data.items:
        if item.event_id and not db.get(Event,item.event_id):raise HTTPException(400,"Presentation contains an invalid event")
        db.add(PresentationItem(presentation_id=presentation.id,**item.model_dump()))
    db.commit();return obj(presentation,items=[obj(i) for i in presentation.items])

@app.put("/api/presentations/{presentation_id}")
async def update_presentation(presentation_id:str,data:PresentationIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    presentation=db.get(Presentation,presentation_id)
    if not presentation:raise HTTPException(404,"Presentation not found")
    presentation.name=data.name;presentation.notes=data.notes;db.query(PresentationItem).filter(PresentationItem.presentation_id==presentation.id).delete()
    for item in data.items:db.add(PresentationItem(presentation_id=presentation.id,**item.model_dump()))
    db.commit();return obj(presentation,items=[obj(i) for i in presentation.items])

@app.post("/api/presentations/{presentation_id}/export")
async def export_presentation(presentation_id:str,db:Session=Depends(get_db),_=Depends(coach_user)):
    presentation=db.get(Presentation,presentation_id)
    if not presentation:raise HTTPException(404,"Presentation not found")
    event_ids=[item.event_id for item in presentation.items if item.event_id]
    job=Job(kind="presentation",payload={"event_ids":event_ids,"name":presentation.name});db.add(job);db.commit();launch(export_highlight,job.id);return obj(job)

@app.post("/api/videos/{video_id}/calibrations")
async def add_calibration(video_id:str,data:CalibrationIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    if not db.get(Video,video_id):raise HTTPException(404,"Video not found")
    if len(data.image_points)<4 or len(data.image_points)!=len(data.pitch_points):raise HTTPException(400,"At least four matching points are required")
    homography=data.homography
    if homography is None:
        import cv2,numpy as np
        matrix,_=cv2.findHomography(np.array(data.image_points,dtype=np.float32),np.array(data.pitch_points,dtype=np.float32));homography=matrix.tolist() if matrix is not None else None
    calibration=PitchCalibration(video_id=video_id,timestamp=data.timestamp,method="manual",confidence=1.0,image_points=data.image_points,pitch_points=data.pitch_points,homography=homography);db.add(calibration);db.commit();return obj(calibration)

@app.get("/api/videos/{video_id}/calibrations")
async def calibrations(video_id:str,db:Session=Depends(get_db),_=Depends(current_user)):return [obj(x) for x in db.scalars(select(PitchCalibration).where(PitchCalibration.video_id==video_id).order_by(PitchCalibration.timestamp)).all()]

@app.post("/api/tracking/jobs")
async def add_tracking(data:TrackingIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    if not db.get(Video,data.video_id):raise HTTPException(404,"Video not found")
    job=TrackingJob(video_id=data.video_id,status=JobStatus.completed if data.tracks else JobStatus.queued,progress=100 if data.tracks else 0,start=data.start,end=data.end,config=data.config);db.add(job);db.flush()
    for track in data.tracks:db.add(PlayerTrack(tracking_job_id=job.id,**track.model_dump()))
    db.commit();return obj(job,tracks=[obj(t) for t in db.scalars(select(PlayerTrack).where(PlayerTrack.tracking_job_id==job.id)).all()])

@app.get("/api/tracking/jobs/{job_id}")
async def get_tracking(job_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    job=db.get(TrackingJob,job_id)
    if not job:raise HTTPException(404,"Tracking job not found")
    return obj(job,tracks=[obj(t) for t in db.scalars(select(PlayerTrack).where(PlayerTrack.tracking_job_id==job.id)).all()])

@app.patch("/api/tracks/{track_id}")
async def correct_track(track_id:str,data:TrackIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    track=db.get(PlayerTrack,track_id)
    if not track:raise HTTPException(404,"Track not found")
    for key,value in data.model_dump().items():setattr(track,key,value)
    db.commit();return obj(track)

@app.post("/api/ai/jobs")
async def ai_job(data:AIIn,db:Session=Depends(get_db),_=Depends(coach_user)):
    video=db.scalar(select(Video).where(Video.id==data.video_id).with_for_update())
    if not video:raise HTTPException(404,"Video not found")
    if video.status!="ready":raise HTTPException(409,"Wait for video preparation to finish")
    active=db.scalar(select(AIJob).where(AIJob.video_id==video.id,AIJob.status.in_([JobStatus.queued,JobStatus.running])))
    if active:return obj(active)
    j=AIJob(**data.model_dump());db.add(j);db.commit();launch(analyze,j.id);return obj(j)
@app.get("/api/videos/{video_id}/ai-job")
async def latest_video_ai_job(video_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    if not db.get(Video,video_id):raise HTTPException(404,"Video not found")
    job=db.scalar(select(AIJob).where(AIJob.video_id==video_id).order_by(AIJob.created_at.desc()))
    if not job:raise HTTPException(404,"AI job not found")
    suggestions=db.scalars(select(AISuggestion).where(AISuggestion.ai_job_id==job.id).order_by(AISuggestion.timestamp)).all()
    return obj(job,suggestions=[obj(s) for s in suggestions])
@app.get("/api/ai/jobs/{job_id}")
async def get_ai_job(job_id:str,db:Session=Depends(get_db),_=Depends(current_user)):
    j=db.get(AIJob,job_id)
    if not j:raise HTTPException(404,"AI job not found")
    suggestions=db.scalars(select(AISuggestion).where(AISuggestion.ai_job_id==job_id).order_by(AISuggestion.timestamp)).all()
    return obj(j,suggestions=[obj(s) for s in suggestions])
@app.post("/api/ai/suggestions/{suggestion_id}")
async def decide_suggestion(suggestion_id:str,data:SuggestionAction,db:Session=Depends(get_db),user:User=Depends(coach_user)):
    s=db.scalar(select(AISuggestion).where(AISuggestion.id==suggestion_id).with_for_update())
    if not s or s.status!=SuggestionStatus.pending:raise HTTPException(400,"Suggestion is not pending")
    if data.action=="reject":s.status=SuggestionStatus.rejected
    elif data.action=="edit":
        s.corrected_data={**s.corrected_data,**data.model_dump(exclude={"action"},exclude_unset=True)};db.commit();return obj(s)
    elif data.action=="accept":
        job=db.get(AIJob,s.ai_job_id);video=db.get(Video,job.video_id)
        corrected={**s.corrected_data,**data.model_dump(exclude={"action"},exclude_unset=True)}
        category=db.get(Category,corrected.get("category_id")) if corrected.get("category_id") else db.scalar(select(Category).where(Category.name==s.proposed_category))
        if not category:raise HTTPException(400,"Category required")
        timestamp=corrected.get("timestamp",s.timestamp);team_id=corrected.get("team_id",s.proposed_team_id);team=db.get(Team,team_id) if team_id else None
        e=Event(match_id=video.match_id,video_id=video.id,category_id=category.id,timestamp=timestamp,start=max(0,timestamp-category.pre_roll),end=min(video.duration,s.end or timestamp+category.post_roll),creator_id=user.id,team_id=team_id,team=team.name if team else None,note=corrected.get("note") or "Accepted AI suggestion",tags=["ai-assisted"],metadata_={"suggestion_id":s.id,"confidence":s.confidence,**corrected.get("metadata",{})})
        db.add(e);db.flush()
        for participant in corrected.get("players",s.proposed_players):
            values=participant if isinstance(participant,dict) else {"player_id":participant,"role":"actor"}
            if db.get(Player,values.get("player_id")):db.add(EventPlayer(event_id=e.id,player_id=values["player_id"],role=values.get("role","actor")))
        s.status=SuggestionStatus.accepted;s.accepted_event_id=e.id;s.corrected_data=corrected
    else:raise HTTPException(400,"Action must be accept or reject")
    db.commit();return obj(s)
