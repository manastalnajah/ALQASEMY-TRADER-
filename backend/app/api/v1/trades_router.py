from fastapi import APIRouter, Depends, HTTPException, Body, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession  # 🛠️ تم التحديث لدعم AsyncSession
from database import get_db
from app.domain import schemas
from app.repositories.trade_repo import TradeRepository
from app.services import trade_service
from app.config import config

router = APIRouter(prefix="/trades", tags=["Trades"])


def _authorize_control(x_control_key: str | None):
    if config.require_control_api_key:
        if not config.control_api_key:
            raise HTTPException(503, "Control API is locked: CONTROL_API_KEY is not configured")
        if x_control_key != config.control_api_key:
            raise HTTPException(401, "Invalid control API key")


@router.post("/commands", response_model=schemas.CommandResponse)
async def create_command(  # 🛠️ تحويل لـ Async
    command: schemas.CommandCreate, 
    account_id: str = Query(..., description="المعرف الفريد للحساب المراد تنفيذ الأمر عليه"),
    db: AsyncSession = Depends(get_db),  # 🛠️ استخدام AsyncSession
    x_control_key: str | None = Header(default=None)
):
    _authorize_control(x_control_key)
    
    # 💡 يتم سحب account_number تلقائياً من داخل المتغير 'command' المرسل من فلاتر
    # 🛠️ إضافة await لأن الدالة أصبحت غير متزامنة
    return await trade_service.process_new_command(db=db, command=command, account_id=account_id, enforce_risk=True)


@router.get("/commands/pending", response_model=list[schemas.CommandResponse])
async def get_pending_commands(  # 🛠️ تحويل لـ Async
    db: AsyncSession = Depends(get_db),  # 🛠️ استخدام AsyncSession
    x_control_key: str | None = Header(default=None)
):
    _authorize_control(x_control_key) # تأمين المسار
    repo = TradeRepository(db)
    
    # التحقق مما إذا كانت الدالة في الـ Repo متزامنة أم لا
    if hasattr(repo.get_pending_commands, '__await__'):
        return await repo.get_pending_commands()
    return repo.get_pending_commands()


@router.put("/commands/{command_id}/claim", response_model=schemas.CommandResponse)
async def claim_command(  # 🛠️ تحويل لـ Async
    command_id: str, 
    db: AsyncSession = Depends(get_db),  # 🛠️ استخدام AsyncSession
    x_control_key: str | None = Header(default=None)
):
    _authorize_control(x_control_key) # تأمين المسار
    repo = TradeRepository(db)
    
    if hasattr(repo.claim_command, '__await__'):
        command = await repo.claim_command(command_id)
    else:
        command = repo.claim_command(command_id)
        
    if not command:
        raise HTTPException(409, "Command is already claimed or does not exist")
    return command


@router.put("/commands/{command_id}/status", response_model=schemas.CommandResponse)
async def update_command_status(  # 🛠️ تحويل لـ Async
    command_id: str, 
    status: str = Body(..., embed=True), 
    db: AsyncSession = Depends(get_db),  # 🛠️ استخدام AsyncSession
    x_control_key: str | None = Header(default=None)
):
    _authorize_control(x_control_key) # تأمين المسار
    repo = TradeRepository(db)
    
    if hasattr(repo.update_command_status, '__await__'):
        command = await repo.update_command_status(command_id, status)
    else:
        command = repo.update_command_status(command_id, status)
        
    if not command:
        raise HTTPException(404, "Command not found or invalid status")
    return command
