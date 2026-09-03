"""
=============================================================
base.py — Abstract Strategy Interface
=============================================================
All trading strategies inherit from AbstractStrategy.
Each strategy receives live candles and emits signals.
=============================================================
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    NO_SIGNAL     = "NO_SIGNAL"
    LONG_ENTRY    = "LONG_ENTRY"
    SHORT_ENTRY   = "SHORT_ENTRY"
    LONG_EXIT     = "LONG_EXIT"
    SHORT_EXIT    = "SHORT_EXIT"
    REVERSE_LONG  = "REVERSE_LONG"   # Exit short, go long
    REVERSE_SHORT = "REVERSE_SHORT"  # Exit long, go short


@dataclass
class Signal:
    type:           SignalType
    instrument:     str
    strategy_name:  str
    price:          float           # Signal price / current price
    stop_loss:      Optional[float] = None
    target:         Optional[float] = None
    quantity:       int = 1
    reason:         str = ""         # Human-readable reason
    confidence:     float = 1.0     # 0.0 – 1.0
    metadata:       Dict[str, Any] = field(default_factory=dict)
    timestamp:      int = 0


@dataclass
class StrategyConfig:
    """Configuration for a strategy applied to an instrument."""
    name:           str
    instrument:     str
    enabled:        bool = True
    params:         Dict[str, Any] = field(default_factory=dict)


class AbstractStrategy(ABC):
    """
    Base class for all trading strategies.
    Implement on_tick() to receive each new candle and emit signals.
    """

    def __init__(self, name: str, instrument: str, params: Dict[str, Any]):
        self.name       = name
        self.instrument = instrument
        self.params     = params
        self._candles: List[Any] = []   # OHLC list
        self._position_open = False
        self._position_side: str = "FLAT"
        self._entry_price: float = 0.0
        self._logger = logging.getLogger(f"strategy.{name}")

    # ── Candle management ─────────────────────────────────────────────────────

    def add_candle(self, candle) -> None:
        """Add a new OHLC candle to the history."""
        self._candles.append(candle)
        # Keep last 500 candles max
        if len(self._candles) > 500:
            self._candles = self._candles[-500:]

    @property
    def candles(self) -> List[Any]:
        return self._candles

    @property
    def last_candle(self):
        return self._candles[-1] if self._candles else None

    @property
    def closed_candles(self) -> List[Any]:
        """Candles with confirmed close (for strategy logic)."""
        return self._candles

    # ── Position tracking ─────────────────────────────────────────────────────

    def set_position(self, side: str, entry_price: float):
        """Called by the engine when a position is taken."""
        self._position_open = True
        self._position_side = side
        self._entry_price   = entry_price

    def clear_position(self):
        """Called by the engine when position is closed."""
        self._position_open = False
        self._position_side = "FLAT"
        self._entry_price   = 0.0

    # ── Core strategy method ──────────────────────────────────────────────────

    def on_candle(self, candle) -> Optional[Signal]:
        """
        Called for each new candle. Return a Signal or None.
        Default implementation: add candle and call compute().
        """
        self.add_candle(candle)
        return self.compute()

    @abstractmethod
    def compute(self) -> Optional[Signal]:
        """
        Override this with your strategy logic.
        Return a Signal if a trade signal is generated, else None.
        """
        ...

    # ── Utility methods ───────────────────────────────────────────────────────

    def get_atr(self, period: int = 14) -> Optional[float]:
        """Compute ATR from closed candles."""
        if len(self._candles) < period + 1:
            return None
        trs = []
        for i in range(1, len(self._candles)):
            h = self._candles[i].high
            l = self._candles[i].low
            pc = self._candles[i - 1].close
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        if len(trs) < period:
            return None
        atr = sum(trs[:period]) / period
        for t in trs[period:]:
            atr = (atr * (period - 1) + t) / period
        return atr

    def get_atr_pct(self, period: int = 14) -> Optional[float]:
        """ATR as percentage of last close price."""
        atr  = self.get_atr(period)
        last = self.last_candle
        if atr and last:
            return atr / last.close * 100
        return None

    def get_swing_points(self, lookback: int = 3):
        """
        Find swing tops and bottoms from closed candles.
        Returns (tops, bottoms) — each is a list of (index, price).
        """
        data = self._candles
        if len(data) < lookback * 2 + 1:
            return [], []

        tops, bots = [], []
        for i in range(lookback, len(data) - lookback):
            c = data[i].close
            # Check if it's a top (higher than N candles on each side)
            is_top = all(data[i].close > data[i - j].close
                         for j in range(1, lookback + 1))
            is_top = is_top and all(data[i].close > data[i + j].close
                                    for j in range(1, lookback + 1))
            if is_top:
                tops.append((i, data[i].close, data[i].timestamp))
            # Check if it's a bottom
            is_bot = all(data[i].close < data[i - j].close
                         for j in range(1, lookback + 1))
            is_bot = is_bot and all(data[i].close < data[i + j].close
                                    for j in range(1, lookback + 1))
            if is_bot:
                bots.append((i, data[i].close, data[i].timestamp))
        return tops, bots

    def __repr__(self):
        return f"<Strategy {self.name} on {self.instrument}>"
