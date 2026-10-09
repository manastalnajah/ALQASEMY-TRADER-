# ============================================================
# app/repositories/position_command_repo.py
# مستودع أوامر إدارة الصفقات المفتوحة
# ------------------------------------------------------------
# المسؤوليات:
# 1. إدارة أوامر التعديل/الإغلاق في position_management_commands
# 2. إدارة حالة الحماية لكل صفقة في position_management_state
# 3. منع تكرار الأوامر النشطة على الصفقة نفسها
# 4. حفظ القيم المنفذة فعليًا بعد تأكيد EA
# ============================================================

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    PositionManagementCommand,
    PositionManagementState,
)


# ============================================================
# الحالات النهائية لأوامر الإدارة
# ============================================================

FINAL_STATUSES = {
    "executed",
    "failed",
    "cancelled",
    "expired",
    "rejected",
    "ignored",
}

# الحالات النشطة (لا يمكن إنشاء أمر جديد للصفقة أثناء وجودها)
ACTIVE_STATUSES = {"pending", "processing"}

# انتقالات مسموحة لأوامر الإدارة
ALLOWED_TRANSITIONS = {
    "pending":    {"processing", "cancelled", "expired", "ignored"},
    "processing": {"executed", "failed", "rejected", "ignored"},
    "executed":   set(),
    "failed":     set(),
    "cancelled":  set(),
    "expired":    set(),
    "rejected":   set(),
    "ignored":    set(),
}


