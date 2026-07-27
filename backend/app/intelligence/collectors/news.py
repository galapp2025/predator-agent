"""
News Collector — Media mentions, sentiment analysis, narrative tracking.

Sources:
  - NewsAPI (free tier: 100 req/day)
  - Google News RSS (free, no API key)
  - GDELT Project (free, global news index, no API key required for basic queries)

Sentiment: lexicon-based (VADER-style for English, custom for Hebrew/Arabic).
Narrative extraction: keyword frequency + entity co-occurrence.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

NEWS_API_BASE = "https://newsapi.org/v2"
GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


class SentimentAnalyzer:
    """
    Lightweight, multilingual sentiment analyzer.
    No external model dependency — lexicon-based + heuristics.
    """

    # English sentiment lexicon (subset - full version would be much larger)
    POSITIVE_EN = {
        "endorse", "support", "praise", "laud", "commend", "champion",
        "success", "win", "victory", "achievement", "leader", "trusted",
        "popular", "respected", "influential", "effective", "dedicated",
        "hero", "protect", "improve", "strengthen", "unite", "deliver",
    }
    NEGATIVE_EN = {
        "scandal", "corruption", "investigation", "accuse", "allege",
        "controversy", "criticize", "condemn", "fail", "failure",
        "protest", "oppose", "resign", "disgraced", "arrest", "charge",
        "fraud", "misconduct", "violation", "abuse", "criminal",
    }

    # Hebrew sentiment lexicon
    POSITIVE_HE = {
        "תומך", "מנהיג", "הצלחה", "ניצחון", "מוביל", "משפיע",
        "פופולרי", "מכובד", "מסור", "אפקטיבי", "מגן", "משפר",
        "מחזק", "מאחד", "מקדם", "זוכה", "מוערך", "אהוד", "חזק",
    }
    NEGATIVE_HE = {
        "שערורייה", "שחיתות", "חקירה", "האשמה", "ביקורת",
        "כישלון", "מחאה", "התנגדות", "התפטרות", "מעצר",
        "הונאה", "עבירה", "הפרה", "פלילי", "חשד", "תלונה",
    }

    # Arabic sentiment lexicon
    POSITIVE_AR = {
        "يدعم", "قائد", "نجاح", "انتصار", "مؤثر", "محترم",
        "شعبي", "مخلص", "فعال", "يدافع", "يحسن", "يقوي", "يوحد",
    }
    NEGATIVE_AR = {
        "فضيحة", "فساد", "تحقيق", "اتهام", "فشل", "احتجاج",
        "معارضة", "استقالة", "اعتقال", "احتيال", "انتهاك", "إجرامي",
    }

    @classmethod
    def analyze(cls, text: str, lang: str = "auto") -> dict:
        """
        Analyze sentiment of text.
        Returns: {positive: pct, negative: pct, neutral: pct, label: str, score: float}
        """
        if not text.strip():
            return {"positive": 0, "negative": 0, "neutral": 100, "label": "neutral", "score": 0.0}

        text_lower = text.lower()
        words = set(re.findall(r'\w+', text_lower))

        # Detect language (simple heuristic)
        if lang == "auto":
            he_count = sum(1 for w in words if any(0x05D0 <= ord(c) <= 0x05EA for c in w))
            ar_count = sum(1 for w in words if any(0x0600 <= ord(c) <= 0x06FF for c in w))
            if he_count > ar_count and he_count > len(words) * 0.1:
                lang = "he"
            elif ar_count > he_count and ar_count > len(words) * 0.1:
                lang = "ar"
            else:
                lang = "en"

        pos_set = cls.POSITIVE_EN
        neg_set = cls.NEGATIVE_EN
        if lang == "he":
            pos_set = cls.POSITIVE_HE
            neg_set = cls.NEGATIVE_HE
        elif lang == "ar":
            pos_set = cls.POSITIVE_AR
            neg_set = cls.NEGATIVE_AR

        pos_matches = sum(1 for w in words if w in pos_set)
        neg_matches = sum(1 for w in words if w in neg_set)
        total_matches = pos_matches + neg_matches

        if total_matches == 0:
            return {"positive": 0, "negative": 0, "neutral": 100, "label": "neutral", "score": 0.0}

        pos_pct = round(pos_matches / total_matches * 100, 1)
        neg_pct = round(neg_matches / total_matches * 100, 1)
        neutral_pct = round(100 - pos_pct - neg_pct, 1)

        score = round((pos_matches - neg_matches) / max(total_matches, 1) * 100, 1)

        label = "neutral"
        if score > 20:
            label = "positive"
        elif score < -20:
            label = "negative"

        return {
            "positive": pos_pct,
            "negative": neg_pct,
            "neutral": neutral_pct,
            "label": label,
            "score": score,
        }


class NewsCollector:
    """
    Collects news mentions and analyzes sentiment from multiple sources.
    Falls back gracefully when APIs are unavailable.
    """

    def __init__(self, newsapi_key: str | None = None, session=None):
        self.newsapi_key = newsapi_key
        self._session = session
        self._cache: dict[str, dict] = {}
        self._cache_ttl = timedelta(hours=6)

    async def _get_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "BlackOpps-OSINT/1.0"}
            )
        return self._session

    async def collect(self, name: str, days_back: int = 90, timeout: int = 15) -> dict:
        """Collect news data from all available sources."""
        cache_key = hashlib.md5(f"news:{name}:{days_back}".encode()).hexdigest()

        if cache_key in self._cache:
            return self._cache[cache_key]

        result = {
            "mention_count": 0,
            "headlines": [],
            "sources": [],
            "sentiment": {"positive": 0, "negative": 0, "neutral": 100, "label": "neutral", "score": 0.0},
            "negative_mentions": 0,
            "key_topics": [],
            "entity_co_occurrences": [],
            "_sources": [],
        }

        # Try GDELT first (no API key needed for basic queries)
        gdelt_data = await self._fetch_gdelt(name, days_back, timeout)
        if gdelt_data:
            result = self._merge_results(result, gdelt_data)

        # Try NewsAPI if key available
        if self.newsapi_key:
            newsapi_data = await self._fetch_newsapi(name, days_back, timeout)
            if newsapi_data:
                result = self._merge_results(result, newsapi_data)

        # Google News RSS as fallback (always works, no API key)
        rss_data = await self._fetch_google_news_rss(name, timeout)
        if rss_data:
            result = self._merge_results(result, rss_data)

        if result["_sources"]:
            self._cache[cache_key] = result

        return result

    async def _fetch_gdelt(self, name: str, days_back: int, timeout: int) -> dict | None:
        """Fetch from GDELT Project (no API key)."""
        try:
            session = await self._get_session()
            query = quote(f'"{name}"')
            params = {
                "query": query,
                "mode": "artlist",
                "maxrecords": 25,
                "format": "json",
            }
            async with session.get(GDELT_BASE, params=params, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return self._parse_gdelt(data)
        except Exception as e:
            logger.debug(f"GDELT unavailable for '{name}': {e}")
        return None

    def _parse_gdelt(self, data: dict) -> dict:
        """Parse GDELT response."""
        articles = data.get("articles", [])
        result = {
            "mention_count": len(articles),
            "headlines": [],
            "sources": [],
            "_sources": ["gdeltproject.org"],
        }

        all_text = ""
        for art in articles:
            title = art.get("title", "")
            if title:
                result["headlines"].append(title)
                all_text += " " + title
            source = art.get("domain", "")
            if source and source not in result["sources"]:
                result["sources"].append(source)

        if all_text:
            sentiment = SentimentAnalyzer.analyze(all_text)
            result["sentiment"] = sentiment
            result["negative_mentions"] = sum(
                1 for h in result["headlines"]
                if SentimentAnalyzer.analyze(h)["label"] == "negative"
            )

        return result

    async def _fetch_newsapi(self, name: str, days_back: int, timeout: int) -> dict | None:
        """Fetch from NewsAPI (requires API key)."""
        try:
            session = await self._get_session()
            from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            params = {
                "q": f'"{name}"',
                "from": from_date,
                "language": "en,he,ar",
                "sortBy": "relevancy",
                "pageSize": 25,
                "apiKey": self.newsapi_key,
            }
            async with session.get(
                f"{NEWS_API_BASE}/everything", params=params, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return self._parse_newsapi(data)
        except Exception as e:
            logger.debug(f"NewsAPI unavailable for '{name}': {e}")
        return None

    def _parse_newsapi(self, data: dict) -> dict:
        """Parse NewsAPI response."""
        articles = data.get("articles", [])
        result = {
            "mention_count": len(articles),
            "headlines": [],
            "sources": [],
            "_sources": ["newsapi.org"],
        }

        all_text = ""
        for art in articles:
            title = art.get("title", "")
            desc = art.get("description", "")
            if title:
                result["headlines"].append(title)
                all_text += " " + title
            if desc:
                all_text += " " + desc
            source = art.get("source", {}).get("name", "")
            if source and source not in result["sources"]:
                result["sources"].append(source)

        if all_text:
            sentiment = SentimentAnalyzer.analyze(all_text)
            result["sentiment"] = sentiment
            result["negative_mentions"] = sum(
                1 for h in result["headlines"]
                if SentimentAnalyzer.analyze(h)["label"] == "negative"
            )

        return result

    async def _fetch_google_news_rss(self, name: str, timeout: int) -> dict | None:
        """Fetch from Google News RSS (free, no key)."""
        try:
            session = await self._get_session()
            query = quote(f'"{name}"')
            url = f"https://news.google.com/rss/search?q={query}&hl=en"
            async with session.get(url, timeout=timeout) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return self._parse_rss(text)
        except Exception as e:
            logger.debug(f"Google News RSS unavailable for '{name}': {e}")
        return None

    def _parse_rss(self, xml_text: str) -> dict:
        """Parse Google News RSS XML."""
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return {}

        items = root.findall(".//item")
        result = {
            "mention_count": len(items),
            "headlines": [],
            "sources": [],
            "_sources": ["news.google.com"],
        }

        all_text = ""
        for item in items:
            title = item.findtext("title", "")
            if title:
                # Google News titles have " - SourceName" suffix
                clean_title = re.sub(r'\s*-\s*\S+\.\S+$', '', title)
                result["headlines"].append(clean_title)
                all_text += " " + clean_title
            source = item.findtext("source", "")
            if source and source not in result["sources"]:
                result["sources"].append(source)

        if all_text:
            sentiment = SentimentAnalyzer.analyze(all_text)
            result["sentiment"] = sentiment
            result["negative_mentions"] = sum(
                1 for h in result["headlines"]
                if SentimentAnalyzer.analyze(h)["label"] == "negative"
            )

        return result

    def _merge_results(self, base: dict, new: dict) -> dict:
        """Merge new results into base, deduplicating."""
        base["mention_count"] += new.get("mention_count", 0)
        existing_headlines = set(base["headlines"])
        for h in new.get("headlines", []):
            if h not in existing_headlines:
                base["headlines"].append(h)
                existing_headlines.add(h)
        for s in new.get("sources", []):
            if s not in base.get("sources", []):
                base["sources"].append(s)
        base["negative_mentions"] += new.get("negative_mentions", 0)
        if new.get("sentiment", {}).get("score", 0) != 0:
            # Weight by mention count, average sentiment
            old_s = base.get("sentiment", {}).get("score", 0)
            new_s = new.get("sentiment", {}).get("score", 0)
            old_n = base.get("mention_count", 1) - new.get("mention_count", 0)
            new_n = new.get("mention_count", 0)
            if old_n + new_n > 0:
                avg_score = (old_s * max(old_n, 0) + new_s * new_n) / (old_n + new_n)
                label = "neutral"
                if avg_score > 20:
                    label = "positive"
                elif avg_score < -20:
                    label = "negative"
                base["sentiment"] = {
                    "score": round(avg_score, 1),
                    "label": label,
                    "positive": 0, "negative": 0, "neutral": 100,
                }
        base["_sources"].extend(s for s in new.get("_sources", []) if s not in base["_sources"])
        return base

    def collect_sync(self, name: str, days_back: int = 90, timeout: int = 15) -> dict:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.collect(name, days_back, timeout))

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None
