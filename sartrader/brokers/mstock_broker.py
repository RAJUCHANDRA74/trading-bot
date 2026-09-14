"""
=============================================================
mstock_broker.py — M-Stock Type B API Implementation
=============================================================
Implements AbstractBroker for Mirae Asset M-Stock.
Uses the official mStock-TradingApi-B Python SDK
(import name: tradingapi_b.MConnectB).

Connection flow:
  1. connect() → login() → verify_totp() → set_access_token()
  2. TOTP secret from M-Stock portal (regenerate if changed)
  3. Access token valid till midnight — re-authenticate next day
=============================================================
"""
import re
import time
import logging
import threading
from typing import List, Optional

from sartrader.broker_interface import (
    AbstractBroker, AccountInfo, Position, Quote,
    OHLC, OrderType, OrderSide, OrderStatus, PositionSide, Order,
    register_broker,
)

logger = logging.getLogger(__name__)

# ── Exchange code mapping ──────────────────────────────────────
# M-Stock API uses numeric exchange codes
_EXCHANGE_MAP = {
    "NSE": "1",
    "NFO": "2",
    "CDS": "3",
    "BSE": "4",
    "BFO": "5",
}

# ── Interval mapping (M-Stock candle API) ─────────────────────
_INTERVAL_MAP = {
    "1m":  "ONE_MINUTE",
    "3m":  "THREE_MINUTE",
    "5m":  "FIVE_MINUTE",
    "10m": "TEN_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h":  "ONE_HOUR",
    "1d":  "ONE_DAY",
}


