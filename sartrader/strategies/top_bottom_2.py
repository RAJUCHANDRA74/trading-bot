"""
=============================================================
top_bottom_2.py — Top Bottom-2 Strategy (Placeholder)
=============================================================
Rules to be defined by Rajkumar.
Currently fires NO_SIGNAL — implement rules to activate.

This strategy is reserved for the second Top-Bottom variant.
When Rajkumar defines the rules, uncomment/complete the logic below.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from .base import Signal, SignalType, StrategyConfig


class TopBottom2Strategy:
    """
    Top Bottom-2 Strategy.

    ⚠️ Rules not yet defined — edit this file to implement your strategy.
    """

    def __init__(self, instrument: str, params: Dict[str, Any]):
        self.instrument = instrument
        self.params = params
        self.strategy_name = "Top Bottom-2"
        self._swing_tops: List[tuple] = []
        self._swing_bottoms: List[tuple] = []
        self._position_open = False
        self._position_side = None
        self._entry_price = 0.0

    def compute(self) -> Optional[Signal]:
        """
        Compute signal based on strategy rules.
        Uses self._candles (managed by engine via add_candle).
        Currently returns NO_SIGNAL — implement your rules here.
        """
        candles = getattr(self, '_candles', [])
        if not candles or len(candles) < 5:
            return None

        latest = candles[-1]
        close = getattr(latest, 'close', 0) or (latest.get("close") if isinstance(latest, dict) else 0)
        high  = getattr(latest, 'high',  0) or (latest.get("high")  if isinstance(latest, dict) else 0)
        low   = getattr(latest, 'low',   0) or (latest.get("low")   if isinstance(latest, dict) else 0)

        # ── PLACEHOLDER: Implement your rules here ──────────────────────
        # Example structure:
        #
        # if <your_bullish_condition>:
        #     return Signal(
        #         type=SignalType.LONG_ENTRY,
        #         instrument=self.instrument,
        #         strategy_name=self.strategy_name,
        #         price=close,
        #         stop_loss=<your_sl_price>,
        #         quantity=self.params.get("lot_size", 1),
        #         reason="Top Bottom-2 LONG signal",
        #     )
        #
        # elif <your_bearish_condition>:
        #     return Signal(
        #         type=SignalType.SHORT_ENTRY,
        #         instrument=self.instrument,
        #         strategy_name=self.strategy_name,
        #         price=close,
        #         stop_loss=<your_sl_price>,
        #         quantity=self.params.get("lot_size", 1),
        #         reason="Top Bottom-2 SHORT signal",
        #     )
        # ───────────────────────────────────────────────────────────────

        return Signal(
            type=SignalType.NO_SIGNAL,
            instrument=self.instrument,
            strategy_name=self.strategy_name,
            price=close,
        )

    @property
    def is_long(self) -> bool:
        return self._position_side == "LONG"

    @property
    def is_short(self) -> bool:
        return self._position_side == "SHORT"

    def set_position(self, side: str, entry_price: float):
        self._position_open = True
        self._position_side = side
        self._entry_price = entry_price

    def clear_position(self):
        self._position_open = False
        self._position_side = None
        self._entry_price = 0.0

    def add_candle(self, candle):
        """Add candle to history (matches AbstractStrategy interface)."""
        if not hasattr(self, '_candles'):
            self._candles = []
        self._candles.append(candle)
        if len(self._candles) > 500:
            self._candles = self._candles[-500:]
