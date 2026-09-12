from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class CommandCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    order_type: str
    lot_size: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    strategy_name: str = "manual"
    signal_key: str = ""
    ea_id: str = ""


class CommandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    symbol: str
    order_type: str
    lot_size: float
    status: str
    created_at: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    strategy_name: str = ""
    signal_key: str = ""
    ea_id: str = ""


class SymbolSpecSync(BaseModel):
    symbol: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int = 0
    contract_size: float = 0.0


class AccountHeartbeat(BaseModel):
    account_number: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    profit: float
    is_connected: bool
    margin_level: float | None = None
