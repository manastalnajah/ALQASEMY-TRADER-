# ============================================================
# database.py
# النسخة: 2.1.0
# ------------------------------------------------------------
# - إدارة اتصال Async مع Supabase (PgBouncer في transaction mode)
# - Pool محسّن لـ Render (avoid timeouts)
# - Diagnostic logs للجداول المُسجَّلة
# ============================================================

import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base

from app.logging.logger import system_logger


# ============================================================
# Environment
# ============================================================

load_dotenv(override=True)

DATABASE_URL = os.getenv("SUPABASE_DB_URL")
if not DATABASE_URL:
    raise ValueError("SUPABASE_DB_URL is required")


# ============================================================
# Engine
# ============================================================

# Pool settings — تُضبط عبر Environment Variables في Render
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "900"))
ECHO_SQL = os.getenv("DB_ECHO", "false").lower() == "true"


engine = create_async_engine(
    DATABASE_URL,
    echo=ECHO_SQL,

    # Pool
    pool_pre_ping=True,
    pool_recycle=POOL_RECYCLE,      # 15 دقيقة — آمن مع PgBouncer
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,

    # ========================================================
    # Supabase PgBouncer في Transaction Mode
    # --------------------------------------------------------
    # - prepared_statement_cache_size=0:
    #   يمنع asyncpg من إعادة استخدام prepared statements
    #   عبر جلسات PgBouncer المختلفة.
    #
    # - statement_cache_size=0:
    #   يمنع تخزين prepared statements محليًا.
    #
    # ⚠️ بدون هذين الإعدادين، ستظهر أخطاء:
    #   "prepared statement __asyncpg_stmt_XX already exists"
    #   "invalid input for query argument" (خطأ النوع)
    # ========================================================
    connect_args={
        "prepared_statement_cache_size": 0,
        "statement_cache_size": 0,
    },
)


# ============================================================
# Session Factory
# ============================================================

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # مهم للوصول للكائنات بعد commit
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


# ============================================================
# Database Initialization
# ============================================================

# الجداول التي يجب أن تكون مسجَّلة في Base.metadata
EXPECTED_TABLES = [
    "trading_accounts",
    "trade_commands",
    "candles",
    "symbol_specs",
    "risk_state",
    "position_snapshots",
    "open_positions",
    "pending_orders",
    "bot_state",
    "position_management_commands",
    "position_management_state",
]


async def initialize_database():
    """
    تهيئة قاعدة البيانات عند بدء التطبيق:
    1. تفعيل extensions (uuid-ossp, pgcrypto).
    2. تسجيل النماذج.
    3. إنشاء الجداول غير الموجودة (create_all).
    4. Diagnostic: التأكد من تسجيل الجداول الجديدة.
    """
    try:
        async with engine.begin() as conn:
            # ----------------------------------------------------
            # 1. Extensions
            # ----------------------------------------------------
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

            # ----------------------------------------------------
            # 2. تسجيل النماذج
            # ----------------------------------------------------
            try:
                from app.domain import models  # noqa: F401
                system_logger.info("Models imported from app.domain.models")
            except ImportError as exc:
                system_logger.warning(f"app.domain.models import failed: {exc}")

            try:
                import models  # noqa: F401
                system_logger.info("Models imported from models")
            except ImportError:
                pass

            # ----------------------------------------------------
            # 3. Create missing tables
            # ----------------------------------------------------
            await conn.run_sync(Base.metadata.create_all)

        # --------------------------------------------------------
        # 4. Diagnostic: الجداول المُسجَّلة
        # --------------------------------------------------------
        registered = list(Base.metadata.tables.keys())
        system_logger.info(
            f"Registered tables ({len(registered)}): {registered}"
        )

        missing = [t for t in EXPECTED_TABLES if t not in registered]
        if missing:
            system_logger.error(
                f"⚠️ MISSING TABLES in metadata: {missing}"
            )
        else:
            system_logger.info("✅ All expected tables registered")

        system_logger.info("Database initialized successfully")

    except Exception as e:
        system_logger.error(f"Database initialization failed: {e}")
        raise


# ============================================================
# FastAPI Dependency
# ============================================================

async def get_db():
    """
    FastAPI dependency — يوفر AsyncSession لكل طلب.
    """
    db = AsyncSessionLocal()
    try:
        yield db
    finally:
        await db.close()
