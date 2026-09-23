"""Analyst sentiment agent.

Deliberately distinct from NewsScannerAgent, which scores the *wording* of
headlines. This agent instead reads yfinance's aggregated analyst data:
the consensus recommendation (recommendationMean, 1=Strong Buy..5=Strong
Sell) and the trend of upgrades/downgrades over the last few months
(`get_recommendations`/`recommendations`). This is real, free data sourced
from actual sell-side analyst coverage, not a lexicon over scraped text.
"""

from datetime import datetime, timezone
from agents.base_agent import BaseAgent, fetch_yf_info


class SentimentAgent(BaseAgent):
    """Reads aggregated analyst recommendation consensus and its trend."""

    name = "sentiment_agent"
    description = "Analyst recommendation consensus and upgrade/downgrade trend"

    def analyze(self, symbol, data=None):
        info = fetch_yf_info(symbol)
        if not info:
            return None

        signals = []

        rec_mean = info.get("recommendationMean")
        rec_key = info.get("recommendationKey")
        num_analysts = info.get("numberOfAnalystOpinions", 0)

        if rec_mean is not None and num_analysts and num_analysts >= 3:
            if rec_mean <= 2.0:
                signals.append({
                    "type": "analyst_consensus_bullish",
                    "recommendation_mean": round(rec_mean, 2),
                    "recommendation_key": rec_key,
                    "num_analysts": num_analysts,
                    "confidence": min((2.5 - rec_mean) / 1.0, 1.0),
                })
            elif rec_mean >= 4.0:
                signals.append({
                    "type": "analyst_consensus_bearish",
                    "recommendation_mean": round(rec_mean, 2),
                    "recommendation_key": rec_key,
                    "num_analysts": num_analysts,
                    "confidence": min((rec_mean - 3.5) / 1.0, 1.0),
                })

        trend_signal = self._upgrade_downgrade_trend(symbol)
        if trend_signal:
            signals.append(trend_signal)

        target_signal = self._price_target_signal(info)
        if target_signal:
            signals.append(target_signal)

        if not signals:
            return None

        max_conf = max(s["confidence"] for s in signals)
        return {
            "symbol": symbol,
            "agent": self.name,
            "signals": signals,
            "price": None,
            "confidence": round(max_conf, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert": max_conf >= 0.7,
        }

    def _upgrade_downgrade_trend(self, symbol):
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            df = ticker.upgrades_downgrades
            if df is None or df.empty:
                return None
            recent = df.sort_index(ascending=False).head(10)
            grades = recent.get("ToGrade")
            if grades is None:
                return None
            upgrades = recent[recent.get("Action", "") == "up"] if "Action" in recent.columns else recent.iloc[0:0]
            downgrades = recent[recent.get("Action", "") == "down"] if "Action" in recent.columns else recent.iloc[0:0]
            n_up, n_down = len(upgrades), len(downgrades)
            if n_up == 0 and n_down == 0:
                return None
            if n_up > n_down:
                return {
                    "type": "analyst_upgrade_trend",
                    "upgrades": n_up,
                    "downgrades": n_down,
                    "confidence": min(0.5 + 0.15 * (n_up - n_down), 1.0),
                }
            if n_down > n_up:
                return {
                    "type": "analyst_downgrade_trend",
                    "upgrades": n_up,
                    "downgrades": n_down,
                    "confidence": min(0.5 + 0.15 * (n_down - n_up), 1.0),
                }
            return None
        except Exception:
            return None

    def _price_target_signal(self, info):
        try:
            target_mean = info.get("targetMeanPrice")
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            if not target_mean or not current or current <= 0:
                return None
            upside_pct = (target_mean - current) / current * 100
            if upside_pct >= 20:
                return {
                    "type": "price_target_upside",
                    "target_mean": round(target_mean, 2),
                    "current_price": round(current, 2),
                    "upside_pct": round(upside_pct, 1),
                    "confidence": min(upside_pct / 40.0, 1.0),
                }
            if upside_pct <= -15:
                return {
                    "type": "price_target_downside",
                    "target_mean": round(target_mean, 2),
                    "current_price": round(current, 2),
                    "upside_pct": round(upside_pct, 1),
                    "confidence": min(abs(upside_pct) / 30.0, 1.0),
                }
            return None
        except Exception:
            return None
