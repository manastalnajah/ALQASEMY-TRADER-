from fastapi import APIRouter, HTTPException
from app.schemas.history import HistorySyncRequest
from app.services.performance_service import PerformanceService

router = APIRouter(prefix="/api/v1/mt5/history", tags=["History"])

@router.post("/sync")
async def sync_history(request: HistorySyncRequest):
    success = await PerformanceService.process_history_sync(request)
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to process history sync")
        
    return {"status": "success", "message": "History and performance synced successfully"}
