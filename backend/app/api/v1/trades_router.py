from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

# استدعاء ملف الاتصال بقاعدة البيانات
from database import get_db
from app.domain import schemas
from app.repositories.trade_repo import TradeRepository
from app.services import trade_service

router = APIRouter(
    prefix="/trades",
    tags=["Trades"]
)

# 1. مسار إرسال أمر جديد (يستخدمه تطبيق فلاتر)
@router.post("/commands", response_model=schemas.CommandResponse)
def create_command(command: schemas.CommandCreate, db: Session = Depends(get_db)):
    # التوجيه لنقطة التفتيش
    return trade_service.process_new_command(db=db, command=command)

# 2. مسار جلب الأوامر المعلقة (يستخدمه الميتاتريدر)
@router.get("/commands/pending", response_model=list[schemas.CommandResponse])
def get_pending_commands(db: Session = Depends(get_db)):
    repo = TradeRepository(db)
    return repo.get_pending_commands()

# 3. مسار تحديث حالة الأمر (يستخدمه الميتاتريدر بعد التنفيذ)
@router.put("/commands/{command_id}/status", response_model=schemas.CommandResponse)
def update_command_status(
    command_id: str, # 💡 تم تعديلها إلى str لتقبل الـ UUID الخاص بـ Supabase
    status: str = Body(..., embed=True), # 💡 تم التعديل ليقرأ الحالة من الـ JSON Body وليس من الرابط
    db: Session = Depends(get_db)
):
    repo = TradeRepository(db)
    updated_command = repo.update_command_status(command_id=command_id, new_status=status)
    
    if not updated_command:
        raise HTTPException(status_code=404, detail="Command not found")
        
    return updated_command
