import json
import os
from datetime import datetime, timezone


class BaseAgent:
    """Base class for all agents in the Kaito Detector pipeline."""

    name = "base"
    description = "Base agent"

    def __init__(self, config=None):
        self.config = config or {}
        self.results = []

    def analyze(self, symbol, data=None):
        raise NotImplementedError("Subclasses must implement analyze()")

    def run(self, symbols, shared_data=None):
        results = []
        for symbol in symbols:
            try:
                result = self.analyze(symbol, data=shared_data)
                if result:
                    results.append(result)
            except Exception as e:
                results.append({
                    "symbol": symbol,
                    "agent": self.name,
                    "error": str(e),
                    "timestamp": _utcnow(),
                })
        return results

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "config": self.config,
        }


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def save_json(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return filepath


def load_json(filepath):
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r") as f:
        return json.load(f)


def load_watchlist(filepath="watchlist.txt"):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        return [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]


def get_data_dir():
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def fetch_yf_history(symbol, period="5d", interval="5m"):
    """Fetch history with polite pacing and retries so large watchlists (60+ symbols)
    scanned back-to-back don't trip Yahoo's burst rate limiting (HTTP 429)."""
    import time
    for attempt in range(3):
        try:
            # Pacing between Yahoo calls; back off progressively on retries.
            time.sleep(0.3 * (attempt + 1))
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period, interval=interval)
            if hist is not None and not hist.empty:
                return hist
        except Exception:
            pass
    return _fetch_simple_history(symbol, period=period)


def _fetch_simple_history(symbol, period="5d"):
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        return hist
    except Exception:
        return None


def get_price_change(hist):
    if hist is None or hist.empty:
        return None
    try:
        first = hist["Close"].iloc[0]
        last = hist["Close"].iloc[-1]
        change = last - first
        pct = (change / first) * 100 if first != 0 else 0
        return {
            "open": float(first),
            "close": float(last),
            "change": float(change),
            "change_pct": round(float(pct), 2),
            "high": float(hist["High"].max()),
            "low": float(hist["Low"].min()),
            "volume": int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0,
        }
    except Exception:
        return None
