"""Relative-strength agent: how is this stock doing versus its peers/market?

A stock up 5% means very different things if its sector is up 15% (weak
relative strength - money is rotating elsewhere) versus if its sector is
flat or down (genuine outperformance). This agent benchmarks each US stock
against its GICS sector ETF and the broad market (SPY), and each Japanese
stock (".T" tickers) against the Nikkei 225 index, over a ~1 month window.
"""

from datetime import datetime, timezone
from agents.base_agent import BaseAgent, fetch_yf_history, fetch_yf_info

# GICS sector -> representative SPDR sector ETF.
SECTOR_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Discretionary": "XLY",
    "Consumer Defensive": "XLP",
    "Consumer Staples": "XLP",
    "Healthcare": "XLV",
    "Health Care": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Communication Services": "XLC",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
    "Materials": "XLB",
    "Real Estate": "XLRE",
}


class SectorAgent(BaseAgent):
    """Compares a symbol's recent return against its sector/market benchmark."""

    name = "sector_agent"
    description = "Relative strength vs sector ETF / market index"

    def __init__(self, config=None):
        super().__init__(config)
        self.outperform_threshold = config.get("outperform_threshold", 4.0) if config else 4.0

    def analyze(self, symbol, data=None):
        stock_return = self._return_pct(symbol, period="1mo")
        if stock_return is None:
            return None

        is_japan = symbol.upper().endswith(".T")
        if is_japan:
            benchmark_symbol = "^N225"
            benchmark_label = "Nikkei 225"
        else:
            sector = (fetch_yf_info(symbol) or {}).get("sector")
            benchmark_symbol = SECTOR_ETF.get(sector, "SPY")
            benchmark_label = sector or "S&P 500"

        benchmark_return = self._return_pct(benchmark_symbol, period="1mo")
        if benchmark_return is None:
            return None

        relative_strength = stock_return - benchmark_return
        signals = []

        if relative_strength >= self.outperform_threshold:
            signals.append({
                "type": "relative_strength_bullish",
                "vs": benchmark_label,
                "relative_strength_pct": round(relative_strength, 2),
                "confidence": min(relative_strength / (self.outperform_threshold * 2), 1.0),
            })
        elif relative_strength <= -self.outperform_threshold:
            signals.append({
                "type": "relative_strength_bearish",
                "vs": benchmark_label,
                "relative_strength_pct": round(relative_strength, 2),
                "confidence": min(abs(relative_strength) / (self.outperform_threshold * 2), 1.0),
            })

        if not signals:
            return None

        max_conf = max(s["confidence"] for s in signals)
        return {
            "symbol": symbol,
            "agent": self.name,
            "signals": signals,
            "price": None,
            "benchmark": {
                "symbol": benchmark_symbol,
                "label": benchmark_label,
                "stock_return_1mo_pct": round(stock_return, 2),
                "benchmark_return_1mo_pct": round(benchmark_return, 2),
            },
            "confidence": round(max_conf, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert": max_conf >= 0.7,
        }

    def _return_pct(self, symbol, period="1mo"):
        try:
            hist = fetch_yf_history(symbol, period=period, interval="1d")
            if hist is None or hist.empty or len(hist) < 2:
                return None
            first = float(hist["Close"].iloc[0])
            last = float(hist["Close"].iloc[-1])
            if first == 0:
                return None
            return (last - first) / first * 100
        except Exception:
            return None
