# Kaito Detector

Stock early-move scanner that detects unusual price movements, volume spikes, and news sentiment across a watchlist of symbols.

## Features

- **Early Movement Detection**: Identifies price changes >2% and volume spikes >1.5x average
- **Momentum Analysis**: RSI, MACD, and SMA indicators for trend strength
- **News Sentiment**: Scrapes and analyzes news headlines for bullish/bearish signals
- **Due Diligence**: Fundamental analysis (P/E ratio, market cap, float, beta)
- **AI Advisor**: Consolidates signals from all agents into BUY/SELL/WATCH recommendations
- **Learning Loop**: Tracks prediction accuracy and adjusts confidence thresholds over time
- **Live Dashboard**: Auto-refreshing web UI at the GitHub Pages URL

## Dashboard

The dashboard is deployed automatically via GitHub Actions:

```
https://mattappsaibagus-wq.github.io/stock-scanner/
```

## How It Works

```
watchlist.txt → run_pipeline.py → agents/ → advisor.py → data/signals.json + dashboard/data.json
```

1. **Symbols** are loaded from `watchlist.txt`
2. **Agents** analyze each symbol (4 active agents)
3. **Advisor** consolidates signals into recommendations
4. **Learning Loop** records results for accuracy tracking
5. **Dashboard** displays the latest recommendations

## Agents

| Agent | File | Description |
|-------|------|-------------|
| Early Detector | `agents/early_detector.py` | Price movements and volume anomalies |
| Momentum | `agents/momentum_agent.py` | RSI, MACD, SMA technical indicators |
| News Scanner | `agents/news_scanner.py` | News headline sentiment analysis |
| DD Agent | `agents/dd_agent.py` | Fundamentals (P/E, market cap, float) |
| Advisor | `agents/advisor.py` | Signal consolidation and recommendations |
| Learning Loop | `agents/learning_loop.py` | Accuracy tracking and config tuning |

## Local Development

```bash
pip install -r requirements.txt
python run_pipeline.py
```

Results are saved to:
- `data/signals.json` — Full pipeline output
- `data/learning_history.json` — Prediction history
- `data/advisor_config.json` — Auto-tuned configuration
- `dashboard/data.json` — Dashboard data

## Automation

The workflow runs automatically every weekday at 14:00 UTC and can be triggered manually from the **Actions** tab.

## License

Private use for trading signal generation.
