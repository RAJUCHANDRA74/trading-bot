# SARTrader — Agent Collaboration Guide

## Project Overview

**SARTrader** is a semi-automated NSE futures trading platform built for swing/positional trading.
- **Market**: NSE futures segment (Index Futures: NIFTY, BANKNIFTY, FINNIFTY; Stock Futures)
- **Broker**: M-Stock (Integrated Stock Brokers Pvt. Ltd.)
- **Framework**: Python 3.12, websockets, Upstox Pro SDK
- **Repo**: `github.com/RAJUCHANDRA74/trading-bot`

---

## Architecture

```
trading-bot/
├── sartrader/
│   ├── __init__.py
│   ├── engine.py          # Core: tick loop, signal routing, position management, TB-1
│   ├── paper_engine.py    # Paper trading engine (capital, trades, positions, DB)
│   ├── broker_interface.py
│   ├── config.py          # INSTRUMENTS, MODE, API keys, tick interval
│   ├── signals.py         # Signal dataclass + SignalType enum
│   ├── strategies/
│   │   └── sar_top_bottom.py   # SAR Top/Bottom + TB-1 R1 daily levels monitor
│   └── brokers/
│       ├── broker_interface.py  # Abstract base + OHLC dataclass
│       ├── mstock_broker.py     # M-Stock: WS streaming, REST API, candles
│       └── zerodha_broker.py    # (reference, not in active use)
├── dashboard/
│   ├── index.html         # Dashboard UI (WebSocket state, trade log, charts)
│   ├── tb1_charts.html    # TB-1 strategy charts (deployed separately)
│   ├── r1_timing_explainer.html
│   └── pyramiding_explainer.html
├── data/
│   ├── watchlist.json     # Persisted watchlist instruments
│   └── trades.db         # SQLite: paper trades + positions
└── sartrader.log         # Runtime log
```

---

## Running the Engine

```powershell
cd C:\Users\Rajkumar\.minimax-agent\projects\trading-bot
python -m sartrader.engine
```

- **Dashboard**: `http://localhost:8765`
- **WebSocket**: `ws://localhost:8766`
- **Mode**: Set in `sartrader/config.py` → `MODE = "PAPER"` or `"LIVE"`
- **TOTP**: In LIVE mode, M-Stock TOTP is auto-generated from `config.MSTOCK["totp_secret"]`

---

## Current Strategy: TB-1 (Swing Top/Bottom — Rules 1–6 + Pyramiding)

### Rule 1 — Swing Top/Bottom (Daily Close Confirmation)
- Applied on **daily closing prices only**
- TOP: `close[N+1] < close[N]` → Day N confirmed as top at Day N+1 close
- BOTTOM: `close[N+1] > close[N]` → Day N confirmed as bottom at Day N+1 close
- Level is confirmed only at **end of Day N+1 trading (15:30 IST)**
- Intraday: only use confirmed levels from previous days' closes

### Rule 2 — Entry (Intraday, no candle-close wait)
- LONG: LTP crosses above most recent confirmed top → fire immediately
- SHORT: LTP crosses below most recent confirmed bottom → fire immediately
- Most recent = last confirmed top/bottom regardless of size/height

### Rule 6 — Day 1 SL (same for R1 and R2 entries)
- Index Futures: `MIN(recent_level, entry × 99%)`
- Stock Futures: `MIN(recent_level, entry × 98.5%)`
- SHORT: `MAX(recent_level, entry × 101%)` / `MAX(recent_level, entry × 101.5%)`

### Rule 3 — Day 2+ SL
- Index Futures: `MIN(recent_level, entry × 98%)`
- Stock Futures: `MIN(recent_level, entry × 97%)`

### Rule 4 — Break-Even Move
- LONG profit > 2% (index) / >3% (stock) → SL moves to entry price
- SHORT profit > 2% (index) / >3% (stock) → SL moves to entry price

### Rule 5 — Gap Day Handling
- LONG example (symmetric for SHORT):
  - Already in LONG, gap-down at open
  - Gap < 2% from SL: wait 15-min candle low break → exit LONG + reverse to SHORT (Day 1)
  - Gap ≥ 2% from SL: exit LONG only, no re-entry, wait fresh R1/R2 signal
- Gap measured: `(SL − today_open) / SL`

### Pyramiding
- Same lot size for every entry
- New pyramid entry fires → initial trade's SL moves to new confirmed level
- New entry: Day 1 → Rule 6 | Day 2+ → Rules 3 & 4
- From Day 2 onwards: ALL units share one unified SL (Rules 3 & 4)
- Each entry's day counter is independent

---

## Key Code Locations

### TB-1 Position Structure
```python
pos = {
    "side":           "LONG" or "SHORT",
    "tb1_mode":       True,
    "entries": [
        {"entry_price": float, "entry_date": "YYYY-MM-DD", "sl": float},
        # ... one per pyramid unit
    ],
    "qty_per_entry":  int,
    "unified_sl":     float,   # shared SL for all units (Rules 3/4)
    "be_done":        bool,
    "be_trigger_price": float,
    "gap_tracking": {
        "prev_close": float, "gap_15m_low": float, "gap_15m_high": float,
        "gap_open": float, "gap_tracked_date": str, "gap_handled": bool
    },
    "recent_level":  float,   # last confirmed R1 top/bottom
}
```

