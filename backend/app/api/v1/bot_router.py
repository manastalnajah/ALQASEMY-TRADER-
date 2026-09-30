from fastapi import APIRouter, HTTPException, Header, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from app.domain.models import BotState
from app.config import config

router = APIRouter(prefix="/api/v1/bot", tags=["Bot Control"])
bot_state = {"is_running": False, "status": "stopped"}  # compatibility cache only


# 🛠️ تحويل دالة جلب الحالة إلى async
async def _get_state(db: AsyncSession) -> BotState:
    result = await db.execute(select(BotState).filter(BotState.id == 1))
    state = result.scalars().first()
    
    if not state:
        state = BotState(id=1, is_running=False, status="stopped")
        db.add(state)
        await db.commit()
        await db.refresh(state)
    return state


def _authorize_control(x_control_key: str | None):
    if config.require_control_api_key:
        if not config.control_api_key:
            raise HTTPException(503, "Control API is locked: CONTROL_API_KEY is not configured")
        if x_control_key != config.control_api_key:
            raise HTTPException(401, "Invalid control API key")


# 🛠️ تحويل هذه الدالة لـ async (وهذا يتوافق مع ما قمنا به في trading_worker.py)
async def is_bot_running(db: AsyncSession) -> bool:
    state = await _get_state(db)
    bot_state["is_running"] = bool(state.is_running)
    bot_state["status"] = state.status
    return bool(state.is_running)


@router.post("/start")
async def start_bot(
    x_control_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)  # 🛠️ استخدام Depends
):
    _authorize_control(x_control_key)
    try:
        state = await _get_state(db)
        state.is_running = True
        state.status = "running"
        await db.commit()
        bot_state.update(is_running=True, status="running")
        return {"status": "success", "is_running": True, "risk_mode": "strict"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"Error starting bot: {e}")


@router.post("/stop")
async def stop_bot(
    x_control_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)  # 🛠️ استخدام Depends
):
    _authorize_control(x_control_key)
    try:
        state = await _get_state(db)
        state.is_running = False
        state.status = "stopped"
        await db.commit()
        bot_state.update(is_running=False, status="stopped")
        return {"status": "success", "is_running": False}
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"Error stopping bot: {e}")


@router.get("/status")
async def get_bot_status(
    x_control_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db)  # 🛠️ استخدام Depends
):
    # [تحديث أمني]: حماية مسار فحص الحالة لمنع تسريب إعدادات المخاطر للعامة
    _authorize_control(x_control_key)
    try:
        state = await _get_state(db)
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
    except Exception as e:
        raise HTTPException(500, f"Error getting status: {e}")
