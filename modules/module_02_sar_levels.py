"""
================================================================================
MODULE 2: S-A-R LEVEL MANAGER
================================================================================
Purpose : Manage and update S-A-R (Stop and Reverse) levels on a daily basis.
         Connect to broker API to fetch live prices and auto-update levels
         at end of day.

Key Functions:
    - Maintain current position (LONG / SHORT / FLAT)
    - Track S-A-R levels from Module 1
    - Update levels end-of-day
    - Generate intraday alerts when price crosses S-A-R levels
    - Manage trade state and P&L tracking

S-A-R Logic:
    - BUY  when price crosses ABOVE Previous Top
    - SELL when price crosses BELOW Previous Bottom
    - Always in market (Stop and Reverse) — no flat positions
================================================================================
"""

import sys
import json
import os
from datetime import datetime, date, time as dtime, timedelta
import pandas as pd
import numpy as np

# Safe print that handles encoding on all platforms
_orig_print = print
def _safe_print(*args, **kwargs):
    try:
        _orig_print(*args, **kwargs)
    except (UnicodeEncodeError, IOError):
        clean_args = [str(a).encode('ascii', 'replace').decode('ascii') if isinstance(a, str) else a for a in args]
        _orig_print(*clean_args, **kwargs)

print = _safe_print


# Import Module 1
from module_01_tops_bottoms import (
    load_daily_close_data,
    identify_tops_bottoms,
    label_tops_bottoms,
    get_sar_levels,
    update_sar_levels_end_of_day,
    print_sar_report
)


# ------------------------------------------------------------------
# TRADE STATE CLASS
# ------------------------------------------------------------------
class TradeState:
    """
    Tracks the current state of the trading system:
        - Current position (LONG / SHORT / FLAT)
        - Entry price and date
        - Current stop loss level
        - Day count (for Day 1 vs Day 2+ rules)
        - Open positions count (for pyramid tracking)
        - Running P&L
    """

    LONG  = "LONG"
    SHORT = "SHORT"
    FLAT  = "FLAT"

    def __init__(self, instrument="NIFTY FUT", instrument_type="INDEX"):
        self.instrument = instrument
        self.instrument_type = instrument_type  # "INDEX" or "STOCK"

        # Position tracking
        self.position = self.FLAT
        self.entry_price = 0.0
        self.entry_date = None

        # Stop loss tracking
        self.current_sl = 0.0
        self.initial_sl = 0.0  # Day 1 fixed SL

        # Day count
        self.trade_start_day = None
        self.day_count = 0

        # Pyramid tracking
        self.pyramid_count = 0  # How many pyramid additions made
        self.pyramid_entry_prices = []  # Entry prices of each leg

        # P&L tracking
        self.trades_log = []
        self.daily_pnl = 0.0
        self.total_pnl = 0.0

        # S-A-R levels
        self.prev_top = 0.0   # Previous Top — BUY trigger
        self.prev_bottom = 0.0  # Previous Bottom — SELL trigger
        self.latest_top = 0.0
        self.latest_bottom = 0.0

        # Configuration
        self.config = self._default_config()

    def _default_config(self):
        """Default SL configuration based on instrument type."""
        if self.instrument_type == "INDEX":
            return {
                "day1_sl_pct": 0.01,       # Day 1: 1% stop loss
                "max_sl_pct": 0.02,        # Max 2% trailing SL
                "breakeven_trigger_pct": 0.02,  # Move to BE when profit > 2%
                "breakeven_trigger_pct_stock": 0.03,  # Stock: 3%
                "pyramid_enabled": True,
            }
        else:  # STOCK
            return {
                "day1_sl_pct": 0.015,      # Day 1: 1.5% stop loss
                "max_sl_pct": 0.03,        # Max 3% trailing SL
                "breakeven_trigger_pct": 0.03,  # Move to BE when profit > 3%
                "breakeven_trigger_pct_stock": 0.03,
                "pyramid_enabled": True,
            }

    def __repr__(self):
        return (
            f"TradeState({self.instrument})\n"
            f"  Position : {self.position}\n"
            f"  Entry    : {self.entry_price} on {self.entry_date}\n"
            f"  SL       : {self.current_sl}\n"
            f"  Day      : {self.day_count}\n"
            f"  P&L      : Rs.{self.daily_pnl:+.2f}\n"
            f"  S-A-R    : Top={self.prev_top} | Bottom={self.prev_bottom}"
        )


