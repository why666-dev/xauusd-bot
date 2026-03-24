"""
xauusd_bot.py — Main XAUUSD Trading Bot
Orchestrates all 3 strategies with risk management and Capital.com execution

1-MONTH HARDENING FIXES:
  1. State restored on startup — trade_history survives session restart
  2. Log rotation — log file won't grow to GB over 30 days
  3. trade_history capped at 500 records — prevents RAM growth
  4. Stale open trade detection — if bot restarts mid-trade, it reconciles
  5. Watchdog thread crash recovery — threads restart themselves if they die
  6. record_trade double-count fix — was adding daily_trades twice
  7. Weekly reset properly wired into watchdog
  8. Breakeven SL actually calls API (was only logging)
  9. EOD close handles API failure gracefully
"""

import os
import json
import time
import logging
import logging.handlers
import threading
from datetime import datetime, date
from dataclasses import dataclass, field, asdict
from typing import Optional
import pytz
from dotenv import load_dotenv

from capital_api  import CapitalAPI, EPIC
from risk_manager import RiskManager
from news_filter  import NewsFilter
from strategies   import AsianRangeBreakout, GoldmineStrategy, SilverBullet
from excel_logger import log_trade

load_dotenv()

# ── LOGGING — with rotation so log file never grows >50MB ────────────────────
_log_handler = logging.handlers.RotatingFileHandler(
    "xauusd_bot.log", maxBytes=10 * 1024 * 1024, backupCount=5
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_log_handler, logging.StreamHandler()]
)
log = logging.getLogger(__name__)

IST        = pytz.timezone("Asia/Kolkata")
STATE_FILE = "xauusd_state.json"
LOOP_SECS  = 60
MAX_HISTORY = 500   # cap trade_history per strategy to prevent RAM growth


