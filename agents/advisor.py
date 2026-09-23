"""Consolidates every agent's signals into BUY / WATCH / SELL calls.

Unlike the original version - which counted positive vs. negative signals
with equal weight regardless of track record - this advisor:
  1. Uses the learned per-signal-type weight (how reliable has this exact
     kind of signal actually been?) from WeightLearner, preferring the
     regime-specific track when there's enough data.
  2. Applies each contributing agent's win-rate multiplier, so an agent
     that's been consistently right earns more influence over time.
  3. Gates confidence by the current market regime: the same evidence
     is trusted a bit less for a BUY call when the broad market is
     risk_off, and a bit less for a SELL call when it's risk_on - chasing
     a single stock against a strong macro tide is exactly when signals
     tend to fail.
"""

from datetime import datetime, timezone

from agents.signal_taxonomy import signal_direction
from agents.weight_learner import WeightLearner


class AdvisorAgent:
    """Consolidates signals from all agents and generates investment advice."""

    name = "advisor"
    description = "Consolidates signals and generates investment advice"

    def __init__(self, config=None, learning_state=None):
        self.config = config or {}
        self.risk_tolerance = self.config.get("risk_tolerance", "moderate")
        self.regime = self.config.get("regime", "neutral")
        # learning_state is the WeightLearner's persisted memory dict, loaded
        # by the caller from data/learning_state.json. Passing {} gives every
        # signal/agent the default neutral weight - i.e. behaves sanely even
        # before any history has accumulated.
        self.learner = WeightLearner(learning_state if learning_state is not None else {})

    def consolidate(self, agent_results):
        summary = {}

        for result in agent_results:
            if not result or result.get("error"):
                continue
            symbol = result.get("symbol")
            agent = result.get("agent")
            if not symbol:
                continue

            entry = summary.setdefault(symbol, {
                "symbol": symbol,
                "signals": [],
                "agents": [],
                "alerts": [],
                "weighted_bull": 0.0,
                "weighted_bear": 0.0,
                "confidence_sum": 0.0,
                "confidence_count": 0,
            })

            entry["agents"].append(agent)
            if result.get("alert"):
                entry["alerts"].append(agent)

            conf = result.get("confidence", 0) or 0
            entry["confidence_sum"] += conf
            entry["confidence_count"] += 1

            agent_mult = self.learner.agent_multiplier(agent)
            for sig in result.get("signals", []):
                entry["signals"].append(sig)
                direction = signal_direction(sig)
                if direction == 0:
                    continue
                sig_weight = self.learner.signal_weight(sig.get("type", ""), regime=self.regime)
                sig_conf = sig.get("confidence", conf) or conf
                weighted = sig_conf * sig_weight * agent_mult
                if direction > 0:
                    entry["weighted_bull"] += weighted
                else:
                    entry["weighted_bear"] += weighted

        recommendations = []
        for symbol, data in summary.items():
            avg_confidence = data["confidence_sum"] / data["confidence_count"] if data["confidence_count"] else 0
            action = self._decide(symbol, data, avg_confidence)
            if action:
                recommendations.append(action)

        recommendations.sort(key=lambda x: x["confidence"], reverse=True)
        return recommendations

    def _decide(self, symbol, data, avg_confidence):
        bull, bear = data["weighted_bull"], data["weighted_bear"]
        signal_count = len(data["signals"])
        net = bull - bear
        total_weight = bull + bear

        if total_weight == 0 or signal_count < 2:
            # No directional signals at all, or only one piece of evidence -
            # not enough to act on either way.
            if avg_confidence >= 0.6 and len(data["alerts"]) >= 1:
                return self._build(symbol, "WATCH", avg_confidence, data, signal_count)
            return None

        # Regime gate: same weighted evidence, less trust when fighting the
        # macro tide.
        buy_gate = {"risk_on": 1.05, "neutral": 1.0, "risk_off": 0.85}[self.regime]
        sell_gate = {"risk_on": 0.85, "neutral": 1.0, "risk_off": 1.05}[self.regime]

        conviction = abs(net) / total_weight  # 0..1, how one-sided the evidence is
        blended_confidence = min((avg_confidence * 0.5 + conviction * 0.5), 1.0)

        if net > 0 and signal_count >= 2 and blended_confidence >= 0.45:
            confidence = min(blended_confidence * buy_gate, 1.0)
            if confidence >= 0.5:
                return self._build(symbol, "BUY", confidence, data, signal_count)
        elif net < 0 and signal_count >= 2 and blended_confidence >= 0.45:
            confidence = min(blended_confidence * sell_gate, 1.0)
            if confidence >= 0.5:
                return self._build(symbol, "SELL", confidence, data, signal_count)

        if avg_confidence >= 0.6 and len(data["alerts"]) >= 1:
            return self._build(symbol, "WATCH", avg_confidence, data, signal_count)
        return None

    def _build(self, symbol, action, confidence, data, signal_count):
        return {
            "symbol": symbol,
            "action": action,
            "confidence": round(confidence, 2),
            "signal_count": signal_count,
            "alerts": data["alerts"],
            "agents": sorted(set(data["agents"])),
            "regime": self.regime,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def to_report(self, recommendations):
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_recommendations": len(recommendations),
            "risk_tolerance": self.risk_tolerance,
            "regime": self.regime,
            "recommendations": recommendations,
        }
