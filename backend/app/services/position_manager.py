# ============================================================
# app/services/position_manager.py
# محرك إدارة الصفقات المفتوحة (Smart Position Manager)
# ------------------------------------------------------------
# المسؤوليات:
# 1. جلب الصفقات المفتوحة للحساب
# 2. تحميل/تحديث PositionManagementState لكل صفقة
# 3. تطبيق قواعد الحماية:
#    - Break-Even
#    - Profit Lock
#    - ATR Trailing Stop
#    - TP Progress Protection
#    - Profit Giveback Protection
#    - Early Reversal Detection
# 4. إنشاء أوامر إدارة عبر process_position_command()
# 5. منع تكرار الأوامر على نفس الصفقة
#
# ⚠️ هذا الملف لا ينفذ أوامر MT5 مباشرة.
#    هو يُنشئ أوامر في قاعدة البيانات، و EA هو من ينفذها.
# ============================================================

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import OpenPosition, PositionManagementState
from app.domain.schemas import PositionRiskAnalysis
from app.repositories.position_command_repo import PositionCommandRepository
from app.services.position_risk_analyzer import PositionRiskAnalyzer
from app.services import trade_service


logger = logging.getLogger("AlqasemyTrader.PositionManager")


# ============================================================
# إعدادات الحماية حسب الرمز
# يمكن نقلها لاحقًا إلى config أو قاعدة البيانات
# ============================================================

PROTECTION_SETTINGS = {
    "XAUUSD": {
        "break_even_r": 0.80,
        "profit_lock_r": 1.20,
        "min_profit_lock_r": 0.30,
        "trailing_start_r": 1.50,
        "atr_multiplier": 2.00,
        "atr_period": 14,
        "tp_protection_pct": 0.70,
        "giveback_activation_r": 1.00,
        "max_giveback_r": 0.60,
        "reversal_activation_r": 0.80,
        "reversal_min_score": 70,
        "default_rsi_period": 14,
        "default_ema_period": 20,
    },
    "EURUSD": {
        "break_even_r": 0.70,
        "profit_lock_r": 1.00,
        "min_profit_lock_r": 0.25,
        "trailing_start_r": 1.30,
        "atr_multiplier": 1.50,
        "atr_period": 14,
        "tp_protection_pct": 0.75,
        "giveback_activation_r": 0.80,
        "max_giveback_r": 0.50,
        "reversal_activation_r": 0.70,
        "reversal_min_score": 70,
        "default_rsi_period": 14,
        "default_ema_period": 20,
    },
}

# إعدادات افتراضية إذا لم يوجد الرمز
DEFAULT_SETTINGS = PROTECTION_SETTINGS["EURUSD"]


# ============================================================
# إعدادات عامة
# ============================================================

# فترة صلاحية أمر الإدارة (بالثواني)
COMMAND_TTL_SECONDS = 60

# الحد الأدنى للتغيير في SL قبل إنشاء أمر جديد (بالنسبة المئوية من المسافة)
MIN_SL_CHANGE_PCT = 0.10

# مهلة بين محاولات الإغلاق على نفس الصفقة
CLOSE_RETRY_COOLDOWN_SECONDS = 15

# فاصل زمني بين عمليات التحليل لنفس الصفقة
ANALYSIS_COOLDOWN_SECONDS = 5


# ============================================================
# المحرك الرئيسي
# ============================================================

