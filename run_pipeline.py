#!/usr/bin/env python3
"""
Kaito Detector - Multi-Agent Stock Scanner Pipeline

Runs the full agent roster (price/volume, momentum, chart patterns, sector
relative strength, analyst sentiment, news, due diligence), gates them by
the current market regime, consolidates them into weighted BUY/WATCH/SELL
calls, and closes the self-learning loop by resolving prior predictions
against real outcomes before logging new ones.
"""

import json
import os
import sys
import time
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
from agents.advisor import AdvisorAgent
from agents.learning_loop import LearningLoop

AGENT_COUNT = 8


def _load_learning_state(data_dir):
    path = os.path.join(data_dir, "learning_state.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


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
    advisor = AdvisorAgent(config={"regime": regime}, learning_state=learning_state)
    learning_loop = LearningLoop()

    all_results = []
    reference_prices = {}

    for idx, symbol in enumerate(symbols):
        if idx:
            time.sleep(0.25)  # pace requests so Yahoo doesn't rate-limit long watchlists
        print(f"[Kaito Detector] Scanning {symbol}...")

        # Shared daily history: momentum (trend/oscillators) and pattern
        # (breakouts/candles) both want daily bars, so fetch once at the
        # longer window and let momentum use the tail of it. This also
        # fixes a latent bug where momentum's old 1mo-only fetch (~22 rows)
        # could never actually satisfy its own 50-day SMA check.
        daily_hist = fetch_yf_history(symbol, period="6mo", interval="1d")
        if daily_hist is not None and not daily_hist.empty:
            reference_prices[symbol] = float(daily_hist["Close"].iloc[-1])
            momentum_hist = daily_hist.tail(90)
        else:
            momentum_hist = None

        early_result = early_detector.analyze(symbol)
        momentum_result = momentum_agent.analyze(symbol, data={"history": momentum_hist} if momentum_hist is not None else None)
        news_result = news_scanner.analyze(symbol)
        dd_result = dd_agent.analyze(symbol)
        pattern_result = pattern_agent.analyze(symbol, data={"pattern_history": daily_hist} if daily_hist is not None else None)
        sector_result = sector_agent.analyze(symbol)
        sentiment_result = sentiment_agent.analyze(symbol)

        symbol_results = [early_result, momentum_result, news_result, dd_result,
                           pattern_result, sector_result, sentiment_result]
        for r in symbol_results:
            if r:
                all_results.append(r)

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
    }
    save_json(dashboard_report, dashboard_data_path)
    print(f"[Kaito Detector] Dashboard data saved to {dashboard_data_path}")

    print(f"[Kaito Detector] Pipeline complete! {len(recommendations)} recommendations generated.")
    return report


if __name__ == "__main__":
    main()
