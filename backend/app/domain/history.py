from typing import List, Optional, Union
from pydantic import BaseModel
from datetime import datetime

class HistoryDeal(BaseModel):
    deal_ticket: int
    order_ticket: int = 0
    position_ticket: int = 0
    symbol: str
    side: str
    volume: float
    open_price: float
    close_price: float
    sl: float = 0.0
    tp: float = 0.0
    profit: float
    commission: float
    swap: float
    comment: Optional[str] = ""
    # 🛠️ السر هنا: السماح للباك إند بقبول التاريخ كنص أو كـ رقم أو كـ datetime
    open_time: Union[str, datetime, int, float] 
    close_time: Union[str, datetime, int, float]

class HistorySyncRequest(BaseModel):
    account_number: int
    ea_id: str
    magic: int
    deals: List[HistoryDeal]
