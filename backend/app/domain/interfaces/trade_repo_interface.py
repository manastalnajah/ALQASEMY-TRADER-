from abc import ABC, abstractmethod
from app.domain import schemas
from app.domain import models

class ITradeRepository(ABC):
    """
    هذا 'عقد' يحدد شكل الدوال المطلوبة فقط، دون تفاصيل الاتصال بقاعدة البيانات.
    """
    
    @abstractmethod
    def create_trade_command(self, command: schemas.CommandCreate) -> models.TradeCommand:
        pass

    @abstractmethod
    def get_pending_commands(self) -> list[models.TradeCommand]:
        pass

    @abstractmethod
    def update_command_status(self, command_id: int, new_status: str) -> models.TradeCommand:
        pass