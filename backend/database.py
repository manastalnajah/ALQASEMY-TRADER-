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
    # 🛠️ تم رفع سعة الاتصالات لإنهاء خطأ QueuePool limit تماماً
    pool_size=int(os.getenv("DB_POOL_SIZE", "40")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "60")),
    pool_timeout=60, # 🛠️ إضافة مهلة انتظار أطول للطلبات المزدحمة
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def initialize_database():
    try:
        with engine.begin() as conn:
            # تهيئة الإضافات الأساسية لعمل UUIDs والتشفير في PostgreSQL
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS pgcrypto'))
            
            # استيراد النماذج بجميع مساراتها المحتملة لضمان تسجيل الجداول في Base.metadata
            try:
                from app.domain import models  # noqa: F401
            except ImportError:
                pass
                
            try:
                import models  # noqa: F401
            except ImportError:
                pass
            
            # إنشاء الجداول غير الموجودة فقط
            Base.metadata.create_all(bind=conn)
            
            system_logger.info("Database initialized successfully and all models registered.")
    except Exception as e:
        system_logger.error(f"Database initialization failed: {e}")
        raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