# ------------------------------------------------------------------
# SAR LEVEL MANAGER CLASS
# ------------------------------------------------------------------
class SARLevelManager:
    """
    Manages S-A-R levels and trade execution logic.

    Workflow:
        1. End of Day  : Load close data → Identify tops/bottoms → Update S-A-R
        2. Next Day    : Monitor live price → Check for S-A-R crossover
        3. Entry       : Execute BUY or SELL based on crossover
        4. During Trade: Update stop loss (Rules 3 & 4)
        5. Exit        : Auto-exit via SL or opposite signal
    """

    def __init__(self, state: TradeState):
        self.state = state
        self.df = None          # Daily close price data
        self.tops_df = None
        self.bottoms_df = None

        # Historical data
        self.price_history = []

        # Trading hours
        self.market_open_time = dtime(9, 15)   # 9:15 AM IST
        self.market_close_time = dtime(15, 30)  # 3:30 PM IST

        # Log file
        self.log_file = None

    # ------------------------------------------------------------------
    # INITIALIZATION
    # ------------------------------------------------------------------
    def initialize(self, df, prev_top, prev_bottom):
        """
        Initialize the manager with historical data and S-A-R levels.

        Args:
            df         : DataFrame with Date index and Close column
            prev_top   : Initial Previous Top price (S-A-R for BUY)
            prev_bottom: Initial Previous Bottom price (S-A-R for SELL)
        """
        self.df = df.copy()
        self.state.prev_top = prev_top
        self.state.prev_bottom = prev_bottom

        # Identify initial tops and bottoms
        self.df, tops, bottoms = identify_tops_bottoms(self.df)
        self.tops_df, self.bottoms_df = label_tops_bottoms(self.df, tops, bottoms)

        # Get latest levels
        levels = get_sar_levels(self.tops_df, self.bottoms_df)
        self.state.latest_top = levels['latest_top_price']
        self.state.latest_bottom = levels['latest_bottom_price']

        print(f"[INIT] SAR Level Manager initialized")
        print(f"[INIT] S-A-R BUY Level : Rs.{prev_top:,.2f}")
        print(f"[INIT] S-A-R SELL Level: Rs.{prev_bottom:,.2f}")

    # ------------------------------------------------------------------
    # CHECK FOR ENTRY SIGNALS
    # ------------------------------------------------------------------
    def check_entry_signal(self, current_price, timestamp=None):
        """
        Check if price has crossed S-A-R levels → Generate entry signal.

        Args:
            current_price: Current live market price
            timestamp    : Current time (optional)

        Returns:
            dict: {
                'signal': 'BUY' / 'SELL' / 'NONE',
                'trigger_price': price level crossed,
                'current_price': current price,
                'reason': explanation
            }
        """
        if self.state.position != TradeState.FLAT:
            return {'signal': 'NONE', 'reason': 'Already in position'}

        signal = {'signal': 'NONE', 'reason': 'No signal'}

        # BUY signal: price crosses ABOVE Previous Top
        if current_price >= self.state.prev_top:
            signal = {
                'signal': 'BUY',
                'trigger_price': self.state.prev_top,
                'current_price': current_price,
                'reason': f"Price Rs.{current_price} crossed ABOVE Previous Top Rs.{self.state.prev_top:,.2f}"
            }

        # SELL signal: price crosses BELOW Previous Bottom
        elif current_price <= self.state.prev_bottom:
            signal = {
                'signal': 'SELL',
                'trigger_price': self.state.prev_bottom,
                'current_price': current_price,
                'reason': f"Price Rs.{current_price} crossed BELOW Previous Bottom Rs.{self.state.prev_bottom:,.2f}"
            }

        return signal

    # ------------------------------------------------------------------
    # EXECUTE ENTRY
    # ------------------------------------------------------------------
    def execute_entry(self, signal, current_price, timestamp=None):
        """
        Execute a trade entry based on signal.

        Args:
            signal        : 'BUY' or 'SELL'
            current_price : Execution price
            timestamp     : Execution time

        Returns:
            dict with entry confirmation
        """
        if signal not in ('BUY', 'SELL'):
            return {'success': False, 'reason': 'Invalid signal'}

        ts = timestamp or datetime.now()

        # Determine SL based on Day 1 rules
        if signal == 'BUY':
            sl_price = current_price * (1 - self.state.config['day1_sl_pct'])
            self.state.position = TradeState.LONG
        else:
            sl_price = current_price * (1 + self.state.config['day1_sl_pct'])
            self.state.position = TradeState.SHORT

        self.state.entry_price = current_price
        self.state.entry_date = ts
        self.state.current_sl = sl_price
        self.state.initial_sl = sl_price
        self.state.trade_start_day = ts.date()
        self.state.day_count = 1
        self.state.pyramid_count = 0
        self.state.pyramid_entry_prices = [current_price]
        self.state.daily_pnl = 0.0

        entry_record = {
            'timestamp': str(ts),
            'signal': signal,
            'entry_price': current_price,
            'sl_price': sl_price,
            'prev_top': self.state.prev_top,
            'prev_bottom': self.state.prev_bottom,
            'pyramid_count': 0,
        }
        self.state.trades_log.append(entry_record)

        result = {
            'success': True,
            'position': self.state.position,
            'entry_price': current_price,
            'sl_price': sl_price,
            'sl_pct': f"{self.state.config['day1_sl_pct']*100:.1f}%",
            'message': f"[{ts.strftime('%Y-%m-%d %H:%M')}] {signal} executed at Rs.{current_price:,.2f}, SL: Rs.{sl_price:,.2f}"
        }

        print(f"\n{'='*60}")
        print(f"  EXECUTED: {signal}")
        print(f"  Price    : Rs.{current_price:,.2f}")
        print(f"  Stop Loss: Rs.{sl_price:,.2f} ({self.state.config['day1_sl_pct']*100:.1f}% — Day 1 Rule)")
        print(f"  Level    : Previous Top/Bottom used as S-A-R")
        print(f"{'='*60}\n")

        return result

    # ------------------------------------------------------------------
    # UPDATE STOP LOSS (RULES 3 & 4)
    # ------------------------------------------------------------------
    def update_stop_loss(self, current_price, current_date):
        """
        Update stop loss based on Rules 3 and 4.

        Rule 3: Trailing SL — MAX 2% (Index) / 3% (Stock) below current price
                OR Previous Bottom, whichever is CLOSER

        Rule 4: If profit > 2%/3% → Move SL to BREAKEVEN

        This is called during market hours for open positions.

        Args:
            current_price: Current live price
            current_date : Current date

        Returns:
            dict with old SL, new SL, and reason
        """
        if self.state.position == TradeState.FLAT:
            return {'updated': False, 'reason': 'No open position'}

        old_sl = self.state.current_sl

        # Calculate profit/loss percentage
        if self.state.position == TradeState.LONG:
            pnl_pct = (current_price - self.state.entry_price) / self.state.entry_price
            # How far below current price is the previous bottom?
            prev_bottom_distance_pct = (current_price - self.state.prev_bottom) / current_price
        else:  # SHORT
            pnl_pct = (self.state.entry_price - current_price) / self.state.entry_price
            prev_bottom_distance_pct = (self.state.prev_top - current_price) / current_price

        max_sl_pct = self.state.config['max_sl_pct']
        breakeven_trigger = self.state.config['breakeven_trigger_pct']

        # Update day count if new day
        if current_date > self.state.trade_start_day:
            self.state.day_count = (current_date - self.state.trade_start_day).days + 1
            print(f"[DAY UPDATE] Day {self.state.day_count} — Applying Rule 3 & 4 SL logic")

        # ---- RULE 4: BREAKEVEN ----
        if pnl_pct >= breakeven_trigger:
            # Move SL to breakeven
            new_sl = self.state.entry_price
            reason = f"Profit {pnl_pct*100:.2f}% >= {breakeven_trigger*100:.0f}% → SL moved to BREAKEVEN"

        # ---- RULE 3: TRAILING SL ----
        else:
            # Max allowed distance from current price
            max_sl_distance = current_price * (1 - max_sl_pct)

            # Distance to previous bottom
            if self.state.position == TradeState.LONG:
                prev_bottom_sl = self.state.prev_bottom
            else:
                prev_bottom_sl = self.state.prev_top

            # Choose whichever is CLOSER to current price
            if prev_bottom_sl > max_sl_distance:
                # Previous bottom is closer (tighter stop)
                new_sl = prev_bottom_sl
                reason = f"Previous {('Bottom' if self.state.position == 'LONG' else 'Top')} Rs.{prev_bottom_sl:,.2f} is closer than max {max_sl_pct*100:.0f}% level Rs.{max_sl_distance:,.2f}"
            else:
                # Max distance level is closer
                new_sl = max_sl_distance
                reason = f"Max {max_sl_pct*100:.0f}% trailing level Rs.{max_sl_distance:,.2f} is closer than Previous {'Bottom' if self.state.position == 'LONG' else 'Top'} Rs.{prev_bottom_sl:,.2f}"

            # SL only moves UP (never down) — protect locked profits
            if new_sl < old_sl:
                new_sl = old_sl
                reason = f"SL kept at Rs.{old_sl:,.2f} (only moves UP, not down)"

        # Apply new SL if it improved
        if new_sl > old_sl or (self.state.position == TradeState.SHORT and new_sl < old_sl):
            direction = "UP" if self.state.position == TradeState.LONG else "DOWN"
            self.state.current_sl = new_sl

            result = {
                'updated': True,
                'old_sl': old_sl,
                'new_sl': new_sl,
                'direction': direction,
                'pnl_pct': pnl_pct * 100,
                'reason': reason
            }

            print(f"  [SL UPDATE] SL moved {direction}: Rs.{old_sl:,.2f} → Rs.{new_sl:,.2f}")
            print(f"  [REASON] {reason}")
            print(f"  [P&L] Current P&L: {pnl_pct*100:+.2f}%\n")

            return result

        return {'updated': False, 'reason': 'SL already at best level'}

    # ------------------------------------------------------------------
    # CHECK FOR EXIT (SL HIT OR OPPOSITE SIGNAL)
    # ------------------------------------------------------------------
    def check_exit(self, current_price, timestamp=None):
        """
        Check if position should be exited.

        Exit conditions:
            1. SL hit (price crosses SL level)
            2. Opposite S-A-R signal (price crosses other S-A-R level)

        Args:
            current_price: Current live price
            timestamp    : Current time

        Returns:
            dict: {'exit': True/False, 'reason': str, 'pnl': float}
        """
        if self.state.position == TradeState.FLAT:
            return {'exit': False, 'reason': 'No position'}

        ts = timestamp or datetime.now()
        sl = self.state.current_sl

        if self.state.position == TradeState.LONG:
            # Exit if price drops to or below SL
            if current_price <= sl:
                pnl = (current_price - self.state.entry_price)
                return {
                    'exit': True,
                    'reason': f"SL HIT — Price Rs.{current_price:,.2f} <= SL Rs.{sl:,.2f}",
                    'exit_price': current_price,
                    'pnl': pnl,
                    'signal': 'SELL'  # Stop and Reverse → now SHORT
                }

            # Check for opposite signal (SELL = cross below prev bottom)
            if current_price <= self.state.prev_bottom:
                pnl = (current_price - self.state.entry_price)
                return {
                    'exit': True,
                    'reason': f"SELL SIGNAL — Price Rs.{current_price:,.2f} crossed BELOW Previous Bottom Rs.{self.state.prev_bottom:,.2f} (Stop & Reverse)",
                    'exit_price': current_price,
                    'pnl': pnl,
                    'signal': 'SELL'
                }

        elif self.state.position == TradeState.SHORT:
            # Exit if price rises to or above SL
            if current_price >= sl:
                pnl = (self.state.entry_price - current_price)
                return {
                    'exit': True,
                    'reason': f"SL HIT — Price Rs.{current_price:,.2f} >= SL Rs.{sl:,.2f}",
                    'exit_price': current_price,
                    'pnl': pnl,
                    'signal': 'BUY'  # Stop and Reverse → now LONG
                }

            # Check for opposite signal (BUY = cross above prev top)
            if current_price >= self.state.prev_top:
                pnl = (self.state.entry_price - current_price)
                return {
                    'exit': True,
                    'reason': f"BUY SIGNAL — Price Rs.{current_price:,.2f} crossed ABOVE Previous Top Rs.{self.state.prev_top:,.2f} (Stop & Reverse)",
                    'exit_price': current_price,
                    'pnl': pnl,
                    'signal': 'BUY'
                }

        return {'exit': False, 'reason': 'Position open, no exit signal'}

    # ------------------------------------------------------------------
    # PYRAMID LOGIC (RULE 5)
    # ------------------------------------------------------------------
    def check_pyramid_signal(self, current_price, timestamp=None):
        """
        Check if conditions are met for a pyramid (adding to winning position).

        Pyramid conditions (Rule 5):
            1. Already in a winning trade (profit > breakeven trigger %)
            2. New bottom/top has formed (Previous level has shifted)
            3. Price crosses ABOVE new Previous Top (for LONG) or
               BELOW new Previous Bottom (for SHORT)

        Args:
            current_price: Current live price
            timestamp    : Current time

        Returns:
            dict: {'pyramid_signal': True/False, 'signal': 'BUY'/'SELL'}
        """
        if not self.state.config['pyramid_enabled']:
            return {'pyramid_signal': False, 'reason': 'Pyramid disabled'}

        if self.state.position == TradeState.FLAT:
            return {'pyramid_signal': False, 'reason': 'No position'}

        ts = timestamp or datetime.now()

        # Check if currently profitable enough (Rule 4 already triggered)
        if self.state.position == TradeState.LONG:
            pnl_pct = (current_price - self.state.entry_price) / self.state.entry_price
            # Must be in profit and SL already at breakeven
            if pnl_pct < self.state.config['breakeven_trigger_pct']:
                return {'pyramid_signal': False, 'reason': f'Profit {pnl_pct*100:.2f}% below trigger {self.state.config["breakeven_trigger_pct"]*100:.0f}%'}

            # Check for new BUY signal (price crosses above updated prev_top)
            if current_price >= self.state.prev_top:
                return {
                    'pyramid_signal': True,
                    'signal': 'BUY',
                    'reason': f"Pyramid BUY: Price Rs.{current_price:,.2f} crossed above updated Previous Top Rs.{self.state.prev_top:,.2f}"
                }

        elif self.state.position == TradeState.SHORT:
            pnl_pct = (self.state.entry_price - current_price) / self.state.entry_price
            if pnl_pct < self.state.config['breakeven_trigger_pct']:
                return {'pyramid_signal': False, 'reason': f'Profit {pnl_pct*100:.2f}% below trigger'}

            if current_price <= self.state.prev_bottom:
                return {
                    'pyramid_signal': True,
                    'signal': 'SELL',
                    'reason': f"Pyramid SELL: Price Rs.{current_price:,.2f} crossed below updated Previous Bottom Rs.{self.state.prev_bottom:,.2f}"
                }

        return {'pyramid_signal': False, 'reason': 'No pyramid signal'}

    # ------------------------------------------------------------------
    # EXECUTE PYRAMID
    # ------------------------------------------------------------------
    def execute_pyramid(self, signal, current_price, timestamp=None):
        """
        Execute a pyramid addition (same quantity as initial trade).

        Args:
            signal        : 'BUY' or 'SELL'
            current_price : Execution price
            timestamp     : Execution time

        Returns:
            dict with pyramid confirmation
        """
        if signal not in ('BUY', 'SELL'):
            return {'success': False, 'reason': 'Invalid signal'}

        ts = timestamp or datetime.now()
        self.state.pyramid_count += 1
        self.state.pyramid_entry_prices.append(current_price)

        # Calculate average entry price
        avg_entry = sum(self.state.pyramid_entry_prices) / len(self.state.pyramid_entry_prices)

        pyramid_record = {
            'timestamp': str(ts),
            'pyramid_leg': self.state.pyramid_count,
            'price': current_price,
            'avg_entry': avg_entry,
        }
        self.state.trades_log[-1]['pyramid_count'] = self.state.pyramid_count
        self.state.trades_log[-1]['pyramid_entry_prices'] = self.state.pyramid_entry_prices.copy()

        result = {
            'success': True,
            'pyramid_leg': self.state.pyramid_count,
            'price': current_price,
            'avg_entry': avg_entry,
            'message': f"[{ts.strftime('%Y-%m-%d %H:%M')}] PYRAMID {signal} #Leg{self.state.pyramid_count} at Rs.{current_price:,.2f}, Avg Entry: Rs.{avg_entry:,.2f}"
        }

        print(f"\n{'='*60}")
        print(f"  PYRAMID EXECUTED: {signal} (Leg #{self.state.pyramid_count})")
        print(f"  Price      : Rs.{current_price:,.2f}")
        print(f"  Avg Entry  : Rs.{avg_entry:,.2f}")
        print(f"  Total Legs : {self.state.pyramid_count}")
        print(f"{'='*60}\n")

        return result

    # ------------------------------------------------------------------
    # CLOSE TRADE
    # ------------------------------------------------------------------
    def close_trade(self, exit_price, exit_reason, timestamp=None, new_signal=None):
        """
        Close the current position and optionally open opposite position.

        Args:
            exit_price  : Price at which trade is closed
            exit_reason : Reason for closing (SL hit, signal, manual, etc.)
            timestamp   : Exit time
            new_signal  : If Stop & Reverse, the new signal ('BUY' or 'SELL')

        Returns:
            dict with trade summary
        """
        if self.state.position == TradeState.FLAT:
            return {'success': False, 'reason': 'No open position'}

        ts = timestamp or datetime.now()

        # Calculate P&L
        if self.state.position == TradeState.LONG:
            pnl = (exit_price - self.state.entry_price)
            position_closed = TradeState.LONG
        else:
            pnl = (self.state.entry_price - exit_price)
            position_closed = TradeState.SHORT

        # Trade summary
        trade_summary = {
            'exit_date': str(ts),
            'position_closed': position_closed,
            'entry_price': self.state.entry_price,
            'entry_date': str(self.state.entry_date),
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl': pnl,
            'pyramid_legs': self.state.pyramid_count,
            'days_held': self.state.day_count,
        }

        self.state.daily_pnl = pnl
        self.state.total_pnl += pnl

        print(f"\n{'='*60}")
        print(f"  TRADE CLOSED: {position_closed}")
        print(f"  Entry   : Rs.{self.state.entry_price:,.2f} on {self.state.entry_date}")
        print(f"  Exit    : Rs.{exit_price:,.2f} on {ts}")
        print(f"  P&L     : Rs.{pnl:+.2f} {'PROFIT' if pnl > 0 else 'LOSS'}")
        print(f"  Reason  : {exit_reason}")
        print(f"  Days    : {self.state.day_count}")
        print(f"  Pyramid : {self.state.pyramid_count} legs")
        print(f"  Total P&L: Rs.{self.state.total_pnl:+.2f}")
        print(f"{'='*60}\n")

        # Reset position
        self.state.position = TradeState.FLAT
        self.state.entry_price = 0.0
        self.state.entry_date = None
        self.state.current_sl = 0.0
        self.state.day_count = 0

        return {'success': True, 'trade_summary': trade_summary, 'new_signal': new_signal}

    # ------------------------------------------------------------------
    # END OF DAY UPDATE
    # ------------------------------------------------------------------
    def end_of_day_update(self, close_price, close_date):
        """
        Called at the end of each trading day.

        Steps:
            1. Add today's close to price history
            2. Re-identify tops and bottoms
            3. Update S-A-R levels
            4. Update stop loss for open position

        Args:
            close_price: Today's closing price
            close_date : Today's date
        """
        print(f"\n[EOD] End of Day: {close_date} | Close: Rs.{close_price:,.2f}")

        # Add to history
        new_row = pd.DataFrame({'Close': [close_price]}, index=[pd.Timestamp(close_date)])
        self.df = pd.concat([self.df, new_row]).sort_index()

        # Re-identify tops and bottoms
        self.df, tops, bottoms = identify_tops_bottoms(self.df)
        self.tops_df, self.bottoms_df = label_tops_bottoms(self.df, tops, bottoms)

        # Get updated S-A-R levels
        levels = get_sar_levels(self.tops_df, self.bottoms_df)

        # Update state with new levels
        old_prev_top = self.state.prev_top
        old_prev_bottom = self.state.prev_bottom

        self.state.prev_top = levels['prev_top_price']
        self.state.prev_bottom = levels['prev_bottom_price']
        self.state.latest_top = levels['latest_top_price']
        self.state.latest_bottom = levels['latest_bottom_price']

        print(f"[EOD] S-A-R Levels Updated:")
        print(f"      Previous Top   : Rs.{old_prev_top:,.2f} → Rs.{self.state.prev_top:,.2f}")
        print(f"      Previous Bottom: Rs.{old_prev_bottom:,.2f} → Rs.{self.state.prev_bottom:,.2f}")

        # Print full report
        print_sar_report(levels, self.tops_df, self.bottoms_df)

        # Update SL if in position (Rules 3 & 4)
        if self.state.position != TradeState.FLAT:
            self.update_stop_loss(close_price, close_date)

        return levels

    # ------------------------------------------------------------------
    # FULL DAY SIMULATION
    # ------------------------------------------------------------------
    def run_day_simulation(self, day_date, open_price, high_price, low_price, close_price):
        """
        Simulate a full trading day with intraday price movements.

        This is useful for backtesting — it simulates the day's price action
        and checks for entry/exit signals at each price point.

        Args:
            day_date    : The trading date
            open_price  : Day's opening price
            high_price  : Day's high price
            low_price   : Day's low price
            close_price : Day's closing price

        Returns:
            dict with day's activity log
        """
        print(f"\n{'='*60}")
        print(f"  DAY SIMULATION: {day_date}")
        print(f"  O: {open_price} | H: {high_price} | L: {low_price} | C: {close_price}")
        print(f"{'='*60}")

        events = []

        # Simulate price points through the day
        price_points = [
            ("Open", open_price),
            ("Intraday High", high_price),
            ("Intraday Low", low_price),
            ("Close", close_price),
        ]

        for label, price in price_points:
            ts = datetime.combine(day_date, dtime(9, 30))
            current_time = label  # Use label as time indicator

            # Check exit first
            exit_result = self.check_exit(price, ts)
            if exit_result['exit']:
                close_result = self.close_trade(
                    exit_price=exit_result['exit_price'],
                    exit_reason=exit_result['reason'],
                    timestamp=ts,
                    new_signal=exit_result.get('signal')
                )
                events.append({
                    'time': current_time,
                    'event': 'EXIT',
                    'price': exit_result['exit_price'],
                    'reason': exit_result['reason'],
                    'pnl': exit_result['pnl']
                })

                # If Stop & Reverse, execute new entry immediately
                if exit_result.get('signal'):
                    self.execute_entry(exit_result['signal'], exit_result['exit_price'], ts)
                    events.append({
                        'time': current_time,
                        'event': f"NEW {exit_result['signal']} (S&R)",
                        'price': exit_result['exit_price'],
                    })

            # Check for entry (if flat)
            if self.state.position == TradeState.FLAT:
                entry_signal = self.check_entry_signal(price, ts)
                if entry_signal['signal'] in ('BUY', 'SELL'):
                    self.execute_entry(entry_signal['signal'], price, ts)
                    events.append({
                        'time': current_time,
                        'event': f"ENTRY {entry_signal['signal']}",
                        'price': price,
                        'reason': entry_signal['reason']
                    })

            # Check pyramid
            if self.state.position != TradeState.FLAT:
                pyramid_result = self.check_pyramid_signal(price, ts)
                if pyramid_result['pyramid_signal']:
                    self.execute_pyramid(pyramid_result['signal'], price, ts)
                    events.append({
                        'time': current_time,
                        'event': f"PYRAMID {pyramid_result['signal']}",
                        'price': price,
                        'reason': pyramid_result['reason']
                    })

        # End of day update
        self.end_of_day_update(close_price, day_date)

        return {'day': day_date, 'events': events, 'close': close_price}


