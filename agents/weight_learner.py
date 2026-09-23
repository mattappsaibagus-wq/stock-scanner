"""Regime-aware weight learner - the brain of the self-learning loop.

Modeled on super-crypto-agent's supercrypto/core/learning.py: tracks how
well each *signal type* (e.g. "breakout", "rsi_oversold") and each *agent*
actually performs once outcomes are known, and nudges their trust up or
down with an exponential moving average. Weights are tracked both globally
and per market regime (risk_on / neutral / risk_off), since a signal that
works in a calm bull market may not work in a panic.

This module is pure state manipulation - it doesn't fetch prices or decide
what "correct" means. LearningLoop (learning_loop.py) resolves outcomes and
calls into this; AdvisorAgent (advisor.py) reads the resulting weights.
"""

from __future__ import annotations

from collections import defaultdict

REGIMES = ("risk_on", "neutral", "risk_off")

DEFAULT_WEIGHT = 0.5
MIN_WEIGHT = 0.15
MAX_WEIGHT = 1.5
EMA_ALPHA = 0.25          # how fast weights move toward the new evidence
MIN_SAMPLES = 3           # need at least this many settled outcomes to update a weight
META_MIN_SAMPLES = 5      # need at least this many settled outcomes to trust an agent's win rate


class WeightLearner:
    """Owns `memory['weights']`, `memory['regime_weights']`, `memory['agent_stats']`,
    and `memory['calibration']`. Mutates `memory` (a plain dict) in place so the
    caller can serialize it straight to JSON."""

    def __init__(self, memory: dict):
        self.memory = memory
        memory.setdefault("weights", {})
        memory.setdefault("regime_weights", {r: {} for r in REGIMES})
        memory.setdefault("agent_stats", {})
        memory.setdefault("calibration", {"bins": {}, "ece": 0.0, "n": 0})
        memory.setdefault("accuracy_history", [])

    def signal_weight(self, signal_type: str, regime: str = "neutral") -> float:
        """Trust multiplier for a signal type, preferring the regime-specific
        track when there's enough data, falling back to the global weight."""
        regime_track = self.memory["regime_weights"].get(regime, {})
        if signal_type in regime_track:
            return regime_track[signal_type]
        return self.memory["weights"].get(signal_type, DEFAULT_WEIGHT)

    def agent_multiplier(self, agent: str) -> float:
        """A [0.5, 1.5] multiplier from an agent's historical win rate. Agents
        with too few settled predictions get a neutral 1.0 - we don't punish
        or reward an agent before it's had a fair sample."""
        stats = self.memory.get("agent_stats", {}).get(agent, {})
        if not stats or stats.get("samples", 0) < META_MIN_SAMPLES:
            return 1.0
        win_rate = stats.get("win_rate", 0.5)
        return round(max(0.5, min(1.5, 0.5 + win_rate)), 2)

    def update_weights(self, settled: list[dict]) -> None:
        """`settled` is a list of resolved predictions, each with at minimum:
        {signal_type, agent, regime, outcome_return_pct}. Blends new evidence
        into both the global and regime-specific weight for that signal type,
        and updates each agent's win-rate stats for agent_multiplier()."""
        by_signal: dict[str, list[tuple[float, str]]] = defaultdict(list)
        by_agent: dict[str, list[float]] = defaultdict(list)

        for pred in settled:
            signal_type = pred.get("signal_type")
            ret = pred.get("outcome_return_pct")
            agent = pred.get("agent")
            regime = pred.get("regime", "neutral")
            if signal_type is None or ret is None:
                continue
            # Reward: was this signal's implied direction right, and by how
            # much? tanh keeps outliers from dominating the EMA.
            direction = pred.get("direction", 1)  # +1 bullish signal, -1 bearish signal
            reward = _tanh(direction * ret / 8.0)
            by_signal[signal_type].append((reward, regime))
            if agent:
                by_agent[agent].append(direction * ret)

        weights = self.memory["weights"]
        regime_weights = self.memory["regime_weights"]

        for signal_type, reward_regimes in by_signal.items():
            rewards = [r for r, _ in reward_regimes]
            if len(rewards) < MIN_SAMPLES:
                continue
            mean_reward = sum(rewards) / len(rewards)
            target = 0.5 + 0.5 * mean_reward  # reward in [-1,1] -> target weight in [0,1]-ish
            old = weights.get(signal_type, DEFAULT_WEIGHT)
            updated = old * (1 - EMA_ALPHA) + target * EMA_ALPHA
            weights[signal_type] = round(max(MIN_WEIGHT, min(MAX_WEIGHT, updated)), 4)

            for regime in REGIMES:
                regime_rewards = [r for r, rg in reward_regimes if rg == regime]
                if len(regime_rewards) < MIN_SAMPLES:
                    continue
                r_mean = sum(regime_rewards) / len(regime_rewards)
                r_target = 0.5 + 0.5 * r_mean
                r_old = regime_weights[regime].get(signal_type, DEFAULT_WEIGHT)
                r_updated = r_old * (1 - EMA_ALPHA) + r_target * EMA_ALPHA
                regime_weights[regime][signal_type] = round(max(MIN_WEIGHT, min(MAX_WEIGHT, r_updated)), 4)

        agent_stats = self.memory["agent_stats"]
        for agent, returns in by_agent.items():
            wins = sum(1 for r in returns if r > 0)
            stats = agent_stats.setdefault(agent, {"samples": 0, "wins": 0, "win_rate": 0.5, "avg_return": 0.0})
            prev_samples = stats.get("samples", 0)
            prev_avg = stats.get("avg_return", 0.0)
            new_samples = prev_samples + len(returns)
            stats["samples"] = new_samples
            stats["wins"] = stats.get("wins", 0) + wins
            stats["win_rate"] = round(stats["wins"] / new_samples, 3) if new_samples else 0.5
            stats["avg_return"] = round((prev_avg * prev_samples + sum(returns)) / new_samples, 3) if new_samples else 0.0

        self.memory["accuracy_history"].append({
            "weights": dict(weights),
            "sample_size": sum(len(v) for v in by_signal.values()),
        })
        # Keep the history from growing unbounded across months of daily runs.
        if len(self.memory["accuracy_history"]) > 200:
            self.memory["accuracy_history"] = self.memory["accuracy_history"][-200:]

    def update_calibration(self, settled: list[dict], n_bins: int = 5) -> float:
        """Expected Calibration Error: when the pipeline said "80% confident",
        was it actually right about 80% of the time? Lower is better."""
        bins: dict[int, list[tuple[float, int]]] = defaultdict(list)
        for pred in settled:
            conf = pred.get("confidence")
            ret = pred.get("outcome_return_pct")
            direction = pred.get("direction", 1)
            if conf is None or ret is None:
                continue
            hit = 1 if direction * ret > 0 else 0
            idx = min(n_bins - 1, int(conf * n_bins))
            bins[idx].append((conf, hit))

        total = sum(len(v) for v in bins.values())
        if total == 0:
            return self.memory.get("calibration", {}).get("ece", 0.0)

        ece = 0.0
        serialized = {}
        for idx, items in bins.items():
            n = len(items)
            mean_conf = sum(c for c, _ in items) / n
            mean_acc = sum(h for _, h in items) / n
            ece += (n / total) * abs(mean_conf - mean_acc)
            serialized[str(idx)] = {"n": n, "mean_conf": round(mean_conf, 3), "mean_acc": round(mean_acc, 3)}

        self.memory["calibration"] = {"bins": serialized, "ece": round(ece, 4), "n": total}
        return round(ece, 4)


def _tanh(x: float) -> float:
    import math
    return math.tanh(x)
