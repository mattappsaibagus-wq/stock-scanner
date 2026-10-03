# Kaito Detector

A multi-agent stock scanner specialized for the **Japanese market** — Nikkei
mega-caps down to TSE Growth Market micro-caps — with a smaller secondary US
watchlist for cross-market context. Eight independent agents sweep price
action, momentum, chart patterns, sector relative strength, analyst
sentiment, news, fundamentals, and (for Tokyo names) Kronos foundation-model
forecasts; a regime-aware advisor weighs their
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
| **Kronos Forecast** | `agents/kronos_agent.py` | TSE-only probabilistic next-session forecasts from the [Kronos](https://github.com/shiyu-coder/Kronos) candlestick foundation model |
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

## Kronos Forecast Agent

[Kronos](https://github.com/shiyu-coder/Kronos) (MIT, AAAI 2026) is a
Transformer pre-trained on candlestick (OHLCV) sequences from 45+ exchanges.
Its inference code is vendored under `vendor/kronos/`; the `Kronos-small`
weights are pulled from Hugging Face and cached in Actions.

For each `.T` symbol it samples **8 independent forecast paths** from ~200
complete daily bars and only emits `kronos_forecast_up` / `kronos_forecast_down`
when **all three** hold: ≥75% of paths agree on direction, the mean move is
significant across paths (t ≥ 2.5), and the move is ≥ 0.5%. Pure-noise
forecasts fire on roughly 5% of names under these gates.

Japan-specific handling:
- Unfinished sessions (the 11:45 JST lunch-break scan) are dropped, never fed
  to the model as a complete candle.
- Future timestamps follow the real TSE calendar — weekends, Japanese public
  holidays (`jpholiday`), and the Dec 31 – Jan 3 closure.
- The forecast target is the session the learning loop will actually grade
  (~one session out), so Kronos is judged on the same horizon it predicts.
- Sampling is seeded per JST date, so the four daily scans don't flip a call
  on sampling noise alone.

Kronos gets **no special trust**: its two signal types go through the same
WeightLearner as everything else, so if it has no edge on TSE names its
influence decays automatically. If torch or the weights are unavailable it
emits nothing and the scan carries on (`KRONOS_ENABLED=0` disables it).

Local setup (optional):

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-kronos.txt
```

Next step once there's a track record: fine-tune the tokenizer + predictor on
TSE history with the upstream `finetune/` scripts (needs a GPU), and only
switch if the fine-tuned model beats zero-shot on the learning loop's
resolved outcomes.

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
- `data/signals.json` - full pipeline output, including the detected regime and Kronos run stats
- `data/prediction_history.json` - every logged prediction (signal- and recommendation-level) and its resolved outcome
- `data/learning_state.json` - learned per-signal-type and per-agent weights, read back by the advisor
- `dashboard/data.json` - what the live dashboard renders

## Automation

The workflow runs automatically twice a day (US session open, Tokyo
session open) and can be triggered manually from the **Actions** tab.

## License

Private use for trading signal generation. Not financial advice.
