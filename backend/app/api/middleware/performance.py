import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.logging.logger import system_logger

class PerformanceMiddleware(BaseHTTPMiddleware):
    """
    بوابة المراقبة: تقيس الزمن الذي استغرقه السيرفر لمعالجة أي طلب بدقة عالية.
    تم تحسينها لمنع إغراق السجل (Log Spam) بسبب طلبات الـ Polling المستمرة من الإكسبرت.
    """
    async def dispatch(self, request: Request, call_next):
        # 1. استخدام perf_counter بدلاً من time لأنه أدق لحساب الفترات الزمنية 
        # ولا يتأثر إذا قامت خوادم لينكس بتحديث ساعة النظام أثناء معالجة الطلب
        start_time = time.perf_counter()
        
        # 2. تمرير الطلب للداخل
        response = await call_next(request)
        
        # 3. حساب الزمن المستغرق
        process_time = time.perf_counter() - start_time
        
        # 4. فلترة مسارات الإكسبرت المزعجة (التي تتكرر كل بضع ثوانٍ)
        path = request.url.path
        is_noisy_endpoint = path.endswith(("/commands", "/heartbeat", "/status"))
        
        log_msg = (
            f"🌐 [Middleware] مسار: {path} | "
            f"طريقة: {request.method} | "
            f"زمن التنفيذ: {process_time:.4f} ثانية"
        )
        
        # 5. طباعة تقرير في لوحة المراقبة (مخفي للنبضات، وواضح للطلبات الحقيقية كالـ SYNC)
        if is_noisy_endpoint:
            system_logger.debug(log_msg)
        else:
            system_logger.info(log_msg)
        
        # 6. إرفاق زمن التنفيذ في ترويسة الرد
        response.headers["X-Process-Time"] = str(process_time)
        
        return response
