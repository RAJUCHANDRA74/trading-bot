"""
=============================================================
M-STOCK Broker Execution Module (module_03)
=============================================================
S-A-R Strategy Broker Connector using Official M-Stock SDK.
Compatible with both paper trading and live trading.

AUTH FLOW:
  1. mconnect.login(client_code, password)
     → sends SMS OTP (ignored), returns refreshToken
  2. mconnect.verify_totp(api_key, refreshToken, totp_code)
     → returns JWT, stored in mconnect.access_token
  3. All subsequent calls use the JWT automatically

TOKEN EXPIRY: Midnight (00:00) same day.
  → Re-authenticate each trading day before use.

WHITELIST: Your home IP must be whitelisted in M-Stock portal.
  Current IP: 103.176.241.46
=============================================================
"""

import sys, os, json, time, logging
from datetime import datetime, date
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

# ── M-Stock SDK ──────────────────────────────────────────────
try:
    from tradingapi_b.mconnect import MConnectB
    import pyotp
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    print("WARNING: mStock-TradingApi-B not installed. Run: pip install mStock-TradingApi-B")

# ── Config ───────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)


# ── M-Stock Connection ──────────────────────────────────────
class MStockConnection:
    """
    Manages M-Stock Type B API connection.
    Handles authentication, token refresh, and API calls.
    """

    def __init__(self, api_key: str = None, client_code: str = None,
                 password: str = None, totp_secret: str = None,
                 paper_mode: bool = True):
        """
        Args:
            api_key: M-Stock API key from trade.mstock.com
            client_code: Your M-Stock client code (e.g. MA1116489)
            password: M-Stock trading password
            totp_secret: TOTP secret from Google Authenticator
            paper_mode: If True, simulates orders without sending to exchange
        """
        if not SDK_AVAILABLE:
            raise RuntimeError("mStock-TradingApi-B not installed")

        self.api_key = api_key
        self.client_code = client_code
        self.password = password
        self.totp_secret = totp_secret
        self.paper_mode = paper_mode
        self.mconnect = None
        self._connected = False

    # ── Authentication ────────────────────────────────────────
    def connect(self) -> bool:
        """Authenticate with M-Stock using TOTP. Returns True on success."""
        try:
            self.mconnect = MConnectB()
            self.mconnect.set_api_key(self.api_key)

            # Step 1: Login → get refreshToken (sends SMS OTP which we ignore)
            login_resp = self.mconnect.login(self.client_code, self.password)
            login_data = login_resp.json()
            if not login_data.get("status"):
                print(f"[MStock] Login failed: {login_data.get('message')}")
                return False

            raw_data = login_data.get("data")
            if not raw_data:
                print(f"[MStock] No data in login response: {login_data}")
                return False
            data = raw_data[0] if isinstance(raw_data, list) else raw_data
            refresh_token = data.get("refreshToken")
            if not refresh_token:
                print(f"[MStock] No refreshToken in login response")
                return False

            # Step 2: Verify TOTP → get JWT
            totp_code = pyotp.TOTP(self.totp_secret).now()
            verify_resp = self.mconnect.verify_totp(
                self.api_key, refresh_token, totp_code
            )
            verify_data = verify_resp.json()
            if not verify_data.get("status"):
                print(f"[MStock] TOTP verify failed: {verify_data.get('message')}")
                return False

            self._connected = True
            token = self.mconnect.access_token
            print(f"[MStock] Connected! Token expires at midnight.")
            print(f"[MStock] Paper Mode: {self.paper_mode}")
            return True

        except Exception as e:
            print(f"[MStock] Connection error: {e}")
            return False

    def is_connected(self) -> bool:
        return self._connected and self.mconnect is not None

    def get_access_token(self) -> Optional[str]:
        """Return current access token."""
        if self.mconnect:
            return self.mconnect.access_token
        return None

    # ── Account Info ─────────────────────────────────────────
    def get_fund_summary(self) -> dict:
        """Get available cash and margin information."""
        if not self.is_connected():
            return {"status": False, "data": None, "error": "Not connected"}

        try:
            result = self.mconnect.get_fund_summary()
            data = result.json() if hasattr(result, 'json') else result
            return data
        except Exception as e:
            return {"status": False, "error": str(e)}

    def get_positions(self) -> dict:
        """Get current net positions."""
        if not self.is_connected():
            return {"status": False, "error": "Not connected"}

        try:
            result = self.mconnect.get_net_position()
            data = result.json() if hasattr(result, 'json') else result
            return data
        except Exception as e:
            return {"status": False, "error": str(e)}

    def get_holdings(self) -> dict:
        """Get holdings (delivery stocks)."""
        if not self.is_connected():
            return {"status": False, "error": "Not connected"}

        try:
            result = self.mconnect.get_holdings()
            data = result.json() if hasattr(result, 'json') else result
            return data
        except Exception as e:
            return {"status": False, "error": str(e)}

    # ── Order Placement ───────────────────────────────────────
    def place_order(self, symbol: str, exchange: str, transaction_type: str,
                    quantity: int, order_type: str = "LIMIT",
                    price: float = None, trigger_price: float = None,
                    product: str = "INTRADAY") -> dict:
        """
        Place a BUY or SELL order.

        Args:
            symbol: Trading symbol (e.g. "BANKNIFTY", "RELIANCE")
            exchange: "NSE" or "NSEFO"
            transaction_type: "BUY" or "SELL"
            quantity: Number of units
            order_type: "LIMIT", "MARKET", or "SL"
            price: Limit price (required for LIMIT orders)
            trigger_price: Stop-loss trigger price
            product: "INTRADAY", "DELIVERY", or "MARGIN"

        Returns:
            Order response from M-Stock
        """
        if not self.is_connected():
            return {"status": False, "error": "Not connected"}

        if self.paper_mode:
            return self._paper_order(symbol, exchange, transaction_type,
                                     quantity, order_type, price, product)

        try:
            result = self.mconnect.place_order(
                exchange=exchange,
                symbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                price=price,
                order_type=order_type,
                product_type=product,
                trigger_price=trigger_price
            )
            data = result.json() if hasattr(result, 'json') else result
            return data
        except Exception as e:
            return {"status": False, "error": str(e)}

    def cancel_order(self, order_id: str, exchange: str = "NSEFO") -> dict:
        """Cancel a pending order."""
        if not self.is_connected():
            return {"status": False, "error": "Not connected"}

        if self.paper_mode:
            return {"status": True, "message": "Paper mode - order not placed"}

        try:
            result = self.mconnect.cancel_order(order_id=order_id, exchange=exchange)
            data = result.json() if hasattr(result, 'json') else result
            return data
        except Exception as e:
            return {"status": False, "error": str(e)}

    def get_order_book(self) -> dict:
        """Get all orders (open + executed)."""
        if not self.is_connected():
            return {"status": False, "error": "Not connected"}

        try:
            result = self.mconnect.get_order_book()
            data = result.json() if hasattr(result, 'json') else result
            return data
        except Exception as e:
            return {"status": False, "error": str(e)}

    # ── Paper Order Simulation ─────────────────────────────────
    def _paper_order(self, symbol, exchange, transaction_type,
                     quantity, order_type, price, product):
        """Simulate an order without sending to exchange."""
        order_id = f"PAPER_{int(time.time()*1000)}"
        return {
            "status": True,
            "message": "PAPER ORDER (not sent to exchange)",
            "data": {
                "order_id": order_id,
                "symbol": symbol,
                "exchange": exchange,
                "transaction_type": transaction_type,
                "quantity": quantity,
                "order_type": order_type,
                "price": price,
                "product": product,
                "paper": True
            }
        }

    def disconnect(self):
        """Logout and close connection."""
        if self.mconnect:
            try:
                self.mconnect.logout()
            except Exception:
                pass
        self._connected = False
        self.mconnect = None


