# Kaito Detector

A multi-agent stock scanner specialized for the **Japanese market** — Nikkei
mega-caps down to TSE Growth Market micro-caps — with a smaller secondary US
watchlist for cross-market context. Seven independent agents sweep price
action, momentum, chart patterns, sector relative strength, analyst
sentiment, news, and fundamentals; a regime-aware advisor weighs their
track records and consolidates everything into **BUY / WATCH / SELL**
calls; a real self-learning loop resolves every past call against what
actually happened and adjusts trust accordingly.

## Agents

| Agent | File | Job |
|-------|------|-----|
| **Early Detector** | `agents/early_detector.py` | Unusual intraday price moves and volume spikes |
| **Momentum** | `agents/momentum_agent.py` | RSI, MACD, SMA20/50 trend strength |
| **Pattern Agent** | `agents/pattern_agent.py` | Breakouts/breakdowns, engulfing candles, support bounces |
| **Sector Agent** | `agents/sector_agent.py` | Relative strength vs. sector ETF (US) / Nikkei 225 (Japan) |
| **Analyst Sentiment** | `agents/sentiment_agent.py` | Analyst consensus, upgrade/downgrade trend, price-target upside |
| **News Scanner** | `agents/news_scanner.py` | Real headline sentiment (never fabricated — see below) |
| **Due Diligence** | `agents/dd_agent.py` | Market cap, P/E, float, sector fundamentals |
| **Macro Agent** | `agents/macro_agent.py` | Market-wide regime (VIX + SPY trend) → risk_on / neutral / risk_off |
| **Advisor** | `agents/advisor.py` | Weighted, regime-gated consolidation into BUY/WATCH/SELL |
| **Weight Learner** | `agents/weight_learner.py` | Regime-aware EMA trust learning per signal type & per agent |
| **Learning Loop** | `agents/learning_loop.py` | Resolves past predictions against real prices, drives the learner |

## How It's Smarter Than a Flat Vote

The advisor doesn't just count bullish vs. bearish signals. Each signal
type (e.g. `breakout`, `rsi_oversold`) carries a **learned weight** based
on how often it's actually paid off, tracked separately per market regime
— a signal that works in a calm bull market may not work in a panic.
Each contributing **agent** also earns a trust multiplier from its
historical win rate. Confidence is further gated by the current regime:
the same bullish evidence is trusted a bit less for a BUY call when the
broad market is risk-off, and vice versa for SELL.

## The Self-Learning Loop

```
run_pipeline.py
  |- MacroAgent.detect_regime()          - once per run, tags everything below
  |- 7 agents scan every symbol          - signals logged with price + regime
  |- AdvisorAgent.consolidate()          - weighted, regime-gated BUY/WATCH/SELL
  `- LearningLoop.run()
       |- resolves predictions >= ~1 trading session old against real prices
       |- feeds outcomes into WeightLearner (EMA update, per signal & agent)
       `- persists data/learning_state.json - read by the advisor next run
```

This closes a loop that previously didn't: predictions used to be logged
with an `outcome` field that was never actually filled in, so accuracy was
permanently 0% and the "learned" config was never read back by anything.
Now every call is checked against what the stock actually did, and the
weights that come out of that are the same weights the advisor uses on the
next run.

## Integrity Notes

- **No fabricated data ever feeds a signal.** The news scanner previously
  fell back to made-up headlines when a real fetch failed, which could
  silently drive a BUY/SELL call off invented text. It now emits no signal
  at all when it can't get real articles.
- **Signal direction is an explicit, reviewable table**
  (`agents/signal_taxonomy.py`), not substring guessing. The old advisor
  classified anything containing `"over"` as bearish, which silently
  mislabeled `rsi_oversold` - a bullish reversal signal - as bearish.
- **NaN/Infinity never reach the dashboard.** `save_json()` sanitizes
  non-finite floats before writing, since bare `NaN` tokens aren't valid
  JSON and used to break the live site outright.

## Watchlist

`watchlist.txt` is organized Japan-first, mega-cap -> micro-cap, with a
smaller US set at the bottom for sector-benchmark context:

- **Japan - Mega Cap**: Nikkei 225 / TOPIX Core30 class (Toyota, Sony, Keyence, SoftBank Group, Mitsubishi UFJ, NTT, ...)
- **Japan - Large Cap**: JPY1T-5T class (Denso, Daiichi Sankyo, Seven & I, Nomura, Bridgestone, ...)
- **Japan - Mid Cap**: semiconductor equipment & growth industrials (DISCO, Lasertec, Renesas, Recruit, CyberAgent, ...)
- **Japan - Small Cap**: (Mercari, Money Forward, Sansan, freee, DeNA, Nexon, ...)
- **Japan - Micro / Growth Market**: recent TSE Growth Market IPOs (ANYCOLOR, COVER, ispace, Timee, ...)
- **US - secondary set**: mega-caps, large-cap growth, mid-cap momentum names

## Dashboard

Deployed automatically via GitHub Actions:

```
https://mattappsaibagus-wq.github.io/stock-scanner/
```

## Local Development

```bash
pip install -r requirements.txt
python run_pipeline.py
```

Results are saved to:
- `data/signals.json` - full pipeline output, including the detected regime
- `data/prediction_history.json` - every logged prediction (signal- and recommendation-level) and its resolved outcome
- `data/learning_state.json` - learned per-signal-type and per-agent weights, read back by the advisor
- `dashboard/data.json` - what the live dashboard renders

## Automation

The workflow runs automatically twice a day (US session open, Tokyo
session open) and can be triggered manually from the **Actions** tab.

## License

Private use for trading signal generation. Not financial advice.
