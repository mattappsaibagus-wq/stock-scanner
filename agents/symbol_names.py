"""Static ticker -> company name map for dashboard display.

Kept as static metadata so every pipeline run can label recommendations
without extra Yahoo API calls. Japanese tickers carry both the official
Japanese company name (kanji/katakana as registered) and the English name;
US tickers carry English only. Notes: Sansan trades under its Latin-script
name even in Japan, and IHI's former kanji name is shown parenthetically.
"""

SYMBOL_NAMES = {
    # ---------- US ----------
    "AAPL": {"en": "Apple"},
    "MSFT": {"en": "Microsoft"},
    "GOOGL": {"en": "Alphabet"},
    "TSLA": {"en": "Tesla"},
    "NVDA": {"en": "NVIDIA"},
    "AMD": {"en": "Advanced Micro Devices"},
    "META": {"en": "Meta Platforms"},
    "NFLX": {"en": "Netflix"},
    "AMZN": {"en": "Amazon"},
    "SPY": {"en": "SPDR S&P 500 ETF"},
    "CRM": {"en": "Salesforce"},
    "ADBE": {"en": "Adobe"},
    "NOW": {"en": "ServiceNow"},
    "INTU": {"en": "Intuit"},
    "UBER": {"en": "Uber Technologies"},
    "ABNB": {"en": "Airbnb"},
    "PLTR": {"en": "Palantir Technologies"},
    "CRWD": {"en": "CrowdStrike"},
    "AXON": {"en": "Axon Enterprise"},
    "ANET": {"en": "Arista Networks"},
    "MU": {"en": "Micron Technology"},
    "VRT": {"en": "Vertiv Holdings"},
    "DDOG": {"en": "Datadog"},
    "ZS": {"en": "Zscaler"},
    "NET": {"en": "Cloudflare"},
    "SNOW": {"en": "Snowflake"},
    "DUOL": {"en": "Duolingo"},
    "HOOD": {"en": "Robinhood Markets"},
    "CELH": {"en": "Celsius Holdings"},
    "ARM": {"en": "Arm Holdings"},
    "APP": {"en": "AppLovin"},
    "RKLB": {"en": "Rocket Lab"},
    # ---------- Japan — mega caps ----------
    "7203.T": {"en": "Toyota Motor", "jp": "トヨタ自動車"},
    "6758.T": {"en": "Sony Group", "jp": "ソニーグループ"},
    "6861.T": {"en": "Keyence", "jp": "キーエンス"},
    "9984.T": {"en": "SoftBank Group", "jp": "ソフトバンクグループ"},
    "9983.T": {"en": "Fast Retailing", "jp": "ファーストリテイリング"},
    "8035.T": {"en": "Tokyo Electron", "jp": "東京エレクトロン"},
    "6981.T": {"en": "Murata Manufacturing", "jp": "村田製作所"},
    "6501.T": {"en": "Hitachi", "jp": "日立製作所"},
    "8306.T": {"en": "Mitsubishi UFJ Financial Group", "jp": "三菱UFJフィナンシャル・グループ"},
    "9432.T": {"en": "Nippon Telegraph & Telephone", "jp": "日本電信電話"},
    "4502.T": {"en": "Takeda Pharmaceutical", "jp": "武田薬品工業"},
    "6857.T": {"en": "Advantest", "jp": "アドバンテスト"},
    # ---------- Japan — mid/large growth ----------
    "6146.T": {"en": "DISCO", "jp": "ディスコ"},
    "7735.T": {"en": "SCREEN Holdings", "jp": "SCREENホールディングス"},
    "7729.T": {"en": "Tokyo Seimitsu", "jp": "東京精密"},
    "6361.T": {"en": "Ebara", "jp": "荏原"},
    "6723.T": {"en": "Renesas Electronics", "jp": "ルネサス エレクトロニクス"},
    "6594.T": {"en": "Nidec", "jp": "ニデック"},
    "8473.T": {"en": "SBI Holdings", "jp": "SBIホールディングス"},
    "7013.T": {"en": "IHI Corporation", "jp": "IHI（石川島播磨重工業）"},
    "5803.T": {"en": "Fujikura", "jp": "フジクラ"},
    "6098.T": {"en": "Recruit Holdings", "jp": "リクルートホールディングス"},
    "4751.T": {"en": "CyberAgent", "jp": "サイバーエージェント"},
    # ---------- Japan — small-cap potential ----------
    "4385.T": {"en": "Mercari", "jp": "メルカリ"},
    "3994.T": {"en": "Money Forward", "jp": "マネーフォワード"},
    "4165.T": {"en": "Plaid", "jp": "プレイド"},
    # Sansan's registered Japanese name is Latin-script "Sansan株式会社".
    "4443.T": {"en": "Sansan"},
    "6526.T": {"en": "Socionext", "jp": "ソシオネクスト"},
    "4587.T": {"en": "PeptiDream", "jp": "ペプチドリーム"},
    "4390.T": {"en": "IPS", "jp": "アイ・ピー・エス"},
}


def get_display_name(symbol):
    """Return {name, name_jp} for a symbol, omitting keys that are unknown."""
    entry = SYMBOL_NAMES.get(symbol) or {}
    out = {}
    if entry.get("en"):
        out["name"] = entry["en"]
    if entry.get("jp"):
        out["name_jp"] = entry["jp"]
    return out