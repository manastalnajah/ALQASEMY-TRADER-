from pydantic import BaseModel
from datetime import datetime

# 1. القالب الخاص باستقبال البيانات من تطبيق فلاتر
class CommandCreate(BaseModel):
    symbol: str
    order_type: str
    lot_size: float

# 2. القالب الخاص بإرجاع البيانات (الرد) إلى تطبيق فلاتر
class CommandResponse(BaseModel):
    id: int
    symbol: str
    order_type: str
    lot_size: float
    status: str
    created_at: datetime

    # إعداد ضروري لكي تفهم Pydantic بيانات SQLAlchemy
    class Config:
        from_attributes = True