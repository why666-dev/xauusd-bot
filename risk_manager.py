"""
risk_manager.py — Strict risk management for XAUUSD bot
Rules based on research: 1% per trade, 3% daily max, ATR stops
"""

import logging
import numpy as np
from datetime import datetime, date
from typing import Optional
import pytz

log = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# ── RISK CONSTANTS ─────────────────────────────────────────────────────────
RISK_PER_TRADE      = 0.01    # 1% of account per trade
DAILY_MAX_LOSS      = 0.03    # 3% daily stop
WEEKLY_MAX_LOSS     = 0.05    # 5% weekly stop
MAX_TRADES_PER_DAY  = 2       # max 2 trades total per day
ATR_PERIOD          = 14      # ATR period
ATR_STOP_MULT       = 1.5     # SL = 1.5 × ATR
TP1_RR              = 1.5     # TP1 at 1.5R
TP2_RR              = 2.0     # TP2 at 2.0R
BREAKEVEN_RR        = 1.0     # Move SL to BE at 1R
MIN_ASIAN_RANGE     = 10.0     # Skip if range < $5
MAX_ASIAN_RANGE     = 200.0    # Skip if range > $25
MAX_SPREAD          = 2.0    # Skip if spread > $0.50


class RiskManager:
    def __init__(self):
        self.reset_daily()
        self.reset_weekly()
        self.start_equity   = 0.0
        self.weekly_equity  = 0.0

    def reset_daily(self):
        self.daily_trades   = 0
        self.daily_pnl      = 0.0
        self.daily_date     = date.today()
        self.daily_halted   = False
        log.info("✅ Daily risk counters reset")

    def reset_weekly(self):
        self.weekly_pnl     = 0.0
        self.weekly_halted  = False
        log.info("✅ Weekly risk counters reset")

    def check_date(self):
        today = date.today()
        if today != self.daily_date:
            self.reset_daily()

    # ── FILTERS ───────────────────────────────────────────────────────────────
    def is_tradeable_day(self) -> tuple[bool, str]:
        """Only trade Tue/Wed/Thu — best days per research."""
        self.check_date()
        now_ist    = datetime.now(IST)
        weekday    = now_ist.weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
        day_name   = now_ist.strftime("%A")

        if weekday not in (1, 2, 3):
            return False, f"Skip {day_name} — best days are Tue/Wed/Thu"
        return True, f"✅ {day_name} — tradeable day"

    def is_tradeable_time(self) -> tuple[bool, str]:
        """Check trading session — avoid dead zones."""
        now_ist  = datetime.now(IST)
        now_et   = datetime.now(pytz.timezone("America/New_York"))
        h_ist    = now_ist.hour
        m_ist    = now_ist.minute
        mins_ist = h_ist * 60 + m_ist
        h_et     = now_et.hour
        m_et     = now_et.minute
        mins_et  = h_et * 60 + m_et

        # London open starts 1:30 PM IST
        london_open_ist  = 13 * 60 + 30
        # NY close 1:30 AM IST
        ny_close_ist     = 1 * 60 + 30
        # Dead zone: 3:30 AM – 1:30 PM IST
        dead_start_ist   = 3 * 60 + 30
        dead_end_ist     = 13 * 60 + 30
        # Friday cutoff: no new trades after 11:30 PM IST (7:30 PM ET)
        friday_cutoff_et = 19 * 60 + 30

        weekday = datetime.now(IST).weekday()

        # Friday cutoff
        if weekday == 4 and mins_et >= friday_cutoff_et:
            return False, "Friday cutoff — no new trades after 7:30 PM ET"

        # Dead zone check (3:30 AM – 1:30 PM IST)
        if dead_start_ist <= mins_ist < dead_end_ist:
            return False, f"Dead zone ({h_ist:02d}:{m_ist:02d} IST) — low liquidity"

        # Valid window: 1:30 PM – 1:30 AM IST
        if mins_ist >= london_open_ist or mins_ist < ny_close_ist:
            return True, f"✅ Active session ({h_ist:02d}:{m_ist:02d} IST)"

        return False, f"Outside trading window ({h_ist:02d}:{m_ist:02d} IST)"

    def check_spread(self, spread: float) -> tuple[bool, str]:
        if spread > MAX_SPREAD:
            return False, f"Spread ${spread:.3f} > max ${MAX_SPREAD}"
        return True, f"✅ Spread ${spread:.3f} OK"

    def check_asian_range(self, range_size: float) -> tuple[bool, str]:
        if range_size < MIN_ASIAN_RANGE:
            return False, f"Asian range ${range_size:.2f} too narrow (min ${MIN_ASIAN_RANGE})"
        if range_size > MAX_ASIAN_RANGE:
            return False, f"Asian range ${range_size:.2f} too wide (max ${MAX_ASIAN_RANGE})"
        return True, f"✅ Asian range ${range_size:.2f} valid"

    def check_daily_limits(self, equity: float) -> tuple[bool, str]:
        self.check_date()
        if self.start_equity == 0:
            self.start_equity = equity

        if self.daily_halted:
            return False, f"Daily loss limit hit — halted for today"

        if self.daily_trades >= MAX_TRADES_PER_DAY:
            return False, f"Max {MAX_TRADES_PER_DAY} trades reached for today"

        daily_loss_pct = self.daily_pnl / self.start_equity if self.start_equity else 0
        if daily_loss_pct <= -DAILY_MAX_LOSS:
            self.daily_halted = True
            return False, f"Daily loss {daily_loss_pct*100:.1f}% — trading halted"

        weekly_loss_pct = self.weekly_pnl / self.weekly_equity if self.weekly_equity else 0
        if weekly_loss_pct <= -WEEKLY_MAX_LOSS:
            self.weekly_halted = True
            return False, f"Weekly loss {weekly_loss_pct*100:.1f}% — trading halted for week"

        return True, f"✅ Daily: {self.daily_trades}/{MAX_TRADES_PER_DAY} trades | PnL: ${self.daily_pnl:.2f}"

    # ── ATR ───────────────────────────────────────────────────────────────────
    def calc_atr(self, candles: list, period: int = ATR_PERIOD) -> float:
        """Calculate ATR from candle list."""
        if len(candles) < period + 1:
            return 3.0  # default fallback

        trs = []
        for i in range(1, len(candles)):
            h  = candles[i]["high"]
            l  = candles[i]["low"]
            pc = candles[i-1]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)

        if len(trs) < period:
            return float(np.mean(trs)) if trs else 3.0

        return float(np.mean(trs[-period:]))

    # ── POSITION SIZING ───────────────────────────────────────────────────────
    def calc_size(self, equity: float, atr: float) -> float:
        """
        Size = (equity × risk%) / (ATR × ATR_mult)
        Returns lot size in oz, minimum 0.01
        """
        if atr <= 0 or equity <= 0:
            return 0.01

        risk_amount  = equity * RISK_PER_TRADE
        stop_dist    = atr * ATR_STOP_MULT
        size         = risk_amount / stop_dist

        # Round to 2 decimal places, min 0.01, max 10
        size = round(max(0.01, min(size, 10.0)), 2)
        log.info(f"  Position size: equity=${equity:.0f} "
                 f"risk=${risk_amount:.0f} ATR={atr:.2f} → {size}oz")
        return size

    # ── STOP LOSS & TAKE PROFIT ───────────────────────────────────────────────
    def calc_levels(self, direction: str, entry: float,
                    atr: float) -> dict:
        """Calculate SL, TP1, TP2 based on ATR."""
        stop_dist = atr * ATR_STOP_MULT
        tp1_dist  = stop_dist * TP1_RR
        tp2_dist  = stop_dist * TP2_RR
        be_dist   = stop_dist * BREAKEVEN_RR

        if direction == "BUY":
            sl  = round(entry - stop_dist, 2)
            tp1 = round(entry + tp1_dist,  2)
            tp2 = round(entry + tp2_dist,  2)
            be  = round(entry + be_dist,   2)
        else:
            sl  = round(entry + stop_dist, 2)
            tp1 = round(entry - tp1_dist,  2)
            tp2 = round(entry - tp2_dist,  2)
            be  = round(entry - be_dist,   2)

        return {
            "sl": sl, "tp1": tp1, "tp2": tp2,
            "be": be, "stop_dist": stop_dist,
            "rr_tp1": TP1_RR, "rr_tp2": TP2_RR
        }

    # ── TRADE RECORDING ───────────────────────────────────────────────────────
    def record_trade(self, pnl: float, equity: float):
        self.check_date()
        self.daily_trades  += 1
        self.daily_pnl     += pnl
        self.weekly_pnl    += pnl
        if self.weekly_equity == 0:
            self.weekly_equity = equity
        log.info(f"Trade recorded | PnL=${pnl:.2f} | "
                 f"Daily={self.daily_trades} | Daily PnL=${self.daily_pnl:.2f}")
