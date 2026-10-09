# ============================================================
# app/services/position_manager_worker.py
# عامل خلفي لتشغيل SmartPositionManager دوريًا
# ------------------------------------------------------------
# - يعمل كل N ثوانٍ (افتراضي 5).
# - يمر على جميع الحسابات النشطة.
# - يُنشئ أوامر إدارة عند الحاجة.
# - يمكن تعطيله عبر ENABLE_POSITION_MANAGER=false
# ============================================================

import asyncio
import logging
import os

from sqlalchemy import text

from database import AsyncSessionLocal
from app.services.position_manager import SmartPositionManager


logger = logging.getLogger("PositionManagerWorker")


# ------------------------------------------------------------
# الإعدادات
# ------------------------------------------------------------
POSITION_MANAGER_INTERVAL = int(
    os.getenv("POSITION_MANAGER_INTERVAL", "5")
)

ENABLE_POSITION_MANAGER = (
    os.getenv("ENABLE_POSITION_MANAGER", "true").lower() == "true"
)


async def run_position_management_once():
    """
    تشغيل دورة واحدة من محرك الإدارة لجميع الحسابات النشطة.
    """
    async with AsyncSessionLocal() as db:
        try:
            # جلب الحسابات النشطة
            accounts = (await db.execute(text("""
                SELECT account_number, ea_id
                FROM trading_accounts
                WHERE is_active = true
                  AND is_trade_allowed = true
                  AND is_connected = true
            """))).mappings().all()

            if not accounts:
                return

            manager = SmartPositionManager(db)

            for acc in accounts:
                try:
                    summary = await manager.run_for_account(
                        account_number=acc["account_number"],
                        ea_id=acc["ea_id"] or "",
                    )

                    if summary["commands_created"] > 0:
                        logger.info(
                            "✅ Position manager created %d commands "
                            "for account %s (analyzed=%d, skipped=%d)",
                            summary["commands_created"],
                            acc["account_number"],
                            summary["analyzed"],
                            summary["skipped"],
                        )

                    if summary["errors"]:
                        for err in summary["errors"][:3]:
                            logger.warning(
                                "Position manager error for account %s: %s",
                                acc["account_number"], err,
                            )

                except Exception as exc:
                    logger.exception(
                        "Position manager failed for account %s: %s",
                        acc["account_number"], exc,
                    )

        except Exception as exc:
            logger.exception("Position manager loop failed: %s", exc)


async def start_position_manager_worker():
    """
    حلقة لا نهائية تشغّل محرك الإدارة كل N ثانية.
    """
    if not ENABLE_POSITION_MANAGER:
        logger.info(
            "⏸️  Position manager worker DISABLED "
            "(ENABLE_POSITION_MANAGER=false)"
        )
        return

    logger.info(
        "🚀 Position manager worker started (interval=%ds)",
        POSITION_MANAGER_INTERVAL,
    )

    while True:
        try:
            await run_position_management_once()
        except asyncio.CancelledError:
            logger.info("Position manager worker cancelled")
            raise
        except Exception as exc:
            logger.exception(
                "Position manager iteration failed: %s", exc
            )

        try:
            await asyncio.sleep(POSITION_MANAGER_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Position manager worker cancelled during sleep")
            raise
