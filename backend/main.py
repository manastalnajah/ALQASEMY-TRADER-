import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 1. استدعاء الموجهات (Routers) من المجلدات الداخلية
from app.api.v1.trades_router import router as trades_router

# 2. استدعاء محرك التداول (Worker) الذي يعمل في الخلفية
from app.workers.trading_worker import start_background_worker

# 3. استدعاء ملفات قاعدة البيانات لإنشاء الجداول تلقائياً
from database import engine
from app.domain import models

# ⚠️ التعديل هنا: استدعاء بوابة مراقبة الأداء (Middleware)
from app.api.middleware.performance import PerformanceMiddleware

# هذا السطر يقوم بفحص قاعدة البيانات وإنشاء أي جداول مفقودة (مثل جدول commands)
models.Base.metadata.create_all(bind=engine)

# 4. إعداد دورة حياة التطبيق (Lifespan)
# هذه الدالة السحرية تقوم بتشغيل الروبوت في الخلفية بمجرد إقلاع السيرفر
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- ما يكتب هنا يعمل عند تشغيل السيرفر ---
    # إنشاء مهمة (Task) مستقلة للمحرك لكي لا يوقف عمل الروابط (APIs)
    worker_task = asyncio.create_task(start_background_worker())
    
    yield # هنا السيرفر يعمل ويستقبل الطلبات
    
    # --- ما يكتب هنا يعمل عند إغلاق السيرفر ---
    # إيقاف المحرك بأمان
    worker_task.cancel()

# 5. تهيئة التطبيق الأساسي للسيرفر وربطه بدورة الحياة (Lifespan)
app = FastAPI(
    title="Alqasemy Trader API",
    description="Backend server for automated trading system",
    version="1.0.0",
    lifespan=lifespan  # تم الربط هنا!
)

# 6. إعدادات CORS للسماح لتطبيق فلاتر بالاتصال بالسيرفر دون مشاكل أمنية
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # يسمح باستقبال الطلبات من أي مكان
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ⚠️ التعديل هنا: تفعيل بوابة مراقبة الأداء (يجب أن تضاف هنا بعد تهيئة التطبيق)
app.add_middleware(PerformanceMiddleware)

# 7. دمج المسارات (Routers) في السيرفر
# تم ربط مسار التداول الذي سيستقبل الأوامر من هاتفك أو يرسلها للميتاتريدر
app.include_router(trades_router)

# 8. المسار الرئيسي (لفحص حالة السيرفر من المتصفح)
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

# 10. إعدادات التشغيل للسيرفرات السحابية (Cloud & Production Ready)
if __name__ == "__main__":
    import uvicorn
    import os
    
    # قراءة المنفذ المخصص من السحابة، أو استخدام 8000 افتراضياً إذا كان محلياً
    port = int(os.environ.get("PORT", 8000))
    
    # التشغيل على 0.0.0.0 ليقبل الاتصالات الخارجية وليس الهاتف فقط
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
