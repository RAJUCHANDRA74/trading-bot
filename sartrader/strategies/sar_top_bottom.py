"""
=============================================================
sar_top_bottom.py — SAR Top-Bottom Strategy
=============================================================
Rajkumar's core swing trading strategy.

Rules:
  Entry LONG  : Price closes above most recent swing TOP
  Entry SHORT  : Price closes below most recent swing BOTTOM
  Stop Loss   : X% below entry (default 3%)
  Breakeven   : Move SL to entry when profit >= BE% (default 2.5%)
  Reversal    : Exit and reverse when price crosses opposite swing point
  ATR Filter  : Only trade when ATR% < threshold (default 2.0%)

Parameters:
  stop_pct        — Stop loss percentage (default 3.0)
  be_pct          — Breakeven lock percentage (default 2.5)
  atr_threshold   — Max ATR% to allow entries (default 2.0)
  reversal_exit   — Enable reversal exits (default True)
  trend_filter    — Only long in bullish candles (default False)
  swing_lookback  — Number of candles for swing detection (default 3)
=============================================================
"""
import logging
from typing import List, Optional, Tuple

from sartrader.strategies.base import (
    AbstractStrategy, Signal, SignalType,
)
from sartrader.broker_interface import OHLC

logger = logging.getLogger(__name__)


