import time
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy import text

# الاستيراد الدقيق والصحيح بناءً على ملف database.py الخاص بك
from database import SessionLocal

router = APIRouter(prefix="/api/v1/mt5", tags=["MT5"])
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
    
    if not request.candles:
        return {"status": "success", "message": "No candles provided", "inserted": 0}
        
    logger.info(f"📥 Received {len(request.candles)} candles for EA: {request.ea_id}")

    # 1. تجهيز البيانات كقائمة قواميس لتتوافق مع الإدخال الجماعي لـ SQLAlchemy
    values = []
    for c in request.candles:
        values.append({
            "symbol_name": c.symbol,
            "timeframe": c.timeframe,
            "open_time": c.open_time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        })

    # 2. استعلام ذكي وسريع جداً للإدخال الجماعي (Bulk Insert)
    insert_query = text("""
        INSERT INTO candles 
        (symbol_name, timeframe, open_time, open, high, low, close, volume)
        VALUES (:symbol_name, :timeframe, :open_time, :open, :high, :low, :close, :volume)
        ON CONFLICT (symbol_name, timeframe, open_time) 
        DO UPDATE SET 
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """)

    # 3. فتح الجلسة بقاعدة البيانات
    db = SessionLocal()
    
    try:
        # 4. تنفيذ الإدخال الجماعي
        db.execute(insert_query, values)
        db.commit()
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Successfully inserted/updated {len(request.candles)} candles in {elapsed:.4f} seconds")
        
        return {
            "status": "success", 
            "inserted": len(request.candles), 
            "time_seconds": round(elapsed, 4)
        }

    except Exception as e:
        db.rollback()
        
        # التقاط الخطأ الحقيقي بوضوح لمنع الأخطاء الصامتة
        error_msg = str(e)
        if not error_msg or error_msg.strip() == "":
            error_msg = repr(e)
            
        logger.error(f"❌ DATABASE ERROR in candles sync: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Failed to sync candles: {error_msg}")
        
    finally:
        db.close()

# ==========================================
# (يمكنك إضافة بقية المسارات القديمة الخاصة بك هنا إن وجدت)