# ------------------------------------------------------------------
# DEMO: SIMULATE A FEW DAYS
# ------------------------------------------------------------------
def run_sar_manager_demo():
    """Run a demonstration of the S-A-R Level Manager."""

    print("\n" + "="*60)
    print("  S-A-R LEVEL MANAGER — DEMO")
    print("="*60 + "\n")

    # Create trade state for Bank Nifty Index Futures
    state = TradeState(instrument="BANKNIFTY FUT", instrument_type="INDEX")

    # Create manager
    manager = SARLevelManager(state)

    # Sample historical data (30 days)
    dates = pd.bdate_range('2024-01-01', periods=30)
    prices = [
        45200, 45100, 45350, 45400, 45250,  # Top B = 45400
        45100, 44900, 44700, 45000, 45200,  # Bottom C = 44700
        45500, 45650, 45500, 45800, 45700,  # Top D = 45800
        45400, 45200, 44900, 45100, 45300,  # Bottom E = 44900
        45500, 45700, 45600, 45900, 46000,  # Top F = 46000
        45800, 45500, 45300, 45600, 45800   # Bottom G = 45300
    ]

    df = pd.DataFrame({'Close': prices}, index=dates)

    # Initialize with initial S-A-R levels
    # For demo: Previous Top = 45400, Previous Bottom = 44700
    manager.initialize(df, prev_top=45400.0, prev_bottom=44700.0)

    # Simulate Day 31: Price breaks above previous top (BUY signal)
    print("\n" + "-"*60)
    print("  DAY 31: Price breaks above Previous Top Rs.45,400")
    print("-"*60)

    day31 = date(2024, 2, 8)
    result = manager.run_day_simulation(
        day_date=day31,
        open_price=45450,
        high_price=45600,
        low_price=45350,
        close_price=45580
    )

    # Simulate Day 32: Price continues higher
    print("\n" + "-"*60)
    print("  DAY 32: Price moves to Rs.45,800")
    print("-"*60)

    day32 = date(2024, 2, 9)
    result = manager.run_day_simulation(
        day_date=day32,
        open_price=45600,
        high_price=45900,
        low_price=45500,
        close_price=45850
    )

    # Print final state
    print("\n" + "="*60)
    print("  FINAL TRADE STATE")
    print("="*60)
    print(manager.state)

    return manager


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
if __name__ == "__main__":
    manager = run_sar_manager_demo()