class PositionCommandRepository:
    """
    مستودع أوامر إدارة الصفقات المفتوحة.

    منفصل تمامًا عن TradeRepository لتقليل المخاطر على مسار فتح الصفقات.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _to_uuid(value) -> Optional[uuid.UUID]:
        """تحويل آمن إلى UUID."""
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _utc_now() -> datetime:
        """الوقت الحالي بتوقيت UTC."""
        return datetime.now(timezone.utc)

    # ============================================================
    # أوامر الإدارة - CREATE
    # ============================================================

    async def create_position_command(
        self,
        *,
        account_id: Optional[uuid.UUID],
        account_number: int,
        ea_id: str,
        position_ticket: int,
        position_identifier: Optional[int],
        symbol: str,
        action: str,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
        close_volume: Optional[float] = None,
        reason: str = "",
        risk_score: Optional[float] = None,
        expires_at: Optional[datetime] = None,
    ) -> Optional[PositionManagementCommand]:
        """
        إنشاء أمر إدارة جديد.

        قبل الإنشاء:
        - نتحقق من عدم وجود أمر نشط على الصفقة نفسها (pending أو processing).
        - إذا وُجد، نُرجع None لمنع التكرار.

        ملاحظة: هذا الفحص وقائي. الحماية النهائية على مستوى قاعدة البيانات
        تُطبّق عبر فهرس مركّب في Migration.
        """
        if position_ticket <= 0:
            return None

        if account_number is None or account_number <= 0:
            return None

        # 1. فحص وجود أمر نشط
        active = await self.get_active_command_for_position(
            account_number=account_number,
            position_ticket=position_ticket,
        )
        if active is not None:
            return None

        # 2. إنشاء السجل الجديد
        command = PositionManagementCommand(
            account_id=self._to_uuid(account_id),
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
            status="pending",
            expires_at=expires_at,
        )

        try:
            self.db.add(command)
            await self.db.commit()
            await self.db.refresh(command)
            return command

        except IntegrityError:
            # سباق تزامن — نتحقق مرة أخرى
            await self.db.rollback()
            active = await self.get_active_command_for_position(
                account_number=account_number,
                position_ticket=position_ticket,
            )
            return active  # None أو الأمر النشط

    # ============================================================
    # أوامر الإدارة - READ
    # ============================================================

    async def get_command_by_id(
        self,
        command_id: str,
    ) -> Optional[PositionManagementCommand]:
        """جلب أمر إدارة بـ UUID."""
        valid_uuid = self._to_uuid(command_id)
        if valid_uuid is None:
            return None

        stmt = select(PositionManagementCommand).filter(
            PositionManagementCommand.id == valid_uuid
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_active_command_for_position(
        self,
        account_number: int,
        position_ticket: int,
    ) -> Optional[PositionManagementCommand]:
        """
        جلب أمر نشط (pending أو processing) لصفقة معينة.

        يُستخدم لمنع إنشاء أمر جديد أثناء وجود أمر قيد التنفيذ.
        """
        if account_number <= 0 or position_ticket <= 0:
            return None

        stmt = (
            select(PositionManagementCommand)
            .filter(
                PositionManagementCommand.account_number == account_number,
                PositionManagementCommand.position_ticket == position_ticket,
                PositionManagementCommand.status.in_(ACTIVE_STATUSES),
            )
            .order_by(PositionManagementCommand.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_pending_commands(
        self,
        account_number: int,
        ea_id: str = "",
        limit: int = 10,
    ) -> list[PositionManagementCommand]:
        """
        جلب أوامر الإدارة المعلقة (pending) للحساب المحدد.

        يُستخدم من EA عند polling.
        """
        if account_number is None or account_number <= 0:
            return []

        safe_limit = min(max(limit, 1), 50)
        now = self._utc_now()

        stmt = (
            select(PositionManagementCommand)
            .filter(
                PositionManagementCommand.status == "pending",
                PositionManagementCommand.account_number == account_number,
            )
        )

        if ea_id:
            stmt = stmt.filter(PositionManagementCommand.ea_id == ea_id)

        # استبعاد الأوامر المنتهية
        stmt = stmt.filter(
            or_(
                PositionManagementCommand.expires_at.is_(None),
                PositionManagementCommand.expires_at > now,
            )
        )

        stmt = stmt.order_by(PositionManagementCommand.created_at.asc()).limit(safe_limit)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ============================================================
    # أوامر الإدارة - CLAIM
    # ============================================================

    async def claim_command(
        self,
        command_id: str,
    ) -> Optional[PositionManagementCommand]:
        """
        حجز أمر الإدارة (pending → processing) بشكل ذرّي.
        """
        valid_uuid = self._to_uuid(command_id)
        if valid_uuid is None:
            return None

        stmt = (
            select(PositionManagementCommand)
            .filter(
                PositionManagementCommand.id == valid_uuid,
                PositionManagementCommand.status == "pending",
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
    # أوامر الإدارة - UPDATE RESULT
    # ============================================================

    async def update_command_result(
        self,
        command_id: str,
        status: str,
        *,
        mt5_retcode: Optional[int] = None,
        error_message: Optional[str] = None,
        executed_sl: Optional[float] = None,
        executed_tp: Optional[float] = None,
    ) -> Optional[PositionManagementCommand]:
        """
        تحديث نتيجة تنفيذ أمر الإدارة.

        - يتحقق من صحة الانتقال.
        - لا يعدّل حالة نهائية.
        - يحفظ القيم المنفذة فعليًا إذا أرسلها EA.
        """
        status_norm = (status or "").lower().strip()
        if status_norm not in ALLOWED_TRANSITIONS:
            return None

        command = await self.get_command_by_id(command_id)
        if not command:
            return None

        current = (command.status or "").lower()

        if current in FINAL_STATUSES:
            return command

        allowed_next = ALLOWED_TRANSITIONS.get(current, set())
        if status_norm not in allowed_next:
            return command

        command.status = status_norm

        if mt5_retcode is not None:
            command.mt5_retcode = mt5_retcode

        if error_message is not None:
            command.error_message = error_message

        if executed_sl is not None:
            command.executed_sl = executed_sl

        if executed_tp is not None:
            command.executed_tp = executed_tp

        await self.db.commit()
        await self.db.refresh(command)
        return command

    # ============================================================
    # أوامر الإدارة - CANCEL EXPIRED
    # ============================================================

    async def expire_stale_commands(
        self,
        older_than_seconds: int = 300,
    ) -> int:
        """
        تعليم الأوامر المعلقة المنتهية كـ expired.

        يفيد في تنظيف الأوامر التي لم يسحبها EA.
        يُستدعى دوريًا عبر مهمة مجدولة.
        """
        from datetime import timedelta

        cutoff = self._utc_now() - timedelta(seconds=older_than_seconds)

        stmt = (
            select(PositionManagementCommand)
            .filter(
                PositionManagementCommand.status == "pending",
                PositionManagementCommand.created_at < cutoff,
            )
        )
        result = await self.db.execute(stmt)
        stale = list(result.scalars().all())

        for cmd in stale:
            cmd.status = "expired"

        if stale:
            await self.db.commit()

        return len(stale)

    # ============================================================
    # حالة الإدارة - UPSERT
    # ============================================================

    async def upsert_state(
        self,
        *,
        account_number: int,
        position_ticket: int,
        symbol: str,
        position_identifier: Optional[int] = None,
        entry_price: Optional[float] = None,
        initial_sl: Optional[float] = None,
        initial_risk: Optional[float] = None,
    ) -> PositionManagementState:
        """
        إنشاء أو تحديث صف حالة الإدارة.

        عند الإنشاء الأول:
        - يُحفظ سعر الدخول والوقف الأصلي والمخاطرة الأصلية.

        عند التحديث اللاحق:
        - لا نلمس initial_sl, initial_risk, entry_price (لأنها تاريخية).
        - نُحدّث position_identifier و symbol.

        ملاحظة: هذا يُنشئ السجل عند أول مشاهدة للصفقة من محرك الإدارة.
        """
        stmt = select(PositionManagementState).filter(
            PositionManagementState.account_number == account_number,
            PositionManagementState.position_ticket == position_ticket,
        )
        result = await self.db.execute(stmt)
        state = result.scalars().first()

        if state is None:
            state = PositionManagementState(
                account_number=account_number,
                position_ticket=position_ticket,
                symbol=symbol,
                position_identifier=position_identifier,
                entry_price=entry_price,
                initial_sl=initial_sl,
                initial_risk=initial_risk,
                max_floating_profit=0.0,
            )
            self.db.add(state)
        else:
            # تحديث حقول متغيرة فقط
            if position_identifier is not None:
                state.position_identifier = position_identifier
            if symbol:
                state.symbol = symbol

            # إذا لم تكن القيم التاريخية محفوظة بعد، نحفظها الآن
            if state.entry_price is None and entry_price is not None:
                state.entry_price = entry_price
            if state.initial_sl is None and initial_sl is not None:
                state.initial_sl = initial_sl
            if state.initial_risk is None and initial_risk is not None:
                state.initial_risk = initial_risk

        await self.db.commit()
        await self.db.refresh(state)
        return state

    # ============================================================
    # حالة الإدارة - GET
    # ============================================================

    async def get_state(
        self,
        account_number: int,
        position_ticket: int,
    ) -> Optional[PositionManagementState]:
        """جلب حالة الإدارة لصفقة."""
        stmt = select(PositionManagementState).filter(
            PositionManagementState.account_number == account_number,
            PositionManagementState.position_ticket == position_ticket,
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_states_for_account(
        self,
        account_number: int,
    ) -> list[PositionManagementState]:
        """جلب جميع حالات الإدارة لحساب."""
        stmt = (
            select(PositionManagementState)
            .filter(PositionManagementState.account_number == account_number)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ============================================================
    # حالة الإدارة - UPDATE PEAK PROFIT
    # ============================================================

    async def update_peak_profit(
        self,
        account_number: int,
        position_ticket: int,
        current_profit: float,
        current_price: Optional[float] = None,
        position_type: str = "BUY",  # ✅ جديد
    ) -> Optional[PositionManagementState]:
        """
        تحديث أعلى ربح عائم مرصود + أعلى سعر مواتٍ.

        - max_floating_profit: يُحدَّث فقط إذا كان current_profit أعلى.
        - max_favorable_price:
            * BUY:  يُحدَّث فقط إذا كان current_price أعلى من المخزون.
            * SELL: يُحدَّث فقط إذا كان current_price أدنى من المخزون.

        ملاحظة: هذه الدالة لا تُخفّض القمم أبدًا.
        """
        state = await self.get_state(account_number, position_ticket)
        if state is None:
            return None

        changed = False

        # -------- max_floating_profit --------
        if current_profit > float(state.max_floating_profit or 0.0):
            state.max_floating_profit = current_profit
            changed = True

        # -------- max_favorable_price --------
        if current_price is not None:
            current_val = float(current_price)
            stored_val = (
                float(state.max_favorable_price)
                if state.max_favorable_price is not None
                else None
            )

            pos_type = (position_type or "BUY").upper()

            if stored_val is None:
                # أول تسجيل
                state.max_favorable_price = current_val
                changed = True
            elif pos_type == "BUY":
                # BUY: القمة هي الأعلى
                if current_val > stored_val:
                    state.max_favorable_price = current_val
                    changed = True
            elif pos_type == "SELL":
                # SELL: القمة هي الأدنى
                if current_val < stored_val:
                    state.max_favorable_price = current_val
                    changed = True

        if changed:
            await self.db.commit()
            await self.db.refresh(state)

        return state
    # ============================================================
    # حالة الإدارة - UPDATE FLAGS
    # ============================================================

    async def mark_break_even_activated(
        self,
        account_number: int,
        position_ticket: int,
    ) -> Optional[PositionManagementState]:
        """تعليم تفعيل Break-Even."""
        state = await self.get_state(account_number, position_ticket)
        if state is None:
            return None

        if not state.break_even_activated:
            state.break_even_activated = True
            state.last_management_action = "MOVE_TO_BREAKEVEN"
            state.last_action_at = self._utc_now()
            await self.db.commit()
            await self.db.refresh(state)

        return state

    async def mark_profit_lock_activated(
        self,
        account_number: int,
        position_ticket: int,
    ) -> Optional[PositionManagementState]:
        """تعليم تفعيل Profit Lock."""
        state = await self.get_state(account_number, position_ticket)
        if state is None:
            return None

        if not state.profit_lock_activated:
            state.profit_lock_activated = True
            state.last_management_action = "PROFIT_LOCK"
            state.last_action_at = self._utc_now()
            await self.db.commit()
            await self.db.refresh(state)

        return state

    async def mark_trailing_activated(
        self,
        account_number: int,
        position_ticket: int,
    ) -> Optional[PositionManagementState]:
        """تعليم تفعيل Trailing."""
        state = await self.get_state(account_number, position_ticket)
        if state is None:
            return None

        if not state.trailing_activated:
            state.trailing_activated = True
            state.last_management_action = "TRAILING_STOP"
            state.last_action_at = self._utc_now()
            await self.db.commit()
            await self.db.refresh(state)

        return state

    async def mark_close_attempt(
        self,
        account_number: int,
        position_ticket: int,
    ) -> Optional[PositionManagementState]:
        """تسجيل محاولة إغلاق (لمنع تكرار المحاولات)."""
        state = await self.get_state(account_number, position_ticket)
        if state is None:
            return None

        state.last_close_attempt = self._utc_now()
        state.last_management_action = "CLOSE_POSITION"
        state.last_action_at = self._utc_now()
        await self.db.commit()
        await self.db.refresh(state)
        return state

    # ============================================================
    # حالة الإدارة - DELETE (بعد إغلاق الصفقة)
    # ============================================================

    async def delete_state(
        self,
        account_number: int,
        position_ticket: int,
    ) -> bool:
        """
        حذف حالة إدارة صفقة (بعد تأكيد إغلاقها).

        يُستدعى من مزامنة الصفقات عند اكتشاف صفقة مغلقة.
        """
        state = await self.get_state(account_number, position_ticket)
        if state is None:
            return False

        await self.db.delete(state)
        await self.db.commit()
        return True

    async def cleanup_states_for_closed_positions(
        self,
        account_number: int,
        open_tickets: set[int],
    ) -> int:
        """
        حذف حالات إدارة الصفقات التي لم تعد مفتوحة.

        ⚠️ يجب استدعاء هذه الدالة فقط بعد التأكد من أن قائمة
        open_tickets تمثل لقطة كاملة لجميع صفقات الحساب المفتوحة.
        وإلا، قد نحذف حالة صفقة لا تزال مفتوحة.
        """
        if not open_tickets:
            # لا نحذف شيئًا إذا كانت القائمة فارغة (لتفادي خطأ الإفراغ الكامل)
            return 0

        states = await self.get_states_for_account(account_number)
        deleted = 0

        for state in states:
            if state.position_ticket not in open_tickets:
                await self.db.delete(state)
                deleted += 1

        if deleted:
            await self.db.commit()

        return deleted
