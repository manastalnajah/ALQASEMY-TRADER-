def calculate_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    if period <= 0 or len(highs) != len(lows) or len(lows) != len(closes) or len(closes) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    return float(sum(true_ranges[-period:]) / period)