class MStockBroker(AbstractBroker):

    def __init__(self, api_key: str, client_code: str,
                 password: str, totp_secret: str, ip: str = ""):
        self.api_key        = api_key
        self.client_code    = client_code
        self.password       = password
        self.totp_secret    = totp_secret
        self.whitelisted_ip = ip

        self._client: Optional["MConnectB"] = None
        self._connected: bool = False
        self._lock: threading.Lock = threading.Lock()

        # ── Live Quote Streaming ──────────────────────────────────────────────
        self._instruments_cache: List[dict] = []        # All NFO/NSE instruments
        self._token_map: dict = {}                      # "SYMBOL:EXPIRY" → token (for futures)
        self._cash_token_map: dict = {}                 # "SYMBOL" → token (for NSE cash)
        self._live_quotes: dict = {}                    # symbol → {ltp, timestamp}
        self._poll_thread: Optional[threading.Thread] = None
        self._poll_running: bool = False
        self._poll_interval: int = 1                    # seconds (live futures LTP)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "M-Stock"

    def is_connected(self) -> bool:
        return self._connected

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """
        Full flow: login → verify_totp → set_access_token
        Returns True on success, False on failure.
        """
        try:
            import pyotp
            from tradingapi_b.mconnect import MConnectB

            logger.info("Connecting to M-Stock...")

            # Step 1: Create client and login
            self._client = MConnectB(api_key=self.api_key, disable_ssl=True)
            login_resp = self._client.login(
                user_id=self.client_code,
                password=self.password,
            )
            login_data = self._get_json(login_resp)
            logger.info(f"M-Stock login: {login_data.get('status')} — {login_data.get('message')}")

            if not login_data.get("status"):
                logger.error(f"M-Stock login failed: {login_data.get('message')}")
                return False

            refresh_token = login_data.get("data", {}).get("refreshToken", "")
            if not refresh_token:
                logger.error("No refreshToken in login response")
                return False

            # Step 2: Generate TOTP and verify
            totp_code = pyotp.TOTP(self.totp_secret).now()
            logger.info(f"TOTP generated: {totp_code}")

            vresp = self._client.verify_totp(
                _api_key=self.api_key,
                _request_token=refresh_token,
                _tOtp=totp_code,
            )
            vdata = self._get_json(vresp)
            logger.info(f"TOTP verify: {vdata.get('status')} — {vdata.get('message')}")

            if not vdata.get("status"):
                logger.error(f"TOTP verify failed: {vdata.get('message')}")
                return False

            # Step 3: Extract and set JWT
            token_data = vdata.get("data", {})
            jwt = token_data.get("jwtToken", "") if isinstance(token_data, dict) else ""
            if not jwt:
                logger.error("No jwtToken in verify_totp response")
                return False

            self._client.set_access_token(jwt)
            self._connected = True
            logger.info("M-Stock connected successfully!")

            # Build instrument → token cache for live quote streaming
            self._fetch_instruments()

            return True

        except ImportError as e:
            logger.error(f"Missing dependency: {e}")
            return False
        except Exception as e:
            logger.error(f"M-Stock connection error: {e}")
            return False

    def disconnect(self):
        self.stop_streaming()
        with self._lock:
            if self._client:
                try:
                    self._client.logout()
                except Exception:
                    pass
            self._connected = False
            self._client = None
        logger.info("M-Stock disconnected")

    # ═══════════════════════════════════════════════════════════════════════════
    #  LIVE QUOTE STREAMING  (REST polling — 1-second interval for live futures LTP)
    # ═══════════════════════════════════════════════════════════════════════════

    def _fetch_instruments(self):
        """
        Fetch all instruments once on connect and build the token cache.
        Builds two maps:
          _cash_token_map:  "RELIANCE" → token (NSE equity)
          _token_map:        "ASHOKLEY:29Sep2026" → token (NFO futures)
        """
        try:
            resp = self._client.get_instruments()
            instruments = resp.json()
            if not isinstance(instruments, list):
                logger.warning(f"[MStock] get_instruments returned {type(instruments)}, skipping cache")
                return

            self._instruments_cache = instruments

            for inst in instruments:
                sym   = inst.get("symbol", "").strip().upper()
                token = inst.get("token", "")
                seg   = inst.get("exch_seg", "")
                inst_type = inst.get("instrumenttype", "")
                expiry = inst.get("expiry", "").strip()

                if not sym or not token:
                    continue

                if seg == "NSE" and inst_type in ("EQ", "SM"):
                    # Cash equity
                    self._cash_token_map[sym] = token

                elif seg == "NFO" and expiry:
                    # NFO: store by symbol+expiry+type to distinguish FUT from OPT
                    # For options: include strike so different strikes get unique keys
                    strike = inst.get("strike", "").strip()
                    if inst_type in ("OPTSTK", "OPTIDX") and strike:
                        key = f"{sym}:{expiry}:{strike}:{inst_type}"
                    else:
                        key = f"{sym}:{expiry}:{inst_type}"
                    self._token_map[key] = token

            logger.info(f"[MStock] Instrument cache built: {len(self._cash_token_map)} cash, "
                        f"{len(self._token_map)} NFO entries")

        except Exception as e:
            logger.warning(f"[MStock] Failed to fetch instruments: {e}")

    # ── Token resolution ──────────────────────────────────────────────────────

    def _get_base_symbol(self, instrument: str) -> str:
        """
        Strip exchange-specific suffixes to get the base symbol.
        e.g. 'M&MSEPFUT26' → 'M&M', 'BANKNIFTY26SEPFUT' → 'BANKNIFTY'
        """
        inst = instrument.strip().upper()
        # Strip futures/options suffixes
        for suffix in ["FUT", "FUTURES"]:
            inst = inst.replace(suffix, "")
        # Strip common expiry patterns: SEP26, OCT26, 29Sep2026, etc.
        import re
        inst = re.sub(r'(SEP|OCT|NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG)\s*20\d\d', '', inst)
        inst = re.sub(r'(SEP|OCT|NOV|DEC|JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG)\d{2}(CE|PE|FUT)?', '', inst)
        # Strip CE/PE options suffix (e.g. 150CE → handled above, but also 150CE directly)
        inst = re.sub(r'\d+(CE|PE)$', '', inst)
        # Strip any remaining digits
        inst = re.sub(r'\d+$', '', inst)
        return instrument.strip()  # Return original if stripping makes it empty

    def _resolve_token(self, instrument: str) -> tuple:
        """
        Resolve an instrument name to (exchange, token).
        Returns ("", "") if not found.

        Handles:
          - NFO futures: "ASHOKLEYSEP26FUT" → FUTSTK/FUTIDX token by expiry
          - NFO options:  "ASHOKLEYSEP26150CE" → OPTSTK token by strike
          - Cash equities: "RELIANCE" → NSE token
          - Index futures: "BANKNIFTY" → latest NFO expiry
        """
        inst = instrument.strip().upper()

        # Direct key lookup (exact match)
        if inst in self._token_map:
            return ("NFO", self._token_map[inst])
        if inst in self._cash_token_map:
            return ("NSE", self._cash_token_map[inst])

        # Strip common suffixes to get base symbol and extract strike/ce-pe
        # e.g. ASHOKLEYSEP26FUT → ASHOKLEY, BANKNIFTYSEP26FUT → BANKNIFTY
        base = inst
        for suffix in ["FUT", "FUTURES"]:
            base = base.replace(suffix, "")
        for m in ["SEP26", "OCT26", "NOV26", "DEC26"]:
            base = base.replace(m, "")

        # Determine what type to look for based on original instrument name
        want_types = None
        if "FUT" in inst.upper():
            want_types = {"FUTIDX", "FUTSTK"}
        elif "CE" in inst.upper() or "PE" in inst.upper():
            want_types = {"OPTSTK", "OPTIDX"}

        # For options: try to extract strike from the remaining string
        # e.g. ASHOKLEY150CE → base=ASHOKLEY, strike=150
        # After stripping SEP26/OCT26/etc., the remaining digits before CE/PE = strike
        strike = None
        if want_types and (inst.endswith("CE") or inst.endswith("PE")):
            # Try to find numeric digits before CE/PE
            import re
            m = re.search(r'(\d+)(CE|PE)$', base)
            if m:
                strike = m.group(1)
                base = base[:m.start()]  # Remove "150CE" from base

        # Find matching entries for this base symbol
        from datetime import datetime
        matching = []
        for key, token in self._token_map.items():
            parts = key.split(":")
            key_base = parts[0]
            key_expiry = parts[1] if len(parts) > 1 else ""
            key_type = parts[-1]  # Last part is always type
            if key_base != base:
                continue
            if want_types and key_type not in want_types:
                continue
            # For options, also check strike match
            if want_types and strike:
                key_strike = parts[2] if len(parts) == 4 else None
                if key_strike != strike:
                    continue
            try:
                exp_dt = datetime.strptime(key_expiry, "%d%b%Y")
            except Exception:
                exp_dt = datetime.max
            matching.append((exp_dt, key, token))

        if matching:
            # Sort by expiry date — pick earliest (current month)
            matching.sort(key=lambda x: x[0])
            _, _, token = matching[0]
            return ("NFO", token)

        # Cash lookup (fallback)
        if base in self._cash_token_map:
            return ("NSE", self._cash_token_map[base])

        return ("", "")

    # ── Quote polling ─────────────────────────────────────────────────────────

    def _poll_live_quotes(self):
        """Background thread: polls get_market_quote every _poll_interval seconds."""
        while self._poll_running:
            try:
                if not self._live_quotes:
                    time.sleep(self._poll_interval)
                    continue

                # Group by exchange
                nfo_tokens, nse_tokens = [], []
                symbol_to_key = {}
                for sym in self._live_quotes:
                    exch, token = self._resolve_token(sym)
                    logger.debug(f"[MStock poll] {sym} -> exch={exch}, token={token}")
                    if exch == "NFO" and token:
                        nfo_tokens.append(token)
                        symbol_to_key[token] = sym
                    elif exch == "NSE" and token:
                        nse_tokens.append(token)
                        symbol_to_key[token] = sym
                logger.debug(f"[MStock poll] NFO={len(nfo_tokens)} tokens, NSE={len(nse_tokens)} tokens | live_quotes={list(self._live_quotes.keys())}")
                fetched = []
                if nfo_tokens:
                    try:
                        resp = self._client.get_market_quote("LTP", {"NFO": nfo_tokens[:100]})
                        data = resp.json()
                        for item in (data.get("data", {}).get("fetched", []) if isinstance(data, dict) else []):
                            token = item.get("symbolToken", "")
                            sym = symbol_to_key.get(token)  # Full instrument name (e.g. M&MSEPFUT26)
                            if sym and item.get("ltp", 0) > 0:
                                price = float(item["ltp"])
                                self._live_quotes[sym] = {  # Store under FULL contract name (NFO)
                                    "last_price": price, "bid": price, "ask": price,
                                    "volume": 0, "timestamp": int(time.time()),
                                }
                                # Also store under base symbol for non-futures instruments
                                base = self._get_base_symbol(sym)
                                if base != sym:
                                    self._live_quotes[base] = {
                                        "last_price": price, "bid": price, "ask": price,
                                        "volume": 0, "timestamp": int(time.time()),
                                    }
                                fetched.append(sym)
                    except BaseException as e:  # Catch ALL (including SystemExit, DataException)
                        logger.debug(f"[MStock] NFO quote poll error: {e}")

                if nse_tokens:
                    try:
                        resp = self._client.get_market_quote("LTP", {"NSE": nse_tokens[:100]})
                        data = resp.json()
                        fetched_items = data.get("data", {}).get("fetched", []) if isinstance(data, dict) else []
                        logger.debug(f"[MStock NSE poll] tokens={nse_tokens} -> fetched={len(fetched_items)} items: {fetched_items[:2]}")
                        for item in fetched_items:
                            token = item.get("symbolToken", "")
                            sym = symbol_to_key.get(token)  # Base symbol for NSE (equity)
                            logger.debug(f"[MStock NSE update] token={token!r}(type={type(token).__name__}) sym_lookup={sym!r}")
                            if sym and item.get("ltp", 0) > 0:
                                price = float(item["ltp"])
                                # Store equity quote under base symbol only (NSE = equity)
                                self._live_quotes[sym] = {
                                    "last_price": price, "bid": price, "ask": price,
                                    "volume": 0, "timestamp": int(time.time()),
                                }
                                fetched.append(sym)
                    except BaseException as e:  # Catch ALL (including SystemExit, DataException)
                        logger.debug(f"[MStock] NSE quote poll error: {e}")

                if fetched:
                    logger.debug(f"[MStock] Live quotes updated: {', '.join(fetched[:5])}")

            except BaseException as e:
                logger.warning(f"[MStock] Quote poll error: {e}")

            time.sleep(self._poll_interval)

    def subscribe(self, instruments: List[str]):
        """
        Register instruments for live quote streaming.
        Starts background polling if not already running.
        """
        for inst in instruments:
            inst_upper = inst.strip().upper()
            if inst_upper not in self._live_quotes:
                self._live_quotes[inst_upper] = {
                    "last_price": 0.0, "bid": 0.0, "ask": 0.0,
                    "volume": 0, "timestamp": 0,
                }

        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._poll_running = True
            self._poll_thread = threading.Thread(target=self._poll_live_quotes, daemon=True)
            self._poll_thread.start()
            logger.info(f"[MStock] Live quote streaming started for {len(instruments)} instruments")

    def unsubscribe(self, instruments: List[str]):
        """Remove instruments from live quote streaming."""
        for inst in instruments:
            self._live_quotes.pop(inst.strip().upper(), None)

    def stop_streaming(self):
        """Stop the polling thread."""
        self._poll_running = False
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5)
        self._poll_thread = None

    def get_live_quote(self, instrument: str) -> Optional[dict]:
        """
        Get the latest cached LTP for an instrument.
        Returns dict with last_price, bid, ask, volume, timestamp or None.
        """
        inst = instrument.strip().upper()
        return self._live_quotes.get(inst)

    # ═══════════════════════════════════════════════════════════════════════════
    #  HELPERS & OVERRIDDEN BROKER METHODS
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _get_json(resp) -> dict:
        if hasattr(resp, 'json'):
            return resp.json()
        return resp if isinstance(resp, dict) else {}

    def _resolve_exchange(self, exchange: str) -> str:
        """Convert exchange name to M-Stock numeric code."""
        return _EXCHANGE_MAP.get(exchange.upper(), exchange)

    # ── Account ─────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo:
        if not self._connected or self._client is None:
            return self._dummy_account("Not connected")

        try:
            resp = self._client.get_fund_summary()
            data = self._get_json(resp)

            balance = 0.0
            margin_used = 0.0

            if data.get("status") and data.get("data"):
                d = data["data"]
                if isinstance(d, dict):
                    balance = float(d.get("cash", d.get("availablecolateral", 0) or 0))

            return AccountInfo(
                brokerage_name="M-Stock",
                client_id=self.client_code,
                balance=balance,
                margin=margin_used,
                equity=balance,
                currency="INR",
            )
        except Exception as e:
            logger.error(f"Error fetching M-Stock account: {e}")
            return self._dummy_account(str(e))

    def _dummy_account(self, reason: str) -> AccountInfo:
        return AccountInfo(
            brokerage_name="M-Stock",
            client_id=self.client_code,
            balance=0.0,
            margin=0.0,
            equity=0.0,
            currency="INR",
        )

    def get_nfo_instruments(self) -> List[str]:
        """
        Return list of available NFO futures symbols.
        Format matches engine's _resolve_futures expectation:
          Index futures: NIFTY → NIFTYSEPFUT26
          Stock futures: ASHOKLEY → ASHOKLEYSEPFUT26
        The engine extracts month+year from this format.
        """
        if not self._connected or self._client is None:
            return []

        # Use cache if already built
        if self._instruments_cache:
            return self._build_nfo_futures_list(self._instruments_cache)

        # Fallback: fetch directly
        try:
            resp = self._client.get_instruments()
            data = resp.json()
            if not isinstance(data, list):
                return []
            result = self._build_nfo_futures_list(data)
            logger.info(f"[MStock] NFO futures: {len(result)} unique symbols")
            return result
        except Exception as e:
            logger.error(f"get_nfo_instruments error: {e}")
            return []

    def _build_nfo_futures_list(self, instruments: List[dict]) -> List[str]:
        """Build futures symbol list from raw instrument data.
        Format matches engine's _resolve_futures:
          Index futures:  NIFTY → "NIFTY26SEPFUT"  (yr+month+FUT)
          Stock futures: ASHOKLEY → "ASHOKLEYSEPFUT26" (month+FUT+yr)
        Uses instrumenttype="FUTIDX" to identify true index futures.
        """
        # Map M-Stock's internal symbol names to the names used by engine
        INDEX_SYM_MAP = {
            "NIFTY": "NIFTY", "NIFTYFPI": "FINNIFTY",
            "MIDCPNIFTY": "MIDCPNIFTY", "SENSEX": "SENSEX",
            # Note: BANKNIFTY uses symbol "BANKNIFTY" directly
        }
        symbols = []
        for item in instruments:
            sym = item.get("symbol", "").strip().upper()
            inst_type = item.get("instrumenttype", "")
            expiry = item.get("expiry", "").strip()
            seg = item.get("exch_seg", "")
            if seg != "NFO" or not sym or not expiry:
                continue
            if inst_type == "FUTIDX":
                # True index futures (NIFTY, BANKNIFTY, FINNIFTY, etc.)
                eng_name = INDEX_SYM_MAP.get(sym, sym)  # NIFTYFPI → FINNIFTY
                month = expiry[2:5]   # "Sep" from "29Sep2026"
                yr = expiry[-2:]      # "26" from "29Sep2026"
                name = f"{eng_name}{yr}{month}FUT"
                symbols.append(name)
            elif inst_type == "FUTSTK":
                # Stock futures
                month = expiry[2:5]   # "Sep" from "29Sep2026"
                yr = expiry[-2:]      # "26" from "29Sep2026"
                name = f"{sym}{month}FUT{yr}"
                symbols.append(name)
        return list(set(symbols))

    # ── Positions ───────────────────────────────────────────────────────────

    def get_positions(self) -> List[Position]:
        if not self._connected or self._client is None:
            return []

        try:
            resp = self._client.get_net_position()
            data = self._get_json(resp)
            if not data.get("status"):
                return []

            positions = []
            for item in data.get("data", []) or []:
                qty = int(item.get("netqty", 0) or 0)
                if qty == 0:
                    continue

                avg    = float(item.get("avgnetprice", 0) or 0)
                # symbolname already has full name (e.g. "BANKINDIA-29Sep2026-150-CE")
                inst   = item.get("symbolname", "") or item.get("tradingsymbol", "") or item.get("symbol", "")
                inst_name = inst

                side = PositionSide.LONG if qty > 0 else PositionSide.SHORT
                positions.append(Position(
                    instrument=inst_name,
                    side=side,
                    quantity=abs(qty),
                    avg_price=avg,
                    unrealized_pnl=0.0,  # M-Stock net_position may not include live LTP
                ))
            return positions

        except Exception as e:
            logger.error(f"Error fetching M-Stock positions: {e}")
            return []

    # ── Quotes ───────────────────────────────────────────────────────────────

    def get_quote(self, instrument: str) -> Quote:
        """
        Fetch LTP — first from live quote cache, then via get_market_quote REST API.
        """
        if not self._connected or self._client is None:
            return self._dummy_quote(instrument, "Not connected")

        inst = instrument.strip().upper()

        # 1. Try live quote cache (fastest — updated every 5 seconds)
        live = self._live_quotes.get(inst)
        if live and live.get("last_price", 0) > 0:
            return Quote(
                instrument=inst,
                last_price=live["last_price"],
                bid=live["bid"],
                ask=live["ask"],
                volume=live.get("volume", 0),
                timestamp=live.get("timestamp", int(time.time())),
            )

        # 2. Fall back: resolve token and call get_market_quote directly
        exch, token = self._resolve_token(inst)
        if not exch or not token:
            return self._dummy_quote(inst, f"No token for {inst}")

        try:
            resp = self._client.get_market_quote("LTP", {exch: [token]})
            data = resp.json()
            if data.get("status"):
                for item in data.get("data", {}).get("fetched", []):
                    ltp = float(item.get("ltp", 0))
                    if ltp > 0:
                        return Quote(
                            instrument=inst,
                            last_price=ltp,
                            bid=ltp,
                            ask=ltp,
                            volume=0,
                            timestamp=int(time.time()),
                        )
        except Exception as e:
            logger.debug(f"[MStock] get_quote {inst} error: {e}")

        return self._dummy_quote(inst, "No quote available")

    def _dummy_quote(self, instrument: str, reason: str) -> Quote:
        return Quote(
            instrument=instrument,
            last_price=0.0,
            bid=0.0,
            ask=0.0,
            volume=0,
            timestamp=int(time.time()),
        )

    # ── Candles ─────────────────────────────────────────────────────────────

    def _strip_expiry(self, inst: str) -> str:
        """
        Strip expiry suffix from contract names for base symbol extraction.
        Examples:
          'SBINSEPFUT26'      -> 'SBIN'   (stock futures: SEP FUT 26 suffix)
          'CANBKSEPFUT26'      -> 'CANBK'
          'NIFTY26SEPFUT'      -> 'NIFTY'  (index futures: 26 prefix)
          'BANKNIFTY26SEPFUT'  -> 'BANKNIFTY'
          'ICICIBANKSEPFUT26'  -> 'ICICIBANK'
        """
        s = inst.strip().upper()
        # Step 1: Remove trailing year suffix (FUT26, FUT2026)
        s = re.sub(r'FUT\d{2,4}$', '', s)
        # Step 2: Remove 'FUT' or 'FUTURES' at end (no year suffix)
        s = re.sub(r'FUTURES?$', '', s)
        # Step 3: Remove leading 2-digit year prefix (index futures: 26SEPFUT)
        s = re.sub(r'^(\d{2})(?=(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC))', '', s)
        # Step 3.5: Remove trailing month+year (stock futures: SEP26, OCT26)
        s = re.sub(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}$', '', s)
        # Step 4: Remove trailing 2-digit year (26, 27) from base
        s = re.sub(r'\d{2}$', '', s)
        # DO NOT strip bare month codes — token_map stores "TATAMOTORS" (not "TATAMOTORSEP")
        return s.strip()

    def _extract_expiry_for_nfo(self, inst: str) -> Optional[str]:
        """
        Extract NFO expiry string from instrument name.
        Looks up the ACTUAL expiry from the token_map (authoritative source).
        Falls back to computing last Thursday if not found in token map.
        Returns e.g. '29Sep2026' or None.
        """
        import re, calendar
        inst_upper = inst.strip().upper()

        # Extract month+year BEFORE stripping — needed for correct token_map matching.
        # Stock futures: "SBINSEPFUT26"  → SEP + 26
        # Index futures: "BANKNIFTY26SEPFUT" → SEP + 26
        m = re.search(
            r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})',
            inst_upper
        )
        exp_mon, exp_yr = None, None
        if m:
            exp_mon = m.group(1).title()   # 'Sep'
            exp_yr  = m.group(2)            # '26'

        # Get base from full name (strip only trailing FUT + year suffix carefully)
        base = self._strip_expiry(inst)

        # Find matching entries in token_map for this base symbol
        matching_keys = []
        for key in self._token_map.keys():
            parts = key.split(":")
            if len(parts) >= 3 and parts[0].upper() == base.upper():
                matching_keys.append(key)

        if matching_keys:
            if exp_mon and exp_yr:
                # Match month + year against token_map expiry strings
                for key in matching_keys:
                    expiry_in_key = key.split(":")[1]   # e.g. '29Sep2026'
                    if exp_mon.lower() in expiry_in_key.lower() and exp_yr in expiry_in_key:
                        return expiry_in_key
            # Fallback: return the first matching expiry
            return matching_keys[0].split(":")[1]

        # Fallback: compute last Thursday (old logic)
        # Pattern 1: BASEMONSEPYY  e.g. SBINSEPFUT26
        m1 = re.match(r'^([A-Z]+)(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(FUT|26|27|28|29)?(\d{2})?F?$', inst_upper)
        if m1:
            mon = m1.group(2)
            yy = m1.group(4)
            if yy:
                year = 2000 + int(yy)
                month_map = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
                             'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
                month_num = month_map.get(mon, 9)
                import datetime
                last_day = calendar.monthrange(year, month_num)[1]
                last_thursday = last_day
                while True:
                    dt = datetime.date(year, month_num, last_thursday)
                    if dt.weekday() == 3:
                        break
                    last_thursday -= 1
                return f"{last_thursday}{mon}{year}"

        # Pattern 2: BASEYYMONFUT  e.g. BANKNIFTY26SEPFUT
        m2 = re.match(r'^([A-Z]+)(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)FUT$', inst_upper)
        if m2:
            mon = m2.group(3)
            yy = m2.group(2)
            year = 2000 + int(yy)
            month_map = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,
                         'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
            month_num = month_map.get(mon, 9)
            import datetime
            last_day = calendar.monthrange(year, month_num)[1]
            last_thursday = last_day
            while True:
                dt = datetime.date(year, month_num, last_thursday)
                if dt.weekday() == 3:
                    break
                last_thursday -= 1
            return f"{last_thursday}{mon}{year}"

        return None

    def _find_nfo_futures_token(self, base_symbol: str, expiry_str: str,
                                  inst_type: str = "FUTSTK") -> Optional[str]:
        """
        Find the NFO futures token for a base symbol + expiry.
        token_map keys: "RELIANCE:25Sep2026:FUTSTK" or "BANKNIFTY:29Sep2026:FUTIDX"
        inst_type: "FUTSTK" (stock futures) or "FUTIDX" (index futures).
        Returns token string or None.
        """
        base_upper = base_symbol.upper()
        expiry_upper = expiry_str.upper()

        # Exact match (case-insensitive)
        target = f"{base_upper}:{expiry_upper}:{inst_type}"
        if target in self._token_map:
            return self._token_map[target]

        # Case-insensitive search: match base + expiry + type
        for key, token in self._token_map.items():
            parts = key.split(":")
            if len(parts) >= 3 and parts[0].upper() == base_upper and parts[1].upper() == expiry_upper and parts[2] == inst_type:
                return token
        return None

    def get_nfo_futures_token(self, instrument: str) -> Optional[str]:
        """
        Resolve a full NFO futures contract name → NFO token.
        Handles both index futures (BANKNIFTY26SEPFUT) and stock futures (SBINSEPFUT26).
        Returns token string or None if not found.
        """
        inst = instrument.strip().upper()
        # is_fut: ends with FUT, or has month+year in SEP26 / SEPFUT26 / 26SEP format
        is_fut = bool(
            inst.endswith("FUT") or
            re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC).*\d{2}$', inst)
        )
        if not is_fut:
            return None

        base = self._strip_expiry(inst)
        expiry = self._extract_expiry_for_nfo(inst)  # Pass full name for correct parsing
        if not expiry:
            return None

        INDEX_FUTURES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"}
        inst_type = "FUTIDX" if any(base.startswith(f) for f in INDEX_FUTURES) else "FUTSTK"
        return self._find_nfo_futures_token(base, expiry, inst_type)

    def get_daily_price(self, exchange: str, token: str, trading_symbol: str = "") -> List[list]:
        """
        Fetch historical daily OHLCV from M-Stock get_historical_chart API.
        Uses the SDK's session auth and supports ALL exchanges including NFO futures.
        exchange: "NSE" or "NFO"
        token: instrument token string — if empty, trading_symbol is used to resolve token
        Returns list of OHLC objects (newest last).
        """
        if not self._connected or self._client is None:
            return []

        from datetime import datetime, timezone, timedelta, date
        IST = timezone(timedelta(hours=5, minutes=30))

        # Resolve correct token for futures contracts
        _exch = exchange
        _token = token
        inst = trading_symbol.strip().upper() if trading_symbol else ""
        if inst and not _token:
            # Resolve token from instrument name
            is_fut = bool(
                inst.endswith("FUT") or
                re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}F?$', inst)
            )
            if is_fut:
                base = self._strip_expiry(inst)
                expiry = self._extract_expiry_for_nfo(inst)
                if expiry:
                    # Detect index vs stock futures
                    INDEX_FUTURES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"}
                    inst_type = "FUTIDX" if any(base.startswith(f) for f in INDEX_FUTURES) else "FUTSTK"
                    nfo_token = self._find_nfo_futures_token(base, expiry, inst_type)
                    if nfo_token:
                        _exch = "NFO"
                        _token = nfo_token
            if not _token:
                _exch, _token = self._resolve_token(inst)

        if not _token:
            return []

        # Determine date range (up to 60 trading days back)
        today = date.today()
        from_date = (today - timedelta(days=60)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        try:
            resp = self._client.get_historical_chart(
                _exchange=_exch,
                _security_token=str(_token),
                _interval="ONE_DAY",
                _fromDate=from_date,
                _toDate=to_date,
            )
            raw = resp.text
            try:
                data = resp.json()
            except Exception:
                logger.warning(f"[MStock get_daily_price] JSON parse error for {trading_symbol}: {raw[:100]}")
                return []

            if not isinstance(data, dict):
                logger.warning(f"[MStock get_daily_price] Unexpected response type for {trading_symbol}: {type(data)}")
                return []

            if not data.get("status"):
                logger.warning(f"[MStock get_daily_price] API error for {trading_symbol}: {data.get('error', data)}")
                return []

            # Candles are at data.data.candles or data.data (list)
            raw_candles = (
                data.get("data", {}).get("candles", []) or
                data.get("data", []) or
                []
            )

            candles = []
            for row in raw_candles:
                if not isinstance(row, list) or len(row) < 5:
                    continue
                ts_str = str(row[0])
                o, h, l, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
                v = int(row[5]) if len(row) > 5 else 0

                try:
                    # Parse "2026-09-01 09:15" or "2026-09-01"
                    if " " in ts_str:
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
                    else:
                        dt = datetime.strptime(ts_str[:10], "%Y-%m-%d").replace(tzinfo=IST)
                    ts = int(dt.timestamp())
                except Exception:
                    ts = int(time.time())

                if c > 0:
                    candles.append(OHLC(timestamp=ts, open=o, high=h, low=l, close=c, volume=v))

            if candles:
                logger.info(f"[MStock get_daily_price] {trading_symbol}: {len(candles)} daily bars, "
                            f"latest={candles[-1].close:.2f}")
            return candles

        except Exception as e:
            logger.warning(f"[MStock get_daily_price] Exception for {trading_symbol}: {e}")
            return []

    def get_candles(self, instrument: str, interval: str,
                    from_ts: int, to_ts: int) -> List[OHLC]:
        if not self._connected or self._client is None:
            return []

        interval_key = _INTERVAL_MAP.get(interval, "FIFTEEN_MINUTE")
        inst = instrument.strip().upper()

        # Resolve token — strip expiry suffix so we get the base symbol for token map lookup
        base = self._strip_expiry(inst)
        exch, token = self._resolve_token(base)
        if not exch or not token:
            # Try full name directly (for indices like NIFTY26SEPFUT)
            exch, token = self._resolve_token(inst)
            if not exch or not token:
                return []

        # ── CRITICAL FIX: For NFO futures, use NFO token (not equity token) ──
        # When inst = "ICICIBANKSEPFUT26", _strip_expiry → "ICICIBANK" which falls through
        # to cash_token_map → wrong token. Fix: try NFO token lookup using actual expiry.
        is_futures_contract = bool(
            inst.upper().endswith('FUT') or
            re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}F?$', inst.upper())
        )
        if is_futures_contract and exch == "NSE":
            expiry_str = self._extract_expiry_for_nfo(inst)
            if expiry_str:
                nfo_token = self._find_nfo_futures_token(base, expiry_str)
                if nfo_token:
                    exch, token = "NFO", nfo_token
                    logger.info(f"[MStock get_candles] FUTURES FIX: {inst} → NFO token={token} (expiry={expiry_str})")

        try:
            exch_code = self._resolve_exchange(exch)

            # ── Daily candles: use GetDailyPrice API (gives historical data) ──
            if interval_key == "ONE_DAY":
                daily = self.get_daily_price(exch, token, inst)
                if daily:
                    # Filter by date range
                    filtered = [c for c in daily if from_ts <= c.timestamp <= to_ts]
                    if filtered:
                        return filtered
                    return daily  # Return all if filter yields nothing
                return []

            candles = []  # Initialize before try — used in exception handler
            logger.info(f"[MStock get_candles] inst={inst} base={base} exch={exch}({exch_code}) token={token} interval={interval_key}")
            resp = self._client.get_intraday_chart(
                _exchange=exch_code,
                _symboltoken=token,
                _interval=interval_key,
            )
            cdata = self._get_json(resp)
            if not cdata.get("status"):
                return []

            rows = cdata.get("data", {}).get("candles", []) or cdata.get("data", []) or []

            from datetime import datetime, timezone, timedelta
            IST = timezone(timedelta(hours=5, minutes=30))

            for row in rows:
                if isinstance(row, list) and len(row) >= 5:
                    ts_str = row[0]
                    o = float(row[1])
                    h = float(row[2])
                    l = float(row[3])
                    c = float(row[4])
                    v = int(row[5]) if len(row) > 5 else 0

                    # Parse timestamp — M-Stock returns IST naive datetime "YYYY-MM-DD HH:MM"
                    try:
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
                        ts = int(dt.timestamp())
                    except Exception:
                        ts = int(time.time())

                    # M-Stock intraday_chart returns last session only — no time filtering needed
                    # Return as OHLC dataclass objects (matches Yahoo Finance broker format)
                    candles.append(OHLC(timestamp=ts, open=o, high=h, low=l, close=c, volume=v))

            if candles:
                logger.info(f"[MStock] Candles for {inst}: {len(candles)} bars")

        except Exception as e:
            logger.debug(f"[MStock] Candle fetch error for {inst}: {e}")

        if candles:
            return candles
        logger.warning(f"[MStock] No candles for {inst}")
        return []

    # ── Orders ───────────────────────────────────────────────────────────────

    def place_order(self, instrument: str, side: OrderSide,
                    quantity: int, order_type: OrderType,
                    price: Optional[float] = None,
                    trigger_price: Optional[float] = None) -> "Order":
        if not self._connected or self._client is None:
            return self._error_order(instrument, "Not connected")

        exchange     = "NFO"
        product_type = "NRML"
        side_str     = "BUY" if side == OrderSide.BUY else "SELL"

        if order_type == OrderType.MARKET:
            order_type_str = "MARKET"
            order_price    = "0"
            trig_price     = "0"
        elif order_type == OrderType.SL:
            order_type_str = "STOP_LOSS_LIMIT"
            order_price    = str(price or 0)
            trig_price     = str(trigger_price or 0)
        else:
            order_type_str = "LIMIT"
            order_price    = str(price or 0)
            trig_price     = "0"

        try:
            resp = self._client.place_order(
                _variety="NORMAL",
                _tradingsymbol=instrument,
                _symboltoken=instrument,
                _exchange=exchange,
                _transactiontype=side_str,
                _ordertype=order_type_str,
                _quantity=str(quantity),
                _producttype=product_type,
                _price=order_price,
                _triggerprice=trig_price,
                _squareoff="0",
                _stoploss="0",
                _trailingStopLoss="0",
                _disclosedquantity="0",
                _duration="DAY",
                _ordertag="sartrader",
            )
            data = self._get_json(resp)
            logger.info(f"Order placed: {data}")

            if not data.get("status"):
                return self._error_order(instrument, data.get("message", "Failed"))

            order_id  = data.get("data", {}).get("order_id", "UNKNOWN") if isinstance(data.get("data"), dict) else "UNKNOWN"
            db_order_id = data.get("data", {}).get("orderid", order_id) if isinstance(data.get("data"), dict) else order_id

            return Order(
                order_id=str(db_order_id),
                instrument=instrument,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
                trigger_price=trigger_price,
                status=OrderStatus.SUBMITTED,
                filled_qty=0,
                avg_price=0.0,
                timestamp=int(time.time()),
            )

        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return self._error_order(instrument, str(e))

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected or self._client is None:
            return False
        try:
            resp = self._client.cancel_order(order_id=order_id)
            data = self._get_json(resp)
            return data.get("status", False)
        except Exception as e:
            logger.error(f"Cancel order error: {e}")
            return False

    def modify_order(self, order_id: str, price: Optional[float] = None,
                     quantity: Optional[int] = None) -> bool:
        if not self._connected or self._client is None:
            return False
        try:
            resp = self._client.modify_order(
                order_id=order_id,
                _price=str(price) if price else "0",
                _quantity=str(quantity) if quantity else "0",
            )
            data = self._get_json(resp)
            return data.get("status", False)
        except Exception as e:
            logger.error(f"Modify order error: {e}")
            return False

    def get_order_status(self, order_id: str) -> "Order":
        if not self._connected or self._client is None:
            return self._error_order("", "Not connected")

        try:
            resp = self._client.get_order_details(order_id=order_id)
            data = self._get_json(resp)
            if not data.get("status") or not data.get("data"):
                return self._error_order("", f"Order not found: {order_id}")

            o = data["data"]
            if isinstance(o, list):
                o = o[0] if o else {}

            side_str = o.get("transactiontype", "BUY")
            side = OrderSide.BUY if side_str == "BUY" else OrderSide.SELL

            status_map = {
                "COMPLETE": OrderStatus.FILLED,
                "REJECTED": OrderStatus.REJECTED,
                "CANCELLED": OrderStatus.CANCELLED,
                "OPEN": OrderStatus.SUBMITTED,
                "PENDING": OrderStatus.SUBMITTED,
            }
            mapped = status_map.get(o.get("status", "").upper(), OrderStatus.SUBMITTED)

            return Order(
                order_id=str(o.get("order_id", order_id)),
                instrument=o.get("tradingsymbol", ""),
                side=side,
                quantity=int(o.get("quantity", 0) or 0),
                order_type=OrderType.MARKET,
                price=None,
                trigger_price=None,
                status=mapped,
                filled_qty=int(o.get("filledshares", 0) or 0),
                avg_price=float(o.get("averageprice", 0) or 0),
                timestamp=int(time.time()),
            )
        except Exception as e:
            logger.error(f"get_order_status error: {e}")
            return self._error_order("", str(e))

    def close_position(self, instrument: str) -> "Order":
        """Close entire position by placing opposite MARKET order."""
        if not self._connected or self._client is None:
            return self._error_order(instrument, "Not connected")

        # Find current position
        positions = self.get_positions()
        target = None
        for p in positions:
            if instrument in p.instrument or p.instrument in instrument:
                target = p
                break

        if not target:
            return self._error_order(instrument, f"No open position for {instrument}")

        # Opposite side to close
        close_side = OrderSide.SELL if target.side == PositionSide.LONG else OrderSide.BUY

        return self.place_order(
            instrument=instrument,
            side=close_side,
            quantity=target.quantity,
            order_type=OrderType.MARKET,
        )

    def _error_order(self, instrument: str, reason: str) -> "Order":
        return Order(
            order_id="ERROR",
            instrument=instrument,
            side=OrderSide.BUY,
            quantity=0,
            order_type=OrderType.MARKET,
            price=None,
            trigger_price=None,
            status=OrderStatus.REJECTED,
            filled_qty=0,
            avg_price=0.0,
            timestamp=int(time.time()),
            message=reason,
        )


# ── Register ───────────────────────────────────────────────────────────────
register_broker("MSTOCK", MStockBroker)
