import time
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List
from app.db.database import get_db_connection
from psycopg2.extras import execute_values
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class CandleItem(BaseModel):
    symbol: str
    timeframe: str
    open_time: str
    open: float
    high: float
    low: float
    close: float
    volume: int

class CandlesSyncRequest(BaseModel):
    candles: List[CandleItem]
    source: str
    ea_id: str

@router.post("/candles/sync")
async def sync_candles(request: CandlesSyncRequest):
    start_time = time.time()
    
    # 1. التحقق من وجود بيانات
    if not request.candles:
        return {"status": "success", "message": "No candles provided", "inserted": 0}
        
    logger.info(f"📥 Received {len(request.candles)} candles for EA: {request.ea_id}")

    # 2. تجهيز البيانات للإدخال الجماعي (Bulk Insert)
    # نقوم بتحويل قائمة الـ Pydantic إلى قائمة من الـ Tuples
    values = []
    for c in request.candles:
        values.append((
            c.symbol,
            c.timeframe,
            c.open_time,
            c.open,
            c.high,
            c.low,
            c.close,
            c.volume
        ))

    # 3. استعلام SQL ذكي للـ Bulk Insert مع تخطي التكرار
    insert_query = """
        INSERT INTO candles 
        (symbol_name, timeframe, open_time, open, high, low, close, volume)
        VALUES %s
        ON CONFLICT (symbol_name, timeframe, open_time) 
        DO UPDATE SET 
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """

    conn = get_db_connection()
    if not conn:
        logger.error("❌ Failed to connect to database for candles sync")
        raise HTTPException(status_code=500, detail="Database connection failed")

    try:
        cursor = conn.cursor()
        
        # 4. التنفيذ الجماعي (سريع جداً)
        execute_values(cursor, insert_query, values)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Successfully inserted/updated {len(request.candles)} candles in {elapsed:.4f} seconds")
        
        return {
            "status": "success", 
            "inserted": len(request.candles), 
            "time_seconds": round(elapsed, 4)
        }

    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
            
        # طباعة الخطأ الحقيقي كاملاً بدلاً من إخفائه
        error_msg = str(e)
        if not error_msg:
            error_msg = repr(e) # إذا كان str(e) فارغاً، استخدم repr(e)
            
        logger.error(f"❌ DATABASE ERROR in candles sync: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Failed to sync candles: {error_msg}")
