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
from app.workers.trading_worker import start_background_worker
from app.api.middleware.performance import PerformanceMiddleware

logger = logging.getLogger("AlqasemyTrader")

try:
    initialize_database()
    logger.info("Database initialization completed")
except Exception:
    logger.exception("Database initialization failed")
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
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

allowed_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-MT5-Key", "X-Control-Key"],
)
app.add_middleware(PerformanceMiddleware)
app.include_router(trades_router)
app.include_router(bot_router)
app.include_router(mt5_router)


@app.get("/")
def read_root():
    return {"message": "Alqasemy Trader API", "status": "active", "mode": "strict-rule-based"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "database": "initialized"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, workers=1)
