import uuid
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.domain.models import TradeCommand
from app.domain.schemas import CommandCreate
from app.domain.interfaces.trade_repo_interface import ITradeRepository


class TradeRepository(ITradeRepository):
    def __init__(self, db: Session):
        self.db = db

    def create_trade_command(self, command: CommandCreate) -> TradeCommand:
        """
        إنشاء أمر تداول جديد مع حماية مطلقة ضد التكرار (Idempotency)
        لتجنب خطأ قيد قاعدة البيانات عند تكرار فحص الإشارات لنفس الشمعة.
        """
        # 1. فحص مسبق: هل الأمر موجود مسبقاً بنفس الحساب ومفتاح الإشارة؟
        existing = self.db.query(TradeCommand).filter(
            TradeCommand.account_id == command.account_id,
            TradeCommand.signal_key == command.signal_key
        ).first()
        
        if existing:
            return existing

        # 2. إنشاء السجل الجديد في حال عدم وجوده
        db_command = TradeCommand(
            account_id=command.account_id,
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
            self.db.commit()
            self.db.refresh(db_command)
            return db_command
        except IntegrityError:
            # 3. شبكة أمان أخيرة لمعالجة سباق التزامن (Race Condition) بين العمليات المتزامنة
            self.db.rollback()
            existing = self.db.query(TradeCommand).filter(
                TradeCommand.account_id == command.account_id,
                TradeCommand.signal_key == command.signal_key
            ).first()
            if existing:
                return existing
            raise

    def get_pending_commands(self, limit: int = 10) -> list[TradeCommand]:
        return (self.db.query(TradeCommand)
                .filter(TradeCommand.status == "pending")
                .order_by(TradeCommand.created_at.asc())
                .limit(min(max(limit, 1), 50)).all())

    def claim_command(self, command_id: str) -> TradeCommand | None:
        try:
            valid_uuid = uuid.UUID(command_id)
        except ValueError:
            return None
            
        command = (self.db.query(TradeCommand)
                   .filter(TradeCommand.id == valid_uuid, TradeCommand.status == "pending")
                   .with_for_update(skip_locked=True).first())
                   
        if not command:
            return None
            
        command.status = "processing"
        self.db.commit()
        self.db.refresh(command)
        return command

    def update_command_status(self, command_id: str, new_status: str) -> TradeCommand | None:
        try:
            valid_uuid = uuid.UUID(command_id)
        except ValueError:
            return None
            
        allowed = {"pending", "processing", "executed", "partial", "placed", "failed", "cancelled", "expired", "ignored", "rejected"}
        status = new_status.lower()
        
        if status not in allowed:
            return None
            
        command = self.db.query(TradeCommand).filter(TradeCommand.id == valid_uuid).first()
        if command:
            command.status = status
            self.db.commit()
            self.db.refresh(command)
            
        return command
