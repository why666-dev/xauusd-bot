"""
news_filter.py — Economic calendar filter
Blocks trading 30 minutes before/after high-impact news events
Fetches calendar from Twelve Data API
"""

import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional
import pytz
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)
ET  = pytz.timezone("America/New_York")

TWELVE_DATA_KEY  = os.getenv("TWELVE_DATA_API_KEY", "")
NEWS_BUFFER_MINS = 30   # block 30 min before and after

# High impact events to block
HIGH_IMPACT_KEYWORDS = [
    "nonfarm", "nfp", "non-farm", "payroll",
    "cpi", "inflation", "consumer price",
    "fomc", "federal reserve", "fed rate", "interest rate decision",
    "gdp", "pce", "pmi",
    "ism manufacturing", "ism services",
    "jobless claims", "unemployment",
    "retail sales",
    "powell", "fed chair",
]


class NewsFilter:
    def __init__(self):
        self._cache      = []
        self._cache_time = None

    def _fetch_calendar(self) -> list:
        """Fetch economic calendar from Twelve Data."""
        try:
            today = datetime.now(ET).strftime("%Y-%m-%d")
            url   = "https://api.twelvedata.com/economic_calendar"
            resp  = requests.get(url, params={
                "apikey":     TWELVE_DATA_KEY,
                "start_date": today,
                "end_date":   today,
                "importance": "high",
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {}).get("list", [])
        except Exception as e:
            log.warning(f"News calendar fetch failed: {e} — trading allowed")
            return []

    def _get_events(self) -> list:
        """Get cached or fresh events."""
        now = datetime.now()
        if (self._cache_time is None or
                (now - self._cache_time).seconds > 3600):
            self._cache      = self._fetch_calendar()
            self._cache_time = now
        return self._cache

    def is_news_safe(self) -> tuple[bool, str]:
        """
        Returns (True, msg) if safe to trade.
        Returns (False, msg) if near high-impact news.
        """
        now_et  = datetime.now(ET)
        events  = self._get_events()

        for event in events:
            # Parse event time
            try:
                event_time_str = event.get("date", "") + " " + event.get("time", "")
                event_time     = ET.localize(
                    datetime.strptime(event_time_str, "%Y-%m-%d %H:%M")
                )
            except Exception:
                continue

            # Check if it's a high impact gold-affecting event
            title = event.get("event", "").lower()
            is_high_impact = any(kw in title for kw in HIGH_IMPACT_KEYWORDS)
            if not is_high_impact:
                continue

            # Check if within buffer window
            diff_mins = abs((now_et - event_time).total_seconds() / 60)
            if diff_mins <= NEWS_BUFFER_MINS:
                if now_et < event_time:
                    wait = int((event_time - now_et).total_seconds() / 60)
                    return False, (f"⛔ High impact news in {wait} min: "
                                   f"'{event.get('event')}' — waiting")
                else:
                    elapsed = int((now_et - event_time).total_seconds() / 60)
                    remain  = NEWS_BUFFER_MINS - elapsed
                    return False, (f"⛔ Post-news buffer: {remain} min remaining "
                                   f"after '{event.get('event')}'")

        return True, "✅ No high-impact news — safe to trade"

    def get_todays_events(self) -> list:
        """Return list of today's high impact events for display."""
        events = self._get_events()
        result = []
        for ev in events:
            title = ev.get("event", "").lower()
            if any(kw in title for kw in HIGH_IMPACT_KEYWORDS):
                result.append({
                    "time":  ev.get("time", ""),
                    "event": ev.get("event", ""),
                    "impact": "HIGH"
                })
        return result
