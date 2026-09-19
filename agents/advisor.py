from datetime import datetime, timezone


class AdvisorAgent:
    """Consolidates signals from all agents and generates investment advice."""

    name = "advisor"
    description = "Consolidates signals and generates investment advice"

    def __init__(self, config=None):
        self.config = config or {}
        self.weighted_signals = []
        self.risk_tolerance = self.config.get("risk_tolerance", "moderate")

    def consolidate(self, agent_results):
        summary = {}
        all_signals = []

        for result in agent_results:
            if not result:
                continue
            symbol = result.get("symbol")
            if not symbol:
                continue

            if symbol not in summary:
                summary[symbol] = {
                    "symbol": symbol,
                    "signals": [],
                    "confidence_sum": 0,
                    "confidence_count": 0,
                    "alerts": [],
                    "agents": [],
                }

            summary[symbol]["signals"].extend(result.get("signals", []))
            summary[symbol]["agents"].append(result.get("agent"))

            conf = result.get("confidence", 0)
            summary[symbol]["confidence_sum"] += conf
            summary[symbol]["confidence_count"] += 1

            if result.get("alert"):
                summary[symbol]["alerts"].append(result.get("agent"))

        recommendations = []
        for symbol, data in summary.items():
            avg_confidence = data["confidence_sum"] / data["confidence_count"] if data["confidence_count"] > 0 else 0
            signal_count = len(data["signals"])

            action = self._generate_recommendation(symbol, data, avg_confidence, signal_count)
            if action:
                recommendations.append(action)

        recommendations.sort(key=lambda x: x["confidence"], reverse=True)
        return recommendations

    def _generate_recommendation(self, symbol, data, avg_confidence, signal_count):
        positive_signals = [s for s in data["signals"] if s.get("direction") in ("up", "positive") or "bullish" in s.get("type", "") or "strong" in s.get("type", "") or "undervalued" in s.get("type", "")]
        negative_signals = [s for s in data["signals"] if s.get("direction") in ("down", "negative") or "bearish" in s.get("type", "") or "over" in s.get("type", "")]

        if len(positive_signals) > len(negative_signals) and signal_count >= 2 and avg_confidence >= 0.5:
            action = "BUY"
            confidence = min(avg_confidence * 1.2, 1.0)
        elif len(negative_signals) > len(positive_signals) and signal_count >= 2 and avg_confidence >= 0.5:
            action = "SELL"
            confidence = min(avg_confidence * 1.2, 1.0)
        elif avg_confidence >= 0.6 and len(data["alerts"]) >= 1:
            action = "WATCH"
            confidence = avg_confidence
        else:
            return None

        return {
            "symbol": symbol,
            "action": action,
            "confidence": round(confidence, 2),
            "signal_count": signal_count,
            "alerts": data["alerts"],
            "agents": data["agents"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def to_report(self, recommendations):
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_recommendations": len(recommendations),
            "risk_tolerance": self.risk_tolerance,
            "recommendations": recommendations,
        }
