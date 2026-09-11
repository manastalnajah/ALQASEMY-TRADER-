import uuid  # 👈 استيراد مكتبة UUID للتعامل مع المعرفات بشكل صحيح
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
        # 💡 تم حذف توليد uuid4() من هنا، وقاعدة البيانات ستتولى وضعه تلقائياً
        db_command = TradeCommand(
            symbol=command.symbol,
            order_type=command.order_type,
            lot_size=command.lot_size,
            
            # 🔥 تصحيح حاسم: منع تخزين None إذا تم تمريرها بالخطأ من الـ Schema
            entry_price=getattr(command, 'entry_price', 0.0) or 0.0,
            stop_loss=getattr(command, 'stop_loss', 0.0) or 0.0,
            take_profit=getattr(command, 'take_profit', 0.0) or 0.0,
            
            status="pending" 
        )
        self.db.add(db_command)
        self.db.commit()
        self.db.refresh(db_command)
        return db_command

    def get_pending_commands(self) -> list[TradeCommand]:
        return self.db.query(TradeCommand).filter(TradeCommand.status == "pending").all()

    def update_command_status(self, command_id: str, new_status: str) -> TradeCommand:
        # 🔥 تصحيح حاسم: تحويل النص إلى كائن UUID لمنع خطأ (uuid = character varying)
        try:
            valid_uuid = uuid.UUID(command_id)
        except ValueError:
            # إذا كان المعرف غير صالح كـ UUID، نتجاهل العملية
            return None

        # استخدام valid_uuid بدلاً من command_id النصي
        db_command = self.db.query(TradeCommand).filter(TradeCommand.id == valid_uuid).first()
        
        if db_command:
            db_command.status = new_status
            self.db.commit()
            self.db.refresh(db_command)
            
        return db_command
