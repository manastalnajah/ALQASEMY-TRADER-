import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv(override=True)
DATABASE_URL = os.getenv("SUPABASE_DB_URL")
if not DATABASE_URL:
    raise ValueError("SUPABASE_DB_URL is required")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def initialize_database():
    # Required for UUID defaults used by the existing Supabase schema.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        from app.domain import models  # noqa: F401
        Base.metadata.create_all(bind=conn)
        # Backward-compatible hardening for an already-created trade_commands table.
        conn.execute(text("ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"))
        conn.execute(text("ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS strategy_name VARCHAR DEFAULT ''"))
        conn.execute(text("ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS signal_key VARCHAR DEFAULT ''"))
        conn.execute(text("ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS ea_id VARCHAR DEFAULT ''"))
        conn.execute(text("ALTER TABLE trade_commands ADD COLUMN IF NOT EXISTS error_message VARCHAR DEFAULT ''"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_trade_commands_signal_key ON trade_commands(signal_key)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_trade_commands_symbol_status_created ON trade_commands(symbol,status,created_at)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
