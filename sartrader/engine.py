"""
=============================================================
engine.py — Trading Engine + WebSocket Server
=============================================================
Core platform engine that:
  - Manages broker connections (M-Stock, Zerodha)
  - Runs strategy signal generation
  - Handles paper/live order execution
  - Pushes live updates to the dashboard via WebSocket
  - Serves the HTML dashboard

Run: python -m sartrader.engine
Dashboard: http://localhost:8765
=============================================================
"""
import os
import sys
import json
import time
import logging
import threading
import asyncio
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime as _dt, time as dtime
from typing import Dict, Optional, List, Any
from dataclasses import asdict

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

import sartrader.config as config
from sartrader.broker_interface import (
    AbstractBroker, OrderSide, OrderType, OrderStatus,
    PositionSide, OHLC, get_broker,
)
from sartrader.paper_engine import PaperEngine
from sartrader.strategies.sar_top_bottom import SARTopBottomStrategy
from sartrader.strategies.top_bottom_2 import TopBottom2Strategy
from sartrader.strategies.base import Signal, SignalType
from sartrader.strategies.base import SignalType

# Import broker modules to trigger registration
import sartrader.brokers.mstock_broker   # noqa: F401
import sartrader.brokers.zerodha_broker  # noqa: F401

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "logs" / "engine.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("engine")

# ── WebSocket server (stdlib, no extra deps) ──────────────────────────────────

async def websocket_handler(websocket, path, engine_ref):
    """Handle one dashboard client connection."""
    engine = engine_ref()
    await engine.add_client(websocket)
    logger.info(f"Dashboard connected. Total clients: {len(engine._ws_clients)}")
    try:
        # Send initial state
        await engine.broadcast_state()
        async for msg in websocket:
            try:
                data = json.loads(msg)
                await engine.handle_dashboard_message(data, websocket)
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.debug(f"WebSocket client disconnected: {e}")
    finally:
        await engine.remove_client(websocket)


async def ws_server(engine_ref, host="localhost", port=8765):
    """Run WebSocket server using asyncio."""
    import websockets
    import functools

    # In websockets 13+, handler receives only (websocket)
    # Capture engine_ref via closure
    async def handler(websocket):
        await websocket_handler(websocket, "", engine_ref)

    async with websockets.serve(handler, host, port):
        logger.info(f"WebSocket server running: ws://{host}:{port}")
        await asyncio.Future()   # Run forever


# ── Main Engine ────────────────────────────────────────────────────────────────

