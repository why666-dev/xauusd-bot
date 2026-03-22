"""
capital_api.py — Capital.com REST API wrapper
Handles authentication, price data, and order execution for XAUUSD
"""

import os
import json
import time
import logging
import requests
from datetime import datetime
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
EPIC             = "GOLD"   # Capital.com epic for XAUUSD


class CapitalAPI:
    def __init__(self):
        self.session_token  = None
        self.account_id     = None
        self.cst            = None
        self.x_security     = None
        self.session_expiry = 0
        self._create_session()

    # ── SESSION ───────────────────────────────────────────────────────────────
    def _create_session(self):
        """Authenticate and create a new session."""
        try:
            resp = requests.post(
                f"{BASE_URL}/session",
                headers={"X-CAP-API-KEY": CAPITAL_API_KEY,
                         "Content-Type": "application/json"},
                json={"identifier": CAPITAL_EMAIL, "password": CAPITAL_PASSWORD},
                timeout=10
            )
            resp.raise_for_status()
            self.cst        = resp.headers.get("CST")
            self.x_security = resp.headers.get("X-SECURITY-TOKEN")
            data            = resp.json()
            self.account_id = data.get("accountType")
            self.session_expiry = time.time() + 3600
            log.info("✅ Capital.com session created")
        except Exception as e:
            log.error(f"❌ Session creation failed: {e}")
            raise

    def _ensure_session(self):
        """Refresh session if expired."""
        if time.time() > self.session_expiry - 60:
            self._create_session()

    def _headers(self):
        self._ensure_session()
        return {
            "X-CAP-API-KEY":    CAPITAL_API_KEY,
            "CST":              self.cst,
            "X-SECURITY-TOKEN": self.x_security,
            "Content-Type":     "application/json",
        }

    def _get(self, path: str, params=None):
        try:
            r = requests.get(f"{BASE_URL}{path}",
                             headers=self._headers(), params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"GET {path} failed: {e}")
            return None

    def _post(self, path: str, body: dict):
        try:
            r = requests.post(f"{BASE_URL}{path}",
                              headers=self._headers(), json=body, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"POST {path} failed: {e}")
            return None

    def _delete(self, path: str):
        try:
            r = requests.delete(f"{BASE_URL}{path}",
                                headers=self._headers(), timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"DELETE {path} failed: {e}")
            return None

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
        """Get current bid/ask price for XAUUSD."""
        data = self._get(f"/markets/{EPIC}")
        if not data:
            return {}
        snapshot = data.get("snapshot", {})
        return {
            "bid":    float(snapshot.get("bid", 0)),
            "ask":    float(snapshot.get("offer", 0)),
            "mid":    (float(snapshot.get("bid", 0)) + float(snapshot.get("offer", 0))) / 2,
            "spread": float(snapshot.get("offer", 0)) - float(snapshot.get("bid", 0)),
        }

    def get_candles(self, resolution: str = "MINUTE_15", count: int = 100) -> list:
        """
        Get historical candles.
        resolution: MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY
        """
        data = self._get(f"/prices/{EPIC}",
                         params={"resolution": resolution, "max": count})
        if not data or "prices" not in data:
            return []
        candles = []
        for p in data["prices"]:
            candles.append({
                "time":   p["snapshotTime"],
                "open":   (p["openPrice"]["bid"] + p["openPrice"]["ask"]) / 2,
                "high":   (p["highPrice"]["bid"] + p["highPrice"]["ask"]) / 2,
                "low":    (p["lowPrice"]["bid"]  + p["lowPrice"]["ask"])  / 2,
                "close":  (p["closePrice"]["bid"]+ p["closePrice"]["ask"])/ 2,
                "volume": p.get("lastTradedVolume", 0),
            })
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
        """Get open XAUUSD position if any."""
        for pos in self.get_positions():
            if pos.get("market", {}).get("epic") == EPIC:
                return pos
        return None

    # ── ORDERS ────────────────────────────────────────────────────────────────
    def open_trade(self, direction: str, size: float,
                   stop_level: float, profit_level: float,
                   strategy: str = "") -> Optional[dict]:
        """
        Open a trade.
        direction: "BUY" or "SELL"
        size: lot size in oz (e.g. 1.0 = 1oz)
        stop_level: stop loss price
        profit_level: take profit price
        """
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

    def close_trade(self, deal_id: str, direction: str, size: float) -> Optional[dict]:
        """Close an existing position."""
        close_dir = "SELL" if direction == "BUY" else "BUY"
        body = {
            "epic":      EPIC,
            "direction": close_dir,
            "size":      size,
        }
        result = self._delete(f"/positions/{deal_id}")
        if result:
            log.info(f"✅ TRADE CLOSED | deal_id={deal_id}")
        return result

    def close_all(self):
        """Close all open XAUUSD positions."""
        for pos in self.get_positions():
            if pos.get("market", {}).get("epic") == EPIC:
                deal_id = pos["position"]["dealId"]
                direction = pos["position"]["direction"]
                size = pos["position"]["size"]
                self.close_trade(deal_id, direction, size)

    # ── ACTIVITY LOG ─────────────────────────────────────────────────────────
    def get_activity(self, days: int = 7) -> list:
        """Get recent trade activity."""
        from datetime import timedelta
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        data = self._get("/history/activity",
                         params={"from": from_date, "detailed": True})
        return data.get("activities", []) if data else []

    def get_transactions(self, days: int = 7) -> list:
        from datetime import timedelta
        from_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        data = self._get("/history/transactions",
                         params={"from": from_date})
        return data.get("transactions", []) if data else []
