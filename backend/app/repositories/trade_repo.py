# ============================================================
# app/repositories/trade_repo.py
# النسخة المعدلة — V2
# تدعم: ربط الحساب، منع التكرار، انتقالات حالات صريحة،
#        تحديث نتيجة التنفيذ، جلب أمر بـ id
# ============================================================

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import TradeCommand
from app.domain.schemas import CommandCreate
from app.domain.interfaces.trade_repo_interface import ITradeRepository


# ============================================================
# انتقالات الحالات المسموحة
# يمنع تغيير حالة نهائية إلى حالة أخرى بالخطأ
# ============================================================

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending":    {"processing", "cancelled", "expired", "ignored"},
    "processing": {"executed", "partial", "placed", "failed", "rejected", "ignored"},
    "placed":     {"executed", "partial", "failed", "cancelled", "expired"},
    "partial":    {"executed", "failed", "cancelled"},
    "executed":   set(),   # نهائية
    "failed":     set(),   # نهائية
    "cancelled":  set(),   # نهائية
    "expired":    set(),   # نهائية
    "ignored":    set(),   # نهائية
    "rejected":   set(),   # نهائية
}

# الحالات النهائية (لأغراض الاستعلام)
FINAL_STATUSES = {"executed", "failed", "cancelled", "expired", "ignored", "rejected"}


