from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, market_data: dict):
        """Return either HOLD/BUY/SELL or a decision dictionary."""
        raise NotImplementedError
