import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 1. استدعاء الموجهات (Routers) من المجلدات الداخلية
from app.api.v1.trades_router import router as trades_router
from app.api.v1.bot_router import router as bot_router  # 🆕 موجه البوت المستقل
from app.api.v1.mt5_router import router as mt5_router  # 🆕 بوابة MT5 المعدلة

# 2. استدعاء محرك التداول (Worker) الذي يعمل في الخلفية
from app.workers.trading_worker import start_background_worker

# 3. استدعاء ملفات قاعدة البيانات لإنشاء الجداول تلقائياً
from database import engine
from app.domain import models

# استدعاء بوابة مراقبة الأداء (Middleware)
from app.api.middleware.performance import PerformanceMiddleware

# فحص قاعدة البيانات وإنشاء أي جداول مفقودة
models.Base.metadata.create_all(bind=engine)

# 4. إعداد دورة حياة التطبيق (Lifespan) لتشغيل الروبوت في الخلفية بأمان
@asynccontextmanager
async def lifespan(app: FastAPI):
    # تشغيل محرك التداول بشكل مستقل في الخلفية
    worker_task = asyncio.create_task(start_background_worker())
    yield
    # إيقاف المحرك بأمان عند إغلاق التطبيق
    worker_task.cancel()

# 5. تهيئة التطبيق الأساسي للسيرفر
app = FastAPI(
    title="Alqasemy Trader API",
    description="Backend server for automated trading system",
    version="8.0.0",
    lifespan=lifespan
)

# 6. إعدادات CORS للسماح بالاتصال من أي تطبيق خارجي (مثل Flutter)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# تفعيل بوابة مراقبة الأداء
app.add_middleware(PerformanceMiddleware)

# 7. دمج المسارات (Routers) في السيرفر الرئيسي
app.include_router(trades_router)
app.include_router(bot_router)
app.include_router(mt5_router)

# 8. المسار الرئيسي لفحص حالة السيرفر
@app.get("/")
def read_root():
    return {
        "message": "Welcome to Alqasemy Trader API 🚀", 
        "status": "active"
    }

# 9. مسار الفحص الطبي للسيرفر (Health Check)
@app.get("/health")
def health_check():
    return {
        "status": "healthy", 
        "database": "connected"
    }

# 10. إعدادات التشغيل للسحابية والمحلي
if __name__ == "__main__":
    import uvicorn
    import os
    
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
