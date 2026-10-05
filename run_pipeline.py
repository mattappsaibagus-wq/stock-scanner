#!/usr/bin/env python3
"""
Kaito Detector - Multi-Agent Stock Scanner Pipeline

Runs the full agent roster (price/volume, momentum, chart patterns, sector
relative strength, analyst sentiment, news, due diligence, and Kronos
foundation-model forecasts for Tokyo names), gates them by
the current market regime, consolidates them into weighted BUY/WATCH/SELL
calls, and closes the self-learning loop by resolving prior predictions
against real outcomes before logging new ones.
"""

import json
import os
import sys
import time

import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.base_agent import get_data_dir, load_watchlist, save_json, load_json, fetch_yf_history
from agents.symbol_names import get_display_name
from agents.early_detector import EarlyDetectorAgent
from agents.momentum_agent import MomentumAgent
from agents.news_scanner import NewsScannerAgent
from agents.dd_agent import DdAgent
from agents.pattern_agent import PatternAgent
from agents.sector_agent import SectorAgent
from agents.sentiment_agent import SentimentAgent
from agents.macro_agent import MacroAgent
from agents.kronos_agent import KronosForecastAgent
from agents.advisor import AdvisorAgent
from agents.learning_loop import LearningLoop

AGENT_COUNT = 9


