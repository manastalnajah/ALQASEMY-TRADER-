# ============================================================
# app/services/trade_service.py
# النسخة المعدلة — V2
# ------------------------------------------------------------
# مسؤوليات هذا الملف:
# 1. process_new_command()     → إنشاء أوامر فتح صفقات جديدة
# 2. process_position_command() → إنشاء أوامر إدارة صفقات مفتوحة
#
# ⚠️ ملاحظة معمارية:
# - المسارَان منفصلان تمامًا.
# - لا تُضاف أنواع أوامر الإدارة إلى VALID_TYPES.
# - محرك المخاطر validate_and_size مخصص لفتح الصفقات فقط.
# ============================================================

import time

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.domain import schemas
from app.logging.logger import system_logger
from app.repositories.trade_repo import TradeRepository
from app.repositories.position_command_repo import PositionCommandRepository
from app.services.risk_manager import validate_and_size


# ============================================================
# ثوابت
# ============================================================

# أنواع أوامر فتح الصفقات
VALID_TYPES = {
    "BUY",
    "SELL",
    "BUY_LIMIT",
    "SELL_LIMIT",
    "BUY_STOP",
    "SELL_STOP",
}

# أنواع أوامر إدارة الصفقات المفتوحة
ALLOWED_POSITION_ACTIONS = {
    "MODIFY_SL_TP",
    "CLOSE_POSITION",
    "PARTIAL_CLOSE",
    "MOVE_TO_BREAKEVEN",
    "TRAILING_STOP",
}


# ============================================================
# HELPERS
# ============================================================

async def resolve_account_number(
    db: AsyncSession,
    account_id: str,
) -> int | None:
    """
    استرجاع account_number من trading_accounts بناءً على account_id (UUID).

    يُستخدم للأوامر اليدوية القادمة من التطبيق عندما لا يُرسل
    account_number صراحةً.
    """
    if not account_id:
        return None

    query = text(
        "SELECT account_number FROM trading_accounts "
        "WHERE id = CAST(:acc_id AS UUID)"
    )
    result = await db.execute(query, {"acc_id": account_id})
    row = result.fetchone()
    return int(row[0]) if row and row[0] else None


# ============================================================
# NEW COMMAND — فتح صفقات جديدة
# ============================================================

async def process_new_command(
    db: AsyncSession,
    command: schemas.CommandCreate,
    account_id: str,
    *,
    enforce_risk: bool = True,
):
    """
    معالجة أمر تداول جديد (فتح صفقة أو أمر معلق).

    الخطوات:
    1. توحيد اسم الرمز ونوع الأمر.
    2. ربط الأمر بالحساب.
    3. استرجاع account_number عند الحاجة.
    4. التحقق من نوع الأمر وSL/TP/entry.
    5. تأمين signal_key للأوامر اليدوية.
    6. تشغيل محرك المخاطر (يحدد lot_size النهائي).
    7. حفظ الأمر في قاعدة البيانات.
    """
    command.symbol = command.symbol.upper()
    command.order_type = command.order_type.upper()
    command.account_id = account_id

    # --------------------------------------------------------
    # شبكة الأمان: ضمان وجود account_number
    # --------------------------------------------------------
    if not command.account_number:
        resolved = await resolve_account_number(db, account_id)
        if resolved:
            command.account_number = resolved
        else:
            system_logger.warning(
                "⚠️ Could not auto-resolve account_number for account_id=%s",
                account_id,
            )

    # --------------------------------------------------------
    # تحقق أساسي
    # --------------------------------------------------------
    if command.order_type not in VALID_TYPES:
        raise HTTPException(400, "نوع الأمر غير مسموح")

    if command.entry_price <= 0 or command.stop_loss <= 0 or command.take_profit <= 0:
        raise HTTPException(400, "SL وTP وسعر الدخول مطلوبة ولا يجوز أن تكون صفراً")

    if command.lot_size <= 0:
        raise HTTPException(400, "حجم اللوت يجب أن يكون أكبر من صفر")

    # --------------------------------------------------------
    # تأمين signal_key للأوامر اليدوية
    # --------------------------------------------------------
    if not command.signal_key:
        timestamp = int(time.time())
        command.signal_key = (
            f"manual:{command.symbol}:{command.order_type}:"
            f"{command.entry_price:.5f}:{timestamp}"
        )

    # --------------------------------------------------------
    # محرك المخاطر (مصدر lot_size النهائي)
    # --------------------------------------------------------
    if enforce_risk:
        sized, reason = await validate_and_size(
            db,
            account_id=account_id,
            symbol=command.symbol,
            order_type=command.order_type,
            entry=command.entry_price,
            stop=command.stop_loss,
            target=command.take_profit,
            signal_key=command.signal_key,
        )
        if not sized:
            system_logger.warning(
                "🛑 رفض أمر %s %s: %s",
                command.order_type, command.symbol, reason,
            )
            raise HTTPException(409, f"Trade blocked by risk engine: {reason}")

        command.lot_size = float(sized["lot_size"])
        if command.lot_size <= 0:
            raise HTTPException(409, "Trade blocked: calculated risk size is zero")

    # --------------------------------------------------------
    # الحفظ
    # --------------------------------------------------------
    repo = TradeRepository(db)
    try:
        command_obj = await repo.create_trade_command(command)

        system_logger.info(
            "✅ Command created: %s %s %.4f for account %s (Acc Num: %s)",
            command.symbol,
            command.order_type,
            command.lot_size,
            account_id,
            command.account_number,
        )
        return command_obj

    except Exception as e:
        await db.rollback()
        system_logger.error("❌ Failed to save command: %s", str(e))
        raise HTTPException(500, "Failed to save command to database")


