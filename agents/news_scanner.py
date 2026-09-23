from datetime import datetime, timezone
from agents.base_agent import BaseAgent


class NewsScannerAgent(BaseAgent):
    """Scans recent real news headlines for sentiment and key event keywords.

    Only ever scores real, fetched articles. If a fetch fails, this agent
    emits no signal at all rather than falling back to invented headlines -
    a fabricated headline that happens to read "bullish" would otherwise
    silently push a BUY/SELL recommendation on made-up evidence.
    """

    name = "news_scanner"
    description = "Scans news for sentiment and key events"

    def __init__(self, config=None):
        super().__init__(config)
        self.max_articles = config.get("max_articles", 6) if config else 6

    def analyze(self, symbol, data=None):
        articles = self._fetch_news(symbol)
        if not articles:
            return None

        sentiments = []
        keywords = []
        for article in articles[:self.max_articles]:
            text = (article.get("title", "") + " " + article.get("description", ""))
            sentiments.append(self._sentiment_score(text))
            text_lower = text.lower()
            for kw in ["earnings", "upgrade", "downgrade", "fda", "approval", "launch",
                       "partnership", "lawsuit", "recall", "guidance", "buyback", "merger"]:
                if kw in text_lower:
                    keywords.append(kw)

        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0

        if abs(avg_sentiment) < 0.1:
            return None

        direction = "positive" if avg_sentiment > 0 else "negative"
        confidence = min(abs(avg_sentiment) / 0.5, 1.0)

        return {
            "symbol": symbol,
            "agent": self.name,
            "signals": [{
                "type": "news_sentiment",
                "direction": direction,
                "avg_sentiment": round(avg_sentiment, 3),
                "confidence": round(confidence, 2),
                "keywords": list(set(keywords))[:5],
            }],
            "price": None,
            "articles_count": len(articles),
            "confidence": round(confidence, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert": confidence >= 0.6,
        }

    def _fetch_news(self, symbol):
        """Try Yahoo Finance's JSON search endpoint first (returns real,
        structured article data and is far more stable than scraping
        rendered HTML), then fall back to the old regex scrape. Both are
        real sources; neither path invents content."""
        articles = self._fetch_news_json(symbol)
        if articles:
            return articles
        return self._fetch_news_html(symbol)

    def _fetch_news_json(self, symbol):
        try:
            import requests
            url = "https://query1.finance.yahoo.com/v1/finance/search"
            headers = {"User-Agent": "Mozilla/5.0 (compatible; KaitoDetector/1.0)"}
            resp = requests.get(url, params={"q": symbol, "newsCount": self.max_articles},
                                 headers=headers, timeout=10)
            if resp.status_code != 200:
                return []
            payload = resp.json()
            news_items = payload.get("news", [])
            articles = []
            for item in news_items[:self.max_articles]:
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                articles.append({
                    "title": title[:250],
                    "description": (item.get("summary") or "")[:500],
                    "publisher": item.get("publisher"),
                    "link": item.get("link"),
                    "published_at": item.get("providerPublishTime"),
                })
            return articles
        except Exception:
            return []

    def _fetch_news_html(self, symbol):
        try:
            import requests
            import re
            url = f"https://finance.yahoo.com/quote/{symbol}/"
            headers = {"User-Agent": "Mozilla/5.0 (compatible; KaitoDetector/1.0)"}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return []
            titles = re.findall(r'data-test="post-info">(.*?)</a>', resp.text)
            return [{"title": t.strip()[:200], "description": ""} for t in titles[:self.max_articles]]
        except Exception:
            return []

    def _sentiment_score(self, text):
        positive_words = ["gain", "growth", "up", "rise", "surge", "beat", "strong", "positive",
                           "upgrade", "approval", "breakthrough", "success", "profit", "record",
                           "outperform", "buyback", "raises guidance", "bullish"]
        negative_words = ["loss", "drop", "fall", "down", "decline", "miss", "weak", "negative",
                           "downgrade", "delay", "investigation", "warning", "recall", "lawsuit",
                           "underperform", "cuts guidance", "bearish", "probe"]
        text_lower = text.lower()
        score = 0
        for word in positive_words:
            if word in text_lower:
                score += 1
        for word in negative_words:
            if word in text_lower:
                score -= 1
        return min(max(score / 5.0, -1.0), 1.0)
