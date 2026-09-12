# Compatibility wrapper: there is now ONE execution path.
from sqlalchemy.orm import Session
from app.services.strategy_evaluator import evaluate_and_execute_strategy


def evaluate_and_execute_strategy_legacy(db: Session, strategy_name: str, market_data: dict):
    return evaluate_and_execute_strategy(db, strategy_name, market_data)
