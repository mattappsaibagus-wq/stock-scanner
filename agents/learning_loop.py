"""The actual self-learning loop.

The previous version logged predictions but never resolved them against
real outcomes - `outcome` was always `None`, so accuracy was permanently
stuck at 0% and the learned config it wrote was never even read back by
the advisor. This version:

  1. On every run, before logging anything new, looks at predictions from
     prior runs that are now at least SETTLE_HOURS old and resolves them
     against the symbol's actual price today (a real yfinance lookup) -
     both at the individual-signal level (for weight learning) and the
     symbol-level recommendation (for headline accuracy stats).
  2. Feeds newly-settled signal outcomes into WeightLearner, which
     updates per-signal-type and per-agent trust.
  3. Persists the weight state to data/learning_state.json - which
     AdvisorAgent actually reads on the next run - closing the loop.
  4. Logs this run's new predictions (not yet resolvable) for next time.
"""

import json
import os
from datetime import datetime, timezone, timedelta

from agents.base_agent import fetch_yf_history, _sanitize
from agents.signal_taxonomy import signal_direction
from agents.weight_learner import WeightLearner

SETTLE_HOURS = 20  # ~1 trading session, given the twice-daily scan cadence
DIRECTIONAL_MOVE_THRESHOLD_PCT = 1.0  # noise floor for "did the call actually pay off"


