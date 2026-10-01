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
# 👇 1. استدعاء ملف المسار الخاص بالهستوري
from app.api.v1.history_router import router as history_router 
from app.workers.trading_worker import start_background_worker
from app.api.middleware.performance import PerformanceMiddleware

logger = logging.getLogger("AlqasemyTrader")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. تهيئة قاعدة البيانات أولاً عند الإقلاع
    try:
        await initialize_database()  # 🛠️ استخدام await
        logger.info("Database initialization completed successfully")
    except Exception:
        logger.exception("Database initialization failed")
        raise

    # 2. تشغيل عامل الخلفية (Trading Worker)
    worker_task = asyncio.create_task(start_background_worker())
    try:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Alqasemy Trader API",
    description="Rule-based automated trading backend with strict risk controls. No AI/ML.",
    version="2.0.0",
    lifespan=lifespan,
)

# 1. إضافة الـ Middleware الداخلية أولاً
app.add_middleware(PerformanceMiddleware)

# 2. إضافة الـ CORS Middleware في النهاية لتكون هي الغطاء الخارجي الأول للطلبات
raw_origins = os.getenv("CORS_ORIGINS", "*").strip()
if not raw_origins or raw_origins == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [x.strip() for x in raw_origins.split(",") if x.strip()]

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

# ------------------------------------------------------------
# توجيه المسارات (Routers)
# ------------------------------------------------------------
app.include_router(trades_router)
app.include_router(bot_router)
app.include_router(mt5_router)
# 👇 2. إضافة المسار الجديد لتطبيقك
app.include_router(history_router) 


@app.get("/")
def read_root():
    return {
        "message": "Alqasemy Trader API",
        "status": "active",
        "mode": "strict-rule-based",
    }


@app.get("/health")
def health_check():
    return {"status": "healthy", "database": "initialized"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, workers=1)