# ============================================================
# POSITION COMMAND — إدارة صفقات مفتوحة
# ============================================================

async def validate_position_action(
    action: str,
    new_sl: float | None,
    new_tp: float | None,
    close_volume: float | None,
) -> None:
    """
    التحقق من صلاحية أمر الإدارة قبل إنشائه.

    - MODIFY_SL_TP:      يجب أن يحتوي على new_sl أو new_tp على الأقل.
    - MOVE_TO_BREAKEVEN: يجب أن يحتوي على new_sl.
    - TRAILING_STOP:     يجب أن يحتوي على new_sl.
    - CLOSE_POSITION:    لا يحتاج قيمًا.
    - PARTIAL_CLOSE:     يجب أن يحتوي على close_volume > 0.
    """
    action = (action or "").upper().strip()

    if action not in ALLOWED_POSITION_ACTIONS:
        raise HTTPException(400, f"نوع أمر الإدارة غير مسموح: {action}")

    if action in ("MODIFY_SL_TP",):
        if new_sl is None and new_tp is None:
            raise HTTPException(
                400, "MODIFY_SL_TP يتطلب new_sl أو new_tp على الأقل"
            )

    if action in ("MOVE_TO_BREAKEVEN", "TRAILING_STOP"):
        if new_sl is None:
            raise HTTPException(400, f"{action} يتطلب new_sl")

    if action == "PARTIAL_CLOSE":
        if close_volume is None or close_volume <= 0:
            raise HTTPException(400, "PARTIAL_CLOSE يتطلب close_volume > 0")

    if new_sl is not None and new_sl <= 0:
        raise HTTPException(400, "new_sl يجب أن يكون أكبر من صفر")

    if new_tp is not None and new_tp <= 0:
        raise HTTPException(400, "new_tp يجب أن يكون أكبر من صفر")

    if close_volume is not None and close_volume <= 0:
        raise HTTPException(400, "close_volume يجب أن يكون أكبر من صفر")


