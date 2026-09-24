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


def _sanitize(obj):
    """Replace non-finite floats (NaN/Infinity/-Infinity) with None.

    Python's json module writes these as bare NaN/Infinity tokens by
    default, which are not valid JSON and make browsers' JSON.parse
    (and response.json()) reject the whole payload.
    """
    if isinstance(obj, float):
        return obj if obj == obj and obj not in (float("inf"), float("-inf")) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def save_json(data, filepath):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(_sanitize(data), f, indent=2, default=str, allow_nan=False)
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
    scanned back-to-back don't trip Yahoo's burst rate limiting (HTTP 429).

    Cached per (symbol, period, interval) for the lifetime of the process so
    agents that want the same window of history don't each issue their own
    network call.
    """
    key = (symbol, period, interval)
    if key in _HISTORY_CACHE:
        return _HISTORY_CACHE[key]

    import time
    hist = None
    for attempt in range(3):
        try:
            # Pacing between Yahoo calls; back off progressively on retries.
            time.sleep(0.3 * (attempt + 1))
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period, interval=interval)
            if hist is not None and not hist.empty:
                break
        except Exception:
            hist = None
    if hist is None or hist.empty:
        hist = _fetch_simple_history(symbol, period=period)

    _HISTORY_CACHE[key] = hist
    return hist


_HISTORY_CACHE = {}
_INFO_CACHE = {}


def fetch_yf_info(symbol):
    """Fetch (and cache) yfinance's `.info` dict for a symbol.

    Several agents (due diligence, sentiment) want fundamentals/analyst data
    for the same symbol in the same run; caching avoids duplicate network
    round-trips against the same slow endpoint.
    """
    if symbol in _INFO_CACHE:
        return _INFO_CACHE[symbol]
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception:
        info = {}
    _INFO_CACHE[symbol] = info
    return info


def _fetch_simple_history(symbol, period="5d"):
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        return hist
    except Exception:
        return None


def get_price_change(hist, previous_close=None):
    """Summarizes a price history window into open/close/change/high/low/volume.

    `change`/`change_pct` are computed against `previous_close` (the actual
    previous trading day's official close) when provided - this matches how
    every real market site defines "change," and is NOT the same as the
    first bar of whatever window `hist` happens to cover. The earlier
    version used that first bar as the reference point, which meant a
    3-day intraday fetch reported a 3-day change as "the change," a 5-day
    fetch reported a 5-day change, and so on - each agent silently
    disagreeing with the others and with any real market source, even at
    the same moment in time.

    When `hist` spans more than one calendar day (e.g. a multi-day
    intraday window fetched for signal detection), high/low/volume are
    also narrowed to just the most recent session's rows, so "session
    high/low" means today's session, not the whole fetched window - and
    volume is summed across that session rather than returning a single
    bar's volume.
    """
    if hist is None or hist.empty:
        return None
    try:
        last_date = hist.index[-1].date()
        session = hist[hist.index.map(lambda ts: ts.date()) == last_date]
        if session.empty:
            session = hist

        last = float(hist["Close"].iloc[-1])

        if previous_close is not None and previous_close != 0:
            change = last - float(previous_close)
            pct = (change / float(previous_close)) * 100
        else:
            first = float(hist["Close"].iloc[0])
            change = last - first
            pct = (change / first) * 100 if first != 0 else 0

        return {
            "open": float(session["Close"].iloc[0]),
            "close": last,
            "change": float(change),
            "change_pct": round(float(pct), 2),
            "high": float(session["High"].max()),
            "low": float(session["Low"].min()),
            "volume": int(session["Volume"].sum()) if "Volume" in session.columns else 0,
            "previous_close": float(previous_close) if previous_close is not None else None,
        }
    except Exception:
        return None
