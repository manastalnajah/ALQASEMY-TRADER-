import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.logging.logger import system_logger

class PerformanceMiddleware(BaseHTTPMiddleware):
    """
    بوابة المراقبة: تقيس الزمن الذي استغرقه السيرفر لمعالجة أي طلب (بيع/شراء) بدقة.
    """
    async def dispatch(self, request: Request, call_next):
        # 1. تسجيل وقت وصول الطلب للسيرفر
        start_time = time.time()
        
        # 2. تمرير الطلب للداخل (للموجهات والخدمات) ليتم تنفيذه
        response = await call_next(request)
        
        # 3. حساب الزمن المستغرق بعد انتهاء التنفيذ
        process_time = time.time() - start_time
        
        # 4. طباعة تقرير في لوحة المراقبة
        system_logger.info(
            f"🌐 [Middleware] مسار: {request.url.path} | "
            f"طريقة: {request.method} | "
            f"زمن التنفيذ: {process_time:.4f} ثانية"
        )
        
        # 5. إرفاق زمن التنفيذ في ترويسة الرد (Headers) لكي يراه تطبيق فلاتر
        response.headers["X-Process-Time"] = str(process_time)
        
        return response