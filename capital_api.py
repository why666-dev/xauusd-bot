"""
capital_api.py — Capital.com REST API wrapper
Handles authentication, price data, and order execution for XAUUSD

1-MONTH HARDENING FIXES:
  - Retry logic with exponential backoff on every API call
  - Session auto-refresh with retry on failure (not just silent skip)
  - Rate limit detection — backs off on 429 responses
  - Connection error recovery — keeps retrying, never crashes
"""

import os
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────
CAPITAL_API_KEY  = os.getenv("CAPITAL_API_KEY",  "")
CAPITAL_EMAIL    = os.getenv("CAPITAL_EMAIL",    "")
CAPITAL_PASSWORD = os.getenv("CAPITAL_PASSWORD", "")
BASE_URL         = "https://demo-api-capital.backend-capital.com/api/v1"
SYMBOL           = "XAUUSD"
EPIC             = "GOLD"

MAX_RETRIES      = 4
RETRY_BACKOFF    = [2, 5, 15, 30]  # seconds between retries


class CapitalAPI:
    def __init__(self):
        self.session_token     = None
        self.account_id        = None
        self.cst               = None
        self.x_security        = None
        self.session_expiry    = 0
        self._rate_limit_until = 0
        self._create_session_with_retry()

    # ── SESSION ───────────────────────────────────────────────────────────────
    def _create_session(self):
        resp = requests.post(
            f"{BASE_URL}/session",
            headers={"X-CAP-API-KEY": CAPITAL_API_KEY,
                     "Content-Type": "application/json"},
            json={"identifier": CAPITAL_EMAIL, "password": CAPITAL_PASSWORD},
            timeout=15
        )
        resp.raise_for_status()
        self.cst            = resp.headers.get("CST")
        self.x_security     = resp.headers.get("X-SECURITY-TOKEN")
        data                = resp.json()
        self.account_id     = data.get("accountType")
        # FIX: refresh every 5.5 hours — Capital.com hard cap is 6 hours
        self.session_expiry = time.time() + (5.5 * 3600)
        log.info("✅ Capital.com session created")

    def _create_session_with_retry(self):
        """Create session with retry — never raises, keeps trying."""
        for attempt, wait in enumerate(RETRY_BACKOFF, 1):
            try:
                self._create_session()
                return
            except Exception as e:
                log.error(f"❌ Session creation failed (attempt {attempt}): {e}")
                if attempt < len(RETRY_BACKOFF):
                    log.info(f"   Retrying in {wait}s...")
                    time.sleep(wait)
        log.error("❌ All session retries failed — will retry on next loop")

    def _ensure_session(self):
        if time.time() > self.session_expiry - 60:
            log.info("🔄 Session expiring — refreshing...")
            self._create_session_with_retry()

    def _check_rate_limit(self):
        now = time.time()
        if now < self._rate_limit_until:
            wait = int(self._rate_limit_until - now)
            log.warning(f"⏳ Rate limited — waiting {wait}s")
            time.sleep(wait + 1)

    def _headers(self):
        self._ensure_session()
        return {
            "X-CAP-API-KEY":    CAPITAL_API_KEY,
            "CST":              self.cst or "",
            "X-SECURITY-TOKEN": self.x_security or "",
            "Content-Type":     "application/json",
        }

    # ── CORE HTTP — retry + backoff ───────────────────────────────────────────
    def _request(self, method: str, path: str, body: dict = None, params: dict = None):
        url = f"{BASE_URL}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                self._check_rate_limit()
                headers = self._headers()
                if   method == "GET":    r = requests.get(url,    headers=headers, params=params, timeout=15)
                elif method == "POST":   r = requests.post(url,   headers=headers, json=body,     timeout=15)
                elif method == "PUT":    r = requests.put(url,    headers=headers, json=body,     timeout=15)
                elif method == "DELETE": r = requests.delete(url, headers=headers,                timeout=15)
                else: return None

                if r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", 60))
                    self._rate_limit_until = time.time() + retry_after
                    log.warning(f"⏳ 429 Rate limit — backing off {retry_after}s")
                    time.sleep(retry_after + 1)
                    continue

                if r.status_code in (401, 403):
                    log.warning(f"🔄 Auth error {r.status_code} — refreshing session")
                    self._create_session_with_retry()
                    continue

                r.raise_for_status()
                return r.json()

            except requests.exceptions.ConnectionError as e:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                log.warning(f"🌐 Connection error {method} {path} (attempt {attempt+1}): {e} — retry in {wait}s")
                time.sleep(wait)

            except requests.exceptions.Timeout:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                log.warning(f"⏱ Timeout {method} {path} (attempt {attempt+1}) — retry in {wait}s")
                time.sleep(wait)

            except Exception as e:
                log.error(f"❌ {method} {path} failed (attempt {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])

        log.error(f"❌ {method} {path} failed after {MAX_RETRIES} attempts — skipping")
        return None

    def _get(self, path, params=None):       return self._request("GET",    path, params=params)
    def _post(self, path, body):             return self._request("POST",   path, body=body)
    def _put(self, path, body):              return self._request("PUT",    path, body=body)
    def _delete(self, path):                 return self._request("DELETE", path)

    # ── ACCOUNT ───────────────────────────────────────────────────────────────
    def get_account(self) -> dict:
        data = self._get("/accounts")
        if data and "accounts" in data:
            for acct in data["accounts"]:
                if acct.get("preferred"):
                    return acct
        return {}

    def get_balance(self) -> float:
        acct = self.get_account()
        return float(acct.get("balance", {}).get("available", 0))

    # ── MARKET DATA ───────────────────────────────────────────────────────────
    def get_price(self) -> dict:
        data = self._get(f"/markets/{EPIC}")
        if not data:
            return {"bid": 0, "ask": 0, "mid": 0, "spread": 0}
        snapshot = data.get("snapshot", {})
        bid = float(snapshot.get("bid", 0))
        ask = float(snapshot.get("offer", 0))
        return {
            "bid":    bid,
            "ask":    ask,
            "mid":    (bid + ask) / 2 if bid and ask else 0,
            "spread": ask - bid,
        }

    def get_candles(self, resolution: str = "MINUTE_15", count: int = 100) -> list:
        data = self._get(f"/prices/{EPIC}", params={"resolution": resolution, "max": count})
        if not data or "prices" not in data:
            return []
        candles = []
        for p in data["prices"]:
            try:
                candles.append({
                    "time":   p["snapshotTime"],
                    "open":   (p["openPrice"]["bid"]  + p["openPrice"]["ask"])  / 2,
                    "high":   (p["highPrice"]["bid"]  + p["highPrice"]["ask"])  / 2,
                    "low":    (p["lowPrice"]["bid"]   + p["lowPrice"]["ask"])   / 2,
                    "close":  (p["closePrice"]["bid"] + p["closePrice"]["ask"]) / 2,
                    "volume": p.get("lastTradedVolume", 0),
                })
            except (KeyError, TypeError):
                continue
        return candles

    def get_candles_1m(self,  count=200): return self.get_candles("MINUTE",    count)
    def get_candles_5m(self,  count=200): return self.get_candles("MINUTE_5",  count)
    def get_candles_15m(self, count=100): return self.get_candles("MINUTE_15", count)
    def get_candles_1h(self,  count=50):  return self.get_candles("HOUR",      count)

    # ── POSITIONS ─────────────────────────────────────────────────────────────
    def get_positions(self) -> list:
        data = self._get("/positions")
        return data.get("positions", []) if data else []

    def get_open_position(self) -> Optional[dict]:
        for pos in self.get_positions():
            if pos.get("market", {}).get("epic") == EPIC:
                return pos
        return None

    # ── ORDERS ────────────────────────────────────────────────────────────────
    def open_trade(self, direction: str, size: float,
                   stop_level: float, profit_level: float,
                   strategy: str = "") -> Optional[dict]:
        body = {
            "epic":           EPIC,
            "direction":      direction,
            "size":           size,
            "guaranteedStop": False,
            "stopLevel":      round(stop_level, 2),
            "profitLevel":    round(profit_level, 2),
        }
        result = self._post("/positions", body)
        if result:
            log.info(f"✅ TRADE OPENED | {direction} {size}oz XAUUSD "
                     f"| SL={stop_level:.2f} TP={profit_level:.2f} | {strategy}")
        return result

    def update_stop(self, deal_id: str, new_stop: float) -> Optional[dict]:
        body   = {"stopLevel": round(new_stop, 2)}
        result = self._put(f"/positions/{deal_id}", body)
        if result:
            log.info(f"✅ SL updated | deal_id={deal_id} → new SL={new_stop:.2f}")
        return result

    def close_trade(self, deal_id: str, direction: str, size: float) -> Optional[dict]:
        result = self._delete(f"/positions/{deal_id}")
        if result:
            log.info(f"✅ TRADE CLOSED | deal_id={deal_id}")
        return result

    def close_all(self):
        for pos in self.get_positions():
            if pos.get("market", {}).get("epic") == EPIC:
                deal_id   = pos["position"]["dealId"]
                direction = pos["position"]["direction"]
                size      = pos["position"]["size"]
                self.close_trade(deal_id, direction, size)

    # ── ACTIVITY LOG ─────────────────────────────────────────────────────────
    def get_activity(self, days: int = 7) -> list:
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        data = self._get("/history/activity", params={"from": from_date, "detailed": True})
        return data.get("activities", []) if data else []

    def get_transactions(self, days: int = 7) -> list:
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        data = self._get("/history/transactions", params={"from": from_date})
        return data.get("transactions", []) if data else []
