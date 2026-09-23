"""Chart pattern / price-action agent.

Distinct from MomentumAgent (which reads oscillators like RSI/MACD): this
agent looks at the *shape* of recent price action - breakouts past a prior
range, breakdowns below support, bullish/bearish engulfing candles, and
bounces off a recent floor. These are classic price-action setups traders
watch independently of where an oscillator happens to sit.
"""

from datetime import datetime, timezone
from agents.base_agent import BaseAgent, fetch_yf_history, get_price_change


class PatternAgent(BaseAgent):
    """Detects breakout/breakdown and candlestick price-action patterns."""

    name = "pattern_agent"
    description = "Detects breakouts, breakdowns, and candlestick patterns"

    def __init__(self, config=None):
        super().__init__(config)
        self.lookback = config.get("lookback", 20) if config else 20

    def analyze(self, symbol, data=None):
        hist = data.get("pattern_history") if data else None
        if hist is None:
            hist = fetch_yf_history(symbol, period="6mo", interval="1d")

        if hist is None or hist.empty or len(hist) < self.lookback + 2:
            return None

        price_info = get_price_change(hist)
        if price_info is None:
            return None

        signals = []
        signals.extend(self._breakout_signals(hist))
        signals.extend(self._candle_signals(hist))
        signals.extend(self._support_bounce_signal(hist))

        if not signals:
            return None

        max_conf = max(s["confidence"] for s in signals)
        return {
            "symbol": symbol,
            "agent": self.name,
            "signals": signals,
            "price": price_info,
            "confidence": round(max_conf, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert": max_conf >= 0.7,
        }

    def _breakout_signals(self, hist):
        try:
            window = hist.iloc[-(self.lookback + 1):-1]
            last_close = float(hist["Close"].iloc[-1])
            last_volume = float(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0
            avg_volume = float(window["Volume"].mean()) if "Volume" in window.columns and window["Volume"].mean() > 0 else 0
            prior_high = float(window["High"].max())
            prior_low = float(window["Low"].min())

            signals = []
            volume_confirmed = avg_volume > 0 and last_volume >= 1.3 * avg_volume

            if last_close > prior_high:
                signals.append({
                    "type": "breakout",
                    "level": round(prior_high, 2),
                    "volume_confirmed": volume_confirmed,
                    "confidence": 0.85 if volume_confirmed else 0.65,
                })
            elif last_close < prior_low:
                signals.append({
                    "type": "breakdown",
                    "level": round(prior_low, 2),
                    "volume_confirmed": volume_confirmed,
                    "confidence": 0.85 if volume_confirmed else 0.65,
                })
            return signals
        except Exception:
            return []

    def _candle_signals(self, hist):
        try:
            if len(hist) < 2:
                return []
            prev = hist.iloc[-2]
            last = hist.iloc[-1]
            prev_body_low = min(prev["Open"], prev["Close"])
            prev_body_high = max(prev["Open"], prev["Close"])
            last_body_low = min(last["Open"], last["Close"])
            last_body_high = max(last["Open"], last["Close"])

            signals = []
            # Bullish engulfing: prior red candle, today's green body fully
            # engulfs it.
            if (prev["Close"] < prev["Open"] and last["Close"] > last["Open"]
                    and last_body_low <= prev_body_low and last_body_high >= prev_body_high):
                signals.append({"type": "bullish_engulfing", "confidence": 0.7})
            # Bearish engulfing: mirror image.
            elif (prev["Close"] > prev["Open"] and last["Close"] < last["Open"]
                    and last_body_low <= prev_body_low and last_body_high >= prev_body_high):
                signals.append({"type": "bearish_engulfing", "confidence": 0.7})
            return signals
        except Exception:
            return []

    def _support_bounce_signal(self, hist):
        try:
            window = hist.iloc[-(self.lookback + 1):-1]
            support = float(window["Low"].min())
            last = hist.iloc[-1]
            # Price dipped to (or through) recent support intraday but
            # closed meaningfully above it - a bounce, not a breakdown.
            touched_support = float(last["Low"]) <= support * 1.01
            closed_strong = float(last["Close"]) > support * 1.02
            if touched_support and closed_strong and float(last["Close"]) > float(last["Open"]):
                return [{
                    "type": "support_bounce",
                    "level": round(support, 2),
                    "confidence": 0.65,
                }]
            return []
        except Exception:
            return []