class SmartPositionManager:
    """
    محرك إدارة الصفقات المفتوحة.

    الاستخدام:
        manager = SmartPositionManager(db)
        await manager.run_for_account(account_number=112779425)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.risk_analyzer = PositionRiskAnalyzer(db)
        self.command_repo = PositionCommandRepository(db)

    # ============================================================
    # نقطة الدخول الرئيسية
    # ============================================================

    async def run_for_account(
        self,
        account_number: int,
        ea_id: str = "",
    ) -> dict:
        """
        تشغيل دورة إدارة كاملة لحساب واحد.

        الخطوات:
        1. جلب الصفقات المفتوحة من قاعدة البيانات.
        2. لكل صفقة: تحديث الحالة → تحليل → اتخاذ قرار → إنشاء أمر.
        3. تنظيف حالات الصفقات المغلقة.

        Returns:
            dict ملخص: {"analyzed": N, "commands_created": M, "errors": [...]}
        """
        summary = {
            "analyzed": 0,
            "commands_created": 0,
            "skipped": 0,
            "errors": [],
        }

        if account_number is None or account_number <= 0:
            return summary

        # --------------------------------------------------------
        # 1. جلب الصفقات المفتوحة
        # --------------------------------------------------------
        positions = await self._fetch_open_positions(account_number)

        if not positions:
            # تنظيف أي حالات متبقية
            await self.command_repo.cleanup_states_for_closed_positions(
                account_number=account_number,
                open_tickets=set(),
            )
            return summary

        open_tickets = {int(p.ticket) for p in positions}

        # --------------------------------------------------------
        # 2. لكل صفقة
        # --------------------------------------------------------
        for pos in positions:
            try:
                result = await self._process_position(
                    position=pos,
                    account_number=account_number,
                    ea_id=ea_id,
                )
                summary["analyzed"] += 1

                if result == "created":
                    summary["commands_created"] += 1
                elif result == "skipped":
                    summary["skipped"] += 1

            except Exception as exc:
                logger.exception(
                    "Error processing position %s: %s",
                    pos.ticket, exc,
                )
                summary["errors"].append(f"ticket={pos.ticket}: {exc}")

        # --------------------------------------------------------
        # 3. تنظيف حالات الصفقات المغلقة
        # --------------------------------------------------------
        try:
            await self.command_repo.cleanup_states_for_closed_positions(
                account_number=account_number,
                open_tickets=open_tickets,
            )
        except Exception as exc:
            logger.warning("Cleanup failed: %s", exc)

        return summary

    # ============================================================
    # جلب الصفقات
    # ============================================================

        async def _fetch_open_positions(
        self,
        account_number: int,
    ) -> list[OpenPosition]:
        """
        جلب الصفقات المفتوحة للحساب من قاعدة البيانات.

        ⚠️ مهم: PostgreSQL NUMERIC يُرجع decimal.Decimal في Python.
        نحول كل القيم الرقمية إلى float لتفادي أخطاء:
            TypeError: unsupported operand type(s) for +: 'Decimal' and 'float'
        """
        stmt = text("""
            SELECT ticket, account_number, symbol, position_type,
                   volume, open_price, current_price, sl, tp, profit,
                   identifier, magic, open_time
            FROM open_positions
            WHERE account_number = :acc
              AND symbol IN ('XAUUSD', 'EURUSD')
        """)
        result = await self.db.execute(stmt, {"acc": account_number})
        rows = result.mappings().all()

        # تحويل إلى كائنات بسيطة (لا نستخدم ORM هنا لأن الاستعلام مخصص)
        positions = []
        for row in rows:
            pos = OpenPosition()
            pos.ticket = int(row["ticket"])
            pos.account_number = int(row["account_number"])
            pos.symbol = str(row["symbol"])
            pos.position_type = str(row["position_type"])

            # ✅ تحويل صريح إلى float (Decimal → float)
            pos.volume = self._safe_float(row["volume"])
            pos.open_price = self._safe_float(row["open_price"])
            pos.current_price = self._safe_float(row["current_price"])
            pos.sl = self._safe_float(row["sl"])
            pos.tp = self._safe_float(row["tp"])
            pos.profit = self._safe_float(row["profit"])

            pos.identifier = row.get("identifier")
            pos.magic = row.get("magic")
            pos.open_time = row.get("open_time")

            positions.append(pos)

        return positions
    # ============================================================
    # معالجة صفقة واحدة
    # ============================================================

    async def _process_position(
        self,
        *,
        position: OpenPosition,
        account_number: int,
        ea_id: str,
    ) -> str:
        """
        معالجة صفقة واحدة.

        Returns:
            "created" إذا أُنشئ أمر إدارة
            "skipped" إذا لم يُتخذ إجراء
            "active"  إذا وُجد أمر نشط مسبقًا
        """
        ticket = int(position.ticket)
        symbol = str(position.symbol or "").upper()
        side = self._normalize_side(position.position_type)

        if side not in ("BUY", "SELL"):
            return "skipped"

        # --------------------------------------------------------
        # 1. جلب/تحديث حالة الإدارة
        # --------------------------------------------------------
        entry = self._safe_float(position.open_price)
        current = self._safe_float(position.current_price) or entry
        sl = self._safe_float(position.sl)
        tp = self._safe_float(position.tp)
        profit = self._safe_float(position.profit)

        # حساب المخاطرة الأصلية
        initial_risk = self._calculate_initial_risk(
            side=side,
            entry=entry,
            sl=sl,
            volume=self._safe_float(position.volume),
            symbol=symbol,
        )

        state = await self.command_repo.upsert_state(
            account_number=account_number,
            position_ticket=ticket,
            symbol=symbol,
            position_identifier=int(position.identifier) if position.identifier else None,
            entry_price=entry,
            initial_sl=sl,
            initial_risk=initial_risk,
        )

        if state is None:
            return "skipped"

        # --------------------------------------------------------
        # 2. تحديث أعلى ربح عائم
        # --------------------------------------------------------
        max_favorable = self._calculate_favorable_price(
            side=side, current=current,
        )
        state = await self.command_repo.update_peak_profit(
            account_number=account_number,
            position_ticket=ticket,
            current_profit=profit,
            current_price=max_favorable,
        )

        if state is None:
            return "skipped"

        peak_profit = self._safe_float(state.max_floating_profit)
        stored_risk = self._safe_float(state.initial_risk) or initial_risk

        # --------------------------------------------------------
        # 3. فحص وجود أمر نشط مسبقًا
        # --------------------------------------------------------
        active_cmd = await self.command_repo.get_active_command_for_position(
            account_number=account_number,
            position_ticket=ticket,
        )
        if active_cmd is not None:
            return "active"

        # --------------------------------------------------------
        # 4. إعدادات الحماية للرمز
        # --------------------------------------------------------
        settings = PROTECTION_SETTINGS.get(symbol, DEFAULT_SETTINGS)

        # --------------------------------------------------------
        # 5. حساب current_r و peak_r
        # --------------------------------------------------------
        current_r = profit / stored_risk if stored_risk > 0 else 0.0
        peak_r = peak_profit / stored_risk if stored_risk > 0 else 0.0

        # --------------------------------------------------------
        # 6. تطبيق قواعد الحماية (بالترتيب)
        # --------------------------------------------------------

        # 6.1 Giveback Protection — الأولوية القصوى
        giveback_action = self._check_giveback(
            side=side,
            current_r=current_r,
            peak_r=peak_r,
            settings=settings,
        )
        if giveback_action:
            return await self._create_command(
                account_number=account_number,
                ea_id=ea_id,
                ticket=ticket,
                identifier=position.identifier,
                symbol=symbol,
                action="CLOSE_POSITION",
                reason=giveback_action,
                settings=settings,
            )

        # 6.2 حساب المقترح لـ SL (Break-Even, Profit Lock, Trailing)
        proposed_sl = self._calculate_proposed_sl(
            side=side,
            entry=entry,
            current_price=current,
            current_r=current_r,
            initial_risk=stored_risk,
            volume=self._safe_float(position.volume),
            symbol=symbol,
            settings=settings,
            current_sl=sl,
        )

        # 6.3 TP Progress Protection
        tp_proposed_sl = self._calculate_tp_protection_sl(
            side=side,
            entry=entry,
            current=current,
            tp=tp,
            settings=settings,
        )
        if tp_proposed_sl is not None:
            if proposed_sl is None:
                proposed_sl = tp_proposed_sl
            else:
                proposed_sl = self._more_protective_sl(
                    side=side,
                    sl_a=proposed_sl,
                    sl_b=tp_proposed_sl,
                )

        # 6.4 Early Reversal Detection (يُستدعى فقط عند الحاجة)
        if (
            proposed_sl is not None
            or current_r >= settings["reversal_activation_r"]
        ):
            analysis = await self._safe_analyze(
                position=position,
                side=side,
                entry=entry,
                current=current,
                tp=tp,
                sl=sl,
                initial_risk=stored_risk,
                peak_profit=peak_profit,
                current_profit=profit,
                settings=settings,
            )

            if analysis and analysis.recommended_action == "CLOSE_POSITION":
                return await self._create_command(
                    account_number=account_number,
                    ea_id=ea_id,
                    ticket=ticket,
                    identifier=position.identifier,
                    symbol=symbol,
                    action="CLOSE_POSITION",
                    reason=analysis.reason or "EARLY_REVERSAL",
                    settings=settings,
                )

        # --------------------------------------------------------
        # 7. تنفيذ تعديل SL إن وُجد
        # --------------------------------------------------------
        if proposed_sl is not None:
            # التحقق من أن التعديل ذو معنى
            if self._is_significant_change(
                side=side,
                current_sl=sl,
                proposed_sl=proposed_sl,
                entry=entry,
            ):
                action = self._classify_sl_action(
                    side=side,
                    entry=entry,
                    proposed_sl=proposed_sl,
                    current_r=current_r,
                    settings=settings,
                )
                return await self._create_command(
                    account_number=account_number,
                    ea_id=ea_id,
                    ticket=ticket,
                    identifier=position.identifier,
                    symbol=symbol,
                    action="MODIFY_SL_TP",
                    new_sl=proposed_sl,
                    new_tp=tp if tp > 0 else None,
                    reason=action,
                    settings=settings,
                )

        return "skipped"

    # ============================================================
    # قواعد الحماية
    # ============================================================

    def _check_giveback(
        self,
        *,
        side: str,
        current_r: float,
        peak_r: float,
        settings: dict,
    ) -> Optional[str]:
        """
        فحص Profit Giveback Protection.

        يُفعّل فقط عندما:
        - peak_r >= giveback_activation_r
        - (peak_r - current_r) >= max_giveback_r

        ملاحظة مهمة: لا نضيف شرط current_r > min لمنع الإغلاق.
        هذا كان خطأ في النسخة السابقة.
        """
        activation = settings["giveback_activation_r"]
        max_giveback = settings["max_giveback_r"]

        if peak_r < activation:
            return None

        giveback = peak_r - current_r

        if giveback < max_giveback:
            return None

        return (
            f"PROFIT_GIVEBACK peak={peak_r:.2f}R "
            f"current={current_r:.2f}R giveback={giveback:.2f}R"
        )

    def _calculate_proposed_sl(
        self,
        *,
        side: str,
        entry: float,
        current_price: float,
        current_r: float,
        initial_risk: float,
        volume: float,
        symbol: str,
        settings: dict,
        current_sl: float,
    ) -> Optional[float]:
        """
        حساب SL المقترح بناءً على:
        - Break-Even
        - Profit Lock
        - ATR Trailing

        يعيد أكثر المستويات حماية.
        """
        candidates = []

        # --------------------------------------------------------
        # 1. Break-Even
        # --------------------------------------------------------
        if current_r >= settings["break_even_r"]:
            candidates.append(entry)

        # --------------------------------------------------------
        # 2. Profit Lock
        # --------------------------------------------------------
        if current_r >= settings["profit_lock_r"]:
            lock_r = settings["min_profit_lock_r"]
            locked_money = lock_r * initial_risk

            lock_sl = self._money_to_sl(
                side=side,
                entry=entry,
                money=locked_money,
                volume=volume,
                symbol=symbol,
            )
            if lock_sl is not None:
                candidates.append(lock_sl)

        # --------------------------------------------------------
        # 3. ATR Trailing
        # --------------------------------------------------------
        if current_r >= settings["trailing_start_r"]:
            atr_distance = self._calculate_atr_distance(symbol, settings)
            if atr_distance is not None and atr_distance > 0:
                if side == "BUY":
                    trailing_sl = current_price - atr_distance
                else:
                    trailing_sl = current_price + atr_distance
                candidates.append(trailing_sl)

        if not candidates:
            return None

        return self._most_protective(
            side=side,
            values=candidates,
        )

    def _calculate_tp_protection_sl(
        self,
        *,
        side: str,
        entry: float,
        current: float,
        tp: float,
        settings: dict,
    ) -> Optional[float]:
        """
        TP Progress Protection.

        عندما تصل الصفقة إلى نسبة معينة من المسافة نحو TP،
        نقترح SL عند 50% من الربح المتحقق.
        """
        if tp <= 0 or entry <= 0:
            return None

        activation = settings["tp_protection_pct"]

        if side == "BUY":
            total = tp - entry
            progress = current - entry
        elif side == "SELL":
            total = entry - tp
            progress = entry - current
        else:
            return None

        if total <= 0 or progress <= 0:
            return None

        progress_pct = progress / total

        if progress_pct < activation:
            return None

        # احتفظ بـ 50% من الربح المتحقق
        if side == "BUY":
            return entry + progress * 0.50
        else:
            return entry - progress * 0.50

    # ============================================================
    # المساعدات
    # ============================================================

    async def _safe_analyze(
        self,
        *,
        position: OpenPosition,
        side: str,
        entry: float,
        current: float,
        tp: float,
        sl: float,
        initial_risk: float,
        peak_profit: float,
        current_profit: float,
        settings: dict,
    ) -> Optional[PositionRiskAnalysis]:
        """استدعاء محلل المخاطر بشكل آمن."""
        try:
            return await self.risk_analyzer.analyze(
                position_ticket=int(position.ticket),
                symbol=str(position.symbol),
                side=side,
                entry_price=entry,
                current_price=current,
                take_profit=tp,
                stop_loss=sl,
                initial_risk=initial_risk,
                peak_profit=peak_profit,
                current_profit=current_profit,
                rsi_period=settings["default_rsi_period"],
                ema_period=settings["default_ema_period"],
            )
        except Exception as exc:
            logger.warning(
                "Position analysis failed for ticket=%s: %s",
                position.ticket, exc,
            )
            return None

    async def _create_command(
        self,
        *,
        account_number: int,
        ea_id: str,
        ticket: int,
        identifier,
        symbol: str,
        action: str,
        reason: str = "",
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None,
        close_volume: Optional[float] = None,
        settings: dict,
    ) -> str:
        """إنشاء أمر إدارة عبر trade_service."""
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=COMMAND_TTL_SECONDS
        )

        try:
            result = await trade_service.process_position_command(
                db=self.db,
                account_id="",  # سيُستخرج من account_number
                account_number=account_number,
                ea_id=ea_id,
                position_ticket=ticket,
                position_identifier=int(identifier) if identifier else None,
                symbol=symbol,
                action=action,
                new_sl=new_sl,
                new_tp=new_tp,
                close_volume=close_volume,
                reason=reason,
                expires_at=expires_at,
            )
            if result is None:
                return "active"
            return "created"
        except Exception as exc:
            logger.error(
                "Failed to create position command for ticket=%s: %s",
                ticket, exc,
            )
            return "skipped"

    @staticmethod
    def _normalize_side(position_type) -> str:
        """تحويل نوع الصفقة إلى BUY/SELL."""
        if position_type is None:
            return ""
        s = str(position_type).upper().strip()
        if s in ("BUY", "POSITION_TYPE_BUY", "0"):
            return "BUY"
        if s in ("SELL", "POSITION_TYPE_SELL", "1"):
            return "SELL"
        return s

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _calculate_initial_risk(
        *,
        side: str,
        entry: float,
        sl: float,
        volume: float,
        symbol: str,
    ) -> float:
        """
        حساب المخاطرة الأصلية بالدولار.

        ملاحظة: هذه قيمة تقديرية. الطريقة الدقيقة تتطلب
        مواصفات الرمز (tick_value, tick_size).
        """
        if entry <= 0 or sl <= 0 or volume <= 0:
            return 0.0

        distance = abs(entry - sl)
        if distance <= 0:
            return 0.0

        # محاولة استخدام مواصفات الرمز من قاعدة البيانات
        # سنستخدم قيمًا افتراضية هنا؛ يمكن تحسينها لاحقًا
        # بجلب tick_value و tick_size من symbol_specs.
        # للنسخة الحالية، نستخدم تقديرًا:
        if "XAU" in symbol.upper():
            # الذهب: 1$ حركة = 100$ لكل 1.0 لوت (تقريبًا)
            # 1 لوت = 100 أونصة
            return distance * volume * 100.0
        else:
            # الفوركس: 1 pip = 10$ لكل 1.0 لوت (للأزواج الدولارية)
            # 1 pip = 0.0001
            return distance * volume * 100000.0

    @staticmethod
    def _calculate_favorable_price(
        *,
        side: str,
        current: float,
    ) -> float:
        """السعر المواتي الحالي."""
        return current

    @staticmethod
    def _money_to_sl(
        *,
        side: str,
        entry: float,
        money: float,
        volume: float,
        symbol: str,
    ) -> Optional[float]:
        """تحويل مبلغ بالدولار إلى مسافة سعرية."""
        if money <= 0 or volume <= 0:
            return None

        # نفس افتراضات _calculate_initial_risk
        if "XAU" in symbol.upper():
            distance = money / (volume * 100.0)
        else:
            distance = money / (volume * 100000.0)

        if side == "BUY":
            return entry + distance
        else:
            return entry - distance

    @staticmethod
    def _calculate_atr_distance(
        symbol: str,
        settings: dict,
    ) -> Optional[float]:
        """
        حساب مسافة ATR.

        ملاحظة: للحصول على ATR حقيقي، يجب جلب آخر شمعة
        من قاعدة البيانات. النسخة الحالية تستخدم تقديرًا.
        """
        # TODO: جلب ATR من قاعدة البيانات
        # للنسخة الحالية، نستخدم قيمًا تقديرية:
        if "XAU" in symbol.upper():
            return 3.0  # 3$ للذهب
        else:
            return 0.0020  # 20 pip لليورو

    @staticmethod
    def _most_protective(
        *,
        side: str,
        values: list[float],
    ) -> Optional[float]:
        """اختيار أكثر قيمة حماية."""
        if not values:
            return None
        if side == "BUY":
            return max(values)  # الأعلى للشراء
        else:
            return min(values)  # الأدنى للبيع

    @staticmethod
    def _more_protective_sl(
        *,
        side: str,
        sl_a: float,
        sl_b: float,
    ) -> float:
        """اختيار الأكثر حماية من SLين."""
        if side == "BUY":
            return max(sl_a, sl_b)
        else:
            return min(sl_a, sl_b)

    @staticmethod
    def _is_significant_change(
        *,
        side: str,
        current_sl: float,
        proposed_sl: float,
        entry: float,
    ) -> bool:
        """هل التعديل ذو معنى؟"""
        if proposed_sl is None or proposed_sl <= 0:
            return False

        if current_sl <= 0:
            # لا يوجد SL حالي
            return True

        # يجب أن يكون التعديل في الاتجاه الصحيح
        if side == "BUY":
            if proposed_sl <= current_sl:
                return False
        else:
            if proposed_sl >= current_sl:
                return False

        # فرق أدنى
        ref = abs(entry) if entry > 0 else 1.0
        min_change = ref * MIN_SL_CHANGE_PCT
        return abs(proposed_sl - current_sl) >= min_change * 0.01

    @staticmethod
    def _classify_sl_action(
        *,
        side: str,
        entry: float,
        proposed_sl: float,
        current_r: float,
        settings: dict,
    ) -> str:
        """تصنيف نوع الإجراء لأنسب سبب."""
        # هل هو Break-Even؟
        if abs(proposed_sl - entry) < 1e-9:
            return "BREAK_EVEN"

        # هل هو Profit Lock؟
        if current_r >= settings["profit_lock_r"]:
            return "PROFIT_LOCK"

        # هل هو Trailing؟
        if current_r >= settings["trailing_start_r"]:
            return "TRAILING_STOP"

        return "SL_MODIFICATION"
