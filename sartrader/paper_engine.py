"""
=============================================================
paper_engine.py — Paper Trading Engine
=============================================================
Simulates order execution without connecting to a real broker.
Used for testing strategies before going live.
=============================================================
"""
import time
import logging
import sqlite3
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field

from sartrader.broker_interface import (
    OrderSide, OrderType, OrderStatus, PositionSide,
)
from sartrader.strategies.base import Signal, SignalType

logger = logging.getLogger("paper_trading")


@dataclass
class PaperPosition:
    instrument:    str
    side:          str           # "LONG" or "SHORT"
    quantity:      int
    entry_price:   float
    current_sl:    float
    entry_idx:     int
    entry_time:    str
    be_done:       bool = False
    pyramids:      int = 0


@dataclass
class PaperTrade:
    trade_id:      str
    instrument:    str
    direction:     str
    entry_date:    str
    entry_price:   float
    exit_date:     str
    exit_price:    float
    quantity:      int
    pnl:           float
    pyramids:      int
    reason:        str
    capital_after: float


class PaperEngine:
    """
    Simulates broker fills with realistic slippage.
    Tracks positions, P&L, and trade history.
    """

    def __init__(self, initial_capital: float = 100_000,
                 lot_size: int = 30,
                 slippage_pct: float = 0.05,
                 brokerage_per_lot: float = 80.0,
                 db_path: str = "data/paper_trades.db"):
        self.initial_capital    = initial_capital
        self.capital            = initial_capital
        self.lot_size           = lot_size
        self.slippage_pct       = slippage_pct
        self.brokerage_per_lot  = brokerage_per_lot
        self.direction          = "long"     # long | short | long_only | short_only
        self.pyramiding         = "ADD"      # ADD | MANUAL

        # Active position
        self.position: Optional[PaperPosition] = None

        # Trade history
        self.trades: List[PaperTrade] = []

        # SQLite persistence
        self._db_path = db_path
        self._lock    = threading.Lock()
        self._trade_counter = 0

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        logger.info(
            f"PaperEngine initialized: Capital=Rs.{initial_capital:,.0f}, "
            f"Lot={lot_size}, Slippage={slippage_pct}%"
        )

    def _init_db(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                trade_id    TEXT PRIMARY KEY,
                instrument  TEXT,
                direction   TEXT,
                entry_date  TEXT,
                entry_price REAL,
                exit_date   TEXT,
                exit_price  REAL,
                quantity    INTEGER,
                pnl         REAL,
                pyramids    INTEGER,
                reason      TEXT,
                capital_after REAL,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS capital_log (
                ts          TEXT,
                capital     REAL,
                position    TEXT,
                notes       TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Load historical trades from DB into memory
        self._load_trades()

    def _load_trades(self):
        """Load closed trades from DB so they survive engine restarts."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        cur = conn.execute(
            "SELECT trade_id, instrument, direction, entry_date, entry_price, "
            "exit_date, exit_price, quantity, pnl, pyramids, reason, capital_after "
            "FROM paper_trades ORDER BY created_at ASC"
        )
        for row in cur.fetchall():
            self.trades.append(PaperTrade(
                trade_id=row[0],
                instrument=row[1],
                direction=row[2],
                entry_date=row[3],
                entry_price=row[4],
                exit_date=row[5],
                exit_price=row[6],
                quantity=row[7],
                pnl=row[8],
                pyramids=row[9],
                reason=row[10],
                capital_after=row[11],
            ))
        conn.close()
        if self.trades:
            logger.info(f"[PaperEngine] Loaded {len(self.trades)} historical trade(s) from DB")

    def _tick(self) -> str:
        self._trade_counter += 1
        return f"PAPER-{datetime.now().strftime('%Y%m%d')}-{self._trade_counter:04d}"

    # ── Simulated fill ────────────────────────────────────────────────────────

    def _fill_price(self, price: float, side: str) -> float:
        """Apply slippage: buy higher, sell lower."""
        if side == "BUY":
            return round(price * (1 + self.slippage_pct / 100), 2)
        else:
            return round(price * (1 - self.slippage_pct / 100), 2)

    # ── Entry ────────────────────────────────────────────────────────────────

    def enter(self, signal: Signal, idx: int = 0) -> Optional[PaperTrade]:
        """Simulate entry order from a signal."""
        with self._lock:
            if self.position is not None:
                logger.warning(
                    f"Cannot enter — position already open: "
                    f"{self.position.instrument}"
                )
                return None

            now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            price = signal.price

            if signal.type == SignalType.LONG_ENTRY:
                fill_price = self._fill_price(price, "BUY")
                side       = "LONG"
            elif signal.type == SignalType.SHORT_ENTRY:
                fill_price = self._fill_price(price, "SELL")
                side       = "SHORT"
            else:
                return None

            # Brokerage
            brokerage = self.brokerage_per_lot * (signal.quantity or 1)
            self.capital -= brokerage

            self.position = PaperPosition(
                instrument=signal.instrument,
                side=side,
                quantity=signal.quantity or self.lot_size,
                entry_price=fill_price,
                current_sl=signal.stop_loss or fill_price * (0.97 if side == "LONG" else 1.03),
                entry_idx=idx,
                entry_time=now,
            )

            trade_id = self._tick()
            logger.info(
                f"[PAPER] Entry: {side} {self.position.quantity} lots @ "
                f"{fill_price:.2f} | Capital: Rs.{self.capital:,.2f} "
                f"| Reason: {signal.reason}"
            )

            # Log to DB
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO capital_log VALUES (?, ?, ?, ?)",
                (now, self.capital, side, f"Entry: {signal.reason}")
            )
            conn.commit()
            conn.close()

            return trade_id

    # ── Exit ─────────────────────────────────────────────────────────────────

    def exit(self, reason: str, exit_price: Optional[float] = None,
             force_side: Optional[str] = None) -> Optional[PaperTrade]:
        """Close current position."""
        with self._lock:
            if self.position is None:
                return None

            pos = self.position
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            price = exit_price or pos.current_sl

            # Fill with slippage (opposite side)
            fill_side = "SELL" if pos.side == "LONG" else "BUY"
            fill_price = self._fill_price(price, fill_side)

            mult    = 1 + pos.pyramids
            qty     = pos.quantity * mult
            pnl_raw = (fill_price - pos.entry_price) * qty \
                      if pos.side == "LONG" \
                      else (pos.entry_price - fill_price) * qty

            brokerage = self.brokerage_per_lot * mult
            pnl       = pnl_raw - brokerage
            self.capital += pnl

            trade_id = self._tick()
            trade = PaperTrade(
                trade_id=trade_id,
                instrument=pos.instrument,
                direction=pos.side,
                entry_date=pos.entry_time,
                entry_price=pos.entry_price,
                exit_date=now,
                exit_price=fill_price,
                quantity=qty,
                pnl=round(pnl, 2),
                pyramids=pos.pyramids,
                reason=reason,
                capital_after=round(self.capital, 2),
            )
            self.trades.append(trade)

            logger.info(
                f"[PAPER] Exit: {pos.side} {qty} lots @ {fill_price:.2f} | "
                f"P&L: Rs.{pnl:,.2f} | Capital: Rs.{self.capital:,.2f} | "
                f"[{reason}]"
            )

            # Persist
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (trade.trade_id, trade.instrument, trade.direction,
                 trade.entry_date, trade.entry_price, trade.exit_date,
                 trade.exit_price, trade.quantity, trade.pnl,
                 trade.pyramids, trade.reason, trade.capital_after)
            )
            conn.execute(
                "INSERT INTO capital_log VALUES (?, ?, ?, ?)",
                (now, self.capital, "CLOSED", reason)
            )
            conn.commit()
            conn.close()

            self.position = None
            return trade

    # ── Pyramiding ───────────────────────────────────────────────────────────

    def pyramid(self, price: float, idx: int) -> bool:
        """Add to position (called when breakeven done + new breakout)."""
        with self._lock:
            if self.position is None or self.position.be_done is False:
                return False
            self.position.quantity += self.lot_size
            self.position.pyramids += 1
            logger.info(
                f"[PAPER] Pyramid +{self.lot_size} lots | "
                f"Total: {self.position.quantity} | "
                f"Avg price: {self.position.entry_price:.2f}"
            )
            return True

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        pos = self.position
        unrealized = 0.0
        if pos:
            mult  = 1 + pos.pyramids
            qty   = pos.quantity * mult
            if pos.side == "LONG":
                unrealized = (pos.current_sl - pos.entry_price) * qty
            else:
                unrealized = (pos.entry_price - pos.current_sl) * qty

        wins  = [t for t in self.trades if t.pnl > 0]
        losses= [t for t in self.trades if t.pnl <= 0]
        wr    = len(wins) / len(self.trades) * 100 if self.trades else 0

        return {
            "capital":       round(self.capital, 2),
            "initial":       self.initial_capital,
            "return_pct":    round((self.capital - self.initial_capital)
                                    / self.initial_capital * 100, 2),
            "unrealized":    round(unrealized, 2),
            "total_trades":  len(self.trades),
            "wins":          len(wins),
            "losses":        len(losses),
            "win_rate":     round(wr, 1),
            "avg_win":       round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss":      round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0,
            "position": {
                "instrument":  pos.instrument if pos else None,
                "side":        pos.side if pos else "FLAT",
                "qty":         pos.quantity if pos else 0,
                "entry_price": pos.entry_price if pos else 0,
                "current_sl":  pos.current_sl if pos else 0,
                "entry_time":  pos.entry_time if pos else "",
                "be_done":     pos.be_done if pos else False,
                "pyramids":    pos.pyramids if pos else 0,
            } if pos else None,
        }

    def get_trade_history(self) -> List[dict]:
        return [
            {
                "trade_id":   t.trade_id,
                "instrument": t.instrument,
                "direction":  t.direction,
                "entry_date": t.entry_date,
                "entry_price":t.entry_price,
                "exit_date":  t.exit_date,
                "exit_price": t.exit_price,
                "quantity":   t.quantity,
                "pnl":        t.pnl,
                "pyramids":   t.pyramids,
                "reason":     t.reason,
                "capital_after": t.capital_after,
            }
            for t in self.trades
        ]
