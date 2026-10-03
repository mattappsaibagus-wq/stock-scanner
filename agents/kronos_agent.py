"""Kronos Forecast Agent - Japan-only candlestick foundation-model forecasts.

Wraps Kronos (https://github.com/shiyu-coder/Kronos, MIT, vendored under
vendor/kronos/) - a decoder-only Transformer pre-trained on K-line (OHLCV)
sequences from 45+ exchanges - and turns its probabilistic forecasts into
ordinary Kaito Detector signals the advisor and learning loop already know
how to weigh.

How a signal is produced, per Tokyo (.T) symbol:
  1. Take the last `lookback` COMPLETE daily bars. A bar for a session that
     hasn't closed yet (e.g. the 11:45 JST lunch-break run) is dropped -
     Kronos would otherwise read a half-day candle as a finished one.
  2. Build future timestamps on the real TSE calendar (weekends, Japanese
     public holidays, Dec 31 - Jan 3 closure) so the model's time features
     line up with actual trading days.
  3. Sample `n_paths` independent forecast paths. Kronos' own predict()
     averages its samples internally, which throws away the uncertainty;
     here every path is a separate batch row so agreement can be measured.
  4. Target = forecast close on the trading day the learning loop will
     actually judge (about one session out, see _target_index), compared
     with the pipeline's reference price.
  5. Emit kronos_forecast_up / kronos_forecast_down only when the paths
     mostly agree on direction, the mean is statistically distinguishable
     from zero across paths (t-stat), AND the move clears a noise floor.
     Otherwise: no signal. Nothing is ever emitted when the model can't be
     loaded - same integrity rule as the news scanner (no fabricated
     evidence ever reaches the advisor).

The WeightLearner then tracks these two signal types like any other, so if
Kronos turns out to have no edge on TSE names, its influence decays on its
own.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from agents.base_agent import BaseAgent

JST = timezone(timedelta(hours=9))
TSE_CLOSE_HOUR, TSE_CLOSE_MINUTE = 15, 30  # TSE close since Nov 2024
# Treat a session as final shortly after the close. Kept inside the 15:45 JST
# after-close scan (scan.yml), which exists precisely to capture the close.
SESSION_FINAL_DELAY_MIN = 10

_VENDOR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor", "kronos")

DEFAULTS = {
    "model_id": "NeoQuasar/Kronos-small",
    "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
    "max_context": 512,
    "lookback": 200,          # daily bars of context (~10 months)
    "min_history": 120,       # skip recent IPOs with less history than this
    "pred_len": 3,            # trading days forecast (covers the target day)
    "n_paths": 8,             # independent sample paths per symbol
    "temperature": 1.0,
    "top_p": 0.9,
    "chunk_size": 64,         # batch rows per forward pass (bounds memory)
    "min_move_pct": 0.5,      # |expected move| noise floor
    "min_agreement": 0.75,    # share of paths that must agree on direction
    "min_t_stat": 2.5,        # mean move / std error across paths (~4% two-sided at 8 paths)
    "vol_window": 60,         # days used for realized daily volatility
}


# ---------------------------------------------------------------- calendar

def _is_tse_holiday(d):
    """Weekend, Japanese public holiday, or the Dec 31 - Jan 3 closure."""
    if d.weekday() >= 5:
        return True
    if (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3):
        return True
    try:
        import jpholiday
        return bool(jpholiday.is_holiday(d))
    except ImportError:
        return False  # weekday-only fallback; minor time-feature error at worst


def next_trading_days(after_date, count):
    days, d = [], after_date
    while len(days) < count:
        d = d + timedelta(days=1)
        if not _is_tse_holiday(d):
            days.append(d)
    return days


def _session_final_at(d):
    return datetime(d.year, d.month, d.day, TSE_CLOSE_HOUR, TSE_CLOSE_MINUTE, tzinfo=JST) \
        + timedelta(minutes=SESSION_FINAL_DELAY_MIN)


# ---------------------------------------------------------------- agent

class KronosForecastAgent(BaseAgent):
    """Probabilistic next-session forecasts from the Kronos foundation model."""

    name = "kronos_agent"
    description = "Kronos foundation-model candlestick forecasts (TSE only)"

    def __init__(self, config=None, predictor=None):
        super().__init__(config)
        self.cfg = dict(DEFAULTS)
        self.cfg.update(config or {})
        self._predictor = predictor          # injectable for tests
        self._load_attempted = predictor is not None
        self.available = predictor is not None
        self.unavailable_reason = None
        self.last_run_stats = {}

    # ---- model loading (lazy; failure = agent silently produces nothing)

    def _load(self):
        if self._load_attempted:
            return self.available
        self._load_attempted = True
        if os.environ.get("KRONOS_ENABLED", "1").strip() in ("0", "false", "no", "off"):
            self.unavailable_reason = "disabled via KRONOS_ENABLED"
            return False
        try:
            import torch
            if _VENDOR_DIR not in sys.path:
                sys.path.insert(0, _VENDOR_DIR)
            from model import Kronos, KronosTokenizer, KronosPredictor

            torch.set_num_threads(max(1, os.cpu_count() or 1))
            tokenizer = KronosTokenizer.from_pretrained(self.cfg["tokenizer_id"])
            model = Kronos.from_pretrained(self.cfg["model_id"])
            tokenizer.eval()
            model.eval()
            self._predictor = KronosPredictor(model, tokenizer, max_context=self.cfg["max_context"])
            self.available = True
        except Exception as e:  # ImportError (no torch), HF download failure, ...
            self.unavailable_reason = f"{type(e).__name__}: {e}"
            self.available = False
        return self.available

    def _seed(self, now_jst):
        # Same day -> same sampled paths, so the 4 daily scans don't flip a
        # call back and forth on sampling noise alone.
        try:
            import torch
            torch.manual_seed(int(now_jst.strftime("%Y%m%d")))
        except Exception:
            pass
        np.random.seed(int(now_jst.strftime("%Y%m%d")) % (2 ** 32))

    # ---- public API

    def analyze(self, symbol, data=None):
        data = data or {}
        out = self.analyze_batch({symbol: (data.get("history"), data.get("reference_price"))})
        return out[0] if out else None

    def analyze_batch(self, inputs, now=None):
        """inputs: {symbol: (daily_history_df, reference_price)} -> list of results."""
        now_jst = (now or datetime.now(timezone.utc)).astimezone(JST)
        stats = {"requested": len(inputs), "eligible": 0, "forecast": 0, "signals": 0,
                 "skipped": {}, "seconds": 0.0}
        self.last_run_stats = stats

        jp = {s: v for s, v in inputs.items() if str(s).upper().endswith(".T")}
        if not jp:
            return []
        if not self._load():
            stats["unavailable"] = self.unavailable_reason
            return []

        prepared = {}
        for symbol, (hist, ref_price) in jp.items():
            item, why = self._prepare(symbol, hist, ref_price, now_jst)
            if item is None:
                stats["skipped"][why] = stats["skipped"].get(why, 0) + 1
            else:
                prepared[symbol] = item
        stats["eligible"] = len(prepared)
        if not prepared:
            return []

        t0 = time.time()
        self._seed(now_jst)
        paths = self._forecast_paths(prepared)
        stats["seconds"] = round(time.time() - t0, 1)

        results = []
        for symbol, item in prepared.items():
            closes = paths.get(symbol)
            if closes is None:
                stats["skipped"]["forecast_failed"] = stats["skipped"].get("forecast_failed", 0) + 1
                continue
            stats["forecast"] += 1
            result = self._to_result(symbol, item, closes)
            if result:
                stats["signals"] += 1
                results.append(result)
        return results

    # ---- preparation

    def _prepare(self, symbol, hist, ref_price, now_jst):
        if hist is None or getattr(hist, "empty", True):
            return None, "no_history"
        cols = {c.lower(): c for c in hist.columns}
        if not all(k in cols for k in ("open", "high", "low", "close")):
            return None, "bad_columns"

        df = pd.DataFrame({k: hist[cols[k]].astype(float) for k in ("open", "high", "low", "close")})
        df["volume"] = hist[cols["volume"]].astype(float).fillna(0.0) if "volume" in cols else 0.0
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]

        idx = pd.DatetimeIndex(df.index)
        if idx.tz is not None:
            idx = idx.tz_convert("Asia/Tokyo")
        dates = [ts.date() for ts in idx]
        df.index = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])  # naive 00:00, one row/day
        df = df[~df.index.duplicated(keep="last")]

        # Drop an unfinished session's bar (e.g. the lunch-break run).
        if len(df) and df.index[-1].date() == now_jst.date() and now_jst < _session_final_at(now_jst.date()):
            df = df.iloc[:-1]

        if len(df) < self.cfg["min_history"]:
            return None, "short_history"

        x = df.tail(self.cfg["lookback"])
        last_date = x.index[-1].date()
        future = next_trading_days(last_date, self.cfg["pred_len"])
        target = self._target_index(future, now_jst)

        ref = float(ref_price) if ref_price else float(x["close"].iloc[-1])
        rets = np.log(df["close"]).diff().dropna().tail(self.cfg["vol_window"])
        daily_vol_pct = float(rets.std() * 100) if len(rets) > 5 else None

        return {
            "x": x,
            "x_ts": pd.Series(x.index),
            "y_ts": pd.Series(pd.DatetimeIndex([pd.Timestamp(d) for d in future])),
            "future": future,
            "target": target,
            "reference_price": ref,
            "last_close": float(x["close"].iloc[-1]),
            "last_bar_date": last_date,
            "daily_vol_pct": daily_vol_pct,
            "context_len": len(x),
        }, None

    @staticmethod
    def _target_index(future, now_jst):
        """Pick the forecast day the learning loop will effectively grade.

        The loop resolves a prediction on the first run >= ~20h later, using
        the latest close Yahoo has then. So: the last forecast day whose
        session is final within ~24h of now (at least the first future day).
        """
        horizon = now_jst + timedelta(hours=24)
        target = 0
        for i, d in enumerate(future):
            if _session_final_at(d) <= horizon:
                target = i
        return target

    # ---- inference

    def _forecast_paths(self, prepared):
        """Returns {symbol: np.array(n_paths, pred_len) of forecast closes}."""
        n = self.cfg["n_paths"]
        pred_len = self.cfg["pred_len"]

        # predict_batch needs equal context lengths: group by length.
        groups = {}
        for symbol, item in prepared.items():
            groups.setdefault(item["context_len"], []).append(symbol)

        out = {}
        for _, symbols in groups.items():
            rows = [(s, p) for s in symbols for p in range(n)]  # each path = its own row
            for start in range(0, len(rows), self.cfg["chunk_size"]):
                chunk = rows[start:start + self.cfg["chunk_size"]]
                try:
                    preds = self._predictor.predict_batch(
                        df_list=[prepared[s]["x"] for s, _ in chunk],
                        x_timestamp_list=[prepared[s]["x_ts"] for s, _ in chunk],
                        y_timestamp_list=[prepared[s]["y_ts"] for s, _ in chunk],
                        pred_len=pred_len,
                        T=self.cfg["temperature"],
                        top_p=self.cfg["top_p"],
                        sample_count=1,
                        verbose=False,
                    )
                except Exception as e:
                    print(f"[kronos_agent] WARNING: batch failed ({type(e).__name__}: {e})", flush=True)
                    continue
                for (s, _), pdf in zip(chunk, preds):
                    out.setdefault(s, []).append(pdf["close"].to_numpy(dtype=float))

        return {s: np.vstack(v) for s, v in out.items() if len(v) == n}

    # ---- signal

    def _to_result(self, symbol, item, closes):
        ref = item["reference_price"]
        t = item["target"]
        path_rets = (closes[:, t] - ref) / ref * 100.0
        if not np.all(np.isfinite(path_rets)):
            return None

        mean_ret = float(np.mean(path_rets))
        direction = 1 if mean_ret > 0 else -1
        agreement = float(np.mean(np.sign(path_rets) == direction))
        vol = item["daily_vol_pct"]
        z = mean_ret / vol if vol else None

        # t-stat across sampled paths: agreement alone lets pure noise through
        # far too often with only a handful of paths (~1 in 5 in testing).
        sd = float(np.std(path_rets, ddof=1)) if len(path_rets) > 1 else 0.0
        t_stat = mean_ret / (sd / np.sqrt(len(path_rets))) if sd > 0 else float("inf") * direction

        if (abs(mean_ret) < self.cfg["min_move_pct"]
                or agreement < self.cfg["min_agreement"]
                or abs(t_stat) < self.cfg["min_t_stat"]):
            return None

        # 0.45 .. ~0.85: agreement does most of the work, a strong move vs.
        # the stock's own volatility adds a little. Deliberately modest - the
        # weight learner decides how much Kronos is really worth.
        agree_excess = (agreement - 0.5) * 2  # 0..1
        conf = 0.45 + 0.3 * agree_excess + (0.1 * min(abs(z), 1.5) if z is not None else 0.0)
        conf = round(min(conf, 0.85), 2)

        median_path = np.median(closes, axis=0)
        return {
            "symbol": symbol,
            "agent": self.name,
            "signals": [{
                "type": "kronos_forecast_up" if direction > 0 else "kronos_forecast_down",
                "expected_move_pct": round(mean_ret, 2),
                "path_agreement": round(agreement, 2),
                "target_date": item["future"][t].isoformat(),
                "confidence": conf,
            }],
            "forecast": {
                "model": self.cfg["model_id"],
                "target_date": item["future"][t].isoformat(),
                "expected_move_pct": round(mean_ret, 2),
                "range_pct": [round(float(np.percentile(path_rets, 10)), 2),
                              round(float(np.percentile(path_rets, 90)), 2)],
                "path_agreement": round(agreement, 2),
                "t_stat": round(float(t_stat), 2) if np.isfinite(t_stat) else None,
                "paths": int(closes.shape[0]),
                "daily_vol_pct": round(vol, 2) if vol else None,
                "move_vs_vol": round(z, 2) if z is not None else None,
                "reference_price": round(ref, 2),
                "median_path": [{"date": d.isoformat(), "close": round(float(c), 2)}
                                for d, c in zip(item["future"], median_path)],
                "last_bar_date": item["last_bar_date"].isoformat(),
                "context_bars": item["context_len"],
            },
            "confidence": conf,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert": conf >= 0.7,
        }
