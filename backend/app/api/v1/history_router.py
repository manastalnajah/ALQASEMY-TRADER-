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
