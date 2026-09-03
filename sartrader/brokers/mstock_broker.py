"""
=============================================================
mstock_broker.py — M-Stock Type B API Implementation
=============================================================
Implements AbstractBroker for Mirae Asset M-Stock.
Uses the official mStock-TradingApi-B Python SDK.

Connection flow:
  1. connect() → login() → verify_totp()
  2. Access token stored for subsequent calls
  3. Token expires at midnight → re-authenticate next trading day
=============================================================
"""
import time
import logging
import threading
from typing import List, Optional, Dict
from datetime import datetime, timezone

from sartrader.broker_interface import (
    AbstractBroker, AccountInfo, Position, Quote, Order,
    OHLC, OrderType, OrderSide, OrderStatus, PositionSide,
    register_broker,
)

logger = logging.getLogger(__name__)

# ── Interval Mapping ─────────────────────────────────────────────────────────

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


# ── M-Stock Broker ────────────────────────────────────────────────────────────

class MStockBroker(AbstractBroker):

    def __init__(self, api_key: str, client_code: str,
                 password: str, totp_secret: str, ip: str = ""):
        self.api_key     = api_key
        self.client_code = client_code
        self.password    = password
        self.totp_secret = totp_secret
        self.whitelisted_ip = ip

        self._client     = None       # mStock SDK client
        self._access_token = None
        self._refresh_token = None
        self._connected   = False
        self._lock        = threading.Lock()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "M-Stock"

    def is_connected(self) -> bool:
        return self._connected

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Login to M-Stock and verify TOTP."""
        try:
            import mStock

            logger.info("Connecting to M-Stock...")
            client = mStock.connect(self.api_key)

            login_resp = client.login(
                clientCode=self.client_code,
                password=self.password,
                ip=self.whitelisted_ip,
                source="API",
            )
            logger.info(f"M-Stock login response: {login_resp}")

            if not login_resp.get("status"):
                msg = login_resp.get("message", "Login failed")
                logger.error(f"M-Stock login failed: {msg}")
                return False

            refresh_token = login_resp.get("data", {}).get("refreshToken", "")
            if not refresh_token:
                logger.error("No refreshToken in login response")
                return False

            self._refresh_token = refresh_token

            # Generate TOTP
            try:
                import pyotp
                totp = pyotp.TOTP(self.totp_secret).now()
                logger.info("TOTP generated successfully")
            except ImportError:
                logger.warning("pyotp not installed, using fallback TOTP")
                totp = input("Enter 6-digit TOTP from your authenticator: ")

            verify_resp = client.session.verifytotp(
                totp=totp,
                refreshToken=self._refresh_token,
            )
            logger.info(f"TOTP verify response: {verify_resp}")

            if not verify_resp.get("status"):
                msg = verify_resp.get("message", "TOTP verify failed")
                logger.error(f"M-Stock TOTP failed: {msg}")
                return False

            token_data = verify_resp.get("data", {})
            self._access_token = token_data.get("mconnect", {}).get(
                "access_token", ""
            )
            if not self._access_token:
                logger.error("No access_token in TOTP response")
                return False

            # Re-connect with token
            client = mStock.connect(self.api_key, token=self._access_token)
            self._client = client
            self._connected = True
            logger.info("M-Stock connected successfully!")
            return True

        except ImportError as e:
            logger.error(
                "mStock SDK not installed. Run: pip install mStock-TradingApi-B"
            )
            return False
        except Exception as e:
            logger.error(f"M-Stock connection error: {e}")
            return False

    def disconnect(self):
        with self._lock:
            self._connected = False
            self._client = None
            self._access_token = None
        logger.info("M-Stock disconnected")

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo:
        if not self._connected or self._client is None:
            return self._dummy_account("Not connected")

        try:
            resp = self._client.portfolio.getHoldingPosition()
            logger.debug(f"Holding response: {resp}")

            # Get margins
            resp2 = self._client.order.getMargin()

            balance = 0.0
            margin_used = 0.0
            if resp2.get("status"):
                data = resp2.get("data", {})
                balance = float(data.get("availablecash", 0))
                margin_used = float(data.get("utilisedmargin", 0))

            equity = balance + margin_used

            return AccountInfo(
                brokerage_name="M-Stock",
                client_id=self.client_code,
                balance=balance,
                margin=margin_used,
                equity=equity,
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
        )

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> List[Position]:
        if not self._connected or self._client is None:
            return []

        try:
            resp = self._client.portfolio.getPosition()
            if not resp.get("status"):
                return []

            positions = []
            for item in resp.get("data", []):
                qty = int(item.get("netqty", 0))
                if qty == 0:
                    continue
                avg = float(item.get("avgnetprice", 0))
                ltp = float(item.get("ltp", 0))
                inst = item.get("symbol", "")

                pnl = (ltp - avg) * qty if qty > 0 else (avg - ltp) * abs(qty)
                side = PositionSide.LONG if qty > 0 else PositionSide.SHORT

                positions.append(Position(
                    instrument=inst,
                    side=side,
                    quantity=abs(qty),
                    avg_price=avg,
                    unrealized_pnl=pnl,
                ))
            return positions

        except Exception as e:
            logger.error(f"Error fetching M-Stock positions: {e}")
            return []

    # ── Quotes ────────────────────────────────────────────────────────────────

    def get_quote(self, instrument: str) -> Quote:
        if not self._connected or self._client is None:
            return self._dummy_quote(instrument, "Not connected")

        try:
            resp = self._client.scrip.getScripDetails(
                exchange="NFO", symbol=instrument, token=""
            )
            if not resp.get("status"):
                return self._dummy_quote(instrument, resp.get("message", ""))

            data = resp.get("data", [{}])[0]
            ltp  = float(data.get("ltp", 0))
            bp   = float(data.get("bp", 0))
            sp   = float(data.get("sp", 0))
            vol  = int(data.get("volume", 0))
            ts   = int(time.time())

            return Quote(
                instrument=instrument,
                last_price=ltp,
                bid=bp,
                ask=sp,
                volume=vol,
                timestamp=ts,
            )
        except Exception as e:
            logger.error(f"Error fetching quote for {instrument}: {e}")
            return self._dummy_quote(instrument, str(e))

    def _dummy_quote(self, instrument: str, reason: str) -> Quote:
        return Quote(
            instrument=instrument,
            last_price=0.0,
            bid=0.0,
            ask=0.0,
            volume=0,
            timestamp=int(time.time()),
        )

    # ── Candles ───────────────────────────────────────────────────────────────

    def get_candles(self, instrument: str, interval: str,
                    from_ts: int, to_ts: int) -> List[OHLC]:
        if not self._connected or self._client is None:
            return []

        interval_key = _INTERVAL_MAP.get(interval, "FIFTEEN_MINUTE")

        try:
            resp = self._client.scrip.getCandleData(
                exchange="NFO",
                symbol=instrument,
                token="",
                interval=interval_key,
                fromDate=str(from_ts),
                toDate=str(to_ts),
            )
            if not resp.get("status"):
                logger.warning(f"Candle fetch failed: {resp.get('message', '')}")
                return []

            candles = []
            for row in resp.get("data", []):
                candles.append(OHLC(
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=int(row[5]) if len(row) > 5 else 0,
                ))
            return candles

        except Exception as e:
            logger.error(f"Error fetching candles for {instrument}: {e}")
            return []

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(self, instrument: str, side: OrderSide,
                    quantity: int, order_type: OrderType,
                    price: Optional[float] = None,
                    trigger_price: Optional[float] = None) -> Order:
        if not self._connected or self._client is None:
            return self._error_order(instrument, "Not connected")

        exchange = "NFO"
        product_type = "NRML"
        side_str = "BUY" if side == OrderSide.BUY else "SELL"

        try:
            if order_type == OrderType.MARKET:
                resp = self._client.order.placeOrder(
                    exchange=exchange,
                    symbol=instrument,
                    quantity=str(quantity),
                    price="0",
                    triggerPrice="0",
                    productType=product_type,
                    orderType="MARKET",
                    side=side_str,
                    source="API",
                )
            elif order_type == OrderType.SL:
                resp = self._client.order.placeOrder(
                    exchange=exchange,
                    symbol=instrument,
                    quantity=str(quantity),
                    price=str(price or 0),
                    triggerPrice=str(trigger_price or 0),
                    productType=product_type,
                    orderType="STOP_LOSS_LIMIT",
                    side=side_str,
                    source="API",
                )
            else:
                resp = self._client.order.placeOrder(
                    exchange=exchange,
                    symbol=instrument,
                    quantity=str(quantity),
                    price=str(price or 0),
                    triggerPrice="0",
                    productType=product_type,
                    orderType="LIMIT",
                    side=side_str,
                    source="API",
                )

            logger.info(f"Order placed: {resp}")

            if not resp.get("status"):
                return self._error_order(instrument, resp.get("message", "Failed"))

            order_id = str(resp.get("data", {}).get("orderId", ""))
            return Order(
                order_id=order_id,
                instrument=instrument,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                status=OrderStatus.OPEN,
            )

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return self._error_order(instrument, str(e))

    def cancel_order(self, order_id: str) -> bool:
        if not self._connected or self._client is None:
            return False
        try:
            resp = self._client.order.cancelOrder(orderId=order_id, source="API")
            return resp.get("status", False)
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    def get_order_status(self, order_id: str) -> Order:
        if not self._connected or self._client is None:
            return self._error_order("", "Not connected")
        try:
            resp = self._client.order.getOrderBook()
            for item in resp.get("data", []):
                if str(item.get("orderId")) == order_id:
                    status_map = {
                        "OPEN": OrderStatus.OPEN,
                        "COMPLETE": OrderStatus.FILLED,
                        "CANCELLED": OrderStatus.CANCELLED,
                        "REJECTED": OrderStatus.REJECTED,
                    }
                    return Order(
                        order_id=order_id,
                        instrument=item.get("symbol", ""),
                        side=OrderSide.BUY if item.get("side") == "BUY" else OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        quantity=int(item.get("qty", 0)),
                        price=float(item.get("price", 0)),
                        filled_qty=int(item.get("filledQty", 0)),
                        average_price=float(item.get("averagePrice", 0)),
                        status=status_map.get(item.get("status", ""), OrderStatus.PENDING),
                        timestamp=int(item.get("time", 0)),
                    )
            return self._error_order("", f"Order {order_id} not found")
        except Exception as e:
            return self._error_order("", str(e))

    def close_position(self, instrument: str) -> Order:
        positions = self.get_positions()
        for pos in positions:
            if pos.instrument == instrument:
                side = OrderSide.SELL if pos.side == PositionSide.LONG else OrderSide.BUY
                return self.place_order(
                    instrument, side, pos.quantity, OrderType.MARKET
                )
        return self._error_order(instrument, "No open position")

    def _error_order(self, instrument: str, message: str) -> Order:
        return Order(
            order_id="ERROR",
            instrument=instrument,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0,
            price=None,
            status=OrderStatus.ERROR,
            message=message,
        )

    # ── NFO Instrument List ─────────────────────────────────────────────────

    def get_nfo_instruments(self) -> List[str]:
        """
        Fetch all available NSE F&O futures contract symbols from M-Stock.
        Returns a list like ['SBIN26SEPFUT', 'BANKBARODA26SEPFUT', ...]
        Falls back to a hardcoded list if the API call fails.
        """
        if not self._connected or self._client is None:
            logger.warning("M-Stock not connected — cannot fetch NFO instrument list")
            return []

        try:
            # M-Stock: try to fetch scrip list for NFO exchange
            resp = self._client.scrip.getScripData(exchange="NFO", productType="FUT")
            if resp.get("status"):
                data = resp.get("data", [])
                futures = [
                    item.get("symbol", "")
                    for item in data
                    if item.get("instrumentType", "").upper() in ("FUTSTK", "FUTIDX")
                       and item.get("symbol", "")
                ]
                logger.info(f"M-Stock: fetched {len(futures)} futures from NFO")
                return futures
        except Exception as e:
            logger.warning(f"M-Stock get_nfo_instruments error: {e}")

        # Fallback: return empty list (broker API not fully implemented)
        # The hardcoded dashboard stock list will be shown as-is
        logger.info("M-Stock: using fallback empty instrument list")
        return []

    def get_available_futures_for_symbols(self, base_symbols: List[str]) -> List[str]:
        """
        Given a list of base symbols (e.g. ['SBIN','BANKBARODA']),
        return which ones are available as futures in the current expiry cycle.
        """
        available = set(self.get_nfo_instruments())
        if not available:
            # No broker data — optimistically return all requested symbols with current expiry
            from datetime import datetime
            month_map = {
                1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
                5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
                9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
            }
            now = datetime.now()
            yr  = str(now.year)[2:]
            expiry_suffix = f"{yr}{month_map[now.month]}FUT"
            return [f"{sym}{expiry_suffix}" for sym in base_symbols]

        matched = []
        for sym in base_symbols:
            for expiry in ["26SEPFUT", "26OCTFUT", "26DECFUT",
                           "27JANFUT", "27FEBFUT", "27MARFUT"]:
                inst = f"{sym}{expiry}"
                if inst in available:
                    matched.append(inst)
                    break
        return matched


# ── Register ──────────────────────────────────────────────────────────────────
register_broker("MSTOCK", MStockBroker)