# ── Quick Connect Helper ─────────────────────────────────────
def quick_connect(paper_mode: bool = True) -> MStockConnection:
    """
    Connect to M-Stock using credentials from data/config.json.
    Returns a connected MStockConnection object.
    """
    cfg = load_config()

    conn = MStockConnection(
        api_key=cfg.get("api_key"),
        client_code=cfg.get("client_code"),
        password=cfg.get("password"),
        totp_secret=cfg.get("totp_secret"),
        paper_mode=paper_mode
    )

    if not conn.connect():
        raise RuntimeError("Failed to connect to M-Stock")

    return conn


# ── Test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import io
    # Fix Windows console encoding for ₹ symbol
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  M-STOCK BROKER MODULE TEST")
    print("=" * 60)

    try:
        conn = quick_connect(paper_mode=True)

        # Fund summary
        funds = conn.get_fund_summary()
        if funds.get("status"):
            data = funds.get("data", [{}])[0]
            balance = data.get('AVAILABLE_BALANCE', 'N/A')
            clear = data.get('CLEAR_BALANCE', 'N/A')
            print(f"\n  Available Balance: Rs.{balance}")
            print(f"  Clear Balance: Rs.{clear}")
            print(f"  Paper Mode: {conn.paper_mode}")

        # Positions
        positions = conn.get_positions()
        if positions.get("status"):
            pos_data = positions.get("data", [])
            if isinstance(pos_data, list):
                print(f"\n  Open Positions: {len(pos_data)}")
            elif isinstance(pos_data, dict):
                print(f"\n  Positions: {pos_data}")

        # Test a paper BUY order
        print("\n  Testing paper BUY order...")
        order = conn.place_order(
            symbol="BANKNIFTY",
            exchange="NSEFO",
            transaction_type="BUY",
            quantity=25,
            order_type="MARKET",
            product="INTRADAY"
        )
        print(f"  Order result: {json.dumps(order, indent=4)}")

        conn.disconnect()
        print("\n  DISCONNECTED")

    except Exception as e:
        import traceback
        print(f"\n  ERROR: {e}")
        traceback.print_exc()
