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
    "7974.T": {"en": "Nintendo", "jp": "任天堂"},
    "9433.T": {"en": "KDDI", "jp": "KDDI"},
    "8058.T": {"en": "Mitsubishi Corporation", "jp": "三菱商事"},
    "8031.T": {"en": "Mitsui & Co.", "jp": "三井物産"},
    "6367.T": {"en": "Daikin Industries", "jp": "ダイキン工業"},
    "4063.T": {"en": "Shin-Etsu Chemical", "jp": "信越化学工業"},
    "6954.T": {"en": "Fanuc", "jp": "ファナック"},
    "7267.T": {"en": "Honda Motor", "jp": "本田技研工業"},
    "8001.T": {"en": "Itochu", "jp": "伊藤忠商事"},
    "8316.T": {"en": "Sumitomo Mitsui Financial Group", "jp": "三井住友フィナンシャルグループ"},
    "5401.T": {"en": "Nippon Steel", "jp": "日本製鉄"},
    "8411.T": {"en": "Mizuho Financial Group", "jp": "みずほフィナンシャルグループ"},
    "6752.T": {"en": "Panasonic Holdings", "jp": "パナソニック ホールディングス"},
    "7751.T": {"en": "Canon", "jp": "キヤノン"},
    "6503.T": {"en": "Mitsubishi Electric", "jp": "三菱電機"},
    "8766.T": {"en": "Tokio Marine Holdings", "jp": "東京海上ホールディングス"},
    "9020.T": {"en": "East Japan Railway", "jp": "東日本旅客鉄道"},
    "9022.T": {"en": "Central Japan Railway", "jp": "東海旅客鉄道"},
    # ---------- Japan — large-cap ----------
    "6902.T": {"en": "Denso", "jp": "デンソー"},
    "4568.T": {"en": "Daiichi Sankyo", "jp": "第一三共"},
    "4519.T": {"en": "Chugai Pharmaceutical", "jp": "中外製薬"},
    "8053.T": {"en": "Sumitomo Corporation", "jp": "住友商事"},
    "9201.T": {"en": "Japan Airlines", "jp": "日本航空"},
    "9202.T": {"en": "ANA Holdings", "jp": "ANAホールディングス"},
    "2502.T": {"en": "Asahi Group Holdings", "jp": "アサヒグループホールディングス"},
    "2503.T": {"en": "Kirin Holdings", "jp": "キリンホールディングス"},
    "2587.T": {"en": "Suntory Beverage & Food", "jp": "サントリー食品インターナショナル"},
    "4911.T": {"en": "Shiseido", "jp": "資生堂"},
    "4452.T": {"en": "Kao Corporation", "jp": "花王"},
    "3382.T": {"en": "Seven & I Holdings", "jp": "セブン&アイ・ホールディングス"},
    "8604.T": {"en": "Nomura Holdings", "jp": "野村ホールディングス"},
    "9434.T": {"en": "SoftBank Corp", "jp": "ソフトバンク"},
    "5108.T": {"en": "Bridgestone", "jp": "ブリヂストン"},
    "6971.T": {"en": "Kyocera", "jp": "京セラ"},
    "6762.T": {"en": "TDK", "jp": "TDK"},
    "7741.T": {"en": "Hoya", "jp": "HOYA"},
    "4543.T": {"en": "Terumo", "jp": "テルモ"},
    "7733.T": {"en": "Olympus", "jp": "オリンパス"},
    "4901.T": {"en": "Fujifilm Holdings", "jp": "富士フイルムホールディングス"},
    "6301.T": {"en": "Komatsu", "jp": "コマツ"},
    "5411.T": {"en": "JFE Holdings", "jp": "JFEホールディングス"},
    # ---------- Japan — mid-cap ----------
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
    "6920.T": {"en": "Lasertec", "jp": "レーザーテック"},
    "6963.T": {"en": "Rohm", "jp": "ローム"},
    "6988.T": {"en": "Nitto Denko", "jp": "日東電工"},
    "3402.T": {"en": "Toray Industries", "jp": "東レ"},
    "2802.T": {"en": "Ajinomoto", "jp": "味の素"},
    "4902.T": {"en": "Konica Minolta", "jp": "コニカミノルタ"},
    # ---------- Japan — small-cap ----------
    "4385.T": {"en": "Mercari", "jp": "メルカリ"},
    "3994.T": {"en": "Money Forward", "jp": "マネーフォワード"},
    "4165.T": {"en": "Plaid", "jp": "プレイド"},
    # Sansan's registered Japanese name is Latin-script "Sansan株式会社".
    "4443.T": {"en": "Sansan"},
    "6526.T": {"en": "Socionext", "jp": "ソシオネクスト"},
    "4587.T": {"en": "PeptiDream", "jp": "ペプチドリーム"},
    "4390.T": {"en": "IPS", "jp": "アイ・ピー・エス"},
    "4478.T": {"en": "freee", "jp": "フリー"},
    "9449.T": {"en": "GMO Internet Group", "jp": "GMOインターネットグループ"},
    "2432.T": {"en": "DeNA", "jp": "ディー・エヌ・エー"},
    "2121.T": {"en": "Mixi", "jp": "ミクシィ"},
    "3659.T": {"en": "Nexon", "jp": "ネクソン"},
    "6047.T": {"en": "Gunosy", "jp": "グノシー"},
    "3765.T": {"en": "GungHo Online Entertainment", "jp": "ガンホー・オンライン・エンターテイメント"},
    # ---------- Japan — micro / growth market ----------
    "5032.T": {"en": "ANYCOLOR", "jp": "エニーカラー"},
    "5253.T": {"en": "COVER Corporation", "jp": "カバー"},
    "9348.T": {"en": "ispace", "jp": "アイスペース"},
    "215A.T": {"en": "Timee", "jp": "タイミー"},
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