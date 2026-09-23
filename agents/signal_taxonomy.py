"""Single source of truth for "is this signal type bullish or bearish?"

The original advisor classified direction with substring matching
(`"over" in signal_type`), which silently misclassified rsi_oversold -
a bullish reversal signal - as bearish, because "oversold" contains the
substring "over". Bugs like that quietly corrupt every downstream
decision. This module replaces substring guessing with an explicit,
reviewable table, used consistently by the advisor and the weight
learner so a signal's meaning can never drift between the two.

+1 = bullish, -1 = bearish, 0 = informational/risk-context (contributes
to signal_count and confidence but isn't itself a directional bet).
`None` means "look at the signal's own `direction` field at runtime"
(early_movement and news_sentiment carry direction as data, not as
type).
"""

SIGNAL_DIRECTIONS = {
    # early_detector
    "early_movement": None,       # direction: "up" / "down"
    "volume_spike": 0,            # amplifies whatever else is happening; no bias alone

    # momentum_agent
    "rsi_overbought": -1,
    "rsi_oversold": 1,
    "macd_bullish": 1,
    "macd_bearish": -1,
    "above_sma": 1,
    "below_sma": -1,
    "strong_momentum": 1,

    # news_scanner
    "news_sentiment": None,       # direction: "positive" / "negative"

    # dd_agent
    "micro_cap_risk": 0,          # risk flag, not a directional call
    "potential_undervalued": 1,
    "potentially_overvalued": -1,
    "quality_momentum": 1,
    "low_float": 0,               # volatility risk flag, not directional

    # pattern_agent
    "breakout": 1,
    "breakdown": -1,
    "bullish_engulfing": 1,
    "bearish_engulfing": -1,
    "support_bounce": 1,

    # sector_agent
    "relative_strength_bullish": 1,
    "relative_strength_bearish": -1,

    # sentiment_agent
    "analyst_consensus_bullish": 1,
    "analyst_consensus_bearish": -1,
    "analyst_upgrade_trend": 1,
    "analyst_downgrade_trend": -1,
    "price_target_upside": 1,
    "price_target_downside": -1,
}


def signal_direction(signal: dict) -> int:
    """Return +1 (bullish), -1 (bearish), or 0 (neutral/unknown) for a signal dict."""
    signal_type = signal.get("type", "")
    mapped = SIGNAL_DIRECTIONS.get(signal_type, 0)
    if mapped is not None:
        return mapped
    # Runtime-determined direction (early_movement, news_sentiment).
    raw = str(signal.get("direction", "")).lower()
    if raw in ("up", "positive", "bullish"):
        return 1
    if raw in ("down", "negative", "bearish"):
        return -1
    return 0
