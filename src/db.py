"""Database engine/session setup for AI Spending Detective."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.models import Base

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "spending.db"
engine = create_engine(f"sqlite:///{DB_PATH}")
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
