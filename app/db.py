"""
Database models. SQLite by default (fine for getting started); set
DATABASE_URL to a Postgres connection string for real production — SQLite
does not handle concurrent writers well under real multi-user load.

GDPR note: this schema is deliberately structured so a user's data can be
deleted in one transaction (see main.py's DELETE /me endpoint) — every table
that holds personal data has a straight foreign key to users.id with
cascade delete. Don't add a table with user data that isn't wired into that
cascade.
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    credits = Column(Integer, default=0)
    stripe_customer_id = Column(String, nullable=True)
    subscription_active = Column(Integer, default=0)  # 0/1 — simple flag; Stripe is the source of truth
    created_at = Column(DateTime, default=now)

    cvs = relationship("CV", backref="user", cascade="all, delete-orphan")
    applications = relationship("TailoredApplication", backref="user", cascade="all, delete-orphan")
    discovery_runs = relationship("DiscoveryRun", backref="user", cascade="all, delete-orphan")
    jobs = relationship("Job", backref="user", cascade="all, delete-orphan")


class CV(Base):
    __tablename__ = "cvs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    raw_text = Column(Text)
    structured_json = Column(Text)  # same schema as the local pipeline's cv.json
    created_at = Column(DateTime, default=now)


class TailoredApplication(Base):
    __tablename__ = "tailored_applications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cv_id = Column(Integer, ForeignKey("cvs.id", ondelete="CASCADE"), nullable=False)
    job_title = Column(String)
    company = Column(String)
    job_description = Column(Text)
    tailored_json = Column(Text)
    gaps_json = Column(Text)
    created_at = Column(DateTime, default=now)


class DiscoveryRun(Base):
    """Tracks one 'find jobs for me' background job — this is the thing
    your browser polls so the UI can show live progress, the same way the
    local CLI prints '[25/301] scored so far...' as it goes."""
    __tablename__ = "discovery_runs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    query = Column(String)
    status = Column(String, default="running")  # running -> done -> failed
    jobs_found = Column(Integer, default=0)
    jobs_scored = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now)


class Job(Base):
    """One discovered listing, scoped to the user who searched for it —
    same shape as the local pipeline's jobs table, just with an owner."""
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    discovery_run_id = Column(Integer, ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=True)
    source = Column(String)
    title = Column(String)
    company = Column(String)
    location = Column(String)
    country = Column(String)
    url = Column(String)
    description = Column(Text)
    triage_score = Column(Integer, nullable=True)
    triage_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=now)


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
