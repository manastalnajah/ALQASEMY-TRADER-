import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv
from app.logging.logger import system_logger

load_dotenv(override=True)
DATABASE_URL = os.getenv("SUPABASE_DB_URL")
if not DATABASE_URL:
    raise ValueError("SUPABASE_DB_URL is required")

# 🛠️ استخدام المحرك غير المتزامن فائق السرعة
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    # 🛠️ تم رفع سعة الاتصالات لإنهاء خطأ QueuePool limit تماماً
    pool_size=int(os.getenv("DB_POOL_SIZE", "40")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "60")),
    pool_timeout=60, # 🛠️ إضافة مهلة انتظار أطول للطلبات المزدحمة
)

# 🛠️ إنشاء مصنع الجلسات غير المتزامنة
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False, 
    autoflush=False
)
Base = declarative_base()


async def initialize_database():
    try:
        # 🛠️ فتح اتصال غير متزامن
        async with engine.begin() as conn:
            # تهيئة الإضافات الأساسية لعمل UUIDs والتشفير في PostgreSQL
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS pgcrypto'))
            
            # استيراد النماذج بجميع مساراتها المحتملة لضمان تسجيل الجداول في Base.metadata
            try:
                from app.domain import models  # noqa: F401
            except ImportError:
                pass
                
            try:
                import models  # noqa: F401
            except ImportError:
                pass
            
            # إنشاء الجداول غير الموجودة فقط (بطريقة متوافقة مع Async)
            await conn.run_sync(Base.metadata.create_all)
            
        system_logger.info("Database initialized successfully and all models registered.")
    except Exception as e:
        system_logger.error(f"Database initialization failed: {e}")
        raise


# 🛠️ تحويل دالة جلب قاعدة البيانات لتكون Async Generator
async def get_db():
    db = AsyncSessionLocal()
    try:
        yield db
    finally:
        await db.close()