def _load_learning_state(data_dir):
    path = os.path.join(data_dir, "learning_state.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _agent_result_counts(all_results):
    """Per agent: how many symbols it returned a result for, and how many alerted."""
    counts = {}
    for r in all_results:
        name = r.get("agent") or "unknown"
        c = counts.setdefault(name, {"results": 0, "alerts": 0})
        c["results"] += 1
        if r.get("alert"):
            c["alerts"] += 1
    return counts


def main():
    data_dir = get_data_dir()
    print(f"[Kaito Detector] Starting pipeline - data dir: {data_dir}")

    watchlist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt")
    symbols = load_watchlist(watchlist_path)
    print(f"[Kaito Detector] Loaded {len(symbols)} symbols from watchlist")

    macro_agent = MacroAgent()
    regime_info = macro_agent.detect_regime()
    regime = regime_info["regime"]
    print(f"[Kaito Detector] Market regime: {regime} ({regime_info['reason']})")

    learning_state = _load_learning_state(data_dir)

    early_detector = EarlyDetectorAgent()
    momentum_agent = MomentumAgent()
    news_scanner = NewsScannerAgent()
    dd_agent = DdAgent()
    pattern_agent = PatternAgent()
    sector_agent = SectorAgent()
    sentiment_agent = SentimentAgent()
    kronos_agent = KronosForecastAgent()
    advisor = AdvisorAgent(config={"regime": regime}, learning_state=learning_state)
    learning_loop = LearningLoop()

    all_results = []
    reference_prices = {}
    failed_symbols = []
    kronos_inputs = {}  # Tokyo symbols -> (1y daily history, reference price)

    for idx, symbol in enumerate(symbols):
        if idx:
            time.sleep(0.25)  # pace requests so Yahoo doesn't rate-limit long watchlists
        print(f"[Kaito Detector] Scanning {symbol}...")

        # Shared daily history: momentum (trend/oscillators) and pattern
        # (breakouts/candles) both want daily bars, so fetch once at the
        # longer window and let momentum use the tail of it. This also
        # fixes a latent bug where momentum's old 1mo-only fetch (~22 rows)
        # could never actually satisfy its own 50-day SMA check.
        # One bad ticker (or a Yahoo hiccup) must never kill the whole scan:
        # skip it, log it, and keep going with the rest of the watchlist.
        try:
            # Fetch a year once: Kronos wants ~200 bars of context, while the
            # momentum/pattern agents keep seeing exactly the 6 months they
            # always did (sliced locally - no extra Yahoo call).
            daily_hist_1y = fetch_yf_history(symbol, period="1y", interval="1d")
            daily_hist = daily_hist_1y
            if daily_hist_1y is not None and not daily_hist_1y.empty:
                cutoff = daily_hist_1y.index[-1] - pd.DateOffset(months=6)
                daily_hist = daily_hist_1y[daily_hist_1y.index >= cutoff]
            previous_close = None
            # Yahoo sometimes returns a trailing row with a NaN close (common for
            # Tokyo tickers around the session boundary). Price off the last real
            # close so a NaN never becomes the reference price.
            closes = daily_hist["Close"].dropna() if daily_hist is not None and not daily_hist.empty else None
            if closes is not None and not closes.empty:
                reference_prices[symbol] = float(closes.iloc[-1])
                momentum_hist = daily_hist.tail(90)
                if len(closes) >= 2:
                    previous_close = float(closes.iloc[-2])
            else:
                momentum_hist = None

            early_result = early_detector.analyze(symbol, data={"previous_close": previous_close})
            momentum_result = momentum_agent.analyze(symbol, data={"history": momentum_hist, "previous_close": previous_close} if momentum_hist is not None else {"previous_close": previous_close})
            news_result = news_scanner.analyze(symbol)
            dd_result = dd_agent.analyze(symbol, data={"previous_close": previous_close})
            pattern_result = pattern_agent.analyze(symbol, data={"pattern_history": daily_hist, "previous_close": previous_close} if daily_hist is not None else {"previous_close": previous_close})
            sector_result = sector_agent.analyze(symbol)
            sentiment_result = sentiment_agent.analyze(symbol)

            symbol_results = [early_result, momentum_result, news_result, dd_result,
                               pattern_result, sector_result, sentiment_result]
            for r in symbol_results:
                if r:
                    all_results.append(r)

            if symbol.endswith(".T") and symbol in reference_prices:
                kronos_inputs[symbol] = (daily_hist_1y, reference_prices[symbol])
        except Exception as e:
            failed_symbols.append(symbol)
            print(f"[Kaito Detector] WARNING: skipped {symbol} after error: {type(e).__name__}: {e}", flush=True)

    # If Yahoo returned prices for less than half the watchlist, this run is
    # broken data, not a market view. Exit without touching data.json so the
    # dashboard keeps the last good scan (and shows STALE) instead of
    # publishing a half-empty list.
    priced = len(reference_prices)
    print(f"[Kaito Detector] Price data for {priced}/{len(symbols)} symbols; {len(failed_symbols)} skipped after errors", flush=True)
    if priced < len(symbols) * 0.5:
        print("::error::Yahoo returned prices for fewer than half the watchlist - not publishing this run", flush=True)
        sys.exit(1)

    # Kronos runs once over every Tokyo symbol in batched forward passes
    # (far cheaper than one model call per symbol). If torch / the weights
    # aren't available it contributes nothing and the scan carries on.
    kronos_results = kronos_agent.analyze_batch(kronos_inputs)
    all_results.extend(kronos_results)
    print(f"[Kaito Detector] Kronos forecast agent: {kronos_agent.last_run_stats}", flush=True)

    print(f"[Kaito Detector] Collected {len(all_results)} agent results across {AGENT_COUNT} agents")

    recommendations = advisor.consolidate(all_results)
    print(f"[Kaito Detector] Generated {len(recommendations)} recommendations")

    # Attach the per-agent evidence behind each recommendation so the dashboard
    # can open a signal "folder" and show what actually drove the call.
    details_by_symbol = {}
    for result in all_results:
        symbol = result.get("symbol")
        if not symbol:
            continue
        details_by_symbol.setdefault(symbol, []).append({
            "agent": result.get("agent"),
            "confidence": result.get("confidence"),
            "alert": bool(result.get("alert")),
            "signals": result.get("signals", []),
            "price": result.get("price"),
            "indicators": result.get("indicators"),
            "fundamentals": result.get("fundamentals"),
            "benchmark": result.get("benchmark"),
            "forecast": result.get("forecast"),
            "timestamp": result.get("timestamp"),
        })

    for recommendation in recommendations:
        recommendation.update(get_display_name(recommendation["symbol"]))
        recommendation["details"] = details_by_symbol.get(recommendation["symbol"], [])
        recommendation["reference_price"] = reference_prices.get(recommendation["symbol"])

    with_details = sum(1 for r in recommendations if r.get("details"))
    print(f"[Kaito Detector] Attached agent details to {with_details}/{len(recommendations)} recommendations")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": symbols,
        "total_agents": AGENT_COUNT,
        "regime": regime_info,
        "kronos": kronos_agent.last_run_stats,
        "agent_results": all_results,
        "recommendations": recommendations,
    }

    learning_result = learning_loop.run(
        recommendations,
        all_results=all_results,
        regime=regime,
        reference_prices=reference_prices,
    )
    report["learning"] = learning_result
    print(f"[Kaito Detector] Learning loop: {learning_result['stats']}")

    signals_path = os.path.join(data_dir, "signals.json")
    save_json(report, signals_path)
    print(f"[Kaito Detector] Signals saved to {signals_path}")

    dashboard_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "data.json")
    os.makedirs(os.path.dirname(dashboard_data_path), exist_ok=True)
    dashboard_report = {
        "generated_at": report["generated_at"],
        "regime": regime_info,
        "recommendations": recommendations,
        "total_recommendations": len(recommendations),
        "learning_stats": learning_result["stats"],
        "track_record": learning_result.get("track_record"),
        # Read by doctor/doctor.py (System Health): lets it spot an agent that
        # went silent or a Yahoo outage that skipped half the watchlist,
        # instead of us finding out by eyeballing the dashboard.
        "scan_health": {
            "symbols_total": len(symbols),
            "symbols_priced": priced,
            "failed_symbols": failed_symbols,
            "agent_results": _agent_result_counts(all_results),
            "kronos": kronos_agent.last_run_stats,
        },
    }
    save_json(dashboard_report, dashboard_data_path)
    print(f"[Kaito Detector] Dashboard data saved to {dashboard_data_path}")

    print(f"[Kaito Detector] Pipeline complete! {len(recommendations)} recommendations generated.")
    return report


if __name__ == "__main__":
    main()
