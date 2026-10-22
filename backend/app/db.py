from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}, pool_pre_ping=True)
if engine.dialect.name == "sqlite":
    # SQLite ignores the declared ON DELETE CASCADE / SET NULL rules unless this
    # is switched on per connection; without it deleting a match left its
    # events and AI jobs behind. (Alembic uses its own engine, so migrations
    # that rebuild tables are unaffected.)
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor(); cursor.execute("PRAGMA foreign_keys=ON"); cursor.close()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


async def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
