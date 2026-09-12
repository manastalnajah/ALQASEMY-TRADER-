import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from app.logging.logger import system_logger

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
    try:
        with engine.begin() as conn:
            # تهيئة الإضافات الأساسية لعمل UUIDs والتشفير في PostgreSQL
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS pgcrypto'))
            
            # استدعاء النماذج لضمان تسجيلها
            from app.domain import models  # noqa: F401
            
            # إنشاء الجداول غير الموجودة فقط (لن يعبث بالقيود التي أضفناها في الـ Migration)
            Base.metadata.create_all(bind=conn)
            
            system_logger.info("Database initialized successfully.")
    except Exception as e:
        system_logger.error(f"Database initialization failed: {e}")
        raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
