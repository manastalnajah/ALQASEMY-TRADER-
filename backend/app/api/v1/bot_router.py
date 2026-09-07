from fastapi import APIRouter, HTTPException

router = APIRouter(
    prefix="/api/v1/bot",
    tags=["Bot Control"]
)

# متغير لحفظ حالة البوت في الذاكرة (يمكن ربطه بقاعدة البيانات لاحقاً)
bot_state = {
    "is_running": False,
    "status": "stopped"
}

@router.post("/start")
async def start_bot():
    bot_state["is_running"] = True
    bot_state["status"] = "running"
    return {
        "status": "success",
        "message": "تم تشغيل روبوت القاسمي بنجاح",
        "is_running": True
    }

@router.post("/stop")
async def stop_bot():
    bot_state["is_running"] = False
    bot_state["status"] = "stopped"
    return {
        "status": "success",
        "message": "تم إيقاف الروبوت",
        "is_running": False
    }

@router.get("/status")
async def get_bot_status():
    return {
        "status": "success",
        "is_running": bot_state["is_running"],
        "current_state": bot_state["status"]
    }
