"""
=============================================================
zerodha_broker.py — Zerodha Kite Connect Implementation
=============================================================
Implements AbstractBroker for Zerodha Kite API.

Setup:
  1. Get API keys from https://developers.kite.trade
  2. Generate request token via:
     https://kite.trade/connect/login?api_key=YOUR_KEY&v=3
  3. Exchange request token for access token using postLogin()
  4. Save access_token — it doesn't expire (until you revoke it)

Installation: pip install kiteconnect
=============================================================
"""
import time
import logging
from typing import List, Optional
from datetime import datetime

from sartrader.broker_interface import (
    AbstractBroker, AccountInfo, Position, Quote, Order,
    OHLC, OrderType, OrderSide, OrderStatus, PositionSide,
    register_broker,
)

logger = logging.getLogger(__name__)

# Zerodha instrument token mapping (subset — full CSV from kite.instruments())
_ZERODHA_TOKENS = {
    "BANKNIFTY26SEPFUT": "68390",
    "NIFTY26SEPFUT":     "69684",
    "FINNIFTY26SEPFUT":  "70000",
}


class ZerodhaBroker(AbstractBroker):

    def __init__(self, api_key: str, api_secret: str,
                 access_token: str = ""):
        self.api_key      = api_key
        self.api_secret   = api_secret
        self.access_token = access_token
        self._kite        = None
        self._connected   = False

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "Zerodha"

    def is_connected(self) -> bool:
        return self._connected

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """
        If access_token is provided in config, use it directly.
        Otherwise perform full OAuth flow.
        """
        try:
            from kiteconnect import KiteConnect
        except ImportError:
            logger.error("Zerodha Kite Connect not installed. Run: pip install kiteconnect")
            return False

        try:
            self._kite = KiteConnect(api_key=self.api_key)

            if self.access_token:
                self._kite.set_access_token(self.access_token)
                # Validate token
                self._kite.profile()
                self._connected = True
                logger.info("Zerodha connected via stored access token")
                return True

            logger.warning(
                "No access_token configured for Zerodha. "
                "Please complete the OAuth flow:\n"
                "  1. Visit: https://kite.trade/connect/login"
                f"?api_key={self.api_key}&v=3\n"
                "  2. Copy the request_token from the redirect URL\n"
                "  3. Set it in config.py → ZERODHA['request_token']\n"
                "  4. Re-run — I'll exchange it for a permanent access_token"
            )
            return False

        except Exception as e:
            logger.error(f"Zerodha connection error: {e}")
            return False

    def disconnect(self):
        self._connected = False
        self._kite = None
        logger.info("Zerodha disconnected")

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo:
        if not self._connected or self._kite is None:
            return AccountInfo("Zerodha", "—", 0, 0, 0)

        try:
            mf = self._kite.margins()
            eq = mf.get("equity", {})
            return AccountInfo(
                brokerage_name="Zerodha",
                client_id=self._kite.profile().get("user_id", ""),
                balance=float(eq.get("available", {}).get("cash", 0)),
                margin=float(eq.get("used", {}).get("exposure", 0)),
                equity=float(eq.get("net", 0)),
            )
        except Exception as e:
            logger.error(f"Zerodha account error: {e}")
            return AccountInfo("Zerodha", "—", 0, 0, 0)

    # ── Positions ──────────────────────────────────────────────────────────────

    def get_positions(self) -> List[Position]:
        if not self._connected or self._kite is None:
            return []

        try:
            resp = self._kite.positions()
            positions = []
            for item in resp.get("day", []):
                qty = int(item.get("quantity", 0))
                if qty == 0:
                    continue
                avg  = float(item.get("average_price", 0))
                ltp  = float(item.get("last_price", 0))
                inst = item.get("instrument_token")
                sym  = item.get("tradingsymbol", str(inst))
                pnl  = (ltp - avg) * qty

                positions.append(Position(
                    instrument=sym,
                    side=PositionSide.LONG if qty > 0 else PositionSide.SHORT,
                    quantity=abs(qty),
                    avg_price=avg,
                    unrealized_pnl=pnl,
                ))
            return positions
        except Exception as e:
            logger.error(f"Zerodha positions error: {e}")
            return []

    # ── Quotes ────────────────────────────────────────────────────────────────

    def get_quote(self, instrument: str) -> Quote:
        if not self._connected or self._kite is None:
            return Quote(instrument, 0, 0, 0, 0, int(time.time()))

        try:
            token = _ZERODHA_TOKENS.get(instrument, instrument)
            data  = self._kite.ltp(["NFO:" + instrument])["NFO:" + instrument]
            ohlc  = data["ohlc"]
            lp    = float(data["last_price"])
            return Quote(
                instrument=instrument,
                last_price=lp,
                bid=float(data["depth"]["buy"][0]["price"]) if data["depth"]["buy"] else lp,
                ask=float(data["depth"]["sell"][0]["price"]) if data["depth"]["sell"] else lp,
                volume=int(data.get("volume", 0)),
                timestamp=int(time.time()),
            )
        except Exception as e:
            logger.error(f"Zerodha quote error for {instrument}: {e}")
            return Quote(instrument, 0, 0, 0, 0, int(time.time()))

    # ── Candles ────────────────────────────────────────────────────────────────

    def get_candles(self, instrument: str, interval: str,
                    from_ts: int, to_ts: int) -> List[OHLC]:
        if not self._connected or self._kite is None:
            return []

        # interval: 'minute', '3minute', '5minute', '10minute', '15minute',
        #           '30minute', 'hour', 'day'
        z_interval = interval.replace("m", "minute").replace("h", "hour")

        try:
            token = _ZERODHA_TOKENS.get(instrument, instrument)
            data  = self._kite.historical_data(
                instrument_token=int(token),
                from_date=datetime.fromtimestamp(from_ts),
                to_date=datetime.fromtimestamp(to_ts),
                interval=z_interval,
            )
            return [
                OHLC(
                    timestamp=int(d["timestamp"].timestamp()),
                    open=float(d["open"]),
                    high=float(d["high"]),
                    low=float(d["low"]),
                    close=float(d["close"]),
                    volume=int(d.get("volume", 0)),
                )
                for d in data
            ]
        except Exception as e:
            logger.error(f"Zerodha candles error for {instrument}: {e}")
            return []

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(self, instrument: str, side: OrderSide,
                    quantity: int, order_type: OrderType,
                    price: Optional[float] = None,
                    trigger_price: Optional[float] = None) -> Order:
        if not self._connected or self._kite is None:
            return Order("ERROR", instrument, side, order_type, quantity, price,
                         status=OrderStatus.ERROR, message="Not connected")

        side_str   = "BUY" if side == OrderSide.BUY else "SELL"
        o_type_map = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT:  "LIMIT",
            OrderType.SL:     "SL",
            OrderType.SLM:    "SL-M",
        }
        o_type_str = o_type_map.get(order_type, "MARKET")
        prd        = "NRML"

        try:
            order_id = self._kite.place_order(
                tradingsymbol=instrument,
                exchange="NFO",
                transaction_type=side_str,
                quantity=quantity,
                order_type=o_type_str,
                product=prd,
                price=price or 0,
                trigger_price=trigger_price or 0,
            )
            return Order(
                order_id=str(order_id),
                instrument=instrument,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                status=OrderStatus.OPEN,
            )
        except Exception as e:
            logger.error(f"Zerodha order error: {e}")
            return Order(
                "ERROR", instrument, side, order_type, quantity, price,
                status=OrderStatus.ERROR, message=str(e)
            )

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected or self._kite is None:
            return False
        try:
            self._kite.cancel_order(order_id=order_id)
            return True
        except Exception as e:
            logger.error(f"Zerodha cancel error: {e}")
            return False

    def get_order_status(self, order_id: str) -> Order:
        if not self._connected or self._kite is None:
            return Order("ERROR", "", OrderSide.BUY, OrderType.MARKET, 0, None,
                        status=OrderStatus.ERROR)
        try:
            orders = self._kite.orders()
            for o in orders:
                if str(o["order_id"]) == order_id:
                    s_map = {
                        "OPEN": OrderStatus.OPEN,
                        "COMPLETE": OrderStatus.FILLED,
                        "CANCELLED": OrderStatus.CANCELLED,
                        "REJECTED": OrderStatus.REJECTED,
                    }
                    return Order(
                        order_id=order_id,
                        instrument=o.get("tradingsymbol", ""),
                        side=OrderSide.BUY if o.get("transaction_type") == "BUY" else OrderSide.SELL,
                        order_type=OrderType(o.get("order_type", "MARKET")),
                        quantity=int(o.get("quantity", 0)),
                        filled_qty=int(o.get("filled_quantity", 0)),
                        average_price=float(o.get("average_price", 0)),
                        status=s_map.get(o.get("status", ""), OrderStatus.PENDING),
                        timestamp=int(o.get("order_timestamp", 0)),
                    )
            return Order(order_id, "", OrderSide.BUY, OrderType.MARKET, 0, None,
                         status=OrderStatus.ERROR, message="Not found")
        except Exception as e:
            return Order("ERROR", "", OrderSide.BUY, OrderType.MARKET, 0, None,
                        status=OrderStatus.ERROR, message=str(e))

    def close_position(self, instrument: str) -> Order:
        positions = self.get_positions()
        for pos in positions:
            if pos.instrument == instrument:
                side = OrderSide.SELL if pos.side == PositionSide.LONG else OrderSide.BUY
                return self.place_order(instrument, side, pos.quantity, OrderType.MARKET)
        return Order("ERROR", instrument, OrderSide.BUY, OrderType.MARKET, 0, None,
                     status=OrderStatus.ERROR, message="No position")

    # ── NFO Instrument List ─────────────────────────────────────────────────

    def get_nfo_instruments(self) -> List[str]:
        """
        Fetch all available NSE F&O futures contract symbols.
        Returns a list like ['SBIN26SEPFUT', 'BANKBARODA26SEPFUT', ...]
        """
        if not self._connected or self._kite is None:
            logger.warning("Zerodha not connected — returning empty instrument list")
            return []

        try:
            instruments = self._kite.instruments("NFO")
            # Filter to stock futures only (exclude index futures like BANKNIFTY, NIFTY)
            INDEX_INSTRUMENTS = {
                "BANKNIFTY", "NIFTY", "FINNIFTY",
                "MIDCPNIFTY", "SENSEX", "MIDCAP50", "NEXT50"
            }
            futures = [
                inst["tradingsymbol"]
                for inst in instruments
                if inst.get("instrument_type") == "FUT"
                   and inst.get("exchange") == "NFO"
                   and inst.get("name") not in INDEX_INSTRUMENTS
            ]
            logger.info(f"Zerodha: fetched {len(futures)} stock futures from NFO")
            return futures
        except Exception as e:
            logger.error(f"Zerodha get_nfo_instruments error: {e}")
            return []

    def get_available_futures_for_symbols(self, base_symbols: List[str]) -> List[str]:
        """
        Given a list of base symbols (e.g. ['SBIN','BANKBARODA']),
        return which ones are available as futures in the current expiry cycle.
        """
        available = set(self.get_nfo_instruments())
        matched = []
        for sym in base_symbols:
            for expiry in ["26SEPFUT", "26OCTFUT", "26DECFUT", "27JANFUT", "27FEBFUT", "27MARFUT"]:
                inst = f"{sym}{expiry}"
                if inst in available:
                    matched.append(inst)
                    break
        return matched


# ── Register ──────────────────────────────────────────────────────────────────
register_broker("ZERODHA", ZerodhaBroker)
