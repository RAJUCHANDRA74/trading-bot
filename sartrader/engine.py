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
import re
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

async def _safe_send(ws, payload):
    """Send JSON to WebSocket, silently ignore if connection is already closed."""
    try:
        await ws.send(json.dumps(payload))
    except Exception:
        pass  # Connection already closed — nothing to send

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


async def ws_server(engine_ref, host="127.0.0.1", port=8765):
    """
    Run WebSocket server in a dedicated thread with its own asyncio event loop.
    websockets 17.1 Server.__init__ calls asyncio.get_running_loop() so we need
    a running loop in the thread — achieved by running an async task inside it.
    """
    import websockets
    import threading

    async def handler(websocket):
        await websocket_handler(websocket, "", engine_ref)

    ready_event = threading.Event()
    error_holder = [None]  # mutablelist to capture exception

    def ws_run_loop():
        """
        Own event loop in a thread. schedule_server() is an async coroutine that
        calls websockets.serve() — it needs a running loop (get_running_loop is
        called inside Server.__init__). We give it one via ensure_future.
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def schedule_server():
            # This coroutine runs INSIDE the running loop — get_running_loop() works here
            server = websockets.serve(handler, host, port, ping_interval=None)
            async with server:
                logger.info(f"WebSocket server running: ws://{host}:{port}")
                ready_event.set()
                await asyncio.Future()   # run forever

        async def run():
            try:
                await schedule_server()
            except Exception as e:
                error_holder[0] = e
                logger.error(f"[WS] Server error: {e}")
            finally:
                ready_event.set()

        # Run the async task in this loop — get_running_loop() is available
        loop.run_until_complete(run())

    thread = threading.Thread(target=ws_run_loop, daemon=True, name="ws-server")
    thread.start()

    # Wait for server to start (non-blocking via event loop)
    await asyncio.get_event_loop().run_in_executor(None, ready_event.wait)

    if error_holder[0]:
        raise error_holder[0]

    # Server is running in background thread — keep this coroutine alive
    try:
        await asyncio.sleep(float('inf'))
    except asyncio.CancelledError:
        pass


# ── R1 Daily Levels Monitor ────────────────────────────────────────────────────

class TB1R1Monitor:
    """
    Background thread that fetches daily candles from M-Stock and detects
    confirmed TB-1 R1 swing tops and bottoms for all watchlist instruments.

    R1 formula (daily close-line):
      TOP  confirmed: close[N+1] < close[N]
      BOTTOM confirmed: close[N+1] > close[N]
    Level becomes actionable from Day N+2 onwards.
    """

    def __init__(self, engine):
        self._engine = engine
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # instrument -> {tops: [(date_str, price), ...], bots: [(date_str, price), ...],
        #                 confirmed_top: (date_str, price), confirmed_bot: (date_str, price),
        #                 updated_ts: float}
        self._levels: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("[R1] TB1R1Monitor started — daily levels thread active")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def get_levels(self, instrument: str) -> Optional[dict]:
        """Return confirmed R1 levels for an instrument, or None."""
        with self._lock:
            return self._levels.get(instrument)

    def get_confirmed_top(self, instrument: str) -> Optional[float]:
        """Return most recent confirmed TOP price, or None."""
        levels = self.get_levels(instrument)
        if levels and levels.get("confirmed_top"):
            return levels["confirmed_top"][1]
        return None

    def get_confirmed_bot(self, instrument: str) -> Optional[float]:
        """Return most recent confirmed BOTTOM price, or None."""
        levels = self.get_levels(instrument)
        if levels and levels.get("confirmed_bot"):
            return levels["confirmed_bot"][1]
        return None

    def _run(self):
        """Fetch and update R1 levels every 15 minutes during market hours."""
        while self._running:
            try:
                if self._engine._is_market_hours():
                    self._update_all_levels()
                else:
                    # Outside market hours: still refresh once to get last confirmed levels
                    self._update_all_levels()
            except Exception as e:
                logger.error(f"[R1] Error updating daily levels: {e}")
            # Sleep 15 minutes between refreshes
            for _ in range(15 * 60):
                if not self._running:
                    break
                time.sleep(1)

    def _update_all_levels(self):
        """Fetch daily candles for all strategies and compute R1 levels."""
        for inst_key, strat_data in self._engine.strategies.items():
            try:
                self._update_instrument_levels(inst_key)
            except Exception as e:
                logger.debug(f"[R1] Failed to update levels for {inst_key}: {e}")

    def _update_instrument_levels(self, instrument: str):
        """Fetch daily candles for one instrument and compute R1 tops/bottoms."""
        broker = self._engine._get_broker_for_instrument(instrument)
        if not broker or not broker.is_connected():
            return

        try:
            if not hasattr(broker, "get_daily_price"):
                return  # No daily data available

            inst_upper = instrument.upper()
            exch = "NSE"
            token = ""

            # Resolve token: futures use NFO token via broker's internal logic
            is_fut = bool(
                inst_upper.endswith("FUT") or
                re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}F?$', inst_upper)
            )
            if is_fut:
                # get_daily_price handles NFO token resolution internally
                exch = "NFO"
            else:
                if hasattr(broker, "_resolve_token"):
                    exch, token = broker._resolve_token(instrument)

            candles = broker.get_daily_price(exch, token, instrument)

            if not candles or len(candles) < 3:
                # Debug: check token map state
                token_count = len(broker._token_map) if hasattr(broker, '_token_map') else 0
                logger.info(f"[R1] {instrument}: no candles (exch={exch}, token={token!r}, is_fut={is_fut}, token_map_size={token_count})")
                return

            # R1: confirm tops/bottoms from close-line
            tops = []
            bots = []
            for i in range(1, len(candles) - 1):
                c_prev = candles[i - 1].close
                c_curr = candles[i].close
                c_next = candles[i + 1].close
                dt_str = _dt.fromtimestamp(candles[i].timestamp).strftime("%Y-%m-%d")

                if c_curr > c_prev and c_curr >= c_next:
                    tops.append((dt_str, round(c_curr, 2)))
                if c_curr < c_prev and c_curr <= c_next:
                    bots.append((dt_str, round(c_curr, 2)))

            if not tops and not bots:
                return

            confirmed_top = tops[-1] if tops else None
            confirmed_bot = bots[-1] if bots else None

            with self._lock:
                self._levels[instrument] = {
                    "tops":           tops,
                    "bots":           bots,
                    "confirmed_top":  confirmed_top,
                    "confirmed_bot":  confirmed_bot,
                    "candle_count":   len(candles),
                    "last_close":     candles[-1].close,
                    "updated_ts":     time.time(),
                }

            logger.info(
                f"[R1] {instrument}: {len(candles)} daily candles | "
                f"Tops={len(tops)} (latest={confirmed_top[0] if confirmed_top else 'none'}) | "
                f"Bots={len(bots)} (latest={confirmed_bot[0] if confirmed_bot else 'none'})"
            )

        except Exception as e:
            logger.info(f"[R1] {instrument}: error fetching daily candles: {e}")


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
        logger.info(f"[Engine] paper._db_positions = {len(self.paper._db_positions)} | keys = {list(self.paper._db_positions.keys())}")
        self._running   = False
        self._live_trades: List[dict] = []   # Live trade history
        self._tick_thread: Optional[threading.Thread] = None
        self._tick_interval = 1      # seconds between ticks (live updates)
        self._last_candle_fetch: dict[str, float] = {}   # inst_key → last fetch timestamp

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

        # TB-1 R1 daily levels monitor (updated every 15 min in tick loop)
        self._r1_monitor = TB1R1Monitor(self)
        self._r1_last_update: float = 0  # Unix timestamp of last R1 update

        # Track previous LTP for R2 cross detection
        # instrument → previous LTP price
        self._prev_ltp: Dict[str, float] = {}

        # Live LTP cache (populated each tick from broker quotes)
        self._quotes: Dict[str, dict] = {}

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

    # ── Position helpers (used by WS command handlers) ──────────────────────────

    def _all_pos(self) -> dict:
        """Return merged dict: DB-loaded positions + engine live positions."""
        merged = dict(self.paper._db_positions)  # snapshot of DB positions
        for inst, pos in self._positions.items():
            if inst in merged:
                merged[inst].update(pos)   # engine fields override DB fields
            else:
                merged[inst] = dict(pos)
        return merged

    def _persist_pos(self, inst: str, pos: dict):
        """Write a position to both engine dict and DB."""
        self._positions[inst] = pos
        self.paper._save_position(inst, pos)
        return

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
                    # Store in UPPERCASE so lookups in _resolve_futures work (case-insensitive)
                    self._available_futures = {f.upper() for f in futures}
                    logger.info(
                        f"Synced {len(self._available_futures)} NSE stock futures "
                        f"from {name} broker | Expiry: {self._current_expiry}"
                    )
                    return  # Success — stop after first broker
            except Exception as e:
                logger.warning(f"Failed to sync NFO instruments from {name}: {e}")

    def _detect_expiry(self) -> str:
        """
        Detect current futures expiry in M-Stock format (e.g. '29Sep2026').
        Extracts actual expiry date from the broker's available futures data,
        which contains real M-Stock expiry dates.
        Falls back to computing from calendar if no futures data is available.
        """
        # Extract actual expiry from the available futures list (real M-Stock data)
        # Available futures format: "ASHOKLEYSepFUT26" (stocks) or "NIFTY26SepFUT" (indexes)
        # The month in these names (Sep, Oct, Nov) tells us the current series
        MStock_MONTH_MAP = {
            "JAN": "Jan", "FEB": "Feb", "MAR": "Mar", "APR": "Apr",
            "MAY": "May", "JUN": "Jun", "JUL": "Jul", "AUG": "Aug",
            "SEP": "Sep", "OCT": "Oct", "NOV": "Nov", "DEC": "Dec",
        }
        # M-Stock expiry day by month (based on actual NSE data)
        # Sep 2026: 29 (Tue), Oct 2026: 30 (Thu), Nov 2026: 27 (Thu)
        MSTOCK_EXPIRY_DAY = {
            1: 29, 2: 26, 3: 26, 4: 29, 5: 28, 6: 25,
            7: 29, 8: 27, 9: 29, 10: 30, 11: 27, 12: 29,
        }

        now = _dt.now()
        yr = str(now.year)  # "2026"

        # Find which month abbreviations appear in available futures
        current_month_abbr = None
        if self._available_futures:
            sample = list(self._available_futures)[:200]
            for entry in sample:
                e = entry.upper()
                for abbr_upper in MStock_MONTH_MAP:
                    # Stock format: "...SepFUT..." or "...OctFUT..."
                    if f"{abbr_upper}FUT" in e:
                        if current_month_abbr is None or \
                           list(MStock_MONTH_MAP.keys()).index(abbr_upper) < \
                           list(MStock_MONTH_MAP.keys()).index(current_month_abbr.upper()[:3]):
                            current_month_abbr = MStock_MONTH_MAP[abbr_upper]
                        break

        if current_month_abbr:
            mon_num = [k for k, v in MStock_MONTH_MAP.items() if v == current_month_abbr][0]
            mon_num = int(list(MStock_MONTH_MAP.keys())[list(MStock_MONTH_MAP.values()).index(current_month_abbr)])
            day = MSTOCK_EXPIRY_DAY.get(mon_num, 28)
            return f"{day}{current_month_abbr}{yr}"

        # Fallback: use M-Stock expiry day for current month
        mon_num = now.month
        day = MSTOCK_EXPIRY_DAY.get(mon_num, 28)
        return f"{day}{MStock_MONTH_MAP.get(now.strftime('%b').upper(), 'Sep')}{yr}"

    @property
    def current_expiry(self) -> str:
        """Current NSE futures expiry string in M-Stock format, e.g. '29Sep2026'."""
        return getattr(self, "_current_expiry", "29Sep2026")

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
        # NSE format: SYMBOLMONTHFUTYY (e.g. ICICIBANKSEPFUT26, BHELSEPFUT26)
        if re.search(r'(SEP|OCT|NOV|DEC|JAN|AUG|JUL)FUT(26|27)$', inst_upper):
            return "STOCK_FUTURES"
        # Alternative format: SYMBOLYYMONTHFUT (e.g. RELIANCE26SEPFUT)
        if re.search(r'(SEP|OCT|NOV|DEC|JAN|AUG|JUL)(26|27)FUT$', inst_upper):
            return "STOCK_FUTURES"
        return "CASH"

    def _infer_sector(self, inst: str) -> str:
        """
        Map a base stock symbol to a sector name (matches dashboard sectorMap keys).
        Handles both raw base symbols (SBIN, TATAMOTORS) and full contract names.
        Returns uppercase+underscore keys that match the dashboard sectorMap.
        """
        import re
        inst_upper = inst.upper()
        # Strip contract suffixes to get base symbol
        # ORDER MATTERS: strip trailing digits first, then FUT suffix
        # This correctly handles both "TATAMOTORSEPFUT26" -> "TATAMOTORS"
        # and "TATAMOTORS26" -> "TATAMOTORS" and "BHELSEPFUT26" -> "BHELSEP"
        base = re.sub(r'\d+$', '', inst_upper)          # strip trailing digits: 26/2026
        # Strip month codes + year BEFORE stripping FUT — critical order!
        # This handles "BHELSEPFUT26" -> strip SEP+26 -> "BHELFUT" -> strip FUT -> "BHEL"
        base = re.sub(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}$', '', base)  # strip month+2-digit-year: SEP26/OCT26/DEC26
        base = re.sub(r'FUT(FUTURES)?$', '', base)       # strip FUT/FUTURES suffix
        base = base.strip()

        # Index futures / commodity futures — not in the stock map
        if base in self.INDEX_FUTURES:
            return "INDEX_FUTURES"
        if base in self.COMMODITY_FUTURES:
            return "COMMODITY_FUTURES"

        sector_map = {
            "SBIN": "PSU_BANK", "SBI": "PSU_BANK", "CANBK": "PSU_BANK", "BANK OF BARODA": "PSU_BANK",
            "UNIONBANK": "PSU_BANK", "PNB": "PSU_BANK", "CENTRALBK": "PSU_BANK",
            "INDIANB": "PSU_BANK", "UCOBANK": "PSU_BANK",
            "HDFCBANK": "PVT_BANK", "ICICIBANK": "PVT_BANK", "KOTAKBANK": "PVT_BANK",
            "INDUSINDBK": "PVT_BANK", "AXISBANK": "PVT_BANK", "IDFCFIRSTB": "PVT_BANK",
            "BANDHANBNK": "PVT_BANK", "RBLBANK": "PVT_BANK",
            "MARUTI": "AUTO", "M&M": "AUTO", "TATAMOTORS": "AUTO", "BAJAJ-AUTO": "AUTO",
            "HEROMOTOCO": "AUTO", "EICHERMOT": "AUTO", "TVSMOTOR": "AUTO",
            "ASHOKLEY": "AUTO", "BALKRISIND": "AUTO",
            "RELIANCE": "ENERGY", "ONGC": "ENERGY", "BPCL": "ENERGY", "IOC": "ENERGY",
            "HPCL": "ENERGY", "GAIL": "ENERGY",
            "HINDUNILVR": "FMCG", "NESTLE": "FMCG", "DABUR": "FMCG", "COLPAL": "FMCG",
            "BRITANNIA": "FMCG", "MARICO": "FMCG",
            "TITAN": "CONSUMER", "HAVELLS": "CONSUMER", "VOLTAS": "CONSUMER", "CROMPTON": "CONSUMER",
            "BAJFINANCE": "FINANCIAL_SERVICES", "BAJ FINSERV": "FINANCIAL_SERVICES",
            "MUTHOOTFIN": "FINANCIAL_SERVICES",
            "INFY": "IT", "TCS": "IT", "HCLTECH": "IT", "WIPRO": "IT",
            "TECHM": "IT", "LTIM": "IT", "COFORGE": "IT",
            "TATASTEEL": "METAL", "JSWSTEEL": "METAL", "HINDALCO": "METAL",
            "JSPL": "METAL", "NMDC": "METAL", "SAIL": "METAL",
            "SUNPHARMA": "PHARMA", "CIPLA": "PHARMA", "DRREDDY": "PHARMA",
            "APOLLOPHARMA": "PHARMA", "ZYDUSLIFE": "PHARMA",
            "NTPC": "PSE", "POWERGRID": "PSE", "COALINDIA": "PSE",
            "BEL": "DEFENCE", "HAL": "DEFENCE", "BEML": "DEFENCE",
            "DLF": "REALTY", "GODREJPROP": "REALTY",
            "ADANI PORTS": "INFRASTRUCTURE", "ADANIPORTS": "INFRASTRUCTURE",
            "DELHIVERY": "INFRASTRUCTURE", "CONCOR": "INFRASTRUCTURE",
            "ADANIENT": "MISC", "ADANIGREEN": "MISC",
        }
        return sector_map.get(base, "OTHER")

    def _resolve_futures(self, inst: str) -> str:
        """
        Convert base symbol to current month futures contract (UPPERCASE).
        Stock: 'ASHOKLEY' -> 'ASHOKLEYSEPFUT26'
        Index: 'NIFTY'    -> 'NIFTY26SEPFUT'
        Commodity: 'GOLD' -> 'GOLD26SEPFUT'
        Handles M-Stock's current_expiry format (e.g. '29Sep2026').
        """
        inst_upper = inst.upper()
        exp = self.current_expiry
        exp_uc = exp.upper()  # e.g. "29SEP2026"
        yr = exp_uc[-2:]      # "26"
        month = exp_uc[2:5]   # "SEP"

        # Already a full contract name (e.g. "ASHOKLEYSEPFUT26")
        if "FUT" in inst_upper:
            return inst_upper

        # Index futures: NIFTY -> NIFTY26SEPFUT
        for idx in self.INDEX_FUTURES:
            if inst_upper.startswith(idx):
                return f"{idx.upper()}{yr}{month}FUT"
        # Commodity futures: GOLD -> GOLD26SEPFUT
        for c in self.COMMODITY_FUTURES:
            if inst_upper.startswith(c):
                return f"{c.upper()}{yr}{month}FUT"
        # Stock futures: ASHOKLEY -> ASHOKLEYSEPFUT26
        return f"{inst_upper}{month}FUT{yr}"

    # ── Live Trade Tracking ────────────────────────────────────────────────────

    def _add_live_trade(self, order: dict):
        """Add a live trade to the tracking list."""
        self._live_trades.append(order)
        logger.info(f"[LIVE] Trade recorded: {order.get('instrument')} {order.get('side')} {order.get('quantity')}lots @ {order.get('entry_price')}")

    def connect_broker(self, name: str) -> bool:
        """Manually connect a broker by name (sync, runs in thread pool via asyncio.to_thread)."""
        if name not in self.brokers:
            logger.error(f"Unknown broker: {name}")
            return False
        result = self.brokers[name].connect()
        if result:
            self._sync_nfo_instruments()  # Refresh NFO list with new broker
            # Subscribe watchlist + position instruments to live quote streaming
            # Watchlist instruments (dashboard added)
            wl_instruments = list(self._watchlist.keys())
            # Position instruments from DB (loaded at startup)
            pos_instruments = list(self.paper._db_positions.keys())
            # Engine-managed positions (added via dashboard)
            eng_instruments = list(self._positions.keys())
            all_instruments = list(set(wl_instruments + pos_instruments + eng_instruments))
            if all_instruments and hasattr(self.brokers[name], "subscribe"):
                self.brokers[name].subscribe(all_instruments)
                logger.info(f"[LIVE] Subscribed {len(all_instruments)} instruments for live streaming ({len(wl_instruments)} watchlist + {len(pos_instruments)} positions)")
            # Queue broadcast_state from the event loop thread (broadcast_state is async)
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self.broadcast_state())
                )
        return result

    def _subscribe_instruments(self, instruments: List[str]):
        """Subscribe instruments to live quote streaming via all connected brokers.
        Pass base symbols (e.g. "ASHOKLEY") — broker resolves to NFO token internally.
        Live quote cache is keyed by base symbol, so base symbols must be used consistently."""
        for broker in self.brokers.values():
            if broker.is_connected() and hasattr(broker, "subscribe"):
                # Pass base symbols directly — broker._poll_live_quotes resolves to tokens
                broker.subscribe(instruments)
                logger.info(f"[LIVE] Subscribed {len(instruments)} instruments for live streaming")

    def _unsubscribe_instruments(self, instruments: List[str]):
        """Unsubscribe instruments from live quote streaming — pass base symbols."""
        for broker in self.brokers.values():
            if broker.is_connected() and hasattr(broker, "unsubscribe"):
                # Pass base symbols to match how subscribe() stored them
                broker.unsubscribe(instruments)

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

    # Multi-word NSE equity symbols — MUST be listed before regex stripping
    # Otherwise "ADANIPORTSEPFUT26" strips to "ADANIPORT" which is NOT a valid Yahoo Finance symbol
    _YF_SYMBOLS = {
        # Index & commodities
        "BANKNIFTY26SEPFUT": "^NSEBANK",
        "NIFTY26SEPFUT":     "^NSEI",
        "NIFTY":              "^NSEI",
        "BANKNIFTY":          "^NSEBANK",
        "GOLD":               "GC=F",
        "SILVER":             "SI=F",
        # Hindustan Aeronautics Ltd — NSE scrip: HAL (not HALE)
        "HALESEP26":         "HAL.NS",
        # Multi-word NSE equity symbols (strip to correct Yahoo Finance symbol)
        "ADANIPORTSEPFUT":   "ADANIPORTS.NS",
        "ADANIPORT":         "ADANIPORTS.NS",
        "ADANI PORTS":       "ADANIPORTS.NS",   # base symbol with space → correct YF symbol
        "MUTHOOTFINSEPFUT":  "MUTHOOTFIN.NS",
        "MUTHOOTFIN":        "MUTHOOTFIN.NS",
        "APOLLOPHARMASEPFUT":"APOLLOPHARMA.NS",
        "APOLLOPHARMA":      "APOLLOPHARMA.NS",
        "BAJAJFINSVSEPFUT":  "BAJAJFINSV.NS",
        "BAJAJFINSV":        "BAJAJFINSV.NS",
        "BAJFINANCESEPFUT":  "BAJFINANCE.NS",
        "BAJFINANCE":        "BAJFINANCE.NS",
        "SHRIRAMFINSEPFUT":  "SHRIRAMFIN.NS",
        "SHRIRAMFIN":        "SHRIRAMFIN.NS",
        "CHOLAFINSEPFUT":    "CHOLAFIN.NS",
        "CHOLAFIN":          "CHOLAFIN.NS",
        "LICHSGFINSEPFUT":   "LICHSGFIN.NS",
        "LICHSGFIN":         "LICHSGFIN.NS",
        "FEDERALBNKSEPFUT":  "FEDERALBNK.NS",
        "FEDERALBNK":        "FEDERALBNK.NS",
        "KALYANBNKSEPFUT":   "KALYANBNK.NS",
        "KALYANBNK":         "KALYANBNK.NS",
        "INDUSINDBKSEPFUT":  "INDUSINDBK.NS",
        "INDUSINDBK":        "INDUSINDBK.NS",
        "M&MSEPFUT":         "M&M.NS",
        "M&M":               "M&M.NS",
        "L&TFHSEPFUT":       "L&TFH.NS",
        "L&TFH":             "L&TFH.NS",
        "NATIONALUMSEPFUT":  "NATIONALUM.NS",
        "NATIONALUM":         "NATIONALUM.NS",
        "MOTHERSONSEPFUT":   "MOTHERSON.NS",
        "MOTHERSON":         "MOTHERSON.NS",
        "PIRAMALENTERPFUT":  "PIRAMALENT.NS",
        "PIRAMALENT":        "PIRAMALENT.NS",
    }

    def _resolve_yf_symbol(self, instrument: str) -> str:
        """Resolve Yahoo Finance symbol for any instrument.
        Examples:
          BANKNIFTY26SEPFUT  -> ^NSEBANK
          NIFTY26SEPFUT      -> ^NSEI
          ICICIBANKSEP26     -> ICICIBANK.NS
          HDFCBANK26SEPFUT   -> HDFCBANK.NS
          NATIONALUM26SEPFUT -> NATIONALUM.NS
          GOLD               -> GC=F
          SILVER             -> SI=F
          NIFTY              -> ^NSEI
          BANKNIFTY          -> ^NSEBANK
          ADANIPORTSEPFUT26 -> ADANI PORTS.NS  (multi-word symbol)
        """
        if instrument in self._YF_SYMBOLS:
            return self._YF_SYMBOLS[instrument]
        import re
        # Try stripping date suffix first, then check _YF_SYMBOLS again (for multi-word symbols)
        stripped = re.sub(r'(SEPFUT|FUT|26SEPFUT|26FUT|SEPFUT-EQ|EQ)$', '', instrument)
        stripped = re.sub(r'(SEP|OCT|NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG)\d{2}$', '', stripped)
        stripped = re.sub(r'^\d{2}(SEP|OCT|NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG)', '', stripped)
        stripped = stripped.rstrip('.-_')
        if stripped in self._YF_SYMBOLS:
            return self._YF_SYMBOLS[stripped]
        # Also check original instrument (with spaces) for multi-word symbols
        if instrument in self._YF_SYMBOLS:
            return self._YF_SYMBOLS[instrument]
        return stripped + ".NS"

    def _fetch_yahoo_candles(self, instrument: str, interval: str = "5m",
                             range_: str = "5d") -> List[OHLC]:
        """Free live candles from Yahoo Finance (no API key needed).
        Args:
            instrument: base symbol (e.g. 'BHEL', 'CANBK')
            interval: '1d' (daily), '5m' (5-min), '15m' (15-min), '60m' (hourly)
            range_: '60d' (60 days), '5d' (5 days), '1mo' (1 month), '3mo' (3 months)
        Returns: [OHLC, ...] for signal strategy consumption.
        """
        import urllib.request, json

        symbol = self._resolve_yf_symbol(instrument)
        try:
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace(' ', '+')}"
                f"?interval={interval}&range={range_}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
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
            return candles
        except Exception as e:
            logger.debug(f"Yahoo Finance failed for {instrument} ({interval}/{range_}): {e}")
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
        now_ts = time.time()
        # R1 update every 15 min, only after broker is connected AND token map is built
        brokers = [b for b in self.brokers.values() if b.is_connected()]
        token_map_ready = any(
            hasattr(b, '_token_map') and len(b._token_map) > 0
            for b in brokers
        )
        if now_ts - self._r1_last_update >= 900 and token_map_ready:
            self._r1_last_update = now_ts
            try:
                logger.info("[R1] Triggering daily levels update...")
                self._r1_monitor._update_all_levels()
                logger.info("[R1] Daily levels update complete")
            except Exception as e:
                logger.warning(f"[R1] Update failed: {e}")

        # ── TB-1 Position Management: Rules 3/4/5 every tick ─────────────────
        self._manage_tb1_positions()

        for inst_key, strat_data in self.strategies.items():
            strat  = strat_data["strategy"]
            broker = self._get_broker_for_instrument(inst_key)

            try:
                # ── 1. Poll live LTP from broker every tick ────────────────────────
                # Broker's _poll_live_quotes runs every 1 second — get_quote returns fresh cache
                ltp = None
                if broker and broker.is_connected():
                    try:
                        quote = broker.get_quote(inst_key)
                        if quote and quote.get("last_price", 0) > 0:
                            ltp = float(quote.get("last_price", 0))
                            self._quotes[inst_key] = {
                                "last_price": ltp,
                                "price":      ltp,
                                "change":     quote.get("change", 0),
                                "change_pct": quote.get("change_pct", 0),
                            }
                    except Exception:
                        pass  # LTP poll failed — skip silently

                # ── 1b. R2 LTP Cross-check (TB-1 Rule 2) ────────────────────────
                # Fire entry signal when LTP crosses confirmed R1 top/bottom
                # (R1 levels updated every 15 min by TB1R1Monitor background thread)
                if ltp is not None and inst_key not in self._positions:
                    prev_ltp = self._prev_ltp.get(inst_key)
                    confirmed_top = self._r1_monitor.get_confirmed_top(inst_key)
                    confirmed_bot = self._r1_monitor.get_confirmed_bot(inst_key)

                    if prev_ltp is not None and confirmed_top and confirmed_bot:
                        try:
                            strat = strat_data.get("strategy")
                            # R2 LONG: LTP crosses ABOVE most recent confirmed TOP
                            if prev_ltp <= confirmed_top < ltp:
                                sig = Signal(
                                    type=SignalType.LONG_ENTRY,
                                    instrument=inst_key,
                                    strategy_name="TB1_R2",
                                    price=ltp,
                                    reason=f"R2 LONG: LTP {ltp:.2f} crossed above confirmed TOP {confirmed_top:.2f}",
                                    metadata={"r2_top": confirmed_top},
                                )
                                self._process_r2_signal(sig, inst_key, strat)
                                logger.info(
                                    f"[R2] {inst_key}: LONG entry | LTP={ltp:.2f} crossed TOP={confirmed_top:.2f} "
                                    f"(prev={prev_ltp:.2f})"
                                )
                            # R2 SHORT: LTP crosses BELOW most recent confirmed BOTTOM
                            elif prev_ltp >= confirmed_bot > ltp:
                                sig = Signal(
                                    type=SignalType.SHORT_ENTRY,
                                    instrument=inst_key,
                                    strategy_name="TB1_R2",
                                    price=ltp,
                                    reason=f"R2 SHORT: LTP {ltp:.2f} crossed below confirmed BOTTOM {confirmed_bot:.2f}",
                                    metadata={"r2_bot": confirmed_bot},
                                )
                                self._process_r2_signal(sig, inst_key, strat)
                                logger.info(
                                    f"[R2] {inst_key}: SHORT entry | LTP={ltp:.2f} crossed BOT={confirmed_bot:.2f} "
                                    f"(prev={prev_ltp:.2f})"
                                )
                        except Exception as e:
                            logger.error(f"[R2] Error processing R2 signal for {inst_key}: {e}")

                    self._prev_ltp[inst_key] = ltp

                candles = None

                # Try broker first (live data) — throttle to once per 15 min per instrument
                now_ts = time.time()
                last_fetch = self._last_candle_fetch.get(inst_key, 0)
                if broker and broker.is_connected() and (now_ts - last_fetch >= 900):
                    self._last_candle_fetch[inst_key] = now_ts
                    to_ts   = int(_dt.now().timestamp())
                    from_ts = to_ts - (50 * 15 * 60)
                    candles = broker.get_candles(inst_key, "15m", from_ts, to_ts)

                # Fall back to Yahoo Finance — but skip in PAPER mode (avoids DNS/timeouts)
                if not candles and self.mode != "PAPER":
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
            asyncio.run_coroutine_threadsafe(self.broadcast_state(), self._loop)

    def _process_r2_signal(self, signal, strat):
        """
        Handle TB-1 R2 entry signal (LTP cross against confirmed daily levels).
        R2 fires during the trading day — entry executes immediately at LTP.
        Deduplication: same instrument+direction fires at most once per 5 minutes.
        """
        inst = signal.instrument
        dedup_key = f"{inst}:{signal.type.value}"
        now_ts = time.time()
        last_fired = self._signal_fired.get(dedup_key, 0)
        if now_ts - last_fired < 300:  # 5-min dedup for R2
            return
        self._signal_fired[dedup_key] = now_ts

        side = "LONG" if signal.type == SignalType.LONG_ENTRY else "SHORT"
        trade_id = self._enter_instrument(signal)
        if trade_id:
            pos_after = self._positions.get(inst)
            if pos_after and strat:
                strat.on_entry(side, pos_after["entry_price"], pos_after.get("entry_idx", 0))
                strat.set_position(side, pos_after["entry_price"])
            self._push_trade_event("ENTRY", signal, trade_id)

        self._signals.append({
            "time":   _dt.now().isoformat(),
            "inst":   inst,
            "type":   signal.type.value,
            "price":  signal.price,
            "reason": signal.reason,
        })
        logger.info(f"[R2] Signal [{inst}]: {signal.type.value} @ {signal.price:.2f} | {signal.reason} | mode={self.mode}")

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

    # ── TB-1 Instrument Constants ──────────────────────────────────────────────

    # TB-1 SL percentages by instrument type
    TB1_INDEX_SL_DAY1   = 0.990   # 1% below entry  (Rule 6, index)
    TB1_STOCK_SL_DAY1   = 0.985   # 1.5% below entry (Rule 6, stock)
    TB1_INDEX_SL_DAY2   = 0.980   # 2% below entry   (Rule 3, index)
    TB1_STOCK_SL_DAY2   = 0.970   # 3% below entry   (Rule 3, stock)
    TB1_INDEX_BREAKEVEN = 1.020   # 2% profit → break-even (Rule 4, index)
    TB1_STOCK_BREAKEVEN = 1.030   # 3% profit → break-even (Rule 4, stock)
    TB1_INDEX_SL_DAY1_SHORT   = 1.010  # 1% above entry  (Rule 6, index SHORT)
    TB1_STOCK_SL_DAY1_SHORT   = 1.015  # 1.5% above entry (Rule 6, stock SHORT)
    TB1_INDEX_SL_DAY2_SHORT   = 1.020  # 2% above entry   (Rule 3, index SHORT)
    TB1_STOCK_SL_DAY2_SHORT   = 1.030  # 3% above entry   (Rule 3, stock SHORT)

    def _tb1_is_index_futures(self, inst: str) -> bool:
        """Returns True if instrument is an index futures (NIFTY, BANKNIFTY, etc.)."""
        idx = inst.upper()
        return any(idx.startswith(f) for f in ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"])

    def _tb1_sl_ceiling(self, inst: str, day: int) -> float:
        """Return the SL ceiling multiplier for an instrument. day: 1 or 2+."""
        is_idx = self._tb1_is_index_futures(inst)
        if day == 1:
            return 0.990 if is_idx else 0.985  # LONG direction multiplier
        return 0.980 if is_idx else 0.970

    def _tb1_sl_ceiling_short(self, inst: str, day: int) -> float:
        """Return the SL ceiling multiplier for SHORT positions."""
        is_idx = self._tb1_is_index_futures(inst)
        if day == 1:
            return 1.010 if is_idx else 1.015
        return 1.020 if is_idx else 1.030

    def _tb1_be_threshold(self, inst: str) -> float:
        """Return profit threshold multiplier for break-even move (Rule 4)."""
        return 1.020 if self._tb1_is_index_futures(inst) else 1.030

    def _tb1_compute_day1_sl(self, inst: str, side: str, entry_price: float, recent_level: float) -> float:
        """Compute Rule 6 Day 1 SL: MIN(recent_level, entry × ceiling)."""
        if side == "LONG":
            ceiling_price = entry_price * self._tb1_sl_ceiling(inst, 1)
            return min(recent_level, ceiling_price)
        else:  # SHORT
            ceiling_price = entry_price * self._tb1_sl_ceiling_short(inst, 1)
            return max(recent_level, ceiling_price)

    def _tb1_compute_day2_sl(self, inst: str, side: str, entry_price: float, recent_level: float) -> float:
        """Compute Rule 3 Day 2+ SL: MIN(recent_level, entry × ceiling)."""
        if side == "LONG":
            ceiling_price = entry_price * self._tb1_sl_ceiling(inst, 2)
            return min(recent_level, ceiling_price)
        else:  # SHORT
            ceiling_price = entry_price * self._tb1_sl_ceiling_short(inst, 2)
            return max(recent_level, ceiling_price)

    def _tb1_entry_day(self, entry_iso_date: str) -> int:
        """Return calendar day number (1-based) since entry. Day 1 = entry day."""
        try:
            entry_dt = _dt.fromisoformat(entry_iso_date).date()
            return (_dt.now().date() - entry_dt).days + 1
        except Exception:
            return 1

    def _tb1_compute_unified_sl(self, inst: str, side: str, entries: list,
                                 recent_level: float) -> float:
        """
        Compute unified SL for all entry units.
        Rule 3: each unit's Day 2+ SL = MIN(recent_level, entry_price × ceiling_day2)
        Unified SL = MIN over all units of their respective SLs.
        """
        if side == "LONG":
            worst_sl = recent_level
            for e in entries:
                day = self._tb1_entry_day(e["entry_date"])
                if day >= 2:
                    ceiling = self._tb1_sl_ceiling(inst, 2)
                    worst_sl = min(worst_sl, e["entry_price"] * ceiling)
            return worst_sl
        else:  # SHORT
            worst_sl = recent_level
            for e in entries:
                day = self._tb1_entry_day(e["entry_date"])
                if day >= 2:
                    ceiling = self._tb1_sl_ceiling_short(inst, 2)
                    worst_sl = max(worst_sl, e["entry_price"] * ceiling)
            return worst_sl

    def _enter_instrument(self, signal, realized_pnl: float = 0.0) -> Optional[str]:
        """
        Open a position for a specific instrument.
        - TB1_R2 signals: use TB-1 rules (Rule 6 SL, pyramid support).
        - Other signals: use existing paper/live mode (backward compatible).
        """
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

        entry_cond = signal.reason or (
            f"Crossed Top {signal.metadata.get('r2_top', '?')}"
            if side == "LONG"
            else f"Below Bottom {signal.metadata.get('r2_bot', '?')}"
        )

        # ── TB-1 Entry (from R2 signal) ────────────────────────────────────────
        if signal.strategy_name == "TB1_R2":
            return self._tb1_enter(inst, side, fill_price, qty, entry_cond, realized_pnl)

        # ── Non-TB1 Entry (existing paper/live logic, backward compatible) ──────
        sl_pct   = signal.metadata.get("sl_pct", 3.0)
        sl_price = fill_price * (1 - sl_pct/100) if side == "LONG" else fill_price * (1 + sl_pct/100)
        strat_entry = self.strategies.get(inst, {})
        strat_params = strat_entry.get("config", {}).get("strategy_params", {})

        # ── LIVE MODE: place real order with broker ────────────────────────────
        if self.mode == "LIVE":
            broker = next((b for b in self.brokers.values() if b.is_connected()), None)
            if not broker:
                logger.error(f"[LIVE] No broker connected — cannot place order for {inst}")
                return None
            try:
                order_side = OrderSide.BUY if side == "LONG" else OrderSide.SELL
                order = broker.place_order(
                    instrument=inst,
                    side=order_side,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                )
                actual_fill = order.average_price or fill_price
                sl_price = actual_fill * (1 - sl_pct/100) if side == "LONG" else actual_fill * (1 + sl_pct/100)
                self._add_live_trade({
                    "trade_id": order.order_id,
                    "instrument": inst,
                    "segment": self._infer_segment(inst),
                    "direction": side,
                    "entry_date": _dt.now().isoformat(),
                    "entry_price": actual_fill,
                    "exit_price": None,
                    "quantity": qty,
                    "pnl": None,
                    "reason": entry_cond,
                    "status": "OPEN",
                    "sl": sl_price,
                })
                self._positions[inst] = {
                    "side": side, "entry_price": actual_fill,
                    "entry_condition": entry_cond, "entry_time": _dt.now().isoformat(),
                    "qty": qty, "sl_mode": "auto", "sl_pct": sl_pct,
                    "sl_manual_type": "price", "sl_manual_pct": None, "sl_manual_price": None,
                    "current_sl": sl_price,
                    "be_pct": strat_params.get("be_pct", 2.5),
                    "pyramiding_mode": "auto", "pyramiding_on": False, "pyramiding_lots": 1,
                    "exit_mode": "auto", "exit_manual_type": "price", "exit_manual_val": 0,
                    "rollover": True, "realized_pnl": realized_pnl, "be_done": False, "pyramids": 0,
                    "order_id": order.order_id,
                }
                logger.info(
                    f"[LIVE] Entry {side}: {inst} × {qty} @ ₹{actual_fill:.2f} "
                    f"| Order: {order.order_id} | SL: ₹{sl_price:.2f}"
                )
                return order.order_id
            except Exception as e:
                logger.error(f"[LIVE] Order failed for {inst}: {e}")
                return None

        # ── PAPER MODE ───────────────────────────────────────────────────────
        brokerage = self.paper.brokerage_per_lot * qty
        self.paper.capital -= brokerage

        self._positions[inst] = {
            "side":           side,
            "entry_price":    fill_price,
            "entry_condition": entry_cond,
            "entry_time":     _dt.now().isoformat(),
            "qty":            qty,
            "sl_mode":        "auto",
            "sl_pct":         sl_pct,
            "sl_manual_type": "price",
            "sl_manual_pct":  None,
            "sl_manual_price":None,
            "current_sl":      sl_price,
            "be_pct":           strat_params.get("be_pct", 2.5),
            "pyramiding_mode":  "auto",
            "pyramiding_on":    False,
            "pyramiding_lots":  1,
            "exit_mode":        "auto",
            "exit_manual_type": "price",
            "exit_manual_val":  0,
            "rollover":        True,
            "realized_pnl":    realized_pnl,
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

    # ── TB-1 Position Management ─────────────────────────────────────────────

    def _tb1_enter(self, inst: str, side: str, fill_price: float,
                    qty: int, entry_cond: str, realized_pnl: float) -> Optional[str]:
        """
        Handle TB-1 R2 entry (Rule 2): adds a new entry unit.
        - First entry: Rule 6 Day 1 SL (MIN of recent level or entry × ceiling)
        - Pyramid entry: add to entries list, update initial entry's SL to new bottom,
                        new entry gets Rule 6 Day 1 SL.
        """
        existing = self._positions.get(inst)
        today_str = _dt.now().strftime("%Y-%m-%d")

        # ── Get confirmed R1 level for SL calculation ──────────────────────
        confirmed_level = (
            self._r1_monitor.get_confirmed_bot(inst) if side == "LONG"
            else self._r1_monitor.get_confirmed_top(inst)
        )
        if confirmed_level is None:
            logger.warning(f"[TB1] {inst}: No confirmed R1 level — cannot compute SL")
            return None

        # ── First entry: create new TB-1 position ─────────────────────────
        if existing is None:
            entry_sl = self._tb1_compute_day1_sl(inst, side, fill_price, confirmed_level)
            pos = {
                "side":              side,
                "entries":           [{"entry_price": fill_price, "entry_date": today_str, "sl": entry_sl}],
                "unified_sl":        entry_sl,
                "qty":               qty,
                "entry_condition":   entry_cond,
                "qty_per_entry":     qty,
                "be_done":           False,
                "be_trigger_price":  fill_price * self._tb1_be_threshold(inst),
                "gap_tracking":      {"prev_close": None, "gap_15m_low": None, "gap_15m_high": None, "gap_handled": False},
                "rollover":          True,
                "realized_pnl":      realized_pnl,
                "tb1_mode":          True,   # flag: this is a TB-1 managed position
            }
            self._positions[inst] = pos

            if self.mode == "LIVE":
                broker = next((b for b in self.brokers.values() if b.is_connected()), None)
                if broker:
                    try:
                        order_side = OrderSide.BUY if side == "LONG" else OrderSide.SELL
                        order = broker.place_order(inst, order_side, qty, OrderType.MARKET)
                        actual = order.average_price or fill_price
                        pos["entries"][0]["entry_price"] = actual
                        pos["entries"][0]["sl"] = self._tb1_compute_day1_sl(inst, side, actual, confirmed_level)
                        pos["unified_sl"] = pos["entries"][0]["sl"]
                        pos["be_trigger_price"] = actual * self._tb1_be_threshold(inst)
                        self._add_live_trade({
                            "trade_id": order.order_id, "instrument": inst,
                            "segment": self._infer_segment(inst), "direction": side,
                            "entry_date": _dt.now().isoformat(), "entry_price": actual,
                            "exit_price": None, "quantity": qty, "pnl": None,
                            "reason": entry_cond, "status": "OPEN", "sl": pos["unified_sl"],
                        })
                        self._log_trade(inst, side, qty, actual, pos["unified_sl"], f"R2 Pyramid #1 | {entry_cond}")
                        return order.order_id
                    except Exception as e:
                        logger.error(f"[LIVE] TB1 entry failed for {inst}: {e}")
                        return None

            # Paper mode
            self.paper.capital -= self.paper.brokerage_per_lot * qty
            self.paper._trade_counter += 1
            trade_id = f"PAPER-{_dt.now().strftime('%Y%m%d')}-{self.paper._trade_counter:04d}"
            self._log_trade(inst, side, qty, fill_price, entry_sl, f"R2 Entry #1 | {entry_cond}")
            return trade_id

        # ── Pyramid entry: already in position ───────────────────────────────
        if existing.get("tb1_mode") and existing["side"] == side:
            # Same direction: add pyramid unit
            new_entry_sl = self._tb1_compute_day1_sl(inst, side, fill_price, confirmed_level)
            existing["entries"].append({
                "entry_price": fill_price,
                "entry_date":  today_str,
                "sl":          new_entry_sl,
            })
            # Update initial entry's SL to new confirmed bottom (R3 pyramid rule)
            if existing["entries"]:
                existing["entries"][0]["sl"] = confirmed_level
            existing["unified_sl"] = confirmed_level
            existing["be_trigger_price"] = (
                min(e["entry_price"] for e in existing["entries"])
                * self._tb1_be_threshold(inst)
            )
            logger.info(
                f"[TB1] {inst}: PYRAMID {side} # {len(existing['entries'])} @ ₹{fill_price:.2f} "
                f"| New SL={new_entry_sl:.2f} | Unified SL→₹{existing['unified_sl']:.2f}"
            )
            if self.mode == "LIVE":
                broker = next((b for b in self.brokers.values() if b.is_connected()), None)
                if broker:
                    try:
                        order_side = OrderSide.BUY if side == "LONG" else OrderSide.SELL
                        order = broker.place_order(inst, order_side, qty, OrderType.MARKET)
                        actual = order.average_price or fill_price
                        existing["entries"][-1]["entry_price"] = actual
                        existing["entries"][-1]["sl"] = self._tb1_compute_day1_sl(inst, side, actual, confirmed_level)
                        self._add_live_trade({
                            "trade_id": order.order_id, "instrument": inst,
                            "segment": self._infer_segment(inst), "direction": side,
                            "entry_date": _dt.now().isoformat(), "entry_price": actual,
                            "exit_price": None, "quantity": qty, "pnl": None,
                            "reason": entry_cond, "status": "OPEN", "sl": existing["unified_sl"],
                        })
                        return order.order_id
                    except Exception as e:
                        logger.error(f"[LIVE] TB1 pyramid entry failed for {inst}: {e}")
                        return None
            self.paper.capital -= self.paper.brokerage_per_lot * qty
            self.paper._trade_counter += 1
            trade_id = f"PAPER-{_dt.now().strftime('%Y%m%d')}-{self.paper._trade_counter:04d}"
            self._log_trade(inst, side, qty, fill_price, existing["unified_sl"],
                            f"R2 Pyramid #{len(existing['entries'])} | {entry_cond}")
            return trade_id

        # ── Reversal: different direction ───────────────────────────────────
        # Close existing, then open new (TB-1 reversal = Day 1 of new direction)
        self._tb1_exit(inst, reason=f"R2 Reversal: {entry_cond}", exit_price=None)
        return self._tb1_enter(inst, side, fill_price, qty, entry_cond, realized_pnl=0.0)

    def _tb1_exit(self, inst: str, reason: str, exit_price: float = None) -> Optional[Any]:
        """Exit all units of a TB-1 position. Returns trade record."""
        pos = self._positions.get(inst)
        if not pos or not pos.get("tb1_mode"):
            return None

        price = exit_price or pos.get("unified_sl", 0)
        total_qty = pos["qty_per_entry"] * len(pos["entries"])
        avg_entry = sum(e["entry_price"] for e in pos["entries"]) / len(pos["entries"])

        if pos["side"] == "LONG":
            pnl_raw = (price - avg_entry) * total_qty
        else:
            pnl_raw = (avg_entry - price) * total_qty

        brokerage = self.paper.brokerage_per_lot * len(pos["entries"])
        pnl = pnl_raw - brokerage

        if self.mode != "LIVE":
            self.paper.capital += pnl

        self.paper._trade_counter += 1
        trade_id = f"PAPER-{_dt.now().strftime('%Y%m%d')}-{self.paper._trade_counter:04d}"
        trade = self.paper.PaperTrade(
            trade_id=trade_id, instrument=inst, direction=pos["side"],
            entry_date=pos["entries"][0]["entry_date"], entry_price=avg_entry,
            exit_date=_dt.now().isoformat(), exit_price=price,
            quantity=total_qty, pnl=round(pnl, 2),
            pyramids=len(pos["entries"]) - 1, reason=reason,
            capital_after=round(self.paper.capital, 2),
        )
        self.paper.trades.append(trade)
        logger.info(
            f"[TB1] Exit {pos['side']}: {inst} × {total_qty} @ ₹{price:.2f} "
            f"| P&L: ₹{pnl:,.2f} | [{reason}] | Capital: ₹{self.paper.capital:,.2f}"
        )
        del self._positions[inst]
        strat = self.strategies.get(inst, {}).get("strategy")
        if strat:
            strat.clear_position()
        return trade

    def _manage_tb1_positions(self):
        """
        Run TB-1 Rules 3/4/5 on every open position, every tick.
        R3  — Day 2+ unified SL update (Rule 3)
        R4  — Break-even move (Rule 4)
        R5  — Gap day handling (Rule 5)
        Exit — LTP hit unified SL
        """
        to_exit = []

        for inst, pos in list(self._positions.items()):
            if not pos.get("tb1_mode"):
                continue

            side      = pos["side"]
            entries   = pos["entries"]
            recent_lvl = pos.get("recent_level", entries[-1]["sl"] if entries else 0)
            broker    = self._get_broker_for_instrument(inst)

            # ── Poll live LTP ───────────────────────────────────────────────
            ltp = None
            if broker and broker.is_connected():
                try:
                    q = broker.get_quote(inst)
                    ltp = float(q.get("last_price", 0)) if q else None
                except Exception:
                    pass

            if ltp is None or ltp <= 0:
                continue

            # ── R5: Fetch today's first 15-min candle at market open ─────────
            # Must be done once per position at 09:15 IST window (09:15-09:31)
            gt = pos.get("gap_tracking", {})
            if gt.get("prev_close") and gt.get("gap_15m_low") is None:
                now = _dt.now()
                t   = now.time()
                # Check if we're within 09:15-09:31 IST (market open + first 15 min)
                if (t.hour == 9 and 15 <= t.minute <= 31):
                    try:
                        to_ts   = int(now.timestamp())
                        from_ts = to_ts - (16 * 60)   # last ~16 minutes
                        bars = broker.get_candles(inst, "15m", from_ts, to_ts) if broker else []
                        if bars:
                            bar = bars[0]   # oldest = first 15-min bar of the day
                            gt["gap_15m_low"]  = bar.low
                            gt["gap_15m_high"] = bar.high
                            gt["gap_open"]     = bar.open
                            gt["gap_tracked_date"] = now.strftime("%Y-%m-%d")
                            logger.info(
                                f"[R5] {inst}: gap tracked | "
                                f"prev_close={gt['prev_close']:.2f} | "
                                f"gap_open={bar.open:.2f} | "
                                f"15m_low={bar.low:.2f} / high={bar.high:.2f}"
                            )
                    except Exception as e:
                        logger.warning(f"[R5] Candle fetch failed for {inst}: {e}")

            # ── R3: Update unified SL for Day 2+ entries ─────────────────────
            # (already done by _tb1_enter on pyramid — only recalculate when day rolls)
            day = self._tb1_entry_day(entries[-1]["entry_date"])
            if day >= 2:
                unified = self._tb1_compute_unified_sl(inst, side, entries, recent_lvl)
                old_sl  = pos.get("unified_sl", 0)
                if abs(unified - old_sl) > 0.01:
                    pos["unified_sl"] = unified
                    logger.info(f"[R3] {inst} Day {day}: unified SL → {unified:.2f} (was {old_sl:.2f})")

            # ── R4: Break-even move ──────────────────────────────────────────
            if not pos.get("be_done"):
                be_price = pos.get("be_trigger_price", 0)
                if be_price > 0:
                    if side == "LONG" and ltp >= be_price:
                        pos["be_done"] = True
                        pos["unified_sl"] = entries[0]["entry_price"]
                        logger.info(f"[R4] {inst} LONG: BE done @ {ltp:.2f} | SL → entry ₹{entries[0]['entry_price']:.2f}")
                    elif side == "SHORT" and ltp <= be_price:
                        pos["be_done"] = True
                        pos["unified_sl"] = entries[0]["entry_price"]
                        logger.info(f"[R4] {inst} SHORT: BE done @ {ltp:.2f} | SL → entry ₹{entries[0]['entry_price']:.2f}")

            # ── R5: Gap day check ─────────────────────────────────────────────
            gt = pos.get("gap_tracking", {})
            tracked_date = gt.get("gap_tracked_date", "")
            today_str   = _dt.now().strftime("%Y-%m-%d")
            if (tracked_date == today_str
                    and not gt.get("gap_handled")
                    and gt.get("prev_close")
                    and gt.get("gap_15m_low") is not None):
                gap_open = gt["gap_open"]
                sl       = pos.get("unified_sl", entries[-1]["sl"])

                if side == "LONG":
                    gap_pct = (sl - gap_open) / sl if sl > 0 else 0
                    if gap_pct > 0 and gap_pct < 0.02:
                        # Gap < 2% below SL: wait for 15m low break → reverse to SHORT
                        if ltp < gt["gap_15m_low"]:
                            logger.warning(
                                f"[R5] {inst} LONG: gap < 2%, 15m low broken → "
                                f"exit LONG + reverse SHORT @ {ltp:.2f}"
                            )
                            to_exit.append((inst, "R5 Gap SHORT reversal", ltp))
                    elif gap_pct >= 0.02:
                        # Gap ≥ 2%: exit LONG only, no re-entry today
                        logger.warning(
                            f"[R5] {inst} LONG: gap ≥ 2% ({gap_pct*100:.1f}%) → exit only @ {ltp:.2f}"
                        )
                        to_exit.append((inst, f"R5 Gap exit (>{gap_pct*100:.1f}% gap)", ltp))

                elif side == "SHORT":
                    gap_pct = (gap_open - sl) / sl if sl > 0 else 0
                    if gap_pct > 0 and gap_pct < 0.02:
                        if ltp > gt["gap_15m_high"]:
                            logger.warning(
                                f"[R5] {inst} SHORT: gap < 2%, 15m high broken → "
                                f"exit SHORT + reverse LONG @ {ltp:.2f}"
                            )
                            to_exit.append((inst, "R5 Gap LONG reversal", ltp))
                    elif gap_pct >= 0.02:
                        logger.warning(
                            f"[R5] {inst} SHORT: gap ≥ 2% ({gap_pct*100:.1f}%) → exit only @ {ltp:.2f}"
                        )
                        to_exit.append((inst, f"R5 Gap exit (>{gap_pct*100:.1f}% gap)", ltp))

                # Mark gap handled so we don't repeat
                gt["gap_handled"] = True

            # ── Exit check: LTP hit unified SL ─────────────────────────────────
            sl = pos.get("unified_sl", entries[-1]["sl"])
            if sl > 0:
                if side == "LONG" and ltp <= sl:
                    logger.warning(f"[EXIT] {inst} LONG: LTP {ltp:.2f} ≤ SL {sl:.2f}")
                    to_exit.append((inst, "SL hit", sl))
                elif side == "SHORT" and ltp >= sl:
                    logger.warning(f"[EXIT] {inst} SHORT: LTP {ltp:.2f} ≥ SL {sl:.2f}")
                    to_exit.append((inst, "SL hit", sl))

        # ── Execute exits (outside dict iteration to avoid mutation during iteration) ──
        for inst, reason, price in to_exit:
            try:
                self._tb1_exit(inst, reason=reason, exit_price=price)
            except Exception as e:
                logger.error(f"[EXIT] _tb1_exit failed for {inst}: {e}")

    def _log_trade(self, inst: str, side: str, qty: int, price: float, sl: float, note: str):
        """Log paper trade entry."""
        logger.info(
            f"[PAPER] Entry {side}: {inst} × {qty} @ ₹{price:.2f} "
            f"| SL: ₹{sl:.2f} | {note} | Capital: ₹{self.paper.capital:,.2f}"
        )

    def _exit_instrument(self, inst: str, reason: str,
                         exit_price: float = None) -> Optional[Any]:
        """Close position for a specific instrument. Returns PaperTrade or None."""
        pos = self._positions.get(inst)
        if not pos:
            return None

        # ── TB-1 positions: delegate to TB1 exit ─────────────────────────────
        if pos.get("tb1_mode"):
            return self._tb1_exit(inst, reason, exit_price)

        price    = exit_price or pos["current_sl"]
        fill_side = "SELL" if pos["side"] == "LONG" else "BUY"
        slip     = self.paper.slippage_pct / 100
        fill_price = round(price * (1 + slip if fill_side == "BUY" else -slip), 2)

        mult  = 1 + pos["pyramids"]
        qty   = pos["qty"] * mult

        # ── LIVE MODE: place closing order with broker ──────────────────────
        if self.mode == "LIVE":
            broker = next((b for b in self.brokers.values() if b.is_connected()), None)
            live_trade = next((t for t in self._live_trades if t.get("instrument") == inst and t.get("status") == "OPEN"), None)
            if broker and live_trade:
                try:
                    order_side = OrderSide.SELL if pos["side"] == "LONG" else OrderSide.BUY
                    order = broker.place_order(
                        instrument=inst,
                        side=order_side,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                    )
                    actual_fill = order.average_price or fill_price
                    if pos["side"] == "LONG":
                        pnl_raw = (actual_fill - pos["entry_price"]) * qty
                    else:
                        pnl_raw = (pos["entry_price"] - actual_fill) * qty
                    brokerage = self.paper.brokerage_per_lot * mult
                    pnl = pnl_raw - brokerage
                    live_trade.update({
                        "exit_date": _dt.now().isoformat(),
                        "exit_price": actual_fill,
                        "pnl": round(pnl, 2),
                        "status": "CLOSED",
                    })
                    logger.info(
                        f"[LIVE] Exit {pos['side']}: {inst} × {qty} @ ₹{actual_fill:.2f} "
                        f"| Order: {order.order_id} | P&L: ₹{pnl:,.2f}"
                    )
                except Exception as e:
                    logger.error(f"[LIVE] Exit order failed for {inst}: {e}")
            del self._positions[inst]
            strat = self.strategies.get(inst, {}).get("strategy")
            if strat:
                strat.clear_position()
            return None

        # ── PAPER MODE ───────────────────────────────────────────────────────
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
            try:
                self._fetch_and_process()
            except Exception as e:
                logger.error(f"[Tick] _fetch_and_process error: {e}")
            time.sleep(self._tick_interval)

    async def _run_loop_async(self):
        """Async tick loop — runs inside asyncio event loop so it cooperates with HTTP/WS servers."""
        while self._running:
            try:
                # Run the heavy synchronous work in a thread pool so it doesn't block the event loop
                await asyncio.to_thread(self._fetch_and_process)
            except Exception as e:
                logger.error(f"[Tick] _fetch_and_process error: {e}")
            await asyncio.sleep(self._tick_interval)

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
        # Merge config instruments + strategies + watchlist base symbols for live LTP on dashboard
        # Watchlist instruments are stored with base symbol keys in _watchlist
        # Also always include ticker bar symbols: NIFTY, BANKNIFTY, GOLD, SILVER
        # Also include all position instruments so their LTP shows live in Trade Log
        watchlist_symbols = set(self._watchlist.keys())
        ticker_symbols = {"NIFTY", "BANKNIFTY", "GOLD", "SILVER"}
        position_instruments = set(self._positions.keys()) | set(self.paper._db_positions.keys())
        all_instrument_keys = (
            set(config.INSTRUMENTS.keys())
            | set(self.strategies.keys())
            | watchlist_symbols
            | ticker_symbols
            | position_instruments
        )
        quotes = {}
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
            # Yahoo Finance quote fallback — skip in PAPER mode since M-Stock provides live quotes
            # for index futures and NSE cash; SEPFUT symbols return 404 from Yahoo anyway
            if self.mode == "PAPER":
                continue
            try:
                sym = self._resolve_yf_symbol(inst_key)
                import urllib.request, json
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym.replace(' ', '+')}?interval=1d&range=1d"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                result = data.get("chart", {}).get("result", [{}])[0]
                meta  = result.get("meta", {})
                price = float(meta.get("regularMarketPrice", 0))
                prev_close = float(meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0) or 0)
                if price > 0:
                    change = round(price - prev_close, 2) if prev_close > 0 else 0
                    change_pct = round((change / prev_close) * 100, 2) if prev_close > 0 else 0
                    quotes[inst_key] = {
                        "last_price": price,
                        "bid":        price,
                        "ask":        price,
                        "volume":     int(meta.get("regularMarketVolume", 0)),
                        "timestamp":  int(meta.get("regularMarketTime", 0)),
                        "change":     change,
                        "change_pct": change_pct,
                    }
                    logger.info(f"[QUOTE] {inst_key} -> {sym}: Rs.{price} ({change_pct:+.2f}%)")
                else:
                    logger.warning(f"[QUOTE] {inst_key} -> {sym}: no market price")
            except Exception as ex:
                logger.warning(f"[QUOTE] {inst_key}: YF fetch failed - {ex}")

        # ── Compute closed P&L per instrument ──────────────────────────────────
        closed_pnl_per_inst: Dict[str, float] = {}
        for t in self.paper.trades:
            if t.pnl is None:
                continue
            inst = t.instrument
            closed_pnl_per_inst[inst] = closed_pnl_per_inst.get(inst, 0) + t.pnl

        # ── Top bar ticker: copy index futures quotes to base symbol keys ───
        # Dashboard ticker bar looks for 'NIFTY', 'BANKNIFTY' (not contract names).
        for contract_key, base_key in [("NIFTY26SEPFUT", "NIFTY"), ("BANKNIFTY26SEPFUT", "BANKNIFTY")]:
            if contract_key in quotes and base_key not in quotes:
                quotes[base_key] = quotes[contract_key]

        # ── Stock futures: also store quotes under base symbol keys ─────────────────
        # Dashboard's getBaseSymbol() strips month+digit+FUT, producing base symbols
        # like "BHEL" from "BHELSEPFUT26". Ensure both key forms exist in the broadcast.
        import re as _re
        for full_key, qdata in list(quotes.items()):
            base = _re.sub(r'\d+$', '', full_key)
            base = _re.sub(r'FUT(FUTURES)?$', '', base).strip()
            base = base.strip()
            if base and base != full_key and base not in quotes:
                quotes[base] = qdata

        # ── Always fetch change_pct from Yahoo Finance for ticker bar ─────────────
        # Broker quotes don't carry change_pct — merge it in from YF for the 4 tickers
        _TICKER_SYMBOLS = {
            "NIFTY": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "GOLD": "GC=F",
            "SILVER": "SI=F",
        }
        for ticker_key, yf_sym in _TICKER_SYMBOLS.items():
            try:
                import urllib.request, json
                url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym.replace(' ', '+')}"
                       "?interval=1d&range=1d")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read())
                result = data.get("chart", {}).get("result", [{}])[0]
                meta = result.get("meta", {})
                price = float(meta.get("regularMarketPrice", 0) or 0)
                prev = float(meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0) or 0)
                if price > 0 and prev > 0:
                    change = round(price - prev, 2)
                    change_pct = round((change / prev) * 100, 2)
                    if ticker_key in quotes:
                        quotes[ticker_key]["change"] = change
                        quotes[ticker_key]["change_pct"] = change_pct
                    else:
                        quotes[ticker_key] = {
                            "last_price": price,
                            "change": change,
                            "change_pct": change_pct,
                        }
            except Exception:
                pass  # YF unavailable — ticker shows price without % change

        # ── Per-instrument positions ─────────────────────────────────────────
        # Merge engine positions (self._positions) with DB-loaded positions (paper._db_positions).
        # self._positions is empty after engine restart — all DB positions live in paper._db_positions.
        # DB fields differ from engine fields: initial_lots→qty, sl_value→sl_pct, direction→side
        all_positions: Dict[str, dict] = {}
        for inst, db_pos in self.paper._db_positions.items():
            # Normalize DB field names to engine field names
            normalized = dict(db_pos)
            if "qty" not in normalized and "initial_lots" in normalized:
                normalized["qty"] = normalized.pop("initial_lots")
            if "sl_pct" not in normalized and "sl_value" in normalized:
                normalized["sl_pct"] = normalized.pop("sl_value")
            if "pyramids" not in normalized and "pyramid_lots" in normalized:
                normalized["pyramids"] = normalized.pop("pyramid_lots")
            # direction (DB) → side (engine); keep both for dashboard compatibility
            if "direction" in normalized:
                normalized["side"] = normalized["direction"]
            elif "side" in normalized and "direction" not in normalized:
                normalized["direction"] = normalized["side"]
            # Add segment_type to DB positions (not stored in DB, computed on the fly)
            normalized["segment_type"] = self._infer_segment(inst)
            all_positions[inst] = normalized
        for inst, eng_pos in self._positions.items():
            if inst in all_positions:
                # Merge engine fields over DB, keep DB segment_type
                seg = all_positions[inst].get("segment_type")
                all_positions[inst].update(eng_pos)
                if seg:
                    all_positions[inst]["segment_type"] = seg
            else:
                eng_pos = dict(eng_pos)
                eng_pos["segment_type"] = self._infer_segment(inst)
                all_positions[inst] = eng_pos

        positions_state: Dict[str, dict] = {}
        for inst, pos in all_positions.items():
            # Try LTP by contract name first, then by base symbol (e.g. ICICIBANKSEPFUT26 → ICICIBANK)
            base = inst[:-9] if inst.endswith("FUT26") or inst.endswith("FUT") else inst
            ltp = (
                (quotes.get(inst) or {}).get("last_price") or
                (quotes.get(base) or {}).get("last_price") or
                pos.get("entry_price") or
                0
            )
            mult  = 1 + pos.get("pyramids", 0)
            qty   = pos.get("qty") or 1
            entry_price = pos.get("entry_price") or 0
            # Use side (engine standard) for all position logic
            side = pos.get("side") or pos.get("direction") or None
            direction = pos.get("direction") or pos.get("side") or None  # both names for dashboard compat
            if side == "LONG":
                unreal_pnl = (ltp - entry_price) * qty
            elif side == "SHORT":
                unreal_pnl = (entry_price - ltp) * qty
            else:
                unreal_pnl = 0

            # Compute auto SL based on day
            entry_dt  = pos.get("entry_time", "") or pos.get("entry_date", "")
            days_in   = 1
            if entry_dt:
                try:
                    days_in = max(1, (_dt.now() - _dt.fromisoformat(entry_dt)).days)
                except Exception:
                    pass

            # SL%: if 0 or missing, use sensible defaults (DB stores 0 for old positions)
            raw_sl_pct = pos.get("sl_pct")
            seg_type = pos.get("segment_type", "STOCK_FUTURES")
            if raw_sl_pct is None or raw_sl_pct == 0:
                sl_pct = 1.0 if seg_type == "INDEX_FUTURES" else 1.5
            else:
                sl_pct = float(raw_sl_pct)
            be_pct = pos.get("be_pct", 2.5)
            entry_p = entry_price

            if side == "LONG":
                be_price  = entry_p * (1 + be_pct / 100)
                pct3_price = entry_p * 0.97
                sl_auto = be_price if days_in >= 2 else entry_p * (1 - sl_pct / 100)
                if days_in >= 2:
                    sl_auto = min(be_price, pct3_price)
            elif side == "SHORT":
                be_price  = entry_p * (1 - be_pct / 100)
                pct3_price = entry_p * 1.03
                sl_auto = entry_p * (1 + sl_pct / 100)
                if days_in >= 2:
                    sl_auto = max(be_price, pct3_price)
            else:
                be_price  = 0
                pct3_price = 0
                sl_auto = 0

            # SL: always recalculate in auto mode (handles restored positions with stale 0 values)
            sl_mode = pos.get("sl_mode") or "auto"
            if sl_mode == "auto":
                current_sl = round(sl_auto, 2)
            elif pos.get("sl_manual_price"):
                current_sl = pos["sl_manual_price"]
            else:
                current_sl = round(sl_auto, 2)   # fallback to auto

            # Get prev_top / prev_bottom from strategy's swing points.
            # strategies dict keyed by BASE symbol (see add_to_watchlist), not full contract.
            # R1 monitor also uses base symbol. Convert inst (full contract) to base for lookup.
            prev_top_val = float(pos.get("prev_top") or 0)
            prev_bot_val = float(pos.get("prev_bottom") or 0)
            # Derive base symbol from full contract name (e.g. BHELSEPFUT26 → BHEL)
            base_sym = inst
            for suf in ("FUT", "FUTURES"):
                base_sym = base_sym.replace(suf, "")
            base_sym = re.sub(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}$", "", base_sym)
            base_sym = re.sub(r"^\d+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)", "", base_sym)
            base_sym = re.sub(r"\d+$", "", base_sym).strip()
            # Try base-symbol lookup in strategies (engine stores by base symbol)
            strat_entry = self.strategies.get(base_sym) or self.strategies.get(inst, {})
            strat_obj = strat_entry.get("strategy") if strat_entry else None
            if strat_obj:
                tops = getattr(strat_obj, "_recent_tops", [])
                bots = getattr(strat_obj, "_recent_bots", [])
                if tops:
                    prev_top_val = float(tops[-1][1])
                if bots:
                    prev_bot_val = float(bots[-1][1])
            # Fallback: also check R1 monitor using base symbol (strategies are keyed by base sym)
            if prev_top_val == 0:
                m_top = self._r1_monitor.get_confirmed_top(base_sym)
                if m_top:
                    prev_top_val = float(m_top)
            if prev_bot_val == 0:
                m_bot = self._r1_monitor.get_confirmed_bot(base_sym)
                if m_bot:
                    prev_bot_val = float(m_bot)

            # ── TB-1: map recent_level to prev_top/bottom for dashboard display ──
            # recent_level = most recent CONFIRMED swing point used as SL reference.
            # LONG: entry above confirmed TOP → recent_level = confirmed TOP → shown as prev-top
            # SHORT: entry below confirmed BOTTOM → recent_level = confirmed BOTTOM → shown as prev-bottom
            if pos.get("tb1_mode") and pos.get("recent_level"):
                rl = float(pos["recent_level"])
                if pos["side"] == "LONG":
                    prev_top_val = rl    # recent_level = confirmed TOP → shown as prev-top
                else:
                    prev_bot_val = rl    # recent_level = confirmed BOTTOM → shown as prev-bottom

            positions_state[inst] = {
                **pos,
                "unrealized_pnl": round(unreal_pnl, 2),
                "ltp":             ltp,
                "prev_top":        prev_top_val,
                "prev_bottom":     prev_bot_val,
                "days_in_trade":   days_in,
                "sl_auto_price":   round(sl_auto, 2),
                "current_sl":      current_sl,
                "segment_type":    self._infer_segment(inst),
                # Always re-infer sector (overrides stale DB values like "AUTO")
                "sector":         self._infer_sector(inst),
                # Ensure both field names exist for dashboard compatibility
                "side":            side,
                "direction":       direction,
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
            # Full watchlist data keyed by instrument symbol — used by dashboard for live LTP lookups
            "watchlist_data":  {k: v for k, v in self._watchlist.items()},
            # TB-1 R1 confirmed levels from daily candle monitor
            "r1_levels": {
                inst: {
                    "confirmed_top":  self._r1_monitor.get_confirmed_top(inst),
                    "confirmed_bot":  self._r1_monitor.get_confirmed_bot(inst),
                    "tops":  self._r1_monitor.get_levels(inst).get("tops", []) if self._r1_monitor.get_levels(inst) else [],
                    "bots":  self._r1_monitor.get_levels(inst).get("bots", []) if self._r1_monitor.get_levels(inst) else [],
                }
                for inst in self.strategies
            },
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

            # Base symbol for live quote lookups (cache is keyed by base symbol, e.g. "ASHOKLEY")
            # Full contract for candles and trading (e.g. "ASHOKLEYSEPFUT26")
            base_inst = instrument.strip().upper()
            inst = self._resolve_futures(base_inst)
            result = {"success": False, "instrument": inst, "mode": mode, "message": ""}

            # ── Step 1: Get live LTP first (fastest — from streaming cache) ────
            # Live quote cache is keyed by BASE symbol, NOT full contract
            broker = next((b for b in self.brokers.values() if b.is_connected()), None)
            live_ltp = None
            if broker and hasattr(broker, "get_live_quote"):
                live_q = broker.get_live_quote(base_inst)  # Use base symbol!
                if live_q and live_q.get("last_price", 0) > 0:
                    live_ltp = live_q["last_price"]
                    logger.info(f"[hit_trade] {base_inst} live LTP: Rs.{live_ltp}")
                else:
                    logger.info(f"[hit_trade] {base_inst} live quote not in cache yet (will use candles)")

            # ── Step 2: Fetch candles for swing high/low (direction detection) ───
            candles = []
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

            # ── Step 3: Auto-detect direction ────────────────────────────────────
            # Use last 20 candles to find swing high/low
            lookback = min(20, len(candles))
            recent = candles[-lookback:]
            highs = [c.high for c in recent]
            lows  = [c.low  for c in recent]
            swing_high = max(highs)
            swing_low  = min(lows)
            current_close = candles[-1].close

            # Use live LTP if available, otherwise current candle close
            price_for_direction = live_ltp if live_ltp else current_close

            # Direction: LONG if breaking above swing high, SHORT if below swing low
            direction = None
            if price_for_direction > swing_high:
                direction = "LONG"
            elif price_for_direction < swing_low:
                direction = "SHORT"

            if not direction:
                result["message"] = f"No hit — {inst} in range (H:₹{swing_high:.0f} L:₹{swing_low:.0f} C:₹{price_for_direction:.0f})"
                await ws.send(json.dumps({"type": "notification", **result}))
                return

            # ── Step 4: Get entry price (LTP) ───────────────────────────────────
            entry_price = live_ltp if live_ltp else current_close  # MARKET order — use live LTP if available

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
            # Accepts: {instruments: ["NAME", ...]}  OR  {instruments: [{inst:"NAME", strategy:"SAR_TOP_BOTTOM", sector:"PSU_BANK"}, ...]}
            raw_incoming = data.get("instruments", [])

            # Normalise to list of {inst, strategy, sector} objects
            incoming_objs = []
            for item in raw_incoming:
                if isinstance(item, dict):
                    incoming_objs.append({
                        "inst":     item.get("inst", item.get("instrument", "")),
                        "strategy": item.get("strategy", "SAR_TOP_BOTTOM"),
                        "sector":   item.get("sector", "OTHER"),
                    })
                else:
                    incoming_objs.append({"inst": str(item), "strategy": "SAR_TOP_BOTTOM", "sector": "OTHER"})

            # Remove instruments no longer in dashboard's list
            incoming_names = {o["inst"] for o in incoming_objs}
            removed = []
            for inst in list(self._watchlist.keys()):
                if inst not in incoming_names:
                    self._remove_strategy(inst)
                    del self._watchlist[inst]
                    removed.append(inst)
            if removed:
                self._unsubscribe_instruments(removed)

            # Keep existing instruments, add new ones from dashboard
            added = []
            for obj in incoming_objs:
                inst     = obj["inst"].strip()
                strategy = obj.get("strategy", "SAR_TOP_BOTTOM")
                sector   = obj.get("sector", "OTHER")
                if not inst:
                    continue
                if inst not in self._watchlist:
                    self._apply_strategy(inst, strategy, {})
                    self._watchlist[inst] = {
                        "strategy":        strategy,
                        "sector":          sector,
                        "strategy_params":  {},
                    }
                    added.append(inst)
                    self.strategies[inst] = self.strategies.get(inst, {})

            # Subscribe new instruments to live quote streaming
            if added:
                self._subscribe_instruments(added)

            self._save_watchlist()
            await self.broadcast_state()

        elif cmd == "connect_broker":
            name = data.get("broker", "")
            # Run blocking broker connection in background thread to avoid blocking event loop
            ok = await asyncio.to_thread(self.connect_broker, name)
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
            self._unsubscribe_instruments([inst])
            self._save_watchlist()
            await self.broadcast_state()
            await ws.send(json.dumps({
                "type":    "notification",
                "message": f"Removed {inst} from watchlist",
                "success": True,
            }))

        elif cmd == "add_position":
            # Add an instrument directly to the Trade Log (WAITING status — no entry yet).
            # Dashboard GO button uses this to add a futures instrument to Trade Log without
            # triggering strategy signal matching.
            try:
                raw = data.get("instrument", "").strip().upper()
                if not raw:
                    await _safe_send(ws, {"type": "notification", "success": False, "message": "No instrument specified"})
                    return

                inst = self._resolve_futures(raw)
                raw_sector = data.get("sector", "AUTO")
                # Infer real sector when AUTO/unknown is passed
                if raw_sector in ("AUTO", "", None) or raw_sector.startswith("SEC_"):
                    sector = self._infer_sector(raw)
                else:
                    sector = raw_sector
                initial_lots = int(data.get("initial_lots", 1) or 1)

                if inst in self._positions:
                    await _safe_send(ws, {"type": "notification", "success": True, "message": f"{inst} already in trade log"})
                    return

                self._positions[inst] = {
                    "status": "WAITING",
                    "mode": data.get("mode", "PAPER"),
                    "direction": "WAITING",   # explicit so dashboard shows "WAITING" not "—"
                    "side": "WAITING",
                    "strategy": data.get("strategy", "SAR_TOP_BOTTOM"),
                    "sector": sector,
                    "initial_lots": initial_lots,
                    "qty": initial_lots * 15,  # default lot size
                    "entry_date": None,
                    "entry_price": None,
                    "entry_reason": None,
                    "sl_mode": "auto",
                    "sl_value": 0.0,
                    "sl_manual_price": 0,
                    "current_sl": 0,
                    "pyramiding_mode": "auto",
                    "pyramiding_lots": 1,
                    "rollover": True,
                    "gap_rule": "inactive",
                    "prev_top": 0.0,
                    "prev_bottom": 0.0,
                }
                self.paper._save_position(inst, self._positions[inst])
                logger.info(f"[add_position] Added {inst} to trade log as WAITING")
                # Subscribe new instrument to live quote stream so LTP updates immediately
                self._subscribe_instruments([inst])
                await self.broadcast_state()
                await _safe_send(ws, {
                    "type": "notification",
                    "success": True,
                    "message": f"{inst} added to trade log",
                    "forceRefresh": True,
                })
            except Exception as e:
                logger.error(f"[add_position] Failed: {e}", exc_info=True)
                await _safe_send(ws, {"type": "notification", "success": False, "message": str(e)})

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
            self._subscribe_instruments([inst])
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
            Handles: sl_mode, sl_manual_type, sl_manual_pct, sl_manual_price,
                     be_pct, pyramiding_on, pyramiding_mode, pyramiding_lots, exit_mode,
                     exit_manual_type, exit_manual_val, rollover, gap_rule
            Works for both strategy-applied instruments AND add_position entries.
            """
            inst  = data.get("instrument", "")
            has_strat = inst in self.strategies
            has_pos   = inst in self._positions
            if not has_strat and not has_pos:
                await ws.send(json.dumps({
                    "type": "error", "message": f"{inst} not found", "success": False,
                }))
                return

            # ── Update strategy.params (persisted) ────────────────────────────
            if has_strat:
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

                if "initial_lots" in data:
                    lots = max(1, min(10, int(data["initial_lots"])))
                    pos["initial_lots"] = lots
                    pos["qty"] = lots * 15  # update qty to reflect new lot count

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

                if "gap_rule" in data:
                    pos["gap_rule"] = data["gap_rule"]

                # Recompute current SL if auto (uses Day1 1.5%, Day2+ min(3%, breakeven))
                if pos.get("sl_mode") == "auto":
                    entry_p = pos.get("entry_price") or 0
                    be_pct  = pos.get("be_pct", 2.5)
                    sl_pct  = pos.get("sl_pct", 1.5)
                    days_in = pos.get("days_in_trade", 1)
                    if pos.get("side") == "LONG":
                        be_price  = entry_p * (1 + be_pct / 100)
                        pct3_price = entry_p * 0.97
                        sl_auto = be_price if days_in >= 2 else entry_p * (1 - sl_pct / 100)
                        if days_in >= 2:
                            sl_auto = min(be_price, pct3_price)
                    elif pos.get("side") == "SHORT":
                        be_price  = entry_p * (1 - be_pct / 100)
                        pct3_price = entry_p * 1.03
                        sl_auto = entry_p * (1 + sl_pct / 100)
                        if days_in >= 2:
                            sl_auto = max(be_price, pct3_price)
                    else:
                        be_price  = 0
                        pct3_price = 0
                        sl_auto = 0
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

        # ── Stop ────────────────────────────────────────────────────────────────
        elif cmd == "stop_position":
            """
            Mark a position as STOPPED (prevents auto-close triggers).
            Sends: { command: 'stop_position', instrument: 'M&MSEPFUT26', mode: 'PAPER' }
            """
            inst = data.get("instrument", "")
            all_p = self._all_pos()
            if inst not in all_p:
                await _safe_send(ws, {"type": "notification", "success": False, "message": f"{inst} not found"})
                return
            self._persist_pos(inst, {**all_p[inst], "status": "STOPPED"})
            mode = data.get("mode", "PAPER")
            logger.info(f"[stop_position] Stopped {inst} ({mode})")
            await self.broadcast_state()
            await _safe_send(ws, {
                "type": "notification",
                "message": f"Stopped {inst}",
                "success": True,
            })

        # ── Restart ─────────────────────────────────────────────────────────────
        elif cmd == "restart_position":
            """
            Restart a STOPPED or WAITING position back to ACTIVE.
            Sends: { command: 'restart_position', instrument: 'M&MSEPFUT26', mode: 'PAPER' }
            """
            inst = data.get("instrument", "")
            mode = data.get("mode", "PAPER")
            all_p = self._all_pos()
            if inst not in all_p:
                await _safe_send(ws, {"type": "notification", "success": False, "message": f"{inst} not found"})
                return
            pos = all_p[inst]
            new_status = "ACTIVE" if pos.get("entry_price") else "WAITING"
            self._persist_pos(inst, {**pos, "status": new_status})
            logger.info(f"[restart_position] Restarted {inst} → {new_status} ({mode})")
            await self.broadcast_state()
            await _safe_send(ws, {
                "type": "notification",
                "message": f"Restarted {inst}",
                "success": True,
            })

        # ── Remove ──────────────────────────────────────────────────────────────
        elif cmd == "remove_position":
            """
            Remove a position from the Trade Log (sets status=REMOVED).
            Sends: { command: 'remove_position', instrument: 'M&MSEPFUT26' }
            """
            inst = data.get("instrument", "")
            all_p = self._all_pos()
            if inst not in all_p:
                await _safe_send(ws, {"type": "notification", "success": False, "message": f"{inst} not found"})
                return
            self._persist_pos(inst, {**all_p[inst], "status": "REMOVED"})
            logger.info(f"[remove_position] Removed {inst} from trade log")
            await self.broadcast_state()
            await _safe_send(ws, {
                "type": "notification",
                "message": f"Removed {inst}",
                "success": True,
            })

        elif cmd == "echo_token":
            """Debug: look up NFO token for an instrument in the broker's token map."""
            inst = data.get("instrument", "").strip().upper()
            broker = self.brokers.get("MSTOCK")
            result = {"instrument": inst}
            if broker and hasattr(broker, '_token_map'):
                result["nfo_entries"] = {k: v for k, v in broker._token_map.items() if inst.replace("SEPFUT26", "").replace("FUT", "") in k.upper()}
                result["cash_token"] = broker._cash_token_map.get(inst.replace("SEPFUT26", "").replace("FUT", "").upper(), "NOT FOUND")
                if hasattr(broker, '_extract_expiry_for_nfo'):
                    result["expiry_extracted"] = broker._extract_expiry_for_nfo(inst)
                if hasattr(broker, '_find_nfo_futures_token') and result.get("expiry_extracted"):
                    base = re.sub(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2,4}', '', inst).replace('FUT', '').strip()
                    result["nfo_token"] = broker._find_nfo_futures_token(base, result["expiry_extracted"])
            await ws.send(json.dumps({"type": "echo_token", **result}))

        elif cmd == "test_daily_price":
            """
            Test M-Stock GetDailyPrice API for an instrument.
            Sends: { command: 'test_daily_price', instrument: 'ICICIBANKSEPFUT26', exchange: 'NFO' }
            Returns: { type: 'test_result', data: [...] }
            """
            inst = data.get("instrument", "")
            exch = data.get("exchange", "NFO")
            broker = self.brokers.get("MSTOCK")
            if not broker or not broker.is_connected():
                await ws.send(json.dumps({"type": "test_result", "error": "M-Stock not connected"}))
                return
            # Resolve token
            base = inst.strip().upper()
            is_fut = base.endswith('FUT') or re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}F?$', base.upper())
            if is_fut and hasattr(broker, '_extract_expiry_for_nfo') and hasattr(broker, '_find_nfo_futures_token'):
                expiry_str = broker._extract_expiry_for_nfo(base)
                base_sym = re.sub(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2,4}', '', base).replace('FUT', '').strip()
                if expiry_str:
                    nfo_token = broker._find_nfo_futures_token(base_sym, expiry_str)
                    if nfo_token:
                        exch, token = "NFO", nfo_token
                        logger.info(f"[test_daily_price] {inst} → NFO token={token} (expiry={expiry_str})")
                    else:
                        await ws.send(json.dumps({"type": "test_result", "error": f"No NFO token for {inst}", "expiry": expiry_str}))
                        return
                else:
                    await ws.send(json.dumps({"type": "test_result", "error": f"Could not extract expiry from {inst}"}))
                    return
            else:
                exch_n, token_n = broker._resolve_token(base)
                exch, token = exch_n, token_n

            if not token:
                await ws.send(json.dumps({"type": "test_result", "error": f"No token for {inst}"}))
                return

            # Call get_daily_price
            if hasattr(broker, 'get_daily_price'):
                candles = broker.get_daily_price(exch, token, inst)
                if candles:
                    rows = [[c.timestamp, c.open, c.high, c.low, c.close, c.volume] for c in candles]
                    await ws.send(json.dumps({"type": "test_result", "instrument": inst, "exchange": exch, "token": token, "data": rows, "count": len(rows)}))
                else:
                    await ws.send(json.dumps({"type": "test_result", "instrument": inst, "exchange": exch, "token": token, "error": "No data returned"}))
            else:
                await ws.send(json.dumps({"type": "test_result", "error": "get_daily_price not available"}))

        elif cmd == "get_candles":
            """
            Fetch OHLC candles for an instrument and send back to dashboard.
            Sends: { command: 'get_candles', instrument: 'BHELSEPFUT26', symbol: 'BHEL',
                     interval: '1d', range: '60d' }
            Returns: { type: 'candles', instrument: '...', candles: [ [ts, o, h, l, c, v], ... ] }
            """
            inst     = data.get("instrument", "")
            symbol   = data.get("symbol", inst)
            interval = data.get("interval", "1d")   # '1d' = daily, '5m' = 5-min, '15m' = 15-min
            range_   = data.get("range", "60d")    # '60d' = 60 days, '5d' = 5 days

            raw_candles: List[List] = []

            # 1. Try M-Stock for current session intraday (only for short intervals)
            if interval in ("5m", "15m"):
                broker = self.brokers.get("MSTOCK")
                if broker and broker.is_connected():
                    try:
                        to_ts   = int(_dt.now().timestamp())
                        from_ts = to_ts - (200 * 15 * 60)
                        inst_key = self._resolve_futures(inst)
                        mstock_candles = broker.get_candles(inst_key, interval, from_ts, to_ts)
                        if mstock_candles:
                            # Convert OHLC objects to [ts, o, h, l, c, v] lists for WebSocket JSON
                            for c in mstock_candles[-100:]:
                                if hasattr(c, 'timestamp'):  # OHLC dataclass
                                    raw_candles.append([c.timestamp, c.open, c.high, c.low, c.close, c.volume])
                                else:
                                    raw_candles.append(c)  # Already a list (fallback)
                            logger.info(f"[get_candles] {inst}: {len(mstock_candles)} M-Stock candles ({interval})")
                    except Exception as e:
                        logger.warning(f"[get_candles] M-Stock failed for {inst}: {e}")

            # 1b. M-Stock get_daily_price for NFO futures daily candles
            # This fixes charts for stock futures (SBI, TATAMOTORS, etc.) which Yahoo Finance doesn't cover
            if interval == "1d":
                broker = self.brokers.get("MSTOCK")
                if broker and broker.is_connected():
                    try:
                        # Resolve date range (get_daily_price returns up to 365 days of daily OHLCV)
                        to_ts = int(_dt.now().timestamp())
                        if range_ == "60d":
                            from_ts = to_ts - (60 * 86400)
                        elif range_ == "120d":
                            from_ts = to_ts - (120 * 86400)
                        elif range_ == "180d":
                            from_ts = to_ts - (180 * 86400)
                        else:
                            from_ts = to_ts - (60 * 86400)

                        # Get NFO token for this futures contract, then call get_daily_price correctly
                        # Resolve base symbol -> full contract name first (inst might be "BHEL", not "BHELSEPFUT26")
                        full_inst = self._resolve_futures(inst)
                        nfo_token = broker.get_nfo_futures_token(full_inst)
                        if nfo_token:
                            daily_bars = broker.get_daily_price("NFO", nfo_token, full_inst)
                        else:
                            daily_bars = []
                        if daily_bars:
                            # Filter by date range and convert OHLC dataclass → [ts, o, h, l, c, v]
                            for c in daily_bars:
                                if hasattr(c, 'timestamp') and from_ts <= c.timestamp <= to_ts:
                                    raw_candles.append([c.timestamp, c.open, c.high, c.low, c.close, c.volume])
                            logger.info(f"[get_candles] {inst}: {len(raw_candles)} M-Stock daily candles (from get_daily_price)")
                    except Exception as e:
                        logger.warning(f"[get_candles] get_daily_price failed for {inst}: {e}")

            # 2. Yahoo Finance — primary source for daily candles, fallback for intraday
            try:
                yf_interval = interval  # '1d', '5m', '15m' — Yahoo uses same format
                yf_range = range_ if interval == "1d" else "5d"
                yf_candles = self._fetch_yahoo_candles(symbol, interval=yf_interval, range_=yf_range)
                if yf_candles:
                    yf_lists = [[c.timestamp, c.open, c.high, c.low, c.close, c.volume] for c in yf_candles]
                    if not raw_candles:
                        raw_candles = yf_lists
                    else:
                        existing_ts = {c[0] for c in raw_candles}
                        for c in yf_lists:
                            if c[0] not in existing_ts:
                                raw_candles.append(c)
                                existing_ts.add(c[0])
                    logger.info(f"[get_candles] {inst}: {len(yf_lists)} Yahoo candles ({interval}/{yf_range})")
            except Exception as e:
                logger.warning(f"[get_candles] Yahoo Finance failed for {inst}: {e}")

            if raw_candles:
                raw_candles.sort(key=lambda x: x[0])
                await _safe_send(ws, {
                    "type": "candles",
                    "instrument": inst,
                    "symbol": symbol,
                    "interval": interval,
                    "range": range_,
                    "candles": raw_candles[-200:],   # send more for daily (60d ≈ 50 candles)
                })
            else:
                await _safe_send(ws, {"type": "candles", "instrument": inst, "error": "No candle data available"})

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
# Uses Python's built-in http.server (threaded) so it runs independently of
# the asyncio event loop and never blocks dashboard responses.

