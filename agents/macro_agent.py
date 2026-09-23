"""Market-wide regime detector.

Unlike the other agents, this one doesn't analyze individual symbols - it
runs once per pipeline and classifies the overall market as risk_on,
neutral, or risk_off using the VIX (fear gauge) and SPY's trend. The
resulting regime is attached to every signal emitted this run so the
advisor can gate confidence appropriately (e.g. be less eager to push BUY
calls when the broad market is in risk_off), and so the weight learner can
keep separate learned weights per regime - a signal that works in a calm
bull market may not work in a panic, and vice versa.
"""

from datetime import datetime, timezone
from agents.base_agent import BaseAgent, fetch_yf_history


class MacroAgent(BaseAgent):
    """Classifies the current market regime from VIX level + SPY trend."""

    name = "macro_agent"
    description = "Detects market-wide risk regime (VIX + SPY trend)"

    def __init__(self, config=None):
        super().__init__(config)
        self.vix_risk_off = config.get("vix_risk_off", 25.0) if config else 25.0
        self.vix_risk_on = config.get("vix_risk_on", 18.0) if config else 18.0

    def detect_regime(self):
        """Returns a dict: {regime, vix, spy_trend, reason}. Never raises -
        any fetch failure just falls back to 'neutral' so a bad macro read
        never blocks the whole pipeline from running."""
        vix_level = self._get_vix()
        spy_trend = self._get_spy_trend()

        reasons = []
        risk_off_votes = 0
        risk_on_votes = 0

        if vix_level is not None:
            if vix_level >= self.vix_risk_off:
                risk_off_votes += 1
                reasons.append(f"VIX elevated at {vix_level:.1f}")
            elif vix_level <= self.vix_risk_on:
                risk_on_votes += 1
                reasons.append(f"VIX calm at {vix_level:.1f}")

        if spy_trend == "up":
            risk_on_votes += 1
            reasons.append("SPY above its 50-day average and trending up")
        elif spy_trend == "down":
            risk_off_votes += 1
            reasons.append("SPY below its 50-day average and trending down")

        if risk_off_votes > risk_on_votes:
            regime = "risk_off"
        elif risk_on_votes > risk_off_votes:
            regime = "risk_on"
        else:
            regime = "neutral"

        return {
            "regime": regime,
            "vix": vix_level,
            "spy_trend": spy_trend,
            "reason": "; ".join(reasons) if reasons else "insufficient data, defaulting to neutral",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _get_vix(self):
        try:
            hist = fetch_yf_history("^VIX", period="5d", interval="1d")
            if hist is None or hist.empty:
                return None
            return float(hist["Close"].iloc[-1])
        except Exception:
            return None

    def _get_spy_trend(self):
        try:
            hist = fetch_yf_history("SPY", period="3mo", interval="1d")
            if hist is None or hist.empty or len(hist) < 50:
                return None
            close = hist["Close"]
            sma50 = close.rolling(window=50).mean()
            last_close = float(close.iloc[-1])
            last_sma50 = float(sma50.iloc[-1])
            prev_sma50 = float(sma50.iloc[-6]) if len(sma50) > 55 else last_sma50
            if last_close > last_sma50 and last_sma50 >= prev_sma50:
                return "up"
            if last_close < last_sma50 and last_sma50 <= prev_sma50:
                return "down"
            return "flat"
        except Exception:
            return None

    def analyze(self, symbol, data=None):
        # Not used per-symbol; detect_regime() is the entry point.
        raise NotImplementedError("MacroAgent.detect_regime() runs once per pipeline, not per-symbol")