### Critical Methods
| Method | File | Purpose |
|--------|------|---------|
| `_manage_tb1_positions()` | engine.py:1412 | R3/R4/R5 + exit check, every tick |
| `_tb1_enter()` | engine.py:1244 | First entry / pyramid / reversal |
| `_tb1_exit()` | engine.py:1370 | Close all units, record P&L |
| `_tb1_compute_day1_sl()` | engine.py:1069 | Rule 6 SL |
| `_tb1_compute_day2_sl()` | engine.py:1078 | Rule 3 SL |
| `_tb1_compute_unified_sl()` | engine.py:1095 | Unified SL across all entries |
| `_tb1_entry_day()` | engine.py:1087 | Calendar day since entry |
| `_tb1_be_threshold()` | engine.py:1065 | Break-even trigger multiplier |
| `_fetch_and_process()` | engine.py:816 | Tick loop — R1 update, R2 cross, strategy compute |
| `_process_r2_signal()` | engine.py:956 | Handle R2 LONG/SHORT entry signals |
| `TB1R1Monitor` | sar_top_bottom.py | Background thread: fetches daily OHLCV every 15 min |

### Data Sources
| Data | Source | Method |
|------|--------|--------|
| NFO Futures daily OHLC | M-Stock | `get_daily_price()` — resolves NFO token internally |
| Equity cash daily OHLC | M-Stock | `get_daily_price()` |
| Intraday 15m candles | M-Stock | `get_candles()` |
| Live LTP (streaming) | M-Stock WebSocket | `_poll_live_quotes()` → `get_quote()` |
| Index spot price | Yahoo Finance fallback | `_resolve_yf_symbol()` |
| Equity spot price | Yahoo Finance fallback | `_resolve_yf_symbol()` |

### M-Stock Token Resolution (NFO Futures)
- `get_daily_price()` internally resolves: base symbol → NFO expiry → `FUTIDX`/`FUTSTK` token
- `_strip_expiry("BANKNIFTY26SEPFUT")` → `"BANKNIFTY"` (correct)
- `_extract_expiry_for_nfo("BANKNIFTY26SEPFUT")` → `"29Sep2026"` (from token_map keys)
- `_find_nfo_futures_token("BANKNIFTY", "29Sep2026")` → token for NFO BANKNIFTY FUT
- BANKNIFTY FUT uses `FUTIDX` exchange token (NOT `FUTSTK`)

---

## M-Stock API Notes

- **Auth**: TOTP required daily (auto-generated from secret in config)
- **Access token**: Valid to midnight NSE
- **WebSocket**: Subscribes to 25 instruments max per connection
- **IP Whitelist**: `IA403` error = home IP not whitelisted (add in M-Stock settings)
- **get_intraday_chart**: Returns last session only (no historical range filtering)
- **get_daily_price**: Returns up to 365 days historical daily OHLCV

---

## Dashboard Deployment

Static HTML files deployed via MiniMax Code website deployment:
- Dashboard: `http://localhost:8765` (engine serves it)
- TB-1 Charts: `https://t9v90k0baetyl.space.minimax.io`
- R1 Timing Explainer: `https://8frfofnf3tf7m.space.minimax.io`
- Pyramiding Explainer: `https://08jegiksz3hnm.space.minimax.io`

**Note**: Dashboard JS is inline in `index.html` — close/reopen Chrome to pick up JS changes.

---

## Known Issues & Notes

- **NIFTY/BANKNIFTY intraday candles**: M-Stock `get_intraday_chart` returns "No candles" — market closed or token mismatch. Use Yahoo Finance spot as proxy.
- **ADANI PORTS daily candles**: `get_daily_price` returns empty — token resolution fails for this specific instrument. Fallback: Yahoo Finance.
- **Yahoo Finance futures**: Only covers BANKNIFTY/NIFTY spot, NOT NFO futures prices. Never use YF for stock futures data.
- **Expiry migration**: NFO futures roll on the last Thursday of the month. `engine.py` needs manual expiry update in `config.py` and `_sync_nfo_instruments()` to pick up new contract.
- **Mode switching**: Change `config.py` → `MODE` and restart engine. TOTP auto-generates in LIVE mode.
- **GitHub**: Auto CRLF conversion enabled (`core.autocrlf=true`). Set to `false` before `git add` to avoid spurious diffs.

---

## Agent Memory (Cross-Session Context)

- **User**: Rajkumar — non-coder, NSE futures swing/positional trader, planning to build public algo platform
- **Trading**: NSE futures only (Index + Stock futures), 15-min candles for SAR strategy
- **Broker**: M-Stock connected, TOTP auto, LIVE mode running
- **Infrastructure**: Considering DigitalOcean VPS for 24/7 engine
- **GitHub**: `github.com/RAJUCHANDRA74/trading-bot`