# ── STATE ─────────────────────────────────────────────────────────────────────
@dataclass
class StrategyStats:
    name:          str
    trades:        int   = 0
    wins:          int   = 0
    losses:        int   = 0
    gross_pnl:     float = 0.0
    net_pnl:       float = 0.0
    commission:    float = 0.0
    max_win:       float = 0.0
    max_loss:      float = 0.0
    trade_history: list  = field(default_factory=list)

    @property
    def hit_ratio(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def gain_loss_ratio(self) -> float:
        if self.losses == 0:
            return 0.0
        avg_win  = sum(t["net_pnl"] for t in self.trade_history if t["net_pnl"] > 0) / max(self.wins, 1)
        avg_loss = abs(sum(t["net_pnl"] for t in self.trade_history if t["net_pnl"] < 0)) / max(self.losses, 1)
        return avg_win / avg_loss if avg_loss else 0.0

    def to_dict(self):
        d = asdict(self)
        d["hit_ratio"]       = round(self.hit_ratio * 100, 1)
        d["gain_loss_ratio"] = round(self.gain_loss_ratio, 2)
        return d


@dataclass
class OpenTrade:
    deal_id:   str
    strategy:  str
    direction: str
    entry:     float
    sl:        float
    tp1:       float
    tp2:       float
    size:      float
    open_time: str
    tp1_hit:   bool = False

    def to_dict(self):
        return asdict(self)


# ── MAIN BOT ──────────────────────────────────────────────────────────────────
class XAUUSDBot:
    def __init__(self):
        self.api     = CapitalAPI()
        self.risk    = RiskManager()
        self.news    = NewsFilter()
        self.lock    = threading.Lock()
        self.running = False

        self.s1 = AsianRangeBreakout()
        self.s2 = GoldmineStrategy()
        self.s3 = SilverBullet()

        self.stats = {
            "S1_Asian_Breakout": StrategyStats("S1_Asian_Breakout"),
            "S2_Goldmine":       StrategyStats("S2_Goldmine"),
            "S3_Silver_Bullet":  StrategyStats("S3_Silver_Bullet"),
        }

        self.open_trade:    Optional[OpenTrade] = None
        self.account_equity = 0.0

        # FIX 1: Restore state from disk — survives restarts
        self._load_state()

        # FIX 4: Reconcile open trade against live broker positions
        self._reconcile_open_trade()

        log.info("✅ XAUUSDBot initialized — 3 strategies loaded")
        log.info("   S1: Asian Range Breakout | S2: Goldmine | S3: Silver Bullet")

    # ── STATE PERSISTENCE ─────────────────────────────────────────────────────
    def _save_state(self):
        """Save full bot state to disk."""
        try:
            state = {
                "stats":      {k: v.to_dict() for k, v in self.stats.items()},
                "open_trade": self.open_trade.to_dict() if self.open_trade else None,
                "equity":     self.account_equity,
                "timestamp":  datetime.now(IST).isoformat(),
            }
            # Write to temp file first, then rename — prevents corruption
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, default=str, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            log.error(f"State save failed: {e}")

    def _load_state(self):
        """Restore state from disk on startup."""
        if not os.path.exists(STATE_FILE):
            log.info("No state file found — starting fresh")
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)

            # Restore strategy stats
            for key, s in state.get("stats", {}).items():
                if key in self.stats:
                    st = self.stats[key]
                    st.trades        = s.get("trades", 0)
                    st.wins          = s.get("wins", 0)
                    st.losses        = s.get("losses", 0)
                    st.gross_pnl     = s.get("gross_pnl", 0.0)
                    st.net_pnl       = s.get("net_pnl", 0.0)
                    st.commission    = s.get("commission", 0.0)
                    st.max_win       = s.get("max_win", 0.0)
                    st.max_loss      = s.get("max_loss", 0.0)
                    # FIX 3: cap history on load
                    st.trade_history = s.get("trade_history", [])[-MAX_HISTORY:]

            # Restore open trade
            ot = state.get("open_trade")
            if ot:
                self.open_trade = OpenTrade(**{k: ot[k] for k in OpenTrade.__dataclass_fields__})
                log.info(f"🔄 Restored open trade: {self.open_trade.strategy} "
                         f"{self.open_trade.direction} @ ${self.open_trade.entry}")

            self.account_equity = state.get("equity", 0.0)
            log.info(f"✅ State restored from {STATE_FILE} "
                     f"(timestamp: {state.get('timestamp', 'unknown')})")
        except Exception as e:
            log.error(f"State load failed: {e} — starting fresh")

    def _reconcile_open_trade(self):
        """
        FIX 4: After restart, check if our recorded open trade still exists
        on the broker. If not, record it as closed at last known price.
        """
        if not self.open_trade:
            return
        try:
            pos = self.api.get_open_position()
            if not pos:
                log.warning("⚠️ Reconcile: open trade in state but NOT on broker — recording as closed")
                price = self.api.get_price().get("mid", self.open_trade.entry)
                self._record_closed_trade(self.open_trade, price)
                self.open_trade = None
            else:
                log.info(f"✅ Reconcile: open trade confirmed on broker — deal still live")
        except Exception as e:
            log.error(f"Reconcile failed: {e} — keeping state as-is")

    # ── HELPERS ───────────────────────────────────────────────────────────────
    def _equity(self) -> float:
        try:
            bal = self.api.get_balance()
            if bal > 0:
                self.account_equity = bal
            return self.account_equity
        except Exception:
            return self.account_equity

    def get_state_json(self) -> str:
        try:
            equity  = self._equity()
            account = self.api.get_account()
            price   = self.api.get_price()

            total_trades = sum(s.trades  for s in self.stats.values())
            total_wins   = sum(s.wins    for s in self.stats.values())
            total_net    = sum(s.net_pnl for s in self.stats.values())
            overall_hr   = (total_wins / total_trades * 100) if total_trades else 0

            return json.dumps({
                "account": {
                    "equity":    equity,
                    "balance":   float(account.get("balance", {}).get("balance", 0)),
                    "pnl_today": float(account.get("balance", {}).get("pnl", 0)),
                    "available": float(account.get("balance", {}).get("available", 0)),
                },
                "price": price,
                "overall": {
                    "total_trades":  total_trades,
                    "total_wins":    total_wins,
                    "total_losses":  total_trades - total_wins,
                    "hit_ratio":     round(overall_hr, 1),
                    "net_pnl":       round(total_net, 2),
                    "daily_trades":  self.risk.daily_trades,
                    "daily_pnl":     round(self.risk.daily_pnl, 2),
                    "daily_halted":  self.risk.daily_halted,
                },
                "strategies":  {k: v.to_dict() for k, v in self.stats.items()},
                "open_trade":  self.open_trade.to_dict() if self.open_trade else None,
                "news_events": self.news.get_todays_events(),
                "timestamp":   datetime.now(IST).isoformat(),
            }, default=str)
        except Exception as e:
            log.error(f"get_state_json error: {e}")
            return json.dumps({"error": str(e)})

    # ── CANDLE UPDATE ─────────────────────────────────────────────────────────
    def _update_candles(self):
        try:
            c1h  = self.api.get_candles_1h(count=30)
            c15m = self.api.get_candles_15m(count=100)
            c5m  = self.api.get_candles_5m(count=50)
            c1m  = self.api.get_candles_1m(count=100)
            return c1h, c15m, c5m, c1m
        except Exception as e:
            log.error(f"Candle fetch failed: {e}")
            return [], [], [], []

    # ── TRADE EXECUTION ───────────────────────────────────────────────────────
    def _execute_signal(self, signal: dict, atr: float, equity: float):
        direction = signal["direction"]
        entry     = signal["entry"]
        strategy  = signal["strategy"]

        levels = self.risk.calc_levels(direction, entry, atr)
        size   = self.risk.calc_size(equity, atr)

        if size <= 0:
            log.warning(f"Size 0 — skipping {strategy} {direction}")
            return

        result = self.api.open_trade(
            direction    = direction,
            size         = size,
            stop_level   = levels["sl"],
            profit_level = levels["tp2"],
            strategy     = strategy
        )

        if not result:
            log.error(f"Trade execution failed for {strategy}")
            return

        deal_id = result.get("dealReference", result.get("dealId", "unknown"))

        self.open_trade = OpenTrade(
            deal_id   = deal_id,
            strategy  = strategy,
            direction = direction,
            entry     = entry,
            sl        = levels["sl"],
            tp1       = levels["tp1"],
            tp2       = levels["tp2"],
            size      = size,
            open_time = datetime.now(IST).isoformat(),
        )

        log.info(f"✅ TRADE OPENED | {strategy} {direction} {size}oz @ ${entry:.2f}"
                 f" | SL=${levels['sl']:.2f} TP1=${levels['tp1']:.2f} TP2=${levels['tp2']:.2f}")

        # FIX 6: don't increment daily_trades here — record_trade() does it
        self._save_state()

    # ── TRADE MONITOR ─────────────────────────────────────────────────────────
    def _monitor_trade(self, current_price: float):
        if not self.open_trade:
            return

        t   = self.open_trade
        pos = self.api.get_open_position()

        if not pos:
            self._record_closed_trade(t, current_price)
            self.open_trade = None
            return

        # FIX 8: actually call API to move SL to breakeven
        if not t.tp1_hit:
            tp1_hit = (t.direction == "BUY"  and current_price >= t.tp1) or \
                      (t.direction == "SELL" and current_price <= t.tp1)
            if tp1_hit:
                t.tp1_hit = True
                log.info(f"TP1 hit at ${current_price:.2f} — moving SL to breakeven ${t.entry:.2f}")
                result = self.api.update_stop(t.deal_id, t.entry)
                if result:
                    t.sl = t.entry
                    log.info(f"✅ Breakeven SL confirmed at ${t.entry:.2f}")
                else:
                    log.warning(f"⚠️ Breakeven SL API call failed — SL stays at ${t.sl:.2f}")
                self._save_state()

    def _record_closed_trade(self, t: OpenTrade, exit_price: float):
        now_ist    = datetime.now(IST)
        commission = t.size * 0.005

        if t.direction == "BUY":
            gross_pnl = (exit_price - t.entry) * t.size * 100
        else:
            gross_pnl = (t.entry - exit_price) * t.size * 100

        net_pnl = gross_pnl - commission
        result  = "WIN" if net_pnl > 0 else "LOSS"

        stop_dist = abs(t.entry - t.sl)
        pnl_dist  = abs(exit_price - t.entry)
        rr        = round(pnl_dist / stop_dist, 2) if stop_dist > 0 else 0

        trade_record = {
            "date":        now_ist.strftime("%Y-%m-%d"),
            "time_ist":    now_ist.strftime("%H:%M:%S"),
            "strategy":    t.strategy,
            "direction":   t.direction,
            "entry":       round(t.entry, 2),
            "sl":          round(t.sl, 2),
            "tp1":         round(t.tp1, 2),
            "tp2":         round(t.tp2, 2),
            "size":        t.size,
            "exit_price":  round(exit_price, 2),
            "exit_time":   now_ist.strftime("%H:%M:%S"),
            "gross_pnl":   round(gross_pnl, 2),
            "rr_achieved": rr,
            "commission":  round(commission, 2),
            "net_pnl":     round(net_pnl, 2),
            "result":      result,
            "reason":      "",
        }

        stats = self.stats[t.strategy]
        stats.trades     += 1
        stats.net_pnl    += net_pnl
        stats.gross_pnl  += gross_pnl
        stats.commission += commission
        if net_pnl > 0:
            stats.wins    += 1
            stats.max_win  = max(stats.max_win, net_pnl)
        else:
            stats.losses  += 1
            stats.max_loss = min(stats.max_loss, net_pnl)

        stats.trade_history.append(trade_record)
        # FIX 3: cap history size — prevents memory growth over 30 days
        if len(stats.trade_history) > MAX_HISTORY:
            stats.trade_history = stats.trade_history[-MAX_HISTORY:]

        # FIX 6: record_trade is the ONLY place daily_trades increments
        self.risk.record_trade(net_pnl, self.account_equity)

        log_trade(trade_record)

        log.info(f"📊 TRADE CLOSED | {t.strategy} {t.direction} "
                 f"| Exit=${exit_price:.2f} | PnL=${net_pnl:.2f} | {result}")
        self._save_state()

    # ── EOD CLOSE ─────────────────────────────────────────────────────────────
    def end_of_day(self):
        """FIX 9: EOD close handles API failure gracefully."""
        log.info("🏁 EOD: Closing all positions...")
        if self.open_trade:
            try:
                price = self.api.get_price().get("mid", self.open_trade.entry)
                if price == 0:
                    price = self.open_trade.entry   # fallback if price fetch fails
                self.api.close_all()
                self._record_closed_trade(self.open_trade, price)
            except Exception as e:
                log.error(f"EOD close error: {e} — recording at entry price as fallback")
                self._record_closed_trade(self.open_trade, self.open_trade.entry)
            finally:
                self.open_trade = None

        self.risk.reset_daily()
        self.s1.range_valid = False
        self.s2.reset()
        self.s3.reset_daily()
        log.info("✅ EOD complete")
        self._save_state()

    # ── MAIN LOOP ─────────────────────────────────────────────────────────────
    def run_once(self):
        with self.lock:
            equity = self._equity()

            c1h, c15m, c5m, c1m = self._update_candles()
            if not c1m:
                log.warning("No candle data — skipping iteration")
                return

            current_price = c1m[-1]["close"] if c1m else 0
            atr_15m       = self.risk.calc_atr(c15m)

            if self.open_trade:
                self._monitor_trade(current_price)
                return

            day_ok,  day_msg  = self.risk.is_tradeable_day()
            time_ok, time_msg = self.risk.is_tradeable_time()
            news_ok, news_msg = self.news.is_news_safe()
            lim_ok,  lim_msg  = self.risk.check_daily_limits(equity)

            price_data = self.api.get_price()
            spread     = price_data.get("spread", 0)
            spr_ok, spr_msg = self.risk.check_spread(spread)

            if not all([day_ok, time_ok, news_ok, lim_ok, spr_ok]):
                reasons = [m for ok, m in [(day_ok, day_msg), (time_ok, time_msg),
                                           (news_ok, news_msg), (lim_ok, lim_msg),
                                           (spr_ok, spr_msg)] if not ok]
                log.info(f"⏸ Skipping: {' | '.join(reasons)}")
                return

            self.s1.update_asian_range(c1h)
            if self.s1.range_valid:
                range_size = self.s1.asian_high - self.s1.asian_low
                range_ok, range_msg = self.risk.check_asian_range(range_size)
                if not range_ok:
                    log.info(f"⏸ {range_msg}")
                    return
                self.s2.update_from_range(self.s1.asian_high, self.s1.asian_low)

            htf_trend = None
            if c15m and len(c15m) > 5:
                recent_closes = [c["close"] for c in c15m[-5:]]
                htf_trend = "BUY" if recent_closes[-1] > recent_closes[0] else "SELL"

            sig = self.s3.get_signal(c1m, c5m, htf_trend)
            if not sig:
                sig = self.s2.get_signal(c15m)
            if not sig and self.s1.range_valid:
                sig = self.s1.get_signal(c15m)

            if sig:
                log.info(f"🎯 SIGNAL: {sig['strategy']} {sig['direction']} | {sig['reason']}")
                self._execute_signal(sig, atr_15m, equity)

    def run(self):
        self.running = True
        log.info("🚀 XAUUSD Bot started — monitoring 3 strategies")
        log.info("   Trading days: Tue/Wed/Thu | Session: 1:30 PM – 1:30 AM IST")

        # FIX 5: watchdog thread restarts itself if it ever dies
        def eod_watchdog():
            fired    = False
            wk_fired = False
            while self.running:
                try:
                    now_ist = datetime.now(IST)
                    h, m    = now_ist.hour, now_ist.minute
                    wday    = now_ist.weekday()  # 0=Monday

                    # FIX 7: weekly reset every Monday at midnight IST
                    if wday == 0 and h == 0 and m < 2 and not wk_fired:
                        self.risk.reset_weekly()
                        log.info("✅ Weekly risk counters reset (Monday midnight IST)")
                        wk_fired = True
                    if not (wday == 0 and h == 0 and m < 2):
                        wk_fired = False

                    # EOD close at 1:25 AM IST
                    if h == 1 and m >= 25 and not fired:
                        self.end_of_day()
                        fired = True
                    if not (h == 1 and m >= 25):
                        fired = False

                except Exception as e:
                    log.error(f"Watchdog error: {e}")
                time.sleep(1)
            log.warning("⚠️ EOD watchdog thread exiting")

        def start_watchdog():
            while self.running:
                t = threading.Thread(target=eod_watchdog, daemon=True, name="eod-watchdog")
                t.start()
                t.join()   # blocks until watchdog dies
                if self.running:
                    log.warning("🔄 EOD watchdog died — restarting in 5s")
                    time.sleep(5)

        threading.Thread(target=start_watchdog, daemon=True, name="watchdog-supervisor").start()
        log.info("EOD watchdog + supervisor started")

        while self.running:
            try:
                self.run_once()
                self._save_state()
            except Exception as e:
                log.error(f"Loop error: {e}", exc_info=True)
            time.sleep(LOOP_SECS)


if __name__ == "__main__":
    bot = XAUUSDBot()
    bot.run()
