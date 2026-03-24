"""
strategies.py — Three XAUUSD trading strategies
1. Asian Range + 15-min Breakout
2. Goldmine (Asian + London retest)
3. Silver Bullet (FVG entry)
"""

import logging
import numpy as np
from datetime import datetime, time
from typing import Optional
import pytz

log = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")
ET  = pytz.timezone("America/New_York")


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 1 — ASIAN RANGE + 15-MIN BREAKOUT
# Entry: 15-min candle closes outside Asian session HIGH/LOW
# Timeframes: 1H (range) + 15M (breakout signal)
# Best window: London open 1:30 PM IST → NY close 1:30 AM IST
# ─────────────────────────────────────────────────────────────────────────────
class AsianRangeBreakout:
    NAME = "S1_Asian_Breakout"

    def __init__(self):
        self.asian_high  = None
        self.asian_low   = None
        self.range_valid = False
        self.last_signal = None

    def update_asian_range(self, candles_1h: list):
        """
        Build Asian range from 1H candles between 23:00–08:00 GMT
        (4:30 AM – 1:30 PM IST)
        """
        asian_highs = []
        asian_lows  = []

        for c in candles_1h:
            try:
                # Parse candle time
                t = datetime.fromisoformat(str(c["time"]).replace("Z", "+00:00"))
                t_utc_h = t.hour

                # Asian session: 23:00–08:00 UTC
                if t_utc_h >= 23 or t_utc_h < 8:
                    asian_highs.append(c["high"])
                    asian_lows.append(c["low"])
            except Exception:
                continue

        if len(asian_highs) >= 3:  # need at least 3 candles
            self.asian_high  = max(asian_highs)
            self.asian_low   = min(asian_lows)
            range_size       = self.asian_high - self.asian_low
            self.range_valid = True
            log.info(f"S1: Asian range built | "
                     f"High={self.asian_high:.2f} Low={self.asian_low:.2f} "
                     f"Range=${range_size:.2f}")
        else:
            self.range_valid = False
            log.warning("S1: Not enough Asian candles for range")

    def get_signal(self, candles_15m: list) -> Optional[dict]:
        """
        Check if latest 15M candle closes outside Asian range.
        Returns signal dict or None.
        """
        if not self.range_valid or not candles_15m:
            return None

        # Check if we're in London/NY session (1:30 PM – 1:30 AM IST)
        now_ist  = datetime.now(IST)
        h, m     = now_ist.hour, now_ist.minute
        mins_ist = h * 60 + m

        london_open = 13 * 60 + 30   # 1:30 PM IST
        ny_close    = 1  * 60 + 30   # 1:30 AM IST

        in_session = mins_ist >= london_open or mins_ist < ny_close
        if not in_session:
            return None

        latest = candles_15m[-1]
        prev   = candles_15m[-2] if len(candles_15m) > 1 else None
        close  = latest["close"]

        # LONG: candle closes above Asian high
        if close > self.asian_high:
            # Check it's not already moved >50% of ADR
            if prev and prev["close"] <= self.asian_high:  # fresh breakout
                return {
                    "strategy":    self.NAME,
                    "direction":   "BUY",
                    "entry":       close,
                    "breakout_level": self.asian_high,
                    "asian_high":  self.asian_high,
                    "asian_low":   self.asian_low,
                    "reason":      f"15M closed above Asian High ${self.asian_high:.2f}",
                }

        # SHORT: candle closes below Asian low
        elif close < self.asian_low:
            if prev and prev["close"] >= self.asian_low:  # fresh breakout
                return {
                    "strategy":    self.NAME,
                    "direction":   "SELL",
                    "entry":       close,
                    "breakout_level": self.asian_low,
                    "asian_high":  self.asian_high,
                    "asian_low":   self.asian_low,
                    "reason":      f"15M closed below Asian Low ${self.asian_low:.2f}",
                }

        return None


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 2 — GOLDMINE (ASIAN + LONDON RETEST)
# Entry: London breaks Asian range → price retests broken level → enter
# Timeframes: 15M
# Extra filter: Fibonacci 61.8% retest zone
# ─────────────────────────────────────────────────────────────────────────────
class GoldmineStrategy:
    NAME = "S2_Goldmine"

    def __init__(self):
        self.asian_high   = None
        self.asian_low    = None
        self.breakout_dir = None   # "BUY" or "SELL"
        self.broken_level = None
        self.waiting_retest = False

    def update_from_range(self, asian_high: float, asian_low: float):
        """Sync Asian range from Strategy 1."""
        self.asian_high = asian_high
        self.asian_low  = asian_low

    def get_signal(self, candles_15m: list) -> Optional[dict]:
        """
        Phase 1: Detect breakout of Asian range
        Phase 2: Wait for price to retest broken level
        Phase 3: Entry candle closes FROM the retest level
        """
        if not self.asian_high or not candles_15m or len(candles_15m) < 3:
            return None

        # Only trade London open window: 1:30 PM – 6:30 PM IST
        now_ist  = datetime.now(IST)
        h, m     = now_ist.hour, now_ist.minute
        mins_ist = h * 60 + m

        london_start = 13 * 60 + 30   # 1:30 PM IST
        london_end   = 18 * 60 + 30   # 6:30 PM IST
        ny_end       = 22 * 60 + 30   # 10:30 PM IST

        # Goldmine works best London open + NY overlap
        in_window = london_start <= mins_ist <= ny_end
        if not in_window:
            return None

        latest = candles_15m[-1]
        prev   = candles_15m[-2]
        close  = latest["close"]
        low    = latest["low"]
        high   = latest["high"]

        # Phase 1: Detect initial breakout
        if not self.waiting_retest:
            if prev["close"] <= self.asian_high and close > self.asian_high:
                self.breakout_dir   = "BUY"
                self.broken_level   = self.asian_high
                self.waiting_retest = True
                log.info(f"S2: Breakout LONG detected above ${self.asian_high:.2f} — waiting retest")
                return None

            elif prev["close"] >= self.asian_low and close < self.asian_low:
                self.breakout_dir   = "SELL"
                self.broken_level   = self.asian_low
                self.waiting_retest = True
                log.info(f"S2: Breakout SHORT detected below ${self.asian_low:.2f} — waiting retest")
                return None

        # Phase 2 + 3: Wait for retest and entry
        if self.waiting_retest and self.broken_level:
            fib_zone = self._fib_zone()

            if self.breakout_dir == "BUY":
                # Price retests broken level (Asian High) from above
                if low <= self.broken_level * 1.001:  # touched level
                    if close > self.broken_level:      # closed back above
                        self.waiting_retest = False
                        return {
                            "strategy":      self.NAME,
                            "direction":     "BUY",
                            "entry":         close,
                            "retest_level":  self.broken_level,
                            "fib_zone":      fib_zone,
                            "reason":        f"Goldmine: retest of ${self.broken_level:.2f} confirmed",
                        }

            elif self.breakout_dir == "SELL":
                # Price retests broken level (Asian Low) from below
                if high >= self.broken_level * 0.999:
                    if close < self.broken_level:
                        self.waiting_retest = False
                        return {
                            "strategy":      self.NAME,
                            "direction":     "SELL",
                            "entry":         close,
                            "retest_level":  self.broken_level,
                            "fib_zone":      fib_zone,
                            "reason":        f"Goldmine: retest of ${self.broken_level:.2f} confirmed",
                        }

        return None

    def _fib_zone(self) -> dict:
        """Calculate Fibonacci 61.8% zone."""
        if not self.asian_high or not self.asian_low:
            return {}
        diff = self.asian_high - self.asian_low
        return {
            "fib_382": round(self.asian_high - diff * 0.382, 2),
            "fib_500": round(self.asian_high - diff * 0.500, 2),
            "fib_618": round(self.asian_high - diff * 0.618, 2),
        }

    def reset(self):
        self.breakout_dir   = None
        self.broken_level   = None
        self.waiting_retest = False


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 3 — SILVER BULLET (ICT FVG ENTRY)
# Entry: Liquidity sweep → Market Structure Shift → FVG retest
# Timeframes: 1M (entry) + 5M (trend)
# Windows: London 1:30-2:30 PM IST | NY AM 8:30-9:30 PM IST | NY PM 12:30-1:30 AM IST
# ─────────────────────────────────────────────────────────────────────────────
class SilverBullet:
    NAME = "S3_Silver_Bullet"

    # Three Silver Bullet windows (IST)
    WINDOWS = [
        (13 * 60 + 30, 14 * 60 + 30, "London"),     # 1:30–2:30 PM IST
        (20 * 60 + 30, 21 * 60 + 30, "NY_AM"),      # 8:30–9:30 PM IST ← BEST
        (0  * 60 + 30, 1  * 60 + 30, "NY_PM"),      # 12:30–1:30 AM IST
    ]

    def __init__(self):
        self.fvgs          = []   # list of detected Fair Value Gaps
        self.msb_direction = None # Market Structure Shift direction
        self.swept_level   = None

    def _in_silver_bullet_window(self) -> tuple[bool, str]:
        """Check if we're in any Silver Bullet window."""
        now_ist  = datetime.now(IST)
        h, m     = now_ist.hour, now_ist.minute
        mins_ist = h * 60 + m

        for start, end, name in self.WINDOWS:
            if start <= mins_ist <= end:
                return True, name
        return False, ""

    def detect_fvg(self, candles_1m: list) -> list:
        """
        Fair Value Gap detection on 1M chart.
        FVG exists when: candle[i-1] high < candle[i+1] low (bullish)
                      or candle[i-1] low > candle[i+1] high (bearish)
        """
        fvgs = []
        if len(candles_1m) < 3:
            return fvgs

        for i in range(1, len(candles_1m) - 1):
            c1 = candles_1m[i - 1]
            c2 = candles_1m[i]
            c3 = candles_1m[i + 1]

            # Bullish FVG: gap between c1 high and c3 low
            if c1["high"] < c3["low"]:
                fvgs.append({
                    "type":    "bullish",
                    "high":    c3["low"],
                    "low":     c1["high"],
                    "mid":     (c3["low"] + c1["high"]) / 2,
                    "time":    c2["time"],
                    "filled":  False,
                })

            # Bearish FVG: gap between c1 low and c3 high
            elif c1["low"] > c3["high"]:
                fvgs.append({
                    "type":    "bearish",
                    "high":    c1["low"],
                    "low":     c3["high"],
                    "mid":     (c1["low"] + c3["high"]) / 2,
                    "time":    c2["time"],
                    "filled":  False,
                })

        return fvgs[-5:] if len(fvgs) > 5 else fvgs  # keep last 5

    def detect_msb(self, candles_5m: list) -> Optional[str]:
        """
        Market Structure Shift detection on 5M.
        MSB = break of previous swing high/low after liquidity sweep.
        """
        if len(candles_5m) < 10:
            return None

        recent = candles_5m[-10:]

        # Find swing high and low in recent candles
        swing_high = max(c["high"]  for c in recent[:-2])
        swing_low  = min(c["low"]   for c in recent[:-2])
        latest     = recent[-1]

        # Bullish MSB: price was below swing low (sweep) then closes above it
        if (any(c["low"] < swing_low for c in recent[-3:-1]) and
                latest["close"] > swing_low):
            return "BUY"

        # Bearish MSB: price was above swing high (sweep) then closes below it
        if (any(c["high"] > swing_high for c in recent[-3:-1]) and
                latest["close"] < swing_high):
            return "SELL"

        return None

    def get_signal(self, candles_1m: list, candles_5m: list,
                   higher_tf_trend: Optional[str] = None) -> Optional[dict]:
        """
        Silver Bullet signal generation.
        Only trades within the 3 windows and aligns with higher TF trend.
        """
        in_window, window_name = self._in_silver_bullet_window()
        if not in_window:
            return None

        if len(candles_1m) < 10 or len(candles_5m) < 10:
            return None

        # Detect Market Structure Shift
        msb = self.detect_msb(candles_5m)
        if not msb:
            return None

        # If higher TF trend provided, must align
        if higher_tf_trend and msb != higher_tf_trend:
            log.debug(f"S3: MSB {msb} conflicts with HTF trend {higher_tf_trend} — skipped")
            return None

        # Detect FVGs
        fvgs = self.detect_fvg(candles_1m)
        if not fvgs:
            return None

        latest_price = candles_1m[-1]["close"]

        # Find relevant unmitigated FVG to enter on
        for fvg in reversed(fvgs):
            if fvg["filled"]:
                continue

            if msb == "BUY" and fvg["type"] == "bullish":
                # Price entering bullish FVG from above
                if fvg["low"] <= latest_price <= fvg["high"]:
                    return {
                        "strategy":     self.NAME,
                        "direction":    "BUY",
                        "entry":        latest_price,
                        "fvg_high":     fvg["high"],
                        "fvg_low":      fvg["low"],
                        "msb":          msb,
                        "window":       window_name,
                        "reason":       f"Silver Bullet: Bullish FVG retest in {window_name} window",
                    }

            elif msb == "SELL" and fvg["type"] == "bearish":
                # Price entering bearish FVG from below
                if fvg["low"] <= latest_price <= fvg["high"]:
                    return {
                        "strategy":     self.NAME,
                        "direction":    "SELL",
                        "entry":        latest_price,
                        "fvg_high":     fvg["high"],
                        "fvg_low":      fvg["low"],
                        "msb":          msb,
                        "window":       window_name,
                        "reason":       f"Silver Bullet: Bearish FVG retest in {window_name} window",
                    }

        return None

    def reset_daily(self):
        self.fvgs          = []
        self.msb_direction = None
        self.swept_level   = None