async def process_position_command(
    db: AsyncSession,
    *,
    account_id: str,
    account_number: int,
    ea_id: str,
    position_ticket: int,
    position_identifier: int | None = None,
    symbol: str,
    action: str,
    new_sl: float | None = None,
    new_tp: float | None = None,
    close_volume: float | None = None,
    reason: str = "",
    risk_score: float | None = None,
    expires_at=None,
) -> schemas.PositionManagementCommandResponse | None:
    """
    معالجة أمر إدارة صفقة مفتوحة.

    الخطوات:
    1. توحيد action إلى أحرف كبيرة.
    2. التحقق من نوع الأمر والحقول المطلوبة.
    3. التحقق من عدم وجود أمر نشط على الصفقة (في المستودع).
    4. حفظ الأمر في position_management_commands.

    ⚠️ لا يُشغَّل محرك المخاطر هنا.
    ⚠️ التحقق من أن الصفقة لا تزال مفتوحة يتم في محرك الإدارة
        قبل الاستدعاء، ومرة أخرى في EA عند التنفيذ.

    Returns:
        PositionManagementCommandResponse إذا نجح الإنشاء.
        None إذا وُجد أمر نشط مسبقًا (يُتجاهل بصمت).
    """
    action = (action or "").upper().strip()
    symbol = (symbol or "").upper().strip()

    # --------------------------------------------------------
    # 1. تحقق أولي
    # --------------------------------------------------------
    if position_ticket <= 0:
        raise HTTPException(400, "position_ticket غير صالح")

    if account_number is None or account_number <= 0:
        raise HTTPException(400, "account_number غير صالح")

    if not symbol:
        raise HTTPException(400, "symbol مطلوب")

    await validate_position_action(action, new_sl, new_tp, close_volume)

    # --------------------------------------------------------
    # 2. استرجاع account_id إذا كان مفقودًا
    # --------------------------------------------------------
    if not account_id:
        # نحاول استرجاعه من account_number
        query = text(
            "SELECT id FROM trading_accounts "
            "WHERE account_number = CAST(:acc_num AS BIGINT) LIMIT 1"
        )
        result = await db.execute(query, {"acc_num": account_number})
        row = result.fetchone()
        if row:
            account_id = str(row[0])

    # --------------------------------------------------------
    # 3. الإنشاء عبر المستودع
    # --------------------------------------------------------
    repo = PositionCommandRepository(db)

    try:
        command_obj = await repo.create_position_command(
            account_id=account_id,
            account_number=account_number,
            ea_id=ea_id or "",
            position_ticket=position_ticket,
            position_identifier=position_identifier,
            symbol=symbol,
            action=action,
            new_sl=new_sl,
            new_tp=new_tp,
            close_volume=close_volume,
            reason=reason or "",
            risk_score=risk_score,
            expires_at=expires_at,
        )

        if command_obj is None:
            # أمر نشط موجود مسبقًا — نتجاهل بصمت
            system_logger.info(
                "ℹ️ Position command already active for ticket=%s action=%s",
                position_ticket, action,
            )
            return None

        system_logger.info(
            "✅ Position command created: %s ticket=%s for account %s",
            action, position_ticket, account_number,
        )

        # تحويل إلى نموذج الاستجابة
        return _to_response(command_obj)

    except Exception as e:
        await db.rollback()
        system_logger.error(
            "❌ Failed to create position command: %s", str(e),
        )
        raise HTTPException(500, "Failed to create position command")


def _to_response(
    cmd,
) -> schemas.PositionManagementCommandResponse:
    """
    تحويل ORM إلى Response schema.

    يُستخدم من process_position_command و mt5_router.
    """
    created_epoch = None
    expires_epoch = None

    if cmd.created_at:
        try:
            created_epoch = cmd.created_at.timestamp()
        except Exception:
            created_epoch = None

    if cmd.expires_at:
        try:
            expires_epoch = cmd.expires_at.timestamp()
        except Exception:
            expires_epoch = None

    return schemas.PositionManagementCommandResponse(
        id=cmd.id,
        command_id=str(cmd.id),
        account_number=cmd.account_number,
        ea_id=cmd.ea_id or "",
        position_ticket=cmd.position_ticket,
        position_identifier=cmd.position_identifier,
        symbol=cmd.symbol,
        action=cmd.action,
        new_sl=cmd.new_sl,
        new_tp=cmd.new_tp,
        close_volume=cmd.close_volume,
        reason=cmd.reason or "",
        status=cmd.status or "pending",
        created_at=cmd.created_at,
        created_epoch=created_epoch,
        expires_at=cmd.expires_at,
        expires_epoch=expires_epoch,
    )