class TradeRepository(ITradeRepository):
    """
    مستودع أوامر التداول (فتح صفقات جديدة).

    ملاحظة:
    - أوامر إدارة الصفقات المفتوحة (تعديل SL/TP، الإغلاق) لها مستودع منفصل:
      PositionCommandRepository (سيُضاف لاحقًا).
    - هذا المستودع مسؤول فقط عن trade_commands.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============================================================
    # CREATE
    # ============================================================

    async def create_trade_command(self, command: CommandCreate) -> TradeCommand:
        """
        إنشاء أمر تداول جديد مع حماية مطلقة ضد التكرار (Idempotency).

        خطوات:
        1. فحص مسبق: هل الأمر موجود بنفس (account_id, signal_key)؟
        2. إن لم يوجد، إنشاء السجل الجديد.
        3. عند IntegrityError (سباق تزامن)، إعادة القراءة وإرجاع السجل الموجود.

        ملاحظة: القيد الفريد موجود في قاعدة البيانات كفهرس جزئي
        يستثني account_id = NULL. لذلك الفحص المسبق مهم للأوامر اليدوية.
        """
        # --------------------------------------------------------
        # 1. فحص مسبق للأوامر المرتبطة بحساب
        # --------------------------------------------------------
        if command.account_id is not None and command.signal_key:
            existing = await self._find_by_account_and_signal(
                account_id=command.account_id,
                signal_key=command.signal_key,
            )
            if existing:
                return existing

        # --------------------------------------------------------
        # 2. إنشاء السجل الجديد
        # --------------------------------------------------------
        db_command = TradeCommand(
            account_id=command.account_id,
            account_number=command.account_number,   # ✅ جديد
            symbol=command.symbol.upper(),
            order_type=command.order_type.upper(),
            lot_size=command.lot_size,
            entry_price=command.entry_price,
            stop_loss=command.stop_loss,
            take_profit=command.take_profit,
            status="pending",
            strategy_name=command.strategy_name,
            signal_key=command.signal_key,
            ea_id=command.ea_id,
        )

        try:
            self.db.add(db_command)
            await self.db.commit()
            await self.db.refresh(db_command)
            return db_command

        except IntegrityError:
            # ----------------------------------------------------
            # 3. شبكة أمان: سباق تزامن بين عمليتين
            # ----------------------------------------------------
            await self.db.rollback()

            if command.account_id is not None and command.signal_key:
                existing = await self._find_by_account_and_signal(
                    account_id=command.account_id,
                    signal_key=command.signal_key,
                )
                if existing:
                    return existing

            raise

    async def _find_by_account_and_signal(
        self,
        account_id: uuid.UUID,
        signal_key: str,
    ) -> Optional[TradeCommand]:
        """بحث داخلي عن أمر بنفس (account_id, signal_key)."""
        stmt = select(TradeCommand).filter(
            TradeCommand.account_id == account_id,
            TradeCommand.signal_key == signal_key,
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    # ============================================================
    # READ
    # ============================================================

    async def get_command_by_id(
        self,
        command_id: str,
    ) -> Optional[TradeCommand]:
        """
        جلب أمر بـ UUID.

        يُستخدم في ACK و Report للتحقق من وجود الأمر قبل التحديث.
        """
        try:
            valid_uuid = uuid.UUID(command_id)
        except (ValueError, AttributeError):
            return None

        stmt = select(TradeCommand).filter(TradeCommand.id == valid_uuid)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_pending_commands(
        self,
        account_number: int,
        ea_id: str = "",
        limit: int = 10,
    ) -> list[TradeCommand]:
        """
        جلب الأوامر المعلقة (status=pending) للحساب المحدد.

        ⚠️ مهم: account_number إلزامي لمنع ظهور أوامر حساب آخر.

        ملاحظة: إذا كان ea_id فارغًا، لا نُصفّي به.
        لكن account_number يبقى إلزاميًا.
        """
        if account_number is None or account_number <= 0:
            # حماية: لا نُرجع أي أوامر دون حساب صريح
            return []

        safe_limit = min(max(limit, 1), 50)

        stmt = (
            select(TradeCommand)
            .filter(TradeCommand.status == "pending")
            .filter(TradeCommand.account_number == account_number)
        )

        if ea_id:
            stmt = stmt.filter(TradeCommand.ea_id == ea_id)

        stmt = stmt.order_by(TradeCommand.created_at.asc()).limit(safe_limit)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ============================================================
    # CLAIM
    # ============================================================

    async def claim_command(self, command_id: str) -> Optional[TradeCommand]:
        """
        حجز الأمر (تحويله من pending إلى processing) بشكل ذرّي.

        يستخدم with_for_update(skip_locked=True) لمنع نسختين من
        استلام الأمر نفسه.

        ⚠️ لا يتحقق من account_number — يجب أن يتحقق API من ذلك قبله.
        """
        try:
            valid_uuid = uuid.UUID(command_id)
        except (ValueError, AttributeError):
            return None

        stmt = (
            select(TradeCommand)
            .filter(
                TradeCommand.id == valid_uuid,
                TradeCommand.status == "pending",
            )
            .with_for_update(skip_locked=True)
        )

        result = await self.db.execute(stmt)
        command = result.scalars().first()

        if not command:
            return None

        command.status = "processing"
        await self.db.commit()
        await self.db.refresh(command)
        return command

    # ============================================================
    # UPDATE STATUS (مع تحقق من الانتقال)
    # ============================================================

    async def update_command_status(
        self,
        command_id: str,
        new_status: str,
    ) -> Optional[TradeCommand]:
        """
        تحديث حالة الأمر مع التحقق من صحة الانتقال.

        يمنع مثلًا: executed → pending، أو failed → executed.

        ملاحظة:
        - إذا كانت الحالة الجديدة غير معروفة، لا يتم التحديث.
        - إذا لم يكن الانتقال مسموحًا، لا يتم التحديث.
        - إذا لم يوجد الأمر، يُرجع None.
        """
        status = (new_status or "").lower().strip()

        if status not in ALLOWED_TRANSITIONS:
            return None

        command = await self.get_command_by_id(command_id)
        if not command:
            return None

        current = (command.status or "").lower()

        # إذا كانت الحالة الحالية نهائية، لا نسمح بتغييرها
        if current in FINAL_STATUSES:
            return command  # نُرجع الحالة الحالية دون تغيير

        allowed_next = ALLOWED_TRANSITIONS.get(current, set())
        if status not in allowed_next:
            # انتقال غير مسموح — نُرجع الأمر كما هو دون تعديل
            return command

        command.status = status
        await self.db.commit()
        await self.db.refresh(command)
        return command

    # ============================================================
    # UPDATE RESULT (نتيجة التنفيذ الكاملة)
    # ============================================================

    async def update_command_result(
        self,
        command_id: str,
        status: str,
        mt5_ticket: Optional[int] = None,
        mt5_order_ticket: Optional[int] = None,
        mt5_deal_ticket: Optional[int] = None,
        fill_price: Optional[float] = None,
        executed_volume: Optional[float] = None,
        mt5_retcode: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> Optional[TradeCommand]:
        """
        تحديث الأمر بنتيجة التنفيذ الفعلية.

        يجمع كل الحقول التي قد يرسلها EA في تقرير واحد.

        انتقال الحالة محكوم بنفس قواعد update_command_status.
        """
        status_norm = (status or "").lower().strip()
        if status_norm not in ALLOWED_TRANSITIONS:
            return None

        command = await self.get_command_by_id(command_id)
        if not command:
            return None

        current = (command.status or "").lower()

        # لا نغيّر حالة نهائية
        if current in FINAL_STATUSES:
            return command

        # التحقق من الانتقال
        allowed_next = ALLOWED_TRANSITIONS.get(current, set())
        if status_norm not in allowed_next:
            return command

        command.status = status_norm

        # حقول اختيارية
        if mt5_ticket is not None:
            command.mt5_ticket = mt5_ticket

        if mt5_order_ticket is not None:
            command.mt5_order_ticket = mt5_order_ticket

        if mt5_deal_ticket is not None:
            command.mt5_deal_ticket = mt5_deal_ticket

        if fill_price is not None:
            command.fill_price = fill_price

        if executed_volume is not None:
            command.executed_volume = executed_volume

        if mt5_retcode is not None:
            command.mt5_retcode = mt5_retcode

        if error_message is not None:
            command.error_message = error_message

        await self.db.commit()
        await self.db.refresh(command)
        return command
