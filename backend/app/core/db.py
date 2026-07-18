"""
Database connection and session management.

This module configures the SQLAlchemy engine and provides a dependency
for FastAPI endpoints to acquire database sessions.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from backend.app.models import Base

# Overridable so a deployed instance can point at a different file path (or a
# different database engine entirely) without a code change.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./signal.db")

# check_same_thread=False is a SQLite-only requirement; other engines don't need it.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """
    FastAPI dependency that provides a database session.
    
    Yields a SessionLocal instance and ensures it is closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """
    Initializes the database by creating all defined tables.
    """
    Base.metadata.create_all(bind=engine)
