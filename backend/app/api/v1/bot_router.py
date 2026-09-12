from fastapi import APIRouter, HTTPException, Header
from sqlalchemy.orm import Session
from database import SessionLocal
from app.domain.models import BotState
from app.config import config

router = APIRouter(prefix="/api/v1/bot", tags=["Bot Control"])
bot_state = {"is_running": False, "status": "stopped"}  # compatibility cache only


def _get_state(db: Session) -> BotState:
    state = db.query(BotState).filter(BotState.id == 1).first()
    if not state:
        state = BotState(id=1, is_running=False, status="stopped")
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _authorize_control(x_control_key: str | None):
    if config.require_control_api_key:
        if not config.control_api_key:
            raise HTTPException(503, "Control API is locked: CONTROL_API_KEY is not configured")
        if x_control_key != config.control_api_key:
            raise HTTPException(401, "Invalid control API key")


def is_bot_running(db: Session) -> bool:
    state = _get_state(db)
    bot_state["is_running"] = bool(state.is_running)
    bot_state["status"] = state.status
    return bool(state.is_running)


@router.post("/start")
async def start_bot(x_control_key: str | None = Header(default=None)):
    _authorize_control(x_control_key)
    db = SessionLocal()
    try:
        state = _get_state(db)
        state.is_running = True
        state.status = "running"
        db.commit()
        bot_state.update(is_running=True, status="running")
        return {"status": "success", "is_running": True, "risk_mode": "strict"}
    finally:
        db.close()


@router.post("/stop")
async def stop_bot(x_control_key: str | None = Header(default=None)):
    _authorize_control(x_control_key)
    db = SessionLocal()
    try:
        state = _get_state(db)
        state.is_running = False
        state.status = "stopped"
        db.commit()
        bot_state.update(is_running=False, status="stopped")
        return {"status": "success", "is_running": False}
    finally:
        db.close()


@router.get("/status")
async def get_bot_status():
    db = SessionLocal()
    try:
        state = _get_state(db)
        return {
            "status": "success",
            "is_running": bool(state.is_running),
            "current_state": state.status,
            "risk_per_trade_pct": config.risk_per_trade_pct,
            "max_open_positions": config.max_open_positions,
            "max_pending_orders": config.max_pending_orders,
            "max_daily_loss_pct": config.max_daily_loss_pct,
            "max_drawdown_pct": config.max_drawdown_pct,
        }
    finally:
        db.close()