class SARTopBottomStrategy(AbstractStrategy):
    """
    Implements the SAR Top-Bottom swing trading strategy.
    Works on any timeframe (1m, 5m, 15m, 1h, daily).
    """

    def __init__(self, instrument: str, params: dict):
        # Default params
        defaults = {
            "stop_pct":        3.0,
            "be_pct":          2.5,
            "atr_threshold":   2.0,     # Max ATR% to allow entry
            "reversal_exit":   True,
            "trend_filter":    False,
            "swing_lookback":  3,
            "max_swing_age":   20,      # Max candles old a swing can be
        }
        defaults.update(params)
        super().__init__(
            name="SAR_TopBottom",
            instrument=instrument,
            params=defaults,
        )

        self._stop_pct       = defaults["stop_pct"]
        self._be_pct         = defaults["be_pct"]
        self._atr_threshold  = defaults["atr_threshold"]
        self._reversal_exit  = defaults["reversal_exit"]
        self._trend_filter   = defaults["trend_filter"]
        self._swing_lookback = defaults["swing_lookback"]
        self._max_swing_age  = defaults["max_swing_age"]

        # Internal state
        self._entry_idx:    int = 0
        self._be_done:       bool = False
        self._entry_sl:      float = 0.0   # Current trailing stop
        self._recent_tops:   List[Tuple] = []   # (idx, price, timestamp)
        self._recent_bots:   List[Tuple] = []

        logger.info(
            f"[{instrument}] SAR-TopBottom initialized: "
            f"SL={self._stop_pct}%, BE={self._be_pct}%, "
            f"ATR<{self._atr_threshold}%, RevExit={self._reversal_exit}"
        )

    # ── Compute signals ──────────────────────────────────────────────────────

    def compute(self) -> Optional[Signal]:
        """Called on each new candle. Returns Signal or None."""
        candles = self.closed_candles
        if len(candles) < self._swing_lookback * 2 + 2:
            return None

        i      = len(candles) - 1      # Current (most recent) candle index
        candle = candles[i]
        close  = candle.close
        high   = candle.high
        low    = candle.low
        ts     = candle.timestamp

        # ── Update swing points ─────────────────────────────────────────────
        self._update_swing(candles, i, ts)

        if len(self._recent_tops) == 0 or len(self._recent_bots) == 0:
            return None

        # Most recent swing points
        last_top = self._recent_tops[-1]
        last_bot = self._recent_bots[-1]

        # ── ATR Filter ───────────────────────────────────────────────────────
        atr_pct = self.get_atr_pct(14)
        if atr_pct is not None and atr_pct >= self._atr_threshold:
            # Market too volatile — skip entry, but still manage position
            if not self._position_open:
                return None
            return self._manage_position(close, high, low, i, last_top, last_bot)

        # ── No position → look for entry ────────────────────────────────────
        if not self._position_open:
            sig = self._find_entry(close, i, last_top, last_bot, candles)
            if sig is None:
                atr = self.get_atr_pct(14)
                if atr:
                    logger.info(
                        f"[{self.instrument}] No signal | close={close:.2f} "
                        f"| top={top_price:.2f} bot={bot_price:.2f} "
                        f"| ATR%={atr:.2f}% (threshold={self._atr_threshold}%)"
                    )
            return sig

        # ── Have position → manage it ───────────────────────────────────────
        return self._manage_position(close, high, low, i, last_top, last_bot)

    def _update_swing(self, candles: List[OHLC], current_idx: int, ts: int):
        """Detect and maintain swing tops/bottoms."""
        lb = self._swing_lookback

        # Only check the newest candle for a swing point
        if current_idx < lb:
            return
        if current_idx > lb:
            # Only check candle at current_idx - lb
            check_idx = current_idx - lb
        else:
            check_idx = current_idx

        c  = candles[check_idx].close
        hi = check_idx
        lo = check_idx

        # Find local top in lookback window
        for j in range(check_idx - lb + 1, min(check_idx + lb, len(candles))):
            if candles[j].close > candles[hi].close:
                hi = j
            if candles[j].close < candles[lo].close:
                lo = j

        # If current candle is a local top — record at CLOSE (line chart)
        if hi == check_idx:
            price = candles[check_idx].close
            if not self._recent_tops or self._recent_tops[-1][1] != price:
                self._recent_tops.append((check_idx, price, ts))
                logger.info(f"[{self.instrument}] Swing TOP recorded: {price}")

        # If current candle is a local bottom — record at CLOSE (line chart)
        if lo == check_idx:
            price = candles[check_idx].close
            if not self._recent_bots or self._recent_bots[-1][1] != price:
                self._recent_bots.append((check_idx, price, ts))
                logger.info(f"[{self.instrument}] Swing BOTTOM recorded: {price}")

        # Prune old swing points (older than max_swing_age)
        cutoff_idx = current_idx - self._max_swing_age
        self._recent_tops = [(i, p, t) for i, p, t in self._recent_tops if i > cutoff_idx]
        self._recent_bots = [(i, p, t) for i, p, t in self._recent_bots if i > cutoff_idx]

    def _find_entry(self, close: float, i: int,
                    last_top, last_bot,
                    candles) -> Optional[Signal]:
        """Check if entry signal is generated."""
        trend_ok_long  = True
        trend_ok_short = True

        if self._trend_filter and i >= 1:
            prev = candles[i - 1]
            trend_ok_long  = prev.close > prev.open   # Bullish candle
            trend_ok_short = prev.close < prev.open    # Bearish candle

        top_idx,  top_price  = last_top
        bot_idx,  bot_price  = last_bot

        # LONG: price closes above recent swing top
        if close > top_price and i > top_idx and trend_ok_long:
            return Signal(
                type=SignalType.LONG_ENTRY,
                instrument=self.instrument,
                strategy_name=self.name,
                price=close,
                stop_loss=round(close * (1 - self._stop_pct / 100), 2),
                reason=f"Breakout above swing top {top_price:.2f}",
                metadata={"swing_top": top_price, "swing_idx": top_idx},
            )

        # SHORT: price closes below recent swing bottom
        if close < bot_price and i > bot_idx and trend_ok_short:
            return Signal(
                type=SignalType.SHORT_ENTRY,
                instrument=self.instrument,
                strategy_name=self.name,
                price=close,
                stop_loss=round(close * (1 + self._stop_pct / 100), 2),
                reason=f"Breakdown below swing bottom {bot_price:.2f}",
                metadata={"swing_bottom": bot_price, "swing_idx": bot_idx},
            )

        return None

    def _manage_position(self, close: float, high: float, low: float,
                         i: int, last_top, last_bot) -> Optional[Signal]:
        """Check for exit, reversal, breakeven, or trailing stop."""
        direction = self._position_side

        # ── Stop loss hit ───────────────────────────────────────────────────
        if direction == "LONG" and low <= self._entry_sl:
            return Signal(
                type=SignalType.LONG_EXIT,
                instrument=self.instrument,
                strategy_name=self.name,
                price=self._entry_sl,
                reason=f"Stop loss hit at {self._entry_sl:.2f}",
                metadata={"exit_reason": "stop_hit"},
            )
        if direction == "SHORT" and high >= self._entry_sl:
            return Signal(
                type=SignalType.SHORT_EXIT,
                instrument=self.instrument,
                strategy_name=self.name,
                price=self._entry_sl,
                reason=f"Stop loss hit at {self._entry_sl:.2f}",
                metadata={"exit_reason": "stop_hit"},
            )

        # ── Post-entry swing points after our entry ─────────────────────────
        top_list = [(idx, p) for idx, p, _ in self._recent_tops if idx > self._entry_idx]
        bot_list = [(idx, p) for idx, p, _ in self._recent_bots if idx > self._entry_idx]

        prev_top = max((p for _, p in top_list), default=self._entry_price)
        prev_bot = min((p for _, p in bot_list), default=self._entry_price)

        pct = ((close - self._entry_price) / self._entry_price * 100
               if direction == "LONG"
               else (self._entry_price - close) / self._entry_price * 100)

        # ── Breakeven lock ─────────────────────────────────────────────────
        if not self._be_done and pct >= self._be_pct:
            self._be_done = True
            self._entry_sl = self._entry_price
            logger.info(
                f"[{self.instrument}] Breakeven locked at "
                f"{self._entry_price:.2f} | Profit: {pct:.2f}%"
            )

        # ── Trailing stop ───────────────────────────────────────────────────
        if not self._be_done:
            if direction == "LONG":
                trail = min(prev_bot, self._entry_price * (1 - self._stop_pct / 100))
                self._entry_sl = max(self._entry_sl, trail)
            else:
                trail = max(prev_top, self._entry_price * (1 + self._stop_pct / 100))
                self._entry_sl = min(self._entry_sl, trail)
        else:
            # Breakeven done — tighter trailing
            if direction == "LONG":
                trail = min(prev_bot, self._entry_price * (1 - self._stop_pct * 1.5 / 100))
                self._entry_sl = max(self._entry_sl, trail)
            else:
                trail = max(prev_top, self._entry_price * (1 + self._stop_pct * 1.5 / 100))
                self._entry_sl = min(self._entry_sl, trail)

        # ── Reversal exit ───────────────────────────────────────────────────
        if self._reversal_exit:
            if direction == "LONG" and bot_list:
                _, last_bp = bot_list[-1]
                if close < last_bp:
                    return Signal(
                        type=SignalType.REVERSE_SHORT,
                        instrument=self.instrument,
                        strategy_name=self.name,
                        price=close,
                        stop_loss=round(close * (1 + self._stop_pct / 100), 2),
                        reason=f"Reversal: price fell below bottom {last_bp:.2f}",
                        metadata={"exit_reason": "signal_reversal",
                                  "swing_bottom": last_bp},
                    )
            if direction == "SHORT" and top_list:
                _, last_tp = top_list[-1]
                if close > last_tp:
                    return Signal(
                        type=SignalType.REVERSE_LONG,
                        instrument=self.instrument,
                        strategy_name=self.name,
                        price=close,
                        stop_loss=round(close * (1 - self._stop_pct / 100), 2),
                        reason=f"Reversal: price rose above top {last_tp:.2f}",
                        metadata={"exit_reason": "signal_reversal",
                                  "swing_top": last_tp},
                    )

        return None

    # ── Position callbacks ────────────────────────────────────────────────────

    def on_entry(self, side: str, price: float, idx: int):
        """Called by engine when position is entered."""
        self._position_open = True
        self._position_side = side
        self._entry_price   = price
        self._entry_idx     = idx
        self._be_done       = False
        self._entry_sl      = price * (1 - self._stop_pct / 100 if side == "LONG"
                                         else 1 + self._stop_pct / 100)
        logger.info(
            f"[{self.instrument}] Position opened: {side} @ {price:.2f}, "
            f"SL: {self._entry_sl:.2f}"
        )

    def on_exit(self, reason: str):
        """Called by engine when position is closed."""
        logger.info(f"[{self.instrument}] Position closed: {reason}")
        self._position_open = False
        self._position_side = "FLAT"
        self._be_done = False
