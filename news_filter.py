"""
news_filter.py — Economic calendar filter
Blocks trading 30 minutes before/after high-impact news events

1-MONTH HARDENING FIX:
  - Cache was using .seconds which resets every hour — after 24h it would
    never refresh the calendar (always returning stale yesterday's events)
  - Fixed to use total_seconds() and compare dates properly
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
NEWS_BUFFER_MINS = 30

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
        self._cache_date = None   # FIX: track which DATE we cached

    def _fetch_calendar(self) -> list:
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
        now      = datetime.now(ET)
        today    = now.date()

        # FIX: refresh if date changed OR if more than 1 hour since last fetch
        needs_refresh = (
            self._cache_time is None or
            self._cache_date != today or
            (now - self._cache_time).total_seconds() > 3600
        )

        if needs_refresh:
            self._cache      = self._fetch_calendar()
            self._cache_time = now
            self._cache_date = today
            log.info(f"📰 News calendar refreshed — {len(self._cache)} events today")

        return self._cache

    def is_news_safe(self) -> tuple[bool, str]:
        now_et = datetime.now(ET)
        events = self._get_events()

        for event in events:
            try:
                event_time_str = event.get("date", "") + " " + event.get("time", "")
                event_time     = ET.localize(
                    datetime.strptime(event_time_str, "%Y-%m-%d %H:%M")
                )
            except Exception:
                continue

            title = event.get("event", "").lower()
            if not any(kw in title for kw in HIGH_IMPACT_KEYWORDS):
                continue

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
        events = self._get_events()
        result = []
        for ev in events:
            title = ev.get("event", "").lower()
            if any(kw in title for kw in HIGH_IMPACT_KEYWORDS):
                result.append({
                    "time":   ev.get("time", ""),
                    "event":  ev.get("event", ""),
                    "impact": "HIGH"
                })
        return result
