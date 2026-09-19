#!/usr/bin/env python3
"""
Kaito Detector - Stock Early-Move Scanner Pipeline

This is the main entry point for the Kaito Detector stock scanner.
It runs all agents in sequence, consolidates results, and generates
a signals report that powers the web dashboard.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.base_agent import get_data_dir, load_watchlist, save_json, load_json
from agents.early_detector import EarlyDetectorAgent
from agents.momentum_agent import MomentumAgent
from agents.news_scanner import NewsScannerAgent
from agents.dd_agent import DdAgent
from agents.advisor import AdvisorAgent
from agents.learning_loop import LearningLoop


def main():
    data_dir = get_data_dir()
    print(f"[Kaito Detector] Starting pipeline - data dir: {data_dir}")

    watchlist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt")
    symbols = load_watchlist(watchlist_path)
    print(f"[Kaito Detector] Loaded {len(symbols)} symbols from watchlist")

    early_detector = EarlyDetectorAgent()
    momentum_agent = MomentumAgent()
    news_scanner = NewsScannerAgent()
    dd_agent = DdAgent()
    advisor = AdvisorAgent()
    learning_loop = LearningLoop()

    all_results = []
    for symbol in symbols:
        print(f"[Kaito Detector] Scanning {symbol}...")

        early_result = early_detector.analyze(symbol)
        momentum_result = momentum_agent.analyze(symbol)
        news_result = news_scanner.analyze(symbol)
        dd_result = dd_agent.analyze(symbol)

        symbol_results = [early_result, momentum_result, news_result, dd_result]
        for r in symbol_results:
            if r:
                all_results.append(r)

    print(f"[Kaito Detector] Collected {len(all_results)} agent results")

    recommendations = advisor.consolidate(all_results)
    print(f"[Kaito Detector] Generated {len(recommendations)} recommendations")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols_scanned": symbols,
        "total_agents": 4,
        "agent_results": all_results,
        "recommendations": recommendations,
    }

    learning_result = learning_loop.run(recommendations)
    report["learning"] = learning_result

    signals_path = os.path.join(data_dir, "signals.json")
    save_json(report, signals_path)
    print(f"[Kaito Detector] Signals saved to {signals_path}")

    dashboard_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "data.json")
    os.makedirs(os.path.dirname(dashboard_data_path), exist_ok=True)
    dashboard_report = {
        "generated_at": report["generated_at"],
        "recommendations": recommendations,
        "total_recommendations": len(recommendations),
    }
    save_json(dashboard_report, dashboard_data_path)
    print(f"[Kaito Detector] Dashboard data saved to {dashboard_data_path}")

    print(f"[Kaito Detector] Pipeline complete! {len(recommendations)} recommendations generated.")
    return report


if __name__ == "__main__":
    main()
