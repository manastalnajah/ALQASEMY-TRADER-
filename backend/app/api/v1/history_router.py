from fastapi import APIRouter, HTTPException, Request
from app.domain.history import HistorySyncRequest
from app.services.performance_service import PerformanceService

router = APIRouter(prefix="/api/v1/mt5/history", tags=["MT5 History"])

@router.post("/sync")
async def sync_history(request_data: HistorySyncRequest, request: Request):
    mt5_key = request.headers.get("X-MT5-Key")
    
    success = await PerformanceService.process_history_sync(request_data)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to calculate and sync performance")
        
    return {"status": "success", "message": "History synced and performance updated"}


# =========================================================================
# 🚀 مسار مخصص لتطبيق فلاتر لجلب الإحصائيات ومنحنى الأداء
# =========================================================================
@router.get("/{account_id}")
async def get_performance_stats(account_id: str):
    """
    يقوم تطبيق فلاتر باستدعاء هذا المسار لجلب بيانات الأداء 
    ورسم منحنى تطور الحساب (Equity Curve) والمخطط الشهري.
    """
    try:
        data = await PerformanceService.get_performance_data(account_id)
        if data.get("status") == "error":
            raise HTTPException(status_code=500, detail=data.get("message", "Unknown error"))
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error loading performance: {exc}")
