"""
Database engine/session setup.

DATABASE_URL now comes from the centralized `settings` object (core/config.py)
instead of reading the env var directly here - same default as before
(sqlite:///./insightflow.db), so nothing changes for existing setups.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .core.config import settings

DATABASE_URL = settings.DATABASE_URL
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# SQLite does not enforce FOREIGN KEY / cascade-delete constraints unless this
# pragma is turned on per-connection. Postgres enforces them natively, so this
# is a no-op there.
if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
