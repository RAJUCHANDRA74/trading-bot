"""
=============================================================
backtest.py — Backtesting Module
=============================================================
Runs historical backtests on any strategy.
Used for validating parameters before live trading.
=============================================================
"""
import csv
import logging
from typing import List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger("backtest")

INITIAL_CAPITAL = 100_000
LOT_SIZE = 30


def load_csv(path: str) -> List[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "date":  row["date"],
                "open":  float(row["open"]),
                "high":  float(row["high"]),
                "low":   float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row.get("volume", 0)),
            })
    return rows


@dataclass
class BTResult:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    return_pct: float
    avg_win: float
    avg_loss: float
    rr_ratio: float
    max_dd: float
    longs: int
    shorts: int
    breakevens: int
    trades: list


def run(data_path: str,
        stop_pct: float = 3.0,
        be_pct: float = 2.5,
        atr_threshold: float = 2.0,
        reversal_exit: bool = True,
        trend_filter: bool = False,
        initial_capital: float = INITIAL_CAPITAL,
        lot_size: int = LOT_SIZE,
        ) -> Dict[str, Any]:
    """
    Run SAR Top-Bottom backtest on OHLC data.
    Returns a result dict with full trade log.
    """
    data = load_csv(data_path)
    if not data:
        return {"error": "No data loaded"}

    capital = initial_capital
    position = None
    trades = []
    stats = {"total": 0, "wins": 0, "losses": 0,
             "longs": 0, "shorts": 0, "pnl": 0, "breakevens": 0}
    recent_tops, recent_bots = [], []

    # Compute ATR for each day
    atr_pct = compute_atr_pct(data)

    for i in range(2, len(data) - 1):
        row = data[i]
        open_p, high, low, close = row["open"], row["high"], row["low"], row["close"]
        atr = atr_pct[i]

        # Update swing points
        if i > 0 and data[i]["close"] > data[i-1]["close"] and data[i]["close"] > data[i+1]["close"]:
            recent_tops.append((i, data[i]["close"]))
        if i > 0 and data[i]["close"] < data[i-1]["close"] and data[i]["close"] < data[i+1]["close"]:
            recent_bots.append((i, data[i]["close"]))
        if len(recent_tops) > 20: recent_tops = recent_tops[-20:]
        if len(recent_bots) > 20: recent_bots = recent_bots[-20:]

        # ATR filter
        if atr is not None and atr >= atr_threshold:
            continue   # Skip entry in volatile market

        pos = position

        if pos is None:
            # Entry
            if recent_tops:
                t_idx, t_price = recent_tops[-1]
                if close > t_price and i > t_idx:
                    if not trend_filter or (data[i-1]["close"] > data[i-1]["open"]):
                        direction = "LONG"
                        entry_price = close
                        stop = close * (1 - stop_pct / 100)
                        position = {
                            "direction": direction, "entry_price": entry_price,
                            "stop_price": stop, "entry_date": row["date"],
                            "entry_idx": i, "be_done": False,
                        }
                        stats["total"] += 1
                        stats["longs"] += 1
            if position is None and recent_bots:
                b_idx, b_price = recent_bots[-1]
                if close < b_price and i > b_idx:
                    if not trend_filter or (data[i-1]["close"] < data[i-1]["open"]):
                        direction = "SHORT"
                        entry_price = close
                        stop = close * (1 + stop_pct / 100)
                        position = {
                            "direction": direction, "entry_price": entry_price,
                            "stop_price": stop, "entry_date": row["date"],
                            "entry_idx": i, "be_done": False,
                        }
                        stats["total"] += 1
                        stats["shorts"] += 1

        else:
            direction   = pos["direction"]
            entry       = pos["entry_price"]
            stop        = pos["stop_price"]
            be_done     = pos["be_done"]
            entry_idx   = pos["entry_idx"]
            pct = ((close - entry) / entry * 100) if direction == "LONG" \
                  else ((entry - close) / entry * 100)

            bot_prices  = [recent_bots[j][1] for j in range(len(recent_bots))
                            if recent_bots[j][0] > entry_idx]
            top_prices  = [recent_tops[j][1] for j in range(len(recent_tops))
                            if recent_tops[j][0] > entry_idx]
            prev_bottom = min(bot_prices) if bot_prices else entry
            prev_top    = max(top_prices) if top_prices else entry

            exited, reason = False, ""

            # Stop loss
            if direction == "LONG" and low <= stop:
                exited, reason = True, "stop_hit"
            elif direction == "SHORT" and high >= stop:
                exited, reason = True, "stop_hit"

            # Trailing stop
            if not exited:
                if not be_done:
                    if direction == "LONG":
                        trail = min(prev_bottom, entry * (1 - stop_pct / 100))
                        pos["stop_price"] = max(stop, trail)
                    else:
                        trail = max(prev_top, entry * (1 + stop_pct / 100))
                        pos["stop_price"] = min(stop, trail)
                else:
                    if direction == "LONG":
                        trail = min(prev_bottom, entry * (1 - stop_pct * 1.5 / 100))
                        pos["stop_price"] = max(stop, trail)
                    else:
                        trail = max(prev_top, entry * (1 + stop_pct * 1.5 / 100))
                        pos["stop_price"] = min(stop, trail)

            # Breakeven
            if not exited and not be_done and pct >= be_pct:
                pos["be_done"] = True
                pos["stop_price"] = entry
                stats["breakevens"] += 1

            if exited:
                exit_price = stop
                pnl = (exit_price - entry) * lot_size if direction == "LONG" \
                      else (entry - exit_price) * lot_size
                capital += pnl
                stats["pnl"] += pnl
                if pnl > 0: stats["wins"] += 1
                else: stats["losses"] += 1
                trades.append({
                    "direction": direction, "entry_date": pos["entry_date"],
                    "exit_date": row["date"], "entry_price": entry,
                    "exit_price": exit_price, "pnl": round(pnl, 2),
                    "reason": reason,
                })
                position = None

            # Reversal exit
            elif reversal_exit:
                if direction == "LONG" and recent_bots:
                    last_bi, last_bp = recent_bots[-1]
                    if close < last_bp and last_bi > entry_idx:
                        position = None
                        exit_price = close
                        pnl = (exit_price - entry) * lot_size
                        capital += pnl
                        stats["pnl"] += pnl
                        if pnl > 0: stats["wins"] += 1
                        else: stats["losses"] += 1
                        trades.append({
                            "direction": direction, "entry_date": pos["entry_date"],
                            "exit_date": row["date"], "entry_price": entry,
                            "exit_price": exit_price, "pnl": round(pnl, 2),
                            "reason": "signal_reversal",
                        })
                elif direction == "SHORT" and recent_tops:
                    last_ti, last_tp = recent_tops[-1]
                    if close > last_tp and last_ti > entry_idx:
                        position = None
                        exit_price = close
                        pnl = (entry - exit_price) * lot_size
                        capital += pnl
                        stats["pnl"] += pnl
                        if pnl > 0: stats["wins"] += 1
                        else: stats["losses"] += 1
                        trades.append({
                            "direction": direction, "entry_date": pos["entry_date"],
                            "exit_date": row["date"], "entry_price": entry,
                            "exit_price": exit_price, "pnl": round(pnl, 2),
                            "reason": "signal_reversal",
                        })

    # Close open position at end
    if position:
        last = data[-1]
        pnl = (last["close"] - position["entry_price"]) * lot_size \
              if position["direction"] == "LONG" \
              else (position["entry_price"] - last["close"]) * lot_size
        capital += pnl
        stats["pnl"] += pnl
        if pnl > 0: stats["wins"] += 1
        else: stats["losses"] += 1
        trades.append({
            "direction": position["direction"],
            "entry_date": position["entry_date"],
            "exit_date": last["date"],
            "entry_price": position["entry_price"],
            "exit_price": last["close"],
            "pnl": round(pnl, 2),
            "reason": "end_of_data",
        })

    total = stats["total"]
    wins  = stats["wins"]
    win_t = [t for t in trades if t["pnl"] > 0]
    los_t = [t for t in trades if t["pnl"] <= 0]

    return {
        "params": {
            "stop_pct": stop_pct, "be_pct": be_pct,
            "atr_threshold": atr_threshold,
            "reversal_exit": reversal_exit,
            "trend_filter": trend_filter,
        },
        "total_trades": total,
        "wins": wins,
        "losses": stats["losses"],
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "total_pnl": round(stats["pnl"], 2),
        "return_pct": round(stats["pnl"] / initial_capital * 100, 2),
        "avg_win": round(sum(t["pnl"] for t in win_t) / len(win_t), 2) if win_t else 0,
        "avg_loss": round(sum(t["pnl"] for t in los_t) / len(los_t), 2) if los_t else 0,
        "rr_ratio": round(
            abs(sum(t["pnl"] for t in win_t) / len(win_t) /
                (sum(t["pnl"] for t in los_t) / len(los_t))) if los_t else 0, 2
        ),
        "longs": stats["longs"],
        "shorts": stats["shorts"],
        "breakevens": stats["breakevens"],
        "trades": trades,
    }


def compute_atr_pct(data: List[dict], period: int = 14) -> List[float]:
    """Compute ATR% for each candle."""
    result = [None] * len(data)
    trs = []
    for i in range(1, len(data)):
        h = data[i]["high"]
        l = data[i]["low"]
        pc = data[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
        if i >= period:
            atr = sum(trs[i-period:i]) / period
            result[i] = atr / data[i]["close"] * 100
    return result