class LearningLoop:
    """Resolves past predictions, updates learned weights, logs new ones."""

    name = "learning_loop"
    description = "Resolves prediction outcomes and updates agent/signal trust"

    def __init__(self, config=None):
        self.config = config or {}
        self.data_dir = self._get_data_dir()
        self.predictions_file = os.path.join(self.data_dir, "prediction_history.json")
        self.weights_file = os.path.join(self.data_dir, "learning_state.json")

    def run(self, recommendations, all_results=None, regime="neutral", reference_prices=None):
        all_results = all_results or []
        reference_prices = reference_prices or {}
        history = self._load_predictions()
        weight_memory = self._load_weights()
        learner = WeightLearner(weight_memory)

        newly_settled_signals, newly_settled_recs = self._resolve_pending(history)

        if newly_settled_signals:
            learner.update_weights(newly_settled_signals)
            learner.update_calibration(newly_settled_signals)

        self._log_new_signal_predictions(history, all_results, regime, reference_prices)
        self._log_new_recommendations(history, recommendations, regime, reference_prices)

        history["last_run"] = datetime.now(timezone.utc).isoformat()
        self._save_predictions(history)
        self._save_weights(weight_memory)

        stats = self._compute_stats(history, newly_settled_recs)

        return {
            "agent": self.name,
            "stats": stats,
            "track_record": self._track_record(history),
            "weights_sample": self._weight_sample(weight_memory),
            "newly_settled_signals": len(newly_settled_signals),
            "newly_settled_recommendations": len(newly_settled_recs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ---------------- resolving past predictions ----------------

    def _resolve_pending(self, history):
        now = datetime.now(timezone.utc)
        price_cache = {}

        def current_close(symbol):
            if symbol in price_cache:
                return price_cache[symbol]
            price = None
            try:
                hist = fetch_yf_history(symbol, period="5d", interval="1d")
                closes = hist["Close"].dropna() if hist is not None and not hist.empty else None
                if closes is not None and not closes.empty:
                    price = float(closes.iloc[-1])
            except Exception:
                price = None
            price_cache[symbol] = price
            return price

        settled_signals = []
        for pred in history.get("signal_predictions", []):
            if pred.get("resolved"):
                continue
            if not self._is_old_enough(pred.get("timestamp"), now):
                continue
            symbol = pred.get("symbol")
            entry_price = pred.get("price_at_prediction")
            if not symbol or not entry_price:
                pred["resolved"] = True  # can't ever resolve this one; stop retrying
                continue
            price_now = current_close(symbol)
            if price_now is None:
                continue  # try again next run
            ret_pct = (price_now - entry_price) / entry_price * 100
            pred["resolved"] = True
            pred["outcome_return_pct"] = round(ret_pct, 3)
            pred["resolved_at"] = now.isoformat()
            settled_signals.append(pred)

        settled_recs = []
        for pred in history.get("recommendation_predictions", []):
            if pred.get("resolved"):
                continue
            if not self._is_old_enough(pred.get("timestamp"), now):
                continue
            symbol = pred.get("symbol")
            entry_price = pred.get("price_at_prediction")
            if not symbol or not entry_price:
                pred["resolved"] = True
                continue
            price_now = current_close(symbol)
            if price_now is None:
                continue
            ret_pct = (price_now - entry_price) / entry_price * 100
            pred["resolved"] = True
            pred["outcome_return_pct"] = round(ret_pct, 3)
            pred["resolved_at"] = now.isoformat()
            pred["correct"] = self._is_correct(pred.get("action"), ret_pct)
            settled_recs.append(pred)

        return settled_signals, settled_recs

    def _is_old_enough(self, timestamp, now):
        if not timestamp:
            return False
        try:
            ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception:
            return False
        return (now - ts) >= timedelta(hours=SETTLE_HOURS)

    def _is_correct(self, action, ret_pct):
        if action == "BUY":
            return ret_pct >= DIRECTIONAL_MOVE_THRESHOLD_PCT
        if action == "SELL":
            return ret_pct <= -DIRECTIONAL_MOVE_THRESHOLD_PCT
        if action == "WATCH":
            return None  # not a directional bet; excluded from accuracy scoring
        return None

    # ---------------- logging new predictions ----------------

    def _log_new_signal_predictions(self, history, all_results, regime, reference_prices):
        preds = history.setdefault("signal_predictions", [])
        now_iso = datetime.now(timezone.utc).isoformat()
        for result in all_results:
            if not result or result.get("error"):
                continue
            symbol = result.get("symbol")
            agent = result.get("agent")
            price = reference_prices.get(symbol)
            for sig in result.get("signals", []):
                direction = signal_direction(sig)
                if direction == 0 or not price:
                    continue  # neutral/risk-flag signals and priceless symbols aren't directional bets
                preds.append({
                    "symbol": symbol,
                    "agent": agent,
                    "signal_type": sig.get("type"),
                    "direction": direction,
                    "confidence": sig.get("confidence", result.get("confidence", 0)),
                    "regime": regime,
                    "price_at_prediction": price,
                    "timestamp": now_iso,
                    "resolved": False,
                    "outcome_return_pct": None,
                })
        # Cap growth: keep the most recent slice so the file doesn't grow forever.
        if len(preds) > 5000:
            history["signal_predictions"] = preds[-5000:]

    def _log_new_recommendations(self, history, recommendations, regime, reference_prices):
        preds = history.setdefault("recommendation_predictions", [])
        now_iso = datetime.now(timezone.utc).isoformat()
        for rec in recommendations:
            preds.append({
                "symbol": rec.get("symbol"),
                "action": rec.get("action"),
                "confidence": rec.get("confidence"),
                "regime": regime,
                "price_at_prediction": reference_prices.get(rec.get("symbol")),
                "timestamp": now_iso,
                "resolved": False,
                "outcome_return_pct": None,
                "correct": None,
            })
        if len(preds) > 5000:
            history["recommendation_predictions"] = preds[-5000:]

    # ---------------- stats / persistence ----------------

    def _compute_stats(self, history, newly_settled_recs):
        recs = history.get("recommendation_predictions", [])
        resolved = [p for p in recs if p.get("resolved") and p.get("correct") is not None]
        correct = [p for p in resolved if p.get("correct")]
        accuracy = (len(correct) / len(resolved) * 100) if resolved else 0.0

        sig_preds = history.get("signal_predictions", [])
        sig_resolved = [p for p in sig_preds if p.get("resolved") and p.get("outcome_return_pct") is not None]

        return {
            "total_recommendations_logged": len(recs),
            "resolved_recommendations": len(resolved),
            "correct_recommendations": len(correct),
            "accuracy_pct": round(accuracy, 1),
            "total_signal_predictions_logged": len(sig_preds),
            "resolved_signal_predictions": len(sig_resolved),
        }

    def _track_record(self, history):
        """Per-signal / per-agent / per-action win rate and average return.

        A call "wins" when the price moved the way it pointed: up for bullish
        signals and BUY calls, down for bearish signals and SELL calls. Returns
        are directional (a SELL that fell 2% counts as +2%) and measured from
        the price at the call to the close when it was resolved (~1 trading
        session later, see SETTLE_HOURS).

        The scanner runs several times a day and a persistent signal (e.g.
        analyst consensus) is re-logged on every run, so the same signal on the
        same stock is counted once per day. Otherwise one stock could appear
        four times and inflate the sample size.
        """

        def day_key(p, field):
            return (p.get("symbol"), p.get(field), str(p.get("timestamp") or "")[:10])

        def summarize(directional_returns):
            n = len(directional_returns)
            if not n:
                return {"n": 0, "win_rate_pct": None, "avg_return_pct": None}
            wins = sum(1 for r in directional_returns if r > 0)
            return {
                "n": n,
                "win_rate_pct": round(wins / n * 100, 1),
                "avg_return_pct": round(sum(directional_returns) / n, 2),
            }

        seen = set()
        by_signal, by_agent, all_signals = {}, {}, []
        pending_signals = 0
        for p in history.get("signal_predictions", []):
            if not p.get("resolved"):
                pending_signals += 1
                continue
            ret = p.get("outcome_return_pct")
            direction = p.get("direction")
            if ret is None or direction not in (1, -1):
                continue
            key = day_key(p, "signal_type")
            if key in seen:
                continue
            seen.add(key)
            dret = ret * direction
            sig = p.get("signal_type") or "unknown"
            by_signal.setdefault((sig, direction), []).append(dret)
            by_agent.setdefault(p.get("agent") or "unknown", []).append(dret)
            all_signals.append(dret)

        seen = set()
        by_action = {"BUY": [], "SELL": [], "WATCH": []}
        pending_recs = 0
        for p in history.get("recommendation_predictions", []):
            if not p.get("resolved"):
                pending_recs += 1
                continue
            ret = p.get("outcome_return_pct")
            action = p.get("action")
            if ret is None or action not in by_action:
                continue
            key = day_key(p, "action")
            if key in seen:
                continue
            seen.add(key)
            # WATCH isn't a directional bet: report its raw move (win = rose).
            by_action[action].append(-ret if action == "SELL" else ret)

        signals = [
            dict(signal_type=sig, side="bullish" if d == 1 else "bearish", **summarize(rets))
            for (sig, d), rets in by_signal.items()
        ]
        signals.sort(key=lambda r: (-r["n"], r["signal_type"]))
        agents = [dict(agent=a, **summarize(rets)) for a, rets in by_agent.items()]
        agents.sort(key=lambda r: (-r["n"], r["agent"]))

        timestamps = [
            p.get("timestamp")
            for p in history.get("recommendation_predictions", []) + history.get("signal_predictions", [])
            if p.get("timestamp")
        ]
        return {
            "horizon": "~1 trading session",
            "dedupe": "same signal on the same stock counted once per day",
            "tracking_since": min(timestamps) if timestamps else None,
            "pending_signals": pending_signals,
            "pending_recommendations": pending_recs,
            "overall_signals": summarize(all_signals),
            "by_action": {a: summarize(r) for a, r in by_action.items()},
            "by_signal": signals,
            "by_agent": agents,
        }

    def _weight_sample(self, weight_memory, top_n=8):
        weights = weight_memory.get("weights", {})
        ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
        return {k: v for k, v in ranked[:top_n]}

    def _get_data_dir(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base, "data")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir

    def _load_predictions(self):
        if os.path.exists(self.predictions_file):
            try:
                with open(self.predictions_file, "r") as f:
                    data = json.load(f)
                    data.setdefault("signal_predictions", [])
                    data.setdefault("recommendation_predictions", [])
                    return data
            except (json.JSONDecodeError, IOError):
                pass
        return {"signal_predictions": [], "recommendation_predictions": [], "last_run": None}

    def _save_predictions(self, history):
        with open(self.predictions_file, "w") as f:
            # _sanitize turns any stray NaN/inf into null instead of crashing the
            # whole scan (a NaN here aborted the 2026-09-25 run before data.json
            # was written, leaving the dashboard on midday prices).
            json.dump(_sanitize(history), f, indent=2, default=str, allow_nan=False)

    def _load_weights(self):
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _save_weights(self, weight_memory):
        with open(self.weights_file, "w") as f:
            json.dump(_sanitize(weight_memory), f, indent=2, default=str, allow_nan=False)
