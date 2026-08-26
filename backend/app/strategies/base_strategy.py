from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """
    هذا هو القالب الأساسي (Abstract Class) الذي سترث منه كل الاستراتيجيات القادمة.
    يضمن أن كل استراتيجية تمتلك اسماً ودالة تحليل خاصة بها.
    """
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, market_data: dict) -> str:
        """
        كل استراتيجية يجب أن تحتوي على هذه الدالة.
        تستقبل بيانات السوق، وتعيد قراراً: "BUY", "SELL", أو "HOLD"
        """
        pass