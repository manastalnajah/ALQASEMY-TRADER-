# ============================================================
# main.py — Alqasemy Trader API
# النسخة: 2.1.0
# ------------------------------------------------------------
# التغييرات عن 2.0.0:
# - إضافة position_manager_worker كمهمة خلفية
# - إدارة lifecycle أفضل للمهام
# ============================================================

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import initialize_database
from app.api.v1.trades_router import router as trades_router
from app.api.v1.bot_router import router as bot_router
from app.api.v1.mt5_router import router as mt5_router
from app.api.v1.history_router import router as history_router
from app.workers.trading_worker import start_background_worker
from app.api.middleware.performance import PerformanceMiddleware

# ✅ جديد: عامل إدارة الصفقات
from app.services.position_manager_worker import start_position_manager_worker


logger = logging.getLogger("AlqasemyTrader")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    دورة حياة التطبيق:
    1. تهيئة قاعدة البيانات.
    2. تشغيل trading_worker (للاستراتيجيات).
    3. تشغيل position_manager_worker (لإدارة الصفقات المفتوحة).
    """
    # --------------------------------------------------------
    # 1. تهيئة قاعدة البيانات
    # --------------------------------------------------------
    try:
        await initialize_database()
        logger.info("Database initialization completed successfully")
    except Exception:
        logger.exception("Database initialization failed")
        raise

    # --------------------------------------------------------
    # 2. تشغيل العمال (Background Workers)
    # --------------------------------------------------------
    worker_task = asyncio.create_task(
        start_background_worker(),
        name="trading_worker",
    )

    position_manager_task = asyncio.create_task(
        start_position_manager_worker(),
        name="position_manager_worker",
    )

    logger.info(
        "Background workers started: trading_worker, position_manager_worker"
    )

    try:
        yield
    finally:
        # ----------------------------------------------------
        # 3. إيقاف العمال عند الإغلاق
        # ----------------------------------------------------
        logger.info("Stopping background workers...")

        for task, name in [
            (worker_task, "trading_worker"),
            (position_manager_task, "position_manager_worker"),
        ]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception(
                        "Error while stopping worker %s", name
                    )

        logger.info("All background workers stopped")


app = FastAPI(
    title="Alqasemy Trader API",
    description=(
        "Rule-based automated trading backend with strict risk controls. "
        "No AI/ML."
    ),
    version="2.1.0",
    lifespan=lifespan,
)


# ============================================================
# Middleware
# ============================================================

# 1. Middleware الداخلية (Performance)
app.add_middleware(PerformanceMiddleware)


# 2. CORS Middleware (الغطاء الخارجي)
raw_origins = os.getenv("CORS_ORIGINS", "*").strip()
if not raw_origins or raw_origins == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [
        x.strip() for x in raw_origins.split(",") if x.strip()
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=[
        "Content-Type",
        "Accept",
        "Authorization",
        "X-Control-Key",
        "X-MT5-Key",
    ],
    expose_headers=[
        "Content-Type",
        "Accept",
        "Authorization",
        "X-Control-Key",
        "X-MT5-Key",
    ],
)


# ============================================================
# Routers
# ============================================================

app.include_router(trades_router)
app.include_router(bot_router)
app.include_router(mt5_router)
app.include_router(history_router)


# ============================================================
# Root endpoints
# ============================================================

@app.get("/")
def read_root():
    return {
        "message": "Alqasemy Trader API",
        "status": "active",
        "mode": "strict-rule-based",
        "version": "2.1.0",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": "initialized",
        "workers": [
            "trading_worker",
            "position_manager_worker",
        ],
    }


# ============================================================
# Entrypoint
# ============================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        workers=1,
    )
