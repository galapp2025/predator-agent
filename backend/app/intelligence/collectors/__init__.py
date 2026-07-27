"""
OSINT Collector Layer — External data sources for voter enrichment.

Collectors:
  opensanctions.py  — Sanctions, PEPs, political connections (OpenSanctions API)
  news.py           — News mentions & sentiment analysis (NewsAPI / Google News RSS)
  social.py         — Social media presence & influence (Twitter/X, Facebook, LinkedIn)
  public_records.py — Campaign contributions, voter history, property records
  web.py            — Generic web scraping & OSINT aggregation
"""

from .opensanctions import OpenSanctionsCollector
from .news import NewsCollector
from .social import SocialCollector
from .public_records import PublicRecordsCollector
from .web import WebScraper

__all__ = [
    "OpenSanctionsCollector",
    "NewsCollector",
    "SocialCollector",
    "PublicRecordsCollector",
    "WebScraper",
]
