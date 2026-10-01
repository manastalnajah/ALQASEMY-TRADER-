from pydantic import BaseModel
from typing import List
from datetime import datetime

class DealSchema(BaseModel):
    deal_ticket: int
    order_ticket: int
    position_ticket: int
    symbol: str
    side: str
    volume: float
    open_price: float
    close_price: float
    sl: float
    tp: float
    profit: float
    commission: float
    swap: float
    comment: str
    open_time: datetime
    close_time: datetime

class HistorySyncRequest(BaseModel):
    account_number: int
    ea_id: str
    magic: int
    deals: List[DealSchema]