import http.server, socketserver, urllib.parse

class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Serves the dashboard HTML from memory. No file I/O per request."""

    _html_cache: bytes = b""
    _html_loaded: bool = False

    def log_message(self, format, *args):
        pass  # Keep logs clean

    @classmethod
    def load_html(cls):
        if cls._html_loaded:
            return
        dash_file = str(BASE_DIR / "dashboard" / "index.html")
        try:
            with open(dash_file, "rb") as f:  # Binary read — no encoding issues
                cls._html_cache = f.read()
            logger.info(f"[HTTP] Dashboard loaded ({len(cls._html_cache)} bytes)")
            cls._html_loaded = True
        except Exception as e:
            logger.error(f"[HTTP] Failed to load dashboard: {e}")
            cls._html_cache = b"<html><body><h1>Dashboard not found</h1></body></html>"
            cls._html_loaded = True

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        # Serve dashboard.js directly from disk (not from HTML cache)
        if path == "/dashboard.js":
            js_file = str(BASE_DIR / "dashboard" / "dashboard.js")
            try:
                with open(js_file, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
                return
            except Exception as e:
                logger.error(f"[HTTP] Failed to serve dashboard.js: {e}")

        # Serve Lightweight Charts library from project root
        if "lightweight-charts" in path and path.endswith(".js"):
            lc_file = str(BASE_DIR / "lightweight-charts.standalone.production.js")
            try:
                with open(lc_file, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
                return
            except Exception as e:
                logger.error(f"[HTTP] Failed to serve lightweight-charts: {e}")

        # Serve favicon.ico if requested (avoid 404 noise)
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # Serve index.html for all other paths
        self.load_html()
        body = DashboardHTTPHandler._html_cache
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_POST(self):
        # Block all POST requests
        self.send_response(405)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Method Not Allowed")


def run_http_dashboard_in_thread(host, port, server_ready):
    """Start the HTTP server in a background thread and signal when ready."""
    DashboardHTTPHandler.load_html()
    class ReuseAddrTCPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    try:
        httpd = ReuseAddrTCPServer((host, port), DashboardHTTPHandler)
        logger.info(f"HTTP dashboard: http://{host}:{port}")
        if server_ready:
            server_ready.set()
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"[HTTP] Server error: {e}")


async def run_http_dashboard(engine_ref, host="localhost", port=8765, server_ready=None):
    """Launch HTTP server in a background thread (runs outside asyncio)."""
    from concurrent.futures import ThreadPoolExecutor
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="httpd") as executor:
        await loop.run_in_executor(executor, run_http_dashboard_in_thread, host, port, server_ready)

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

    # Capture the running async loop, then start tick loop (its own thread — no asyncio interference)
    engine._loop = asyncio.get_running_loop()
    engine.start()

    # Connect brokers in a background thread so we don't block the event loop
    def _connect_brokers_bg():
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

    import threading
    threading.Thread(target=_connect_brokers_bg, daemon=True).start()

    # Run HTTP + WebSocket servers — event loop stays clean for WebSocket handling only
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