class TradingEngine:

    def __init__(self):
        self.mode       = config.MODE
        self.brokers:  Dict[str, AbstractBroker] = {}
        self.strategies: Dict[str, Any] = {}   # instrument -> strategy
        self.paper     = PaperEngine(
            initial_capital=config.INITIAL_CAPITAL,
            lot_size=config.PAPER["lot_sizes"].get("BANKNIFTY", 30),
            slippage_pct=config.PAPER["slippage_pct"],
            brokerage_per_lot=config.PAPER["brokerage_per_lot"],
            db_path=str(BASE_DIR / "data" / "paper_trades.db"),
        )
        self._running   = False
        self._live_trades: List[dict] = []   # Live trade history
        self._tick_thread: Optional[threading.Thread] = None
        self._tick_interval = 30     # seconds between ticks

        # WebSocket clients
        self._ws_clients: List[Any] = []
        self._ws_lock: Optional[asyncio.Lock] = None   # lazy — set on first use
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # In-memory signal log
        self._signals: List[dict] = []

        # Signal deduplication — prevent same signal firing on every tick
        # Key: (instrument, signal_type) → last fired timestamp
        self._signal_fired: Dict[str, float] = {}

        # Multi-instrument position tracking
        # instrument → {side, entry_price, qty, sl, be_pct, entry_time, be_done, pyramids}
        self._positions: Dict[str, dict] = {}

        # NSE F&O futures cache — synced from broker API
        # Set of available stock futures symbols, e.g. {'SBIN26SEPFUT', ...}
        self._available_futures: set = set()

        # In-memory watchlist: instrument -> {strategy, strategy_params, ...}
        # Persisted to data/watchlist.json
        self._watchlist: Dict[str, dict] = {}

        # Load strategies from config
        self._init_strategies()

        # Connect brokers
        self._init_brokers()

        logger.info(f"TradingEngine initialized in {self.mode} mode")

    # ── Broker setup ─────────────────────────────────────────────────────────

    def _init_brokers(self):
        if config.MSTOCK["enabled"]:
            try:
                broker = get_broker(
                    "MSTOCK",
                    api_key=config.MSTOCK["api_key"],
                    client_code=config.MSTOCK["client_code"],
                    password=config.MSTOCK["password"],
                    totp_secret=config.MSTOCK["totp_secret"],
                    ip=config.MSTOCK["whitelisted_ip"],
                )
                self.brokers["MSTOCK"] = broker
                logger.info("M-Stock broker registered")
            except Exception as e:
                logger.warning(f"M-Stock broker init failed: {e}")

        if config.ZERODHA["enabled"]:
            try:
                broker = get_broker(
                    "ZERODHA",
                    api_key=config.ZERODHA["api_key"],
                    api_secret=config.ZERODHA["api_secret"],
                    access_token=config.ZERODHA.get("access_token", ""),
                )
                self.brokers["ZERODHA"] = broker
                logger.info("Zerodha broker registered")
            except Exception as e:
                logger.warning(f"Zerodha broker init failed: {e}")

        # Try to sync NFO futures list from any connected broker
        self._sync_nfo_instruments()

    def _sync_nfo_instruments(self):
        """
        Fetch the live list of available NSE F&O stock futures from connected brokers.
        Called on startup and periodically to keep the list fresh.
        Stores result in self._available_futures as a set of symbol strings.
        Also detects the current futures expiry month.
        """
        self._current_expiry = self._detect_expiry()
        for name, broker in self.brokers.items():
            if not broker.is_connected():
                continue
            try:
                futures = broker.get_nfo_instruments()
                if futures:
                    self._available_futures = set(futures)
                    logger.info(
                        f"Synced {len(self._available_futures)} NSE stock futures "
                        f"from {name} broker | Expiry: {self._current_expiry}"
                    )
                    return  # Success — stop after first broker
            except Exception as e:
                logger.warning(f"Failed to sync NFO instruments from {name}: {e}")

    def _detect_expiry(self) -> str:
        """Detect current NSE monthly futures expiry (e.g. 'SEP26')."""
        # NSE futures expire on last Thursday of each month
        # Map: detect which month + year suffix
        now = _dt.now()
        month_map = {
            1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
            5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
            9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
        }
        yr = str(now.year)[2:]   # e.g. "26"
        return f"{month_map[now.month]}{yr}"

    @property
    def current_expiry(self) -> str:
        """Current NSE futures expiry string, e.g. 'SEP26'."""
        return getattr(self, "_current_expiry", "SEP26")

    def is_futures_available(self, instrument: str) -> bool:
        """Check if an instrument is in the broker's available futures list."""
        if not self._available_futures:
            return True  # No data — optimistically allow (fallback to hardcoded list)
        return instrument in self._available_futures

    # ── Segment Classification ──────────────────────────────────────────────────

    INDEX_FUTURES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"}
    COMMODITY_FUTURES = {"GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "GOLD-M", "SILVER-M"}

    def _infer_segment(self, inst: str) -> str:
        """Classify instrument into a segment."""
        import re
        inst_upper = inst.upper()
        # Options: CE/PE before a number (e.g. NIFTYCE35000, RELIANCEPE2500)
        if re.search(r'(CE|PE)\d+$', inst_upper):
            return "OPTIONS"
        if any(inst_upper.startswith(f) and len(inst_upper) > len(f)
               for f in self.INDEX_FUTURES):
            return "INDEX_FUTURES"
        if any(inst_upper.startswith(c) and len(inst_upper) > len(c)
               for c in self.COMMODITY_FUTURES):
            return "COMMODITY_FUTURES"
        # Stock futures: ends with FUT (standard) OR has month+YY pattern at end (NSE format)
        if inst_upper.endswith("FUT"):
            return "STOCK_FUTURES"
        if re.search(r'(SEP|OCT|NOV|DEC|JAN|AUG|JUL)(26|27)FUT$', inst_upper):
            return "STOCK_FUTURES"
        if re.search(r'(SEP|OCT|NOV|DEC|JAN|AUG|JUL)(26|27)$', inst_upper):
            return "STOCK_FUTURES"
        return "CASH"

    def _resolve_futures(self, inst: str) -> str:
        """
        Convert base symbol to current month futures contract.
        e.g. 'ICICIBANK' -> 'ICICIBANKSEP26', 'NIFTY' -> 'NIFTY26SEPFUT'
        """
        inst_upper = inst.upper()
        exp = self.current_expiry
        # Already a full contract
        if any(x in inst_upper for x in ["SEP26", "OCT26", "NOV26", "DEC26",
                                          "JAN27", "AUG26", "JUL26", "FUT"]):
            return inst.upper()
        # Index futures: NIFTY -> NIFTY26SEPFUT
        for idx in self.INDEX_FUTURES:
            if inst_upper.startswith(idx):
                yr = exp[-2:]
                month = exp[:3]
                return f"{idx.upper()}{yr}{month}FUT"
        # Commodity futures: GOLD -> GOLD26SEPFUT
        for c in self.COMMODITY_FUTURES:
            if inst_upper.startswith(c):
                yr = exp[-2:]
                month = exp[:3]
                return f"{c.upper()}{yr}{month}FUT"
        # Stock futures: ICICIBANK -> ICICIBANKSEP26
        yr = exp[-2:]
        month = exp[:3]
        return f"{inst_upper}{month}{yr}FUT"

    # ── Live Trade Tracking ────────────────────────────────────────────────────

    def _add_live_trade(self, order: dict):
        """Add a live trade to the tracking list."""
        self._live_trades.append(order)
        logger.info(f"[LIVE] Trade recorded: {order.get('instrument')} {order.get('side')} {order.get('quantity')}lots @ {order.get('entry_price')}")

    def connect_broker(self, name: str) -> bool:
        """Manually connect a broker by name."""
        if name not in self.brokers:
            logger.error(f"Unknown broker: {name}")
            return False
        result = self.brokers[name].connect()
        if result:
            self._sync_nfo_instruments()  # Refresh NFO list with new broker
            self.broadcast_state()
        return result

    # ── Strategy setup ────────────────────────────────────────────────────────

    # ── Watchlist persistence ────────────────────────────────────────────────

    def _watchlist_path(self) -> Path:
        """Path to the watchlist persistence file."""
        return BASE_DIR / "data" / "watchlist.json"

    def _save_watchlist(self):
        """Save current watchlist instruments to disk."""
        try:
            # Only save instruments that are NOT from config.INSTRUMENTS
            # (those are already persistent via the config file)
            config_keys = set(config.INSTRUMENTS.keys())
            saved = {}
            for inst, strat_data in self.strategies.items():
                if inst in config_keys:
                    continue
                saved[inst] = {
                    "strategy":       strat_data.get("config", {}).get("strategy", "SAR_TOP_BOTTOM"),
                    "strategy_params": strat_data.get("config", {}).get("strategy_params", {}),
                    "broker_name":    strat_data.get("broker_name", "MSTOCK"),
                    "enabled":        strat_data.get("enabled", True),
                }
            self._watchlist_path().parent.mkdir(parents=True, exist_ok=True)
            with open(self._watchlist_path(), "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)
            logger.info(f"[PERSIST] Saved {len(saved)} watchlist instrument(s) to {self._watchlist_path()}")
        except Exception as e:
            logger.error(f"[PERSIST] Failed to save watchlist: {e}")

    def _load_watchlist(self):
        """Restore watchlist instruments from disk."""
        path = self._watchlist_path()
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if not saved:
                return
            loaded = 0
            for inst, info in saved.items():
                if inst in self.strategies:
                    continue  # Already loaded from config
                params = info.get("strategy_params", {})
                strat = SARTopBottomStrategy(inst, params)
                self.strategies[inst] = {
                    "strategy":      strat,
                    "config": {
                        "strategy":        info.get("strategy", "SAR_TOP_BOTTOM"),
                        "strategy_params": params,
                        "broker":         info.get("broker_name", "MSTOCK"),
                        "data_source":    "yahoo",
                    },
                    "broker_name": info.get("broker_name", "MSTOCK"),
                    "enabled":     info.get("enabled", True),
                }
                # Also register in the in-memory watchlist registry
                self._watchlist[inst] = info
                loaded += 1
                logger.info(f"[PERSIST] Restored watchlist instrument: {inst}")
            if loaded:
                logger.info(f"[PERSIST] Loaded {loaded} instrument(s) from watchlist file")
        except Exception as e:
            logger.error(f"[PERSIST] Failed to load watchlist: {e}")

    def _apply_strategy(self, inst: str, strategy_name: str, params: dict):
        """Apply a strategy to an instrument (internal helper)."""
        strategy_type = strategy_name  # "SAR_TOP_BOTTOM" or "TOP_BOTTOM_2"
        if strategy_type == "SAR_TOP_BOTTOM":
            strat = SARTopBottomStrategy(inst, params)
        elif strategy_type == "TOP_BOTTOM_2":
            strat = TopBottom2Strategy(inst, params)
        else:
            # Default to SAR Top-Bottom
            strat = SARTopBottomStrategy(inst, params)

        self.strategies[inst] = {
            "strategy":      strat,
            "config": {
                "strategy":         strategy_type,
                "strategy_params":  params,
                "broker":          "MSTOCK",
                "data_source":     "yahoo",
            },
            "broker_name": "MSTOCK",
            "enabled":     params.get("enabled", True),
        }
        logger.info(f"[WATCHLIST] Applied {strategy_type} to {inst}")

    def _remove_strategy(self, inst: str):
        """Remove strategy for an instrument."""
        if inst in self.strategies:
            del self.strategies[inst]
            logger.info(f"[WATCHLIST] Removed strategy for {inst}")

    def _init_strategies(self):
        # Load from config first
        for inst_key, inst_cfg in config.INSTRUMENTS.items():
            if not inst_cfg.get("enabled", True):
                continue

            strategy_name = inst_cfg.get("strategy", "SAR_TOP_BOTTOM")
            params        = inst_cfg.get("strategy_params", {})

            if strategy_name == "SAR_TOP_BOTTOM":
                strat = SARTopBottomStrategy(inst_key, params)
                self.strategies[inst_key] = {
                    "strategy":    strat,
                    "config":      inst_cfg,
                    "broker_name": inst_cfg.get("broker", "MSTOCK"),
                    "enabled":     inst_cfg.get("strategy_params", {}).get("enabled", True),
                }
                logger.info(
                    f"Strategy loaded: {inst_key} -> {strategy_name} "
                    f"with params {params}"
                )

        # Restore dashboard-added instruments from previous session
        self._load_watchlist()

    # ── Broker access ────────────────────────────────────────────────────────

    def _get_broker_for_instrument(self, instrument: str) -> Optional[AbstractBroker]:
        inst_cfg = config.INSTRUMENTS.get(instrument, {})
        broker_name = inst_cfg.get("broker", "MSTOCK")
        return self.brokers.get(broker_name)

    # ── Yahoo Finance free data provider ─────────────────────────────────────

    _YF_SYMBOLS = {
        "BANKNIFTY26SEPFUT": "^NSEBANK",
        "NIFTY26SEPFUT":     "^NSEI",
        # Hindustan Aeronautics Ltd — NSE scrip: HAL (not HALE)
        "HALESEP26":         "HAL.NS",
    }

    def _resolve_yf_symbol(self, instrument: str) -> str:
        """Resolve Yahoo Finance symbol for any instrument.
        Examples:
          BANKNIFTY26SEPFUT  -> ^NSEBANK
          NIFTY26SEPFUT      -> ^NSEI
          ICICIBANKSEP26     -> ICICIBANK.NS
          HDFCBANK26SEPFUT   -> HDFCBANK.NS
          NATIONALUM26SEPFUT -> NATIONALUM.NS
        """
        if instrument in self._YF_SYMBOLS:
            return self._YF_SYMBOLS[instrument]
        import re
        # Remove any expiry suffix: SEP26, OCT26, NOV26, DEC26, etc. (with or without FUT)
        # Pattern: 2-digit year + 3-letter month (SEP26) OR 3-letter month + 2-digit year (26SEP)
        base = re.sub(r'(SEPFUT|FUT|26SEPFUT|26FUT|SEPFUT-EQ|EQ)$', '', instrument)  # strip FUT/EQ suffix
        base = re.sub(r'(SEP|OCT|NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG)\d{2}$', '', base)  # SEP26, OCT26
        base = re.sub(r'^\d{2}(SEP|OCT|NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG)', '', base)  # 26SEP
        base = base.rstrip('.-_')
        return base + ".NS"

    def _fetch_yahoo_candles(self, instrument: str) -> List[OHLC]:
        """Free live candles from Yahoo Finance (no API key needed)."""
        import urllib.request, json

        symbol = self._resolve_yf_symbol(instrument)
        try:
            now = int(_dt.now().timestamp())
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                f"?interval=5m&range=5d"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            result = data.get("chart", {}).get("result", [{}])[0]
            ts_list = result.get("timestamp", [])
            ohlc    = result.get("indicators", {}).get("quote", [{}])[0]

            if not ts_list:
                return []

            candles = []
            for i, ts in enumerate(ts_list):
                o = ohlc.get("open", [None])[i]
                h = ohlc.get("high", [None])[i]
                l = ohlc.get("low", [None])[i]
                c = ohlc.get("close", [None])[i]
                v = ohlc.get("volume", [None])[i] if i < len(ohlc.get("volume", [])) else 0
                if None not in (o, h, l, c):
                    candles.append(OHLC(
                        timestamp=int(ts), open=float(o), high=float(h),
                        low=float(l), close=float(c), volume=int(v or 0),
                    ))
            return candles[-500:]   # Last 500 candles (covers ~2 days of 5m candles)
        except Exception as e:
            logger.debug(f"Yahoo Finance failed for {instrument}: {e}")
            return []

    # ── Tick loop ─────────────────────────────────────────────────────────────

    def _is_market_hours(self) -> bool:
        now = _dt.now()
        t   = now.time()
        # NSE: 09:15 to 15:30 IST
        market_open = dtime(9, 15)
        market_close = dtime(15, 30)
        is_weekday  = now.weekday() < 5
        return is_weekday and market_open <= t <= market_close

    def _fetch_and_process(self):
        """Fetch latest candles and run strategy on each instrument."""
        for inst_key, strat_data in self.strategies.items():
            strat  = strat_data["strategy"]
            broker = self._get_broker_for_instrument(inst_key)

            try:
                candles = None

                # Try broker first (live data)
                if broker and broker.is_connected():
                    to_ts   = int(_dt.now().timestamp())
                    from_ts = to_ts - (50 * 15 * 60)
                    candles = broker.get_candles(inst_key, "15m", from_ts, to_ts)

                # Fall back to Yahoo Finance (free, no auth needed)
                if not candles:
                    candles = self._fetch_yahoo_candles(inst_key)

                if not candles:
                    continue

                # Feed candles to strategy (last 100 to ensure sufficient lookback)
                for candle in candles[-100:]:
                    strat.add_candle(candle)

                # Run strategy
                signal = strat.compute()
                if signal:
                    # ── Deduplicate: only fire each signal type once per instrument ──
                    dedup_key = f"{inst_key}:{signal.type.value}"
                    now_ts    = time.time()
                    last_fired = self._signal_fired.get(dedup_key, 0)
                    if now_ts - last_fired < 120:   # Ignore if same signal within 2 mins
                        logger.debug(f"SIGNAL deduplicated [{inst_key}]: {signal.type.value}")
                        signal = None

                    self._signal_fired[dedup_key] = now_ts

                if signal:
                    # Attach current strategy params (SL%, BE%) to signal for entry use
                    signal.metadata = signal.metadata or {}
                    signal.metadata["sl_pct"] = strat.params.get("stop_pct", 3.0)
                    signal.metadata["be_pct"] = strat.params.get("be_pct",  2.5)
                    self._process_signal(signal, strat)
                    self._signals.append({
                        "time":   _dt.now().isoformat(),
                        "inst":   inst_key,
                        "type":   signal.type.value,
                        "price":  signal.price,
                        "reason": signal.reason,
                    })
                    logger.info(f"SIGNAL [{inst_key}]: {signal.type.value} @ {signal.price:.2f} | {signal.reason}")

            except Exception as e:
                logger.error(f"Error processing {inst_key}: {e}")

        # Broadcast to dashboard via async thread-safe call
        if self._loop:
            self._loop.run_coroutine_threadsafe(self.broadcast_state(), self._loop)

    def _process_signal(self, signal, strat):
        """Execute paper or live trade from signal (per-instrument)."""
        inst = signal.instrument
        pos  = self._positions.get(inst)   # per-instrument position

        if signal.type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
            if pos is not None:
                # Close existing position first (reversal)
                exit_reason = "reversal_entry"
                self._exit_instrument(inst, reason=exit_reason)

            side = "LONG" if signal.type == SignalType.LONG_ENTRY else "SHORT"
            trade_id = self._enter_instrument(signal)
            if trade_id:
                pos_after = self._positions.get(inst)
                if pos_after:
                    strat.on_entry(side, pos_after["entry_price"], pos_after.get("entry_idx", 0))
                    strat.set_position(side, pos_after["entry_price"])
                self._push_trade_event("ENTRY", signal, trade_id)

        elif signal.type in (SignalType.LONG_EXIT, SignalType.SHORT_EXIT):
            reason = signal.metadata.get("exit_reason", "stop_hit")
            trade = self._exit_instrument(inst, reason=reason)
            strat.clear_position()
            if trade:
                self._push_trade_event("EXIT", signal, trade.trade_id, pnl=trade.pnl)

        elif signal.type in (SignalType.REVERSE_LONG, SignalType.REVERSE_SHORT):
            reason = signal.metadata.get("exit_reason", "signal_reversal")
            closed_trade = self._exit_instrument(inst, reason=f"REVERSE: {reason}")
            strat.clear_position()
            if closed_trade:
                self._push_trade_event("REVERSAL", signal, closed_trade.trade_id, pnl=closed_trade.pnl)
            # Open the new reversed position — carry forward the realized P&L
            realized_pnl = closed_trade.pnl if closed_trade else 0.0
            side = "LONG" if signal.type == SignalType.REVERSE_LONG else "SHORT"
            trade_id = self._enter_instrument(signal, realized_pnl=realized_pnl)
            if trade_id:
                pos_after = self._positions.get(inst)
                if pos_after:
                    strat.on_entry(side, pos_after["entry_price"], pos_after.get("entry_idx", 0))
                    strat.set_position(side, pos_after["entry_price"])
                self._push_trade_event("ENTRY", signal, trade_id)

    def _enter_instrument(self, signal, realized_pnl: float = 0.0) -> Optional[str]:
        """Open a position for a specific instrument. Returns trade_id or None."""
        inst  = signal.instrument
        price = signal.price
        qty   = signal.quantity or self.paper.lot_size

        if signal.type == SignalType.LONG_ENTRY:
            fill_price = round(price * (1 + self.paper.slippage_pct / 100), 2)
            side       = "LONG"
        elif signal.type == SignalType.SHORT_ENTRY:
            fill_price = round(price * (1 - self.paper.slippage_pct / 100), 2)
            side       = "SHORT"
        else:
            return None

        brokerage = self.paper.brokerage_per_lot * qty
        self.paper.capital -= brokerage

        # Entry condition from SAR strategy signal
        entry_cond = signal.reason or (
            f"Crossed Top {signal.metadata.get('swing_top', '?')}"
            if side == "LONG"
            else f"Below Bottom {signal.metadata.get('swing_bottom', '?')}"
        )

        sl_pct   = signal.metadata.get("sl_pct", 3.0)
        sl_price = fill_price * (1 - sl_pct/100) if side == "LONG" else fill_price * (1 + sl_pct/100)

        # Get current strategy params for this instrument
        strat_entry = self.strategies.get(inst, {})
        strat_params = strat_entry.get("config", {}).get("strategy_params", {})

        self._positions[inst] = {
            "side":           side,
            "entry_price":    fill_price,
            "entry_condition": entry_cond,
            "entry_time":     _dt.now().isoformat(),
            "qty":            qty,
            "sl_mode":        "auto",         # auto | manual
            "sl_pct":         sl_pct,         # used when sl_mode=auto
            "sl_manual_type": "price",         # price | pct
            "sl_manual_pct":  None,            # manual pct override
            "sl_manual_price":None,            # manual price override
            "current_sl":      sl_price,
            "be_pct":           strat_params.get("be_pct", 2.5),
            "pyramiding_mode":  "auto",         # auto | manual
            "pyramiding_on":    False,           # ON/OFF toggle
            "pyramiding_lots":  1,              # extra lots (0=only entry lot)
            "exit_mode":        "auto",          # auto | manual
            "exit_manual_type": "price",         # price | pct
            "exit_manual_val":  0,               # manual exit trigger value
            "rollover":        True,             # auto rollover at expiry
            "realized_pnl":    realized_pnl,     # locked P&L from previous leg (after reversal)
            "be_done":         False,
            "pyramids":        0,
        }
        self.paper._trade_counter += 1
        trade_id = f"PAPER-{_dt.now().strftime('%Y%m%d')}-{self.paper._trade_counter:04d}"
        logger.info(
            f"[PAPER] Entry {side}: {inst} × {qty} @ ₹{fill_price:.2f} "
            f"| Condition: {entry_cond} | SL: ₹{sl_price:.2f} ({sl_pct}%) "
            f"| Capital: ₹{self.paper.capital:,.2f}"
        )
        return trade_id

    def _exit_instrument(self, inst: str, reason: str,
                         exit_price: float = None) -> Optional[Any]:
        """Close position for a specific instrument. Returns PaperTrade or None."""
        pos = self._positions.get(inst)
        if not pos:
            return None

        price    = exit_price or pos["current_sl"]
        fill_side = "SELL" if pos["side"] == "LONG" else "BUY"
        slip     = self.paper.slippage_pct / 100
        fill_price = round(price * (1 + slip if fill_side == "BUY" else -slip), 2)

        mult  = 1 + pos["pyramids"]
        qty   = pos["qty"] * mult
        if pos["side"] == "LONG":
            pnl_raw = (fill_price - pos["entry_price"]) * qty
        else:
            pnl_raw = (pos["entry_price"] - fill_price) * qty

        brokerage = self.paper.brokerage_per_lot * mult
        pnl       = pnl_raw - brokerage
        self.paper.capital += pnl

        self.paper._trade_counter += 1
        trade_id = f"PAPER-{_dt.now().strftime('%Y%m%d')}-{self.paper._trade_counter:04d}"
        trade = self.paper.PaperTrade(
            trade_id=trade_id,
            instrument=inst,
            direction=pos["side"],
            entry_date=pos["entry_time"],
            entry_price=pos["entry_price"],
            exit_date=_dt.now().isoformat(),
            exit_price=fill_price,
            quantity=qty,
            pnl=round(pnl, 2),
            pyramids=pos["pyramids"],
            reason=reason,
            capital_after=round(self.paper.capital, 2),
        )
        self.paper.trades.append(trade)
        del self._positions[inst]

        # Also remove from strategy's position state
        strat = self.strategies.get(inst, {}).get("strategy")
        if strat:
            strat.clear_position()
        logger.info(
            f"[PAPER] Exit {pos['side']}: {inst} × {qty} @ ₹{fill_price:.2f} "
            f"| P&L: ₹{pnl:,.2f} | [{reason}] | Capital: ₹{self.paper.capital:,.2f}"
        )
        return trade

    def _push_trade_event(self, event_type: str, signal, trade_id: str, pnl: float = None):
        """Push a trade event to the dashboard in real-time."""
        event = {
            "type":    "trade_event",
            "event":   event_type,
            "trade_id": trade_id,
            "inst":    signal.instrument,
            "signal":  signal.type.value,
            "price":   signal.price,
            "reason":  signal.reason,
            "pnl":     pnl,
            "time":    _dt.now().isoformat(),
        }
        if self._loop:
            msg = json.dumps(event)
            clients = list(self._ws_clients)
            if self._ws_lock is None:
                self._ws_lock = asyncio.Lock()
            async def _send():
                async with self._ws_lock:
                    for ws in clients:
                        try:
                            await ws.send(msg)
                        except Exception:
                            pass
            asyncio.run_coroutine_threadsafe(_send(), self._loop)
        logger.info(f"TRADE EVENT: [{event_type}] {signal.instrument} @ {signal.price:.2f} | P&L: {pnl}")

    # ── Background thread ─────────────────────────────────────────────────────

    def start(self):
        if self._running:
            logger.warning("Engine already running")
            return

        self._running = True
        self._tick_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._tick_thread.start()
        logger.info("Trading engine started")

    def stop(self):
        self._running = False
        if self._tick_thread:
            self._tick_thread.join(timeout=5)
        for broker in self.brokers.values():
            broker.disconnect()
        logger.info("Trading engine stopped")

    def _run_loop(self):
        while self._running:
            if self._is_market_hours():
                logger.info("TICK: fetching data...")
                self._fetch_and_process()
            time.sleep(self._tick_interval)

    # ── WebSocket clients ─────────────────────────────────────────────────────

    async def add_client(self, ws):
        if self._ws_lock is None:
            self._ws_lock = asyncio.Lock()
        async with self._ws_lock:
            self._ws_clients.append(ws)

    async def remove_client(self, ws):
        if self._ws_lock is None:
            self._ws_lock = asyncio.Lock()
        async with self._ws_lock:
            if ws in self._ws_clients:
                self._ws_clients.remove(ws)

    async def broadcast_state(self):
        """Push full platform state to all connected dashboards."""
        try:
            state = self._build_state()
            logger.info(f"[BROADCAST] _build_state OK | strategies={len(self.strategies)} | clients={len(self._ws_clients)}")
        except Exception as e:
            logger.error(f"[BROADCAST] _build_state FAILED: {e}", exc_info=True)
            return
        try:
            msg = json.dumps({"type": "state", "data": state})
        except Exception as e:
            logger.error(f"[BROADCAST] JSON serialize FAILED: {e}", exc_info=True)
            return
        logger.info(f"[BROADCAST] Sending state ({len(msg)} bytes) to {len(self._ws_clients)} client(s)")

        clients = list(self._ws_clients)
        if self._ws_lock is None:
            self._ws_lock = asyncio.Lock()
        async with self._ws_lock:
            dead = []
            for ws in clients:
                try:
                    await ws.send(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._ws_clients.remove(ws)

    def _build_state(self) -> dict:
        """Build the full state object for the dashboard."""
        paper_status = self.paper.get_status()
        broker_status = {}
        for name, b in self.brokers.items():
            status = {"connected": b.is_connected()}
            if b.is_connected():
                status["account"] = asdict(b.get_account_info())
                try:
                    positions = b.get_positions()
                    status["positions"] = [
                        {"instrument": p.instrument, "side": p.side.value,
                         "quantity": p.quantity, "avg_price": p.avg_price,
                         "unrealized_pnl": p.unrealized_pnl}
                        for p in positions
                    ]
                except Exception:
                    status["positions"] = []
            broker_status[name] = status

        # Get live quotes — from broker, or Yahoo Finance fallback
        # Merge config instruments + dashboard-added strategies so LTP works for all watchlist entries
        quotes = {}
        all_instrument_keys = set(config.INSTRUMENTS.keys()) | set(self.strategies.keys())
        for inst_key in all_instrument_keys:
            broker = self._get_broker_for_instrument(inst_key)
            if broker and broker.is_connected():
                try:
                    q = broker.get_quote(inst_key)
                    # Only use broker quote if it has a valid price
                    if q and q.last_price and q.last_price > 0:
                        quotes[inst_key] = {
                            "last_price": q.last_price,
                            "bid":        q.bid,
                            "ask":        q.ask,
                            "volume":     q.volume,
                            "timestamp":  q.timestamp,
                        }
                except Exception:
                    pass
            # Yahoo Finance quote fallback (used when broker is not connected OR broker has no quote)
            try:
                sym = self._resolve_yf_symbol(inst_key)
                import urllib.request, json
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                result = data.get("chart", {}).get("result", [{}])[0]
                meta  = result.get("meta", {})
                price = float(meta.get("regularMarketPrice", 0))
                if price > 0:
                    quotes[inst_key] = {
                        "last_price": price,
                        "bid":        price,
                        "ask":        price,
                        "volume":     int(meta.get("regularMarketVolume", 0)),
                        "timestamp":  int(meta.get("regularMarketTime", 0)),
                    }
                    logger.info(f"[QUOTE] {inst_key} -> {sym}: Rs.{price}")
                else:
                    logger.warning(f"[QUOTE] {inst_key} -> {sym}: no market price")
            except Exception as ex:
                logger.warning(f"[QUOTE] {inst_key}: YF fetch failed - {ex}")

        # ── Compute closed P&L per instrument ──────────────────────────────────
        closed_pnl_per_inst: Dict[str, float] = {}
        for t in self.paper.trades:
            inst = t.instrument
            closed_pnl_per_inst[inst] = closed_pnl_per_inst.get(inst, 0) + t.pnl

        # ── Per-instrument positions ─────────────────────────────────────────
        positions_state: Dict[str, dict] = {}
        for inst, pos in self._positions.items():
            ltp = (quotes.get(inst) or {}).get("last_price", pos["entry_price"])
            mult  = 1 + pos.get("pyramids", 0)
            qty   = pos["qty"] * mult
            if pos["side"] == "LONG":
                unreal_pnl = (ltp - pos["entry_price"]) * qty
            else:
                unreal_pnl = (pos["entry_price"] - ltp) * qty

            # Compute auto SL based on day
            entry_dt  = pos.get("entry_time", "")
            days_in   = 1
            if entry_dt:
                try:
                    days_in = max(1, (_dt.now() - _dt.fromisoformat(entry_dt)).days)
                except Exception:
                    pass

            sl_pct = pos.get("sl_pct", 1.5)
            be_pct = pos.get("be_pct", 2.5)
            entry_p = pos["entry_price"]

            if pos["side"] == "LONG":
                be_price  = entry_p * (1 + be_pct / 100)
                pct3_price = entry_p * 0.97
                sl_auto = be_price if days_in >= 2 else entry_p * (1 - sl_pct / 100)
                if days_in >= 2:
                    sl_auto = min(be_price, pct3_price)
            else:
                be_price  = entry_p * (1 - be_pct / 100)
                pct3_price = entry_p * 1.03
                sl_auto = entry_p * (1 + sl_pct / 100)
                if days_in >= 2:
                    sl_auto = max(be_price, pct3_price)

            current_sl = pos["current_sl"]
            if pos["sl_mode"] == "auto":
                current_sl = round(sl_auto, 2)
            elif pos["sl_manual_price"]:
                current_sl = pos["sl_manual_price"]

            positions_state[inst] = {
                **pos,
                "unrealized_pnl": round(unreal_pnl, 2),
                "ltp":             ltp,
                "days_in_trade":   days_in,
                "sl_auto_price":   round(sl_auto, 2),
                "current_sl":       current_sl,
            }

        return {
            "mode":          self.mode,
            "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%S"),
            "market_hours":  self._is_market_hours(),
            "paper":         paper_status,
            "brokers":       broker_status,
            "quotes":        quotes,
            "strategies": {
                k: {
                    "enabled":           v["enabled"],
                    "params":            v["strategy"].params,
                    "_pending_signal":   getattr(v["strategy"], "_pending_signal", False),
                    "_pending_entry":    getattr(v["strategy"], "_pending_entry", 0.0),
                    "_position_open":    v["strategy"]._position_open,
                    "_position_side":    v["strategy"]._position_side,
                    "_entry_price":      v["strategy"]._entry_price,
                    "_closed_pnl":       closed_pnl_per_inst.get(k, 0),
                    # Swing points for SAR Top-Bottom strategy
                    "_recent_tops":      [(p, float(t)) for _, p, t in getattr(v["strategy"], "_recent_tops", [])],
                    "_recent_bots":      [(p, float(t)) for _, p, t in getattr(v["strategy"], "_recent_bots", [])],
                }
                for k, v in self.strategies.items()
            },
            "positions":       positions_state,
            "signals":         self._signals[-20:],
            "trades":          self.paper.get_trade_history()[-50:],
            "segment_pnl":     self.paper.get_segment_pnl(),
            "live_trades":     self._live_trades[-50:],
            "available_futures": list(self._available_futures),
            "current_expiry":  self.current_expiry,
            "watchlist":       list(self._watchlist.keys()),
        }

    async def handle_dashboard_message(self, data: dict, ws):
        """Handle commands from dashboard."""
        cmd = data.get("command", "")

        if cmd == "get_state":
            await ws.send(json.dumps({
                "type": "state",
                "data": self._build_state()
            }))

        elif cmd == "execute_trade":
            # Manual HIT from watchlist — PAPER or LIVE execution
            instrument = data.get("instrument", "")
            exec_price = float(data.get("price", 0))
            sl = data.get("sl")
            sl_price = float(sl) if sl else None
            exec_mode = data.get("mode", "PAPER")
            strategy = data.get("strategy", "MANUAL")
            quantity = int(data.get("quantity", 1))

            # Resolve futures contract to current month
            inst = self._resolve_futures(instrument)
            # Determine direction from price
            quote = None
            for bname, broker in self.brokers.items():
                if broker.is_connected():
                    try: quote = broker.get_quote(inst); break
                    except: pass

            ltp = quote.last_price if quote else exec_price
            direction = "LONG" if ltp >= exec_price else "SHORT"

            result = {"success": False, "mode": exec_mode, "instrument": inst,
                      "direction": direction, "message": ""}

            if exec_mode == "PAPER":
                # Paper trade via paper engine
                sig = Signal(
                    type=SignalType.LONG_ENTRY if direction == "LONG" else SignalType.SHORT_ENTRY,
                    instrument=inst,
                    strategy_name=strategy,
                    price=exec_price,
                    stop_loss=sl_price,
                    quantity=quantity,
                    reason="Manual HIT from watchlist",
                )
                trade_id = self.paper.enter(sig)
                if trade_id:
                    result["success"] = True
                    result["message"] = f"PAPER {direction} @ ₹{exec_price:.2f}"
                    result["trade_id"] = trade_id
                else:
                    result["message"] = "Entry failed — position already open"
            else:
                # LIVE trade via broker
                broker = None
                for bname, b in self.brokers.items():
                    if b.is_connected():
                        broker = b; break

                if not broker:
                    result["message"] = "No broker connected for LIVE trading"
                else:
                    order_side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
                    order_type = OrderType.LIMIT if exec_price else OrderType.MARKET
                    try:
                        order = broker.place_order(
                            instrument=inst,
                            side=order_side,
                            quantity=quantity,
                            order_type=order_type,
                            price=exec_price if exec_price else None,
                        )
                        if order.status == OrderStatus.FILLED or order.average_price:
                            self._add_live_trade({
                                "trade_id": order.order_id,
                                "instrument": inst,
                                "segment": self._infer_segment(inst),
                                "direction": direction,
                                "entry_date": _dt.now().isoformat(),
                                "entry_price": order.average_price or exec_price,
                                "exit_price": None,
                                "quantity": quantity,
                                "pnl": None,
                                "reason": "Manual HIT from watchlist",
                                "status": "OPEN",
                                "sl": sl_price,
                            })
                            result["success"] = True
                            result["message"] = f"LIVE {direction} {inst} @ ₹{order.average_price or exec_price:.2f} | Order: {order.order_id}"
                        else:
                            result["message"] = f"Order placed: {order.order_id} | Status: {order.status.value}"
                    except Exception as e:
                        result["message"] = f"Order error: {str(e)}"

            await self.broadcast_state()
            await ws.send(json.dumps({"type": "notification", **result}))

        elif cmd == "signal_trade":
            # HIT from watchlist → fire strategy signal and auto-enter
            instrument = data.get("instrument", "")
            mode = data.get("mode", "PAPER")
            inst = self._resolve_futures(instrument)
            result = {"success": False, "instrument": inst, "mode": mode, "message": ""}

            # Find strategy by instrument name (not watchlist sysId)
            strat_entry = None
            actual_inst = inst
            for k in self.strategies:
                if inst.upper() == k.upper() or instrument.upper() in k.upper():
                    strat_entry = self.strategies[k]
                    actual_inst = k
                    break

            if not strat_entry:
                result["message"] = f"No strategy found for {inst} — apply strategy first"
                await ws.send(json.dumps({"type": "notification", **result}))
                return

            # Fetch latest candles for this instrument
            strat = strat_entry["strategy"]
            candles = []
            broker = next((b for b in self.brokers.values() if b.is_connected()), None)
            if broker:
                try:
                    to_ts   = int(_dt.now().timestamp())
                    from_ts = to_ts - (300 * 15 * 60)  # last 300 x 15m candles (~75 hrs)
                    candles = broker.get_candles(actual_inst, "15m", from_ts, to_ts)
                except Exception as e:
                    logger.warning(f"[signal_trade] candle fetch error: {e}")
            if not candles:
                # Yahoo gives 5-min candles — fetch 5 days for ample lookback
                candles = self._fetch_yahoo_candles(actual_inst)
                if candles:
                    logger.info(f"[signal_trade] Using {len(candles)} Yahoo candles for {actual_inst}")

            if not candles:
                result["message"] = f"Could not fetch candles for {inst}"
                await ws.send(json.dumps({"type": "notification", **result}))
                return

            # Load candles into strategy so compute() has data to work with
            for candle in candles:
                strat.add_candle(candle)

            # Sync strategy position state from engine before computing
            engine_pos = self._positions.get(actual_inst)
            if engine_pos:
                strat.set_position(engine_pos["direction"], engine_pos["entry_price"])
            else:
                strat.clear_position()

            signal = None
            try:
                signal = strat.compute()
            except Exception as e:
                logger.warning(f"[signal_trade] compute error for {actual_inst}: {e}")

            if not signal or signal.type.name in ("NO_SIGNAL", "LONG_EXIT", "SHORT_EXIT"):
                result["message"] = f"No signal for {inst} — rules not triggered yet"
                await ws.send(json.dumps({"type": "notification", **result}))
                return

            entry_price = signal.price
            sl_price = signal.stop_loss
            direction = "LONG" if signal.type.name in ("LONG_ENTRY", "REVERSE_LONG") else "SHORT"
            sig_type_label = "BUY" if direction == "LONG" else "SELL"

            if mode == "PAPER":
                trade = self.paper.enter(signal)
                if trade:
                    # Sync engine position state so dashboard shows the open position
                    self._positions[actual_inst] = {
                        "side":            trade.direction,
                        "entry_price":      trade.entry_price,
                        "entry_condition":  trade.reason or signal.reason,
                        "entry_time":       trade.entry_date,
                        "qty":              trade.quantity,
                        "sl_mode":          "auto",
                        "sl_pct":           signal.metadata.get("sl_pct", 3.0),
                        "sl_manual_type":   "price",
                        "sl_manual_pct":    None,
                        "sl_manual_price":  None,
                        "current_sl":       signal.stop_loss or (trade.entry_price * (0.97 if direction == "LONG" else 1.03)),
                        "be_pct":           signal.metadata.get("be_pct", 2.5),
                        "pyramiding_mode":  "auto",
                        "pyramiding_on":    False,
                        "pyramiding_lots":  1,
                        "exit_mode":        "auto",
                        "exit_manual_type": "price",
                        "exit_manual_val":  0,
                        "rollover":         True,
                        "realized_pnl":     0.0,
                        "be_done":          False,
                        "pyramids":         0,
                    }
                    # Sync strategy position state
                    strat.set_position(direction, trade.entry_price)
                    result["success"] = True
                    result["message"] = f"📋 PAPER {sig_type_label} {inst} @ ₹{trade.entry_price:.2f}"
                    result["trade_id"] = trade.trade_id
                    self._push_trade_event("ENTRY", signal, trade.trade_id)
                else:
                    result["message"] = "PAPER entry failed — position already open"
            else:
                broker = next((b for b in self.brokers.values() if b.is_connected()), None)
                if not broker:
                    result["message"] = "No broker connected for LIVE trading"
                else:
                    try:
                        order_side = OrderSide.BUY if direction == "LONG" else OrderSide.SELL
                        order = broker.place_order(
                            instrument=actual_inst, side=order_side,
                            quantity=signal.quantity or 1,
                            order_type=OrderType.MARKET,
                        )
                        fill_price = order.average_price or entry_price
                        self._add_live_trade({
                            "trade_id": order.order_id,
                            "instrument": actual_inst,
                            "segment": self._infer_segment(actual_inst),
                            "direction": direction,
                            "entry_date": _dt.now().isoformat(),
                            "entry_price": fill_price,
                            "exit_price": None,
                            "quantity": signal.quantity or 1,
                            "pnl": None,
                            "reason": f"Signal: {sig_type_label} by {signal.strategy_name}",
                            "status": "OPEN",
                            "sl": sl_price,
                        })
                        # Also sync engine position for dashboard display
                        self._positions[actual_inst] = {
                            "side": direction, "entry_price": fill_price,
                            "entry_condition": f"Signal: {sig_type_label}", "entry_time": _dt.now().isoformat(),
                            "qty": signal.quantity or 1, "sl_mode": "auto",
                            "sl_pct": signal.metadata.get("sl_pct", 3.0),
                            "sl_manual_type": "price", "sl_manual_pct": None,
                            "sl_manual_price": None,
                            "current_sl": sl_price or (fill_price * (0.97 if direction == "LONG" else 1.03)),
                            "be_pct": signal.metadata.get("be_pct", 2.5),
                            "pyramiding_mode": "auto", "pyramiding_on": False,
                            "pyramiding_lots": 1, "exit_mode": "auto",
                            "exit_manual_type": "price", "exit_manual_val": 0,
                            "rollover": True, "realized_pnl": 0.0,
                            "be_done": False, "pyramids": 0,
                        }
                        strat.set_position(direction, fill_price)
                        result["success"] = True
                        result["message"] = f"⚡ LIVE {sig_type_label} {actual_inst} @ ₹{fill_price:.2f}"
                    except Exception as e:
                        result["message"] = f"Order error: {str(e)}"

            await self.broadcast_state()
            await ws.send(json.dumps({"type": "notification", **result}))

        elif cmd == "hit_trade":
            # HIT from futures watchlist → auto-detect direction → enter immediately
            # No strategy rules, no signal check — pure price action entry
            instrument = data.get("instrument", "")
            mode = data.get("mode", "PAPER")
            strat_name = data.get("strategy_name", "HIT")
            quantity = int(data.get("quantity", 1))

            inst = self._resolve_futures(instrument)
            result = {"success": False, "instrument": inst, "mode": mode, "message": ""}

            # ── Step 1: Fetch candles for direction detection ─────────────────────
            candles = []
            broker = next((b for b in self.brokers.values() if b.is_connected()), None)
            if broker:
                try:
                    to_ts = int(_dt.now().timestamp())
                    from_ts = to_ts - (300 * 15 * 60)
                    candles = broker.get_candles(inst, "15m", from_ts, to_ts)
                except Exception as e:
                    logger.debug(f"[hit_trade] broker candle error: {e}")
            if not candles:
                candles = self._fetch_yahoo_candles(inst)

            if len(candles) < 5:
                result["message"] = f"Not enough candle data for {inst}"
                await ws.send(json.dumps({"type": "notification", **result}))
                return

            # ── Step 2: Auto-detect direction ────────────────────────────────────
            # Use last 20 candles to find swing high/low
            lookback = min(20, len(candles))
            recent = candles[-lookback:]
            highs = [c.high for c in recent]
            lows  = [c.low  for c in recent]
            swing_high = max(highs)
            swing_low  = min(lows)
            current_close = candles[-1].close

            # Direction: LONG if breaking above swing high, SHORT if below swing low
            direction = None
            if current_close > swing_high:
                direction = "LONG"
            elif current_close < swing_low:
                direction = "SHORT"

            if not direction:
                result["message"] = f"No hit — {inst} in range (H:₹{swing_high:.0f} L:₹{swing_low:.0f} C:₹{current_close:.0f})"
                await ws.send(json.dumps({"type": "notification", **result}))
                return

            # ── Step 3: Get entry price (LTP) ───────────────────────────────────
            entry_price = current_close  # MARKET order — use current LTP

            # ── Step 4: Execute trade ───────────────────────────────────────────
            sig_type = SignalType.LONG_ENTRY if direction == "LONG" else SignalType.SHORT_ENTRY

            if mode == "PAPER":
                sig = Signal(
                    type=sig_type,
                    instrument=inst,
                    strategy_name=strat_name,
                    price=entry_price,
                    stop_loss=None,
                    quantity=quantity,
                    reason=f"HIT auto-entry: {direction} @ ₹{entry_price:.2f}",
                )
                trade = self.paper.enter(sig)
                if trade:
                    self._positions[inst] = {
                        "side": trade.direction, "entry_price": trade.entry_price,
                        "entry_condition": sig.reason, "entry_time": trade.entry_date,
                        "qty": trade.quantity, "sl_mode": "auto", "sl_pct": 3.0,
                        "sl_manual_type": "price", "sl_manual_pct": None,
                        "sl_manual_price": None,
                        "current_sl": entry_price * (0.97 if direction == "LONG" else 1.03),
                        "be_pct": 2.5, "pyramiding_mode": "auto", "pyramiding_on": False,
                        "pyramiding_lots": 1, "exit_mode": "auto",
                        "exit_manual_type": "price", "exit_manual_val": 0,
                        "rollover": True, "realized_pnl": 0.0, "be_done": False, "pyramids": 0,
                    }
                    result["success"] = True
                    result["message"] = f"PAPER {direction} {inst} @ ₹{entry_price:.2f}"
                    result["trade_id"] = trade.trade_id
                    self._push_trade_event("ENTRY", sig, trade.trade_id)
                else:
                    result["message"] = f"PAPER entry failed — position already open for {inst}"
            else:
                broker = next((b for b in self.brokers.values() if b.is_connected()), None)
                if not broker:
                    result["message"] = "No broker connected for LIVE trading"
                else:
                    try:
                        order = broker.place_order(
                            instrument=inst,
                            side=OrderSide.BUY if direction == "LONG" else OrderSide.SELL,
                            quantity=quantity,
                            order_type=OrderType.MARKET,
                        )
                        fill_price = order.average_price or entry_price
                        self._add_live_trade({
                            "trade_id": order.order_id,
                            "instrument": inst, "segment": self._infer_segment(inst),
                            "direction": direction,
                            "entry_date": _dt.now().isoformat(),
                            "entry_price": fill_price,
                            "exit_price": None, "quantity": quantity,
                            "pnl": None,
                            "reason": f"HIT auto-entry: {direction} by {strat_name}",
                            "status": "OPEN", "sl": None,
                        })
                        result["success"] = True
                        result["message"] = f"LIVE {direction} {inst} @ ₹{fill_price:.2f}"
                        self._push_trade_event("ENTRY", Signal(type=sig_type, instrument=inst,
                            strategy_name=strat_name, price=fill_price, stop_loss=None,
                            quantity=quantity, reason=f"HIT {direction}"), order.order_id)
                    except Exception as e:
                        result["message"] = f"Order error: {str(e)}"

            await self.broadcast_state()
            await ws.send(json.dumps({"type": "notification", **result}))

        elif cmd == "exit_trade":
            # Exit a specific live or paper trade
            trade_id = data.get("trade_id", "")
            mode = data.get("mode", "PAPER")
            instrument = data.get("instrument", "")

            result = {"success": False, "message": ""}
            if mode == "PAPER":
                t = self.paper.exit(reason="manual_exit")
                if t:
                    result["success"] = True
                    result["message"] = f"PAPER exit: {t.instrument} | P&L: ₹{t.pnl:.2f}"
            else:
                broker = None
                for bname, b in self.brokers.items():
                    if b.is_connected(): broker = b; break
                if broker:
                    try:
                        order = broker.close_position(instrument)
                        result["success"] = True
                        result["message"] = f"LIVE exit: {order.order_id} | Status: {order.status.value}"
                    except Exception as e:
                        result["message"] = f"Exit error: {str(e)}"
                else:
                    result["message"] = "No broker connected"

            await self.broadcast_state()
            await ws.send(json.dumps({"type": "notification", **result}))

        elif cmd == "sync_watchlist":
            # Dashboard sends full watchlist; DASHBOARD is source of truth
            # Engine replaces its internal watchlist with whatever dashboard sends
            incoming = data.get("instruments", [])

            # Remove instruments no longer in dashboard's list
            for inst in list(self._watchlist.keys()):
                if inst not in incoming:
                    self._remove_strategy(inst)
                    del self._watchlist[inst]

            # Keep existing instruments, add new ones from dashboard
            for inst in incoming:
                if inst not in self._watchlist:
                    self._apply_strategy(inst, "SAR_TOP_BOTTOM", {})
                    self._watchlist[inst] = {
                        "strategy":        "SAR_TOP_BOTTOM",
                        "strategy_params":  {},
                    }

            self._save_watchlist()
            await self.broadcast_state()

        elif cmd == "connect_broker":
            name = data.get("broker", "")
            ok   = self.connect_broker(name)
            await self.broadcast_state()
            await ws.send(json.dumps({
                "type": "notification",
                "message": f"{name} {'connected' if ok else 'failed'}",
                "success": ok,
            }))

        elif cmd == "disconnect_broker":
            name = data.get("broker", "")
            if name in self.brokers:
                self.brokers[name].disconnect()
                await self.broadcast_state()
                await ws.send(json.dumps({
                    "type": "notification",
                    "message": f"{name} disconnected",
                    "success": True,
                }))
            else:
                await ws.send(json.dumps({
                    "type": "notification",
                    "message": f"Unknown broker: {name}",
                    "success": False,
                }))

        elif cmd == "set_mode":
            self.mode = data.get("mode", self.mode)
            await self.broadcast_state()

        elif cmd == "toggle_strategy":
            inst = data.get("instrument", "")
            if inst in self.strategies:
                self.strategies[inst]["enabled"] = data.get("enabled", True)
                await self.broadcast_state()

        elif cmd == "exit_position":
            trade = self.paper.exit(reason="manual_exit")
            await self.broadcast_state()
            await ws.send(json.dumps({
                "type": "notification",
                "message": "Position closed manually",
                "success": trade is not None,
            }))

        elif cmd == "exit_all":
            # Exit all open positions
            while self.paper.position is not None:
                self.paper.exit(reason="emergency_exit_all")
            await self.broadcast_state()
            await ws.send(json.dumps({
                "type": "notification",
                "message": "All positions closed",
                "success": True,
            }))

        elif cmd == "apply_strategy":
            # Apply a strategy from the dashboard selector (supports multiple instruments)
            strat_name   = data.get("strategyName", "Unknown")
            instruments  = data.get("instruments", [])  # list of instrument codes
            direction    = data.get("direction", "LONGSHORT")
            pyramiding   = data.get("pyramiding", "ADD")
            lot_size     = int(data.get("lotSize", 30))
            capital      = int(data.get("capital", 100000))
            category     = data.get("category", "Future")
            strat_key    = data.get("strategy", "")  # e.g. "FUTURE-TOPBTM"

            # Fallback: if no list, try old single-instrument field
            if not instruments and data.get("instrument"):
                instruments = [data["instrument"]]

            if not instruments:
                await ws.send(json.dumps({
                    "type":    "error",
                    "message": "No instruments selected!",
                    "success": False,
                }))
                return

            logger.info(
                f"[DASHBOARD] Strategy '{strat_name}' applied | "
                f"Instruments: {instruments} | Direction: {direction} | "
                f"Pyramiding: {pyramiding} | Lots: {lot_size} | Capital: Rs.{capital:,}"
            )

            # ── Resolve strategy type ──────────────────────────────────────────
            SAR_STRATS = {
                "TOPBTM", "CASH-TOPBTM", "FUTURE-TOPBTM", "DISC-GFS", "DISC-ADV",
                "DISC-PRD", "DISC-DIV", "DISC-DIVP"
            }
            TB2_STRATS = {"TOPBTM2", "CASH-TOPBTM2", "FUTURE-TOPBTM2"}
            CUP_STRATS = {"CASH-CUP", "FUTURE-CUP"}
            # CASH-RSI: recognized but rules not yet defined — logged, acknowledged
            RSI_STRATS = {"CASH-RSI", "FUTURE-RSI"}
            strategy_type = "SAR_TOP_BOTTOM"
            if strat_key in SAR_STRATS:
                strategy_type = "SAR_TOP_BOTTOM"
            elif strat_key in TB2_STRATS:
                strategy_type = "TOP_BOTTOM_2"
            elif strat_key in CUP_STRATS:
                strategy_type = "CUP_STRATEGY"
            elif strat_key in RSI_STRATS:
                strategy_type = "RSI_STRATEGY"
            elif strat_key.startswith("CASH-") or strat_key.startswith("FUTURE-"):
                logger.warning(f"[apply_strategy] Unknown strategy '{strat_key}' — ignored")
                await ws.send(json.dumps({
                    "type": "error",
                    "message": f"Strategy '{strat_name}' is not yet available. Coming soon!",
                    "success": False,
                }))
                return

            # ── Build strategy params ─────────────────────────────────────────
            direction_map = {
                "LONGSHORT": "long_short",
                "LONGONLY":  "long_only",
                "SHORTONLY": "short_only",
            }
            strat_params = {
                "direction":      direction_map.get(direction, "long_short"),
                "pyramiding":     pyramiding,
                "stop_pct":        3.0,
                "be_pct":          2.5,
                "atr_threshold":   2.0,
                "reversal_exit":   True,
                "trend_filter":    False,
                "enabled":         True,
                "lot_size":        lot_size,
                "strategy_name":   "Top Bottom-1" if strategy_type == "SAR_TOP_BOTTOM" else ("Top Bottom-2" if strategy_type == "TOP_BOTTOM_2" else strat_name),
            }

            # ── Create and register strategy for EACH instrument ───────────────
            # Force-replace: user's explicit strategy selection ALWAYS wins over
            # the auto-applied SAR_TOP_BOTTOM from sync_watchlist
            loaded = []
            skipped = []
            for inst in instruments:
                inst = inst.strip()
                if not inst:
                    continue

                if strategy_type == "SAR_TOP_BOTTOM":
                    strat = SARTopBottomStrategy(inst, strat_params)
                    self.strategies[inst] = {
                        "strategy":      strat,
                        "config": {
                            "strategy":         "SAR_TOP_BOTTOM",
                            "strategy_params":  strat_params,
                            "broker":          "MSTOCK",
                            "data_source":     "yahoo",
                        },
                        "broker_name":  "MSTOCK",
                        "enabled":      True,
                    }
                    # Keep in-memory registry in sync
                    self._watchlist[inst] = {"strategy": "SAR_TOP_BOTTOM", "strategy_params": strat_params}
                    logger.info(f"[DASHBOARD] Top Bottom-1 strategy loaded for {inst}")
                    loaded.append(inst)

                elif strategy_type == "TOP_BOTTOM_2":
                    strat = TopBottom2Strategy(inst, strat_params)
                    self.strategies[inst] = {
                        "strategy":      strat,
                        "config": {
                            "strategy":         "TOP_BOTTOM_2",
                            "strategy_params":  strat_params,
                            "broker":          "MSTOCK",
                            "data_source":     "yahoo",
                        },
                        "broker_name":  "MSTOCK",
                        "enabled":      True,
                    }
                    # Keep in-memory registry in sync
                    self._watchlist[inst] = {"strategy": "TOP_BOTTOM_2", "strategy_params": strat_params}
                    logger.info(f"[DASHBOARD] Top Bottom-2 strategy loaded for {inst}")
                    loaded.append(inst)

                elif strategy_type == "RSI_STRATEGY":
                    # RSI rules not yet defined — acknowledge but don't create strategy
                    logger.info(f"[DASHBOARD] RSI strategy acknowledged for {inst} — rules coming soon")
                    skipped.append(inst)

            # ── Update paper engine settings ───────────────────────────────────
            self.paper.lot_size    = lot_size
            self.paper.initial     = capital
            self.paper.direction   = direction_map.get(direction, "long_short")
            self.paper.pyramiding = pyramiding

            await self.broadcast_state()
            self._save_watchlist()
            if strategy_type == "RSI_STRATEGY":
                msg = f"'{strat_name}' — rules coming soon! You'll be the first to know."
            else:
                msg = f"'{strat_name}' applied on {len(loaded)} instrument(s)!"
                if skipped:
                    msg += f" ({len(skipped)} already existed - skipped)"
            await ws.send(json.dumps({
                "type":    "notification",
                "message": msg,
                "success": True,
            }))

        elif cmd == "remove_strategy":
            inst = data.get("instrument", "")
            if inst in self.strategies:
                del self.strategies[inst]
            if inst in self._watchlist:
                del self._watchlist[inst]
            logger.info(f"[DASHBOARD] Removed strategy for {inst}")
            self._save_watchlist()
            await self.broadcast_state()
            await ws.send(json.dumps({
                "type":    "notification",
                "message": f"Removed {inst} from watchlist",
                "success": True,
            }))

        elif cmd == "add_to_watchlist":
            """
            Add a single instrument to the watchlist (from the Watchlist page Add button).
            Reuses the SAR Top-Bottom strategy with current settings.
            """
            inst = data.get("instrument", "").strip()
            if not inst:
                await ws.send(json.dumps({
                    "type": "error", "message": "No instrument specified", "success": False,
                }))
                return
            if inst in self.strategies:
                await ws.send(json.dumps({
                    "type": "notification", "message": f"{inst} is already in watchlist", "success": True,
                }))
                return

            # Use current paper engine settings for direction/pyramiding
            dir_map = {
                "long_short": "long_short",
                "long_only":  "long_only",
                "short_only": "short_only",
            }
            strat_params = {
                "direction":      dir_map.get(self.paper.direction, "long_short"),
                "pyramiding":     self.paper.pyramiding,
                "stop_pct":        3.0,
                "be_pct":          2.5,
                "atr_threshold":    2.0,
                "reversal_exit":   True,
                "trend_filter":    False,
                "enabled":         True,
                "lot_size":        self.paper.lot_size,
                "strategy_name":   "Top Bottom-1",
            }
            strat = SARTopBottomStrategy(inst, strat_params)
            self.strategies[inst] = {
                "strategy":     strat,
                "config": {
                    "strategy":        "SAR_TOP_BOTTOM",
                    "strategy_params": strat_params,
                    "broker":         "MSTOCK",
                    "data_source":    "yahoo",
                },
                "broker_name": "MSTOCK",
                "enabled":     True,
            }
            logger.info(f"[DASHBOARD] Added {inst} to watchlist via Add button")
            await self.broadcast_state()
            self._save_watchlist()
            await ws.send(json.dumps({
                "type": "notification",
                "message": f"{inst} added to watchlist!",
                "success": True,
            }))

        elif cmd == "update_strategy_params":
            """
            Update per-instrument params from dashboard dropdowns.
            Handles: direction, sl_mode, sl_manual_type, sl_manual_pct, sl_manual_price,
                     be_pct, pyramiding_on, pyramiding_mode, pyramiding_lots, exit_mode,
                     exit_manual_type, exit_manual_val, rollover
            """
            inst  = data.get("instrument", "")
            if inst not in self.strategies:
                await ws.send(json.dumps({
                    "type": "error", "message": f"{inst} not found", "success": False,
                }))
                return

            # ── Update strategy.params (persisted) ────────────────────────────
            strat = self.strategies[inst]["strategy"]
            cfg   = self.strategies[inst]["config"]["strategy_params"]

            if "direction" in data:
                d = data["direction"]
                strat.params["direction"] = d
                cfg["direction"] = d

            if "stop_pct" in data:
                p = float(data["stop_pct"])
                strat.params["stop_pct"] = p
                cfg["stop_pct"] = p

            if "be_pct" in data:
                p = float(data["be_pct"])
                strat.params["be_pct"] = p
                cfg["be_pct"] = p

            # ── Update active position settings ──────────────────────────────
            if inst in self._positions:
                pos = self._positions[inst]

                if "sl_mode" in data:
                    pos["sl_mode"] = data["sl_mode"]

                if "sl_manual_pct" in data:
                    pos["sl_manual_pct"] = float(data["sl_manual_pct"])

                if "sl_manual_price" in data:
                    pos["sl_manual_price"] = float(data["sl_manual_price"])

                if "pyramiding_mode" in data:
                    pos["pyramiding_mode"] = data["pyramiding_mode"]

                if "pyramiding_on" in data:
                    pos["pyramiding_on"] = bool(data["pyramiding_on"])

                if "pyramiding_lots" in data:
                    pos["pyramiding_lots"] = int(data["pyramiding_lots"])

                if "exit_mode" in data:
                    pos["exit_mode"] = data["exit_mode"]

                if "exit_manual_type" in data:
                    pos["exit_manual_type"] = data["exit_manual_type"]

                if "exit_manual_val" in data:
                    pos["exit_manual_val"] = float(data["exit_manual_val"])

                if "sl_manual_type" in data:
                    pos["sl_manual_type"] = data["sl_manual_type"]

                if "rollover" in data:
                    pos["rollover"] = bool(data["rollover"])

                # Recompute current SL if auto (uses Day1 1.5%, Day2+ min(3%, breakeven))
                if pos["sl_mode"] == "auto":
                    entry_p = pos["entry_price"]
                    be_pct  = pos.get("be_pct", 2.5)
                    sl_pct  = pos.get("sl_pct", 1.5)
                    days_in = pos.get("days_in_trade", 1)
                    if pos["side"] == "LONG":
                        be_price  = entry_p * (1 + be_pct / 100)
                        pct3_price = entry_p * 0.97
                        sl_auto = be_price if days_in >= 2 else entry_p * (1 - sl_pct / 100)
                        if days_in >= 2:
                            sl_auto = min(be_price, pct3_price)
                    else:
                        be_price  = entry_p * (1 - be_pct / 100)
                        pct3_price = entry_p * 1.03
                        sl_auto = entry_p * (1 + sl_pct / 100)
                        if days_in >= 2:
                            sl_auto = max(be_price, pct3_price)
                    pos["current_sl"] = round(sl_auto, 2)
                elif pos.get("sl_manual_price"):
                    pos["current_sl"] = pos["sl_manual_price"]

            logger.info(f"[DASHBOARD] Updated {inst} params: {data}")
            self._save_watchlist()
            await self.broadcast_state()
            await ws.send(json.dumps({
                "type": "notification",
                "message": f"{inst} updated!",
                "success": True,
            }))

        elif cmd == "exit_instrument":
            """
            Emergency/manual exit of a specific instrument position.
            """
            inst = data.get("instrument", "")
            if inst not in self._positions:
                await ws.send(json.dumps({
                    "type": "error",
                    "message": f"No active position for {inst}",
                    "success": False,
                }))
                return
            trade = self._exit_instrument(inst, reason="manual_exit")
            strat = self.strategies.get(inst, {}).get("strategy")
            if strat:
                strat.clear_position()
            await self.broadcast_state()
            if trade:
                await ws.send(json.dumps({
                    "type": "notification",
                    "message": f"{inst} exited! P&L: ₹{trade.pnl:,.2f}",
                    "success": True,
                }))
            else:
                await ws.send(json.dumps({
                    "type": "notification",
                    "message": f"{inst} exit failed",
                    "success": False,
                }))

        elif cmd == "run_backtest":
            # Kick off a backtest (runs in background)
            threading.Thread(
                target=self._run_backtest,
                args=(data.get("params", {}),),
                daemon=True
            ).start()
            await ws.send(json.dumps({
                "type": "notification",
                "message": "Backtest started...",
                "success": True,
            }))

    def _run_backtest(self, params: dict):
        """Run backtest and save results (called in background thread)."""
        logger.info(f"Backtest triggered with params: {params}")
        # Import here to avoid circular
        import sartrader.backtest as backtest
        result = backtest.run(
            data_path=str(BASE_DIR / "data" / "nsebank_daily.csv"),
            **params,
        )
        logger.info(f"Backtest complete: {result.get('total_pnl', 0)}")


# ── HTTP Server (for dashboard) ────────────────────────────────────────────────

async def run_http_dashboard(engine_ref, host="localhost", port=8765, server_ready=None):
    """Simple HTTP server serving the dashboard HTML."""
    import aiohttp
    from aiohttp import web

    dashboard_path = BASE_DIR / "dashboard"
    if not dashboard_path.exists():
        dashboard_path.mkdir(parents=True, exist_ok=True)

    # Write the dashboard HTML if not exists
    dash_file = dashboard_path / "index.html"
    if not dash_file.exists():
        # Copy from the dark theme we built earlier
        dark_src = BASE_DIR / "dashboards" / "dark_theme.html"
        if dark_src.exists():
            import shutil
            shutil.copy(dark_src, dash_file)

    async def serve_dashboard(request):
        return web.FileResponse(str(dash_file))

    app = web.Application()
    app.router.add_get("/", serve_dashboard)
    app.router.add_static("/static", str(dashboard_path))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"HTTP dashboard: http://{host}:{port}")
    # Signal HTTP server is ready — safe to start tick loop now
    if server_ready:
        server_ready.set()
    await asyncio.Future()


# ── Entry Point ───────────────────────────────────────────────────────────────

async def main_async():
    # Parse CLI args
    parser = argparse.ArgumentParser(description="SARTrader Engine")
    parser.add_argument("--host", default="localhost", help="Dashboard host (use 0.0.0.0 for public)")
    parser.add_argument("--port", type=int, default=config.DASHBOARD_PORT, help="Dashboard port")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("  SARTrader Platform v1.0")
    logger.info("  Mode: " + config.MODE)
    logger.info("=" * 60)

    engine = TradingEngine()

    # Start HTTP + WebSocket
    host = args.host
    port = args.port

    # Event: fires when HTTP server is listening — tick loop waits for this
    server_ready = asyncio.Event()

    # HTTP dashboard server
    http_task = asyncio.create_task(
        run_http_dashboard(lambda: engine, host, port, server_ready)
    )

    # WebSocket server on port 8766
    ws_task = asyncio.create_task(
        ws_server(lambda: engine, host, port + 1)
    )

    # Wait for HTTP server to be listening before starting tick loop
    await server_ready.wait()
    logger.info("Servers ready — starting tick loop")

    # Capture the running async loop, then start tick loop
    engine._loop = asyncio.get_running_loop()
    engine.start()

    # Connect brokers on startup (only if enabled in config)
    for name in list(engine.brokers.keys()):
        logger.info(f"Attempting {name} connection (TOTP required daily)...")
        try:
            ok = engine.connect_broker(name)
            if ok:
                logger.info(f"{name} connected successfully")
            else:
                logger.warning(f"{name} connection failed — will retry on next tick")
        except Exception as e:
            logger.warning(f"{name} connection error: {e}")

    try:
        await asyncio.gather(http_task, ws_task)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        engine.stop()


def main():
    """Run with: python -m sartrader.engine"""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
