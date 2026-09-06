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
import time
import logging
import threading
from typing import List, Optional

from sartrader.broker_interface import (
    AbstractBroker, AccountInfo, Position, Quote,
    OHLC, OrderType, OrderSide, OrderStatus, PositionSide,
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
            return True

        except ImportError as e:
            logger.error(f"Missing dependency: {e}")
            return False
        except Exception as e:
            logger.error(f"M-Stock connection error: {e}")
            return False

    def disconnect(self):
        with self._lock:
            if self._client:
                try:
                    self._client.logout()
                except Exception:
                    pass
            self._connected = False
            self._client = None
        logger.info("M-Stock disconnected")

    # ── Helpers ──────────────────────────────────────────────────────────────

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
        """Return list of available NFO futures/option symbols."""
        if not self._connected or self._client is None:
            return []
        try:
            resp = self._client.get_instruments()
            data = self._get_json(resp)
            if not data.get("status"):
                return []
            symbols = []
            for item in data.get("data", []) or []:
                sym = item.get("symbol", "") or item.get("tradingsymbol", "")
                exch = item.get("exchange", "")
                if exch in ("NFO", "2") and sym:
                    symbols.append(sym)
            logger.info(f"M-Stock NFO instruments: {len(symbols)} symbols")
            return list(set(symbols))
        except Exception as e:
            logger.error(f"get_nfo_instruments error: {e}")
            return []

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
        """Fetch LTP for an instrument via intraday_chart (last candle close)."""
        if not self._connected or self._client is None:
            return self._dummy_quote(instrument, "Not connected")

        # Try NFO first (futures/options), then NSE (cash)
        for exchange in ["NFO", "NSE"]:
            try:
                exch_code = self._resolve_exchange(exchange)
                resp = self._client.get_intraday_chart(
                    _exchange=exch_code,
                    _symboltoken=instrument,
                    _interval="ONE_MINUTE",
                )
                cdata = self._get_json(resp)
                if cdata.get("status") and cdata.get("data"):
                    rows = cdata["data"].get("candles", []) or cdata["data"]
                    if rows and isinstance(rows, list) and len(rows) > 0:
                        last = rows[-1]
                        if isinstance(last, list) and len(last) >= 5:
                            ltp = float(last[4])  # close price
                            return Quote(
                                instrument=instrument,
                                last_price=ltp,
                                bid=ltp,
                                ask=ltp,
                                volume=0,
                                timestamp=int(time.time()),
                            )
            except Exception:
                continue

        return self._dummy_quote(instrument, "No quote available")

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

    def get_candles(self, instrument: str, interval: str,
                    from_ts: int, to_ts: int) -> List[OHLC]:
        if not self._connected or self._client is None:
            return []

        interval_key = _INTERVAL_MAP.get(interval, "FIFTEEN_MINUTE")

        # Try NFO first, then NSE
        for exchange in ["NFO", "NSE"]:
            try:
                exch_code = self._resolve_exchange(exchange)
                resp = self._client.get_intraday_chart(
                    _exchange=exch_code,
                    _symboltoken=instrument,
                    _interval=interval_key,
                )
                cdata = self._get_json(resp)
                if not cdata.get("status"):
                    continue

                rows = cdata.get("data", {}).get("candles", []) or cdata.get("data", [])
                candles = []

                for row in rows:
                    if isinstance(row, list) and len(row) >= 5:
                        ts_str = row[0]
                        o = float(row[1])
                        h = float(row[2])
                        l = float(row[3])
                        c = float(row[4])
                        v = int(row[5]) if len(row) > 5 else 0

                        # Parse timestamp — M-Stock returns IST naive datetime
                        try:
                            from datetime import datetime, timezone, timedelta
                            IST = timezone(timedelta(hours=5, minutes=30))
                            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
                            ts = int(dt.timestamp())
                        except Exception:
                            ts = int(time.time())

                        # Filter by time window
                        if from_ts <= ts <= to_ts:
                            candles.append(OHLC(
                                timestamp=ts,
                                open=o, high=h, low=l, close=c,
                                volume=v,
                            ))

                if candles:
                    logger.info(f"M-Stock candles for {instrument} on {exchange}: {len(candles)} bars")
                    return candles

            except Exception as e:
                logger.debug(f"Candle fetch {instrument}@{exchange}: {e}")
                continue

        logger.warning(f"No M-Stock candles for {instrument}")
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
