from fastapi import APIRouter, Depends, HTTPException, Body, Header
from sqlalchemy.orm import Session
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
def create_command(command: schemas.CommandCreate, db: Session = Depends(get_db), x_control_key: str | None = Header(default=None)):
    _authorize_control(x_control_key)
    return trade_service.process_new_command(db, command, enforce_risk=True)


@router.get("/commands/pending", response_model=list[schemas.CommandResponse])
def get_pending_commands(db: Session = Depends(get_db)):
    return TradeRepository(db).get_pending_commands()


@router.put("/commands/{command_id}/claim", response_model=schemas.CommandResponse)
def claim_command(command_id: str, db: Session = Depends(get_db)):
    command = TradeRepository(db).claim_command(command_id)
    if not command:
        raise HTTPException(409, "Command is already claimed or does not exist")
    return command


@router.put("/commands/{command_id}/status", response_model=schemas.CommandResponse)
def update_command_status(command_id: str, status: str = Body(..., embed=True), db: Session = Depends(get_db)):
    command = TradeRepository(db).update_command_status(command_id, status)
    if not command:
        raise HTTPException(404, "Command not found or invalid status")
    return command
