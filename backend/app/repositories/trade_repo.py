import uuid
from sqlalchemy.orm import Session
from app.domain.models import TradeCommand
from app.domain.schemas import CommandCreate
# استدعاء العقد (Interface) الذي يجب أن نلتزم به
from app.domain.interfaces.trade_repo_interface import ITradeRepository

class TradeRepository(ITradeRepository):
    """
    مستودع البيانات الفعلي الذي يتعامل مع قاعدة البيانات (PostgreSQL/Supabase).
    وهو يلتزم التزاماً كاملاً بالدوال المحددة في ITradeRepository.
    """
    
    def __init__(self, db: Session):
        self.db = db

    def create_trade_command(self, command: CommandCreate) -> TradeCommand:
        # 💡 الحل الجذري: توليد معرف فريد بصيغة نصية (UUID) لمنع خطأ NULL identity key
        command_id = str(uuid.uuid4())

        db_command = TradeCommand(
            id=command_id,
            symbol=command.symbol,
            order_type=command.order_type,
            lot_size=command.lot_size,
            # استخراج الحقول المضافة حديثاً مع قيم افتراضية آمنة
            entry_price=getattr(command, 'entry_price', 0.0),
            stop_loss=getattr(command, 'stop_loss', 0.0),
            take_profit=getattr(command, 'take_profit', 0.0),
            status="pending" 
        )
        self.db.add(db_command)
        self.db.commit()
        self.db.refresh(db_command)
        return db_command

    def get_pending_commands(self) -> list[TradeCommand]:
        return self.db.query(TradeCommand).filter(TradeCommand.status == "pending").all()

    def update_command_status(self, command_id: str, new_status: str) -> TradeCommand:
        # ملاحظة: تم تعديل نوع المعرف إلى str ليتوافق مع UUID
        db_command = self.db.query(TradeCommand).filter(TradeCommand.id == command_id).first()
        
        if db_command:
            db_command.status = new_status
            self.db.commit()
            self.db.refresh(db_command)
            
        return db_command
