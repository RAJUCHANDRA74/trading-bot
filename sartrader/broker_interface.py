"""
=============================================================
broker_interface.py — Abstract Broker Interface
=============================================================
All brokers (M-Stock, Zerodha, etc.) implement this interface.
The trading engine only talks to this interface — never directly
to any broker SDK.
=============================================================
"""
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum

logger = logging.getLogger(__name__)


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT  = "LIMIT"
    SL     = "SL"
    SLM    = "SLM"        # Stop Loss Market


class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class PositionSide(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    FLAT  = "FLAT"


class OrderStatus(str, Enum):
    PENDING  = "PENDING"
    OPEN     = "OPEN"
    FILLED   = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR    = "ERROR"


@dataclass
class OHLC:
    timestamp: int          # Unix timestamp (seconds)
    open:       float
    high:       float
    low:        float
    close:      float
    volume:     int = 0


@dataclass
class Quote:
    instrument: str
    last_price: float
    bid:        float
    ask:        float
    volume:     int
    timestamp:  int          # Unix timestamp


@dataclass
class Order:
    order_id:        str
    instrument:      str
    side:            OrderSide
    order_type:      OrderType
    quantity:        int
    price:           Optional[float]   # None for MARKET/SLM
    trigger_price:   Optional[float]   # For SL orders
    filled_qty:      int = 0
    average_price:   Optional[float] = None
    status:          OrderStatus = OrderStatus.PENDING
    timestamp:       int = field(default_factory=lambda: int(time.time()))
    message:         str = ""


@dataclass
class Position:
    instrument:    str
    side:           PositionSide
    quantity:       int
    avg_price:      float
    unrealized_pnl: float = 0.0
    realized_pnl:   float = 0.0


@dataclass
class AccountInfo:
    brokerage_name: str
    client_id:      str
    balance:        float          # Available cash
    margin:         float          # Used margin
    equity:         float          # Total equity
    currency:       str = "INR"


# ── Abstract Broker ────────────────────────────────────────────────────────────

class AbstractBroker(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Broker display name: 'M-Stock', 'Zerodha', etc."""
        ...

    @abstractmethod
    def connect(self) -> bool:
        """
        Initialize connection. For M-Stock: login + TOTP.
        For Zerodha: get access token.
        Returns True if successful, False otherwise.
        """
        ...

    @abstractmethod
    def disconnect(self):
        """Close connection cleanly."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if broker is currently connected."""
        ...

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Fetch account balance, margin, equity."""
        ...

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Get all open positions."""
        ...

    @abstractmethod
    def get_quote(self, instrument: str) -> Quote:
        """Get live quote for an instrument."""
        ...

    @abstractmethod
    def get_candles(self, instrument: str, interval: str,
                    from_ts: int, to_ts: int) -> List[OHLC]:
        """
        Fetch historical OHLC candles.
        interval: '1m', '5m', '15m', '30m', '1h', '1d'
        from_ts / to_ts: Unix timestamps
        """
        ...

    @abstractmethod
    def place_order(self, instrument: str, side: OrderSide,
                    quantity: int, order_type: OrderType,
                    price: Optional[float] = None,
                    trigger_price: Optional[float] = None) -> Order:
        """Place a new order. Returns Order object with order_id."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> Order:
        """Get current status of an order."""
        ...

    @abstractmethod
    def close_position(self, instrument: str) -> Order:
        """Close entire position in one order."""
        ...


# ── Broker Factory ────────────────────────────────────────────────────────────

_BROKERS: Dict[str, type] = {}


def register_broker(name: str, broker_class: type):
    """Register a broker class. Call this at bottom of each broker file."""
    _BROKERS[name.upper()] = broker_class


def get_broker(name: str, **kwargs) -> AbstractBroker:
    """Get broker instance by name."""
    name = name.upper()
    if name not in _BROKERS:
        raise ValueError(
            f"Unknown broker: '{name}'. Available: {list(_BROKERS.keys())}"
        )
    return _BROKERS[name](**kwargs)


def list_brokers() -> List[str]:
    return list(_BROKERS.keys())
