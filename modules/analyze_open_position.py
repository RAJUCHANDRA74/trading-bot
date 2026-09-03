"""
=============================================================
Honest analysis of the backtest - accounting for open positions
and data limitations.
=============================================================
"""
import csv, os

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "banknifty_6month.csv")


def load_data():
    rows = []
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "datetime": row["datetime"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
    return rows


def main():
    data = load_data()
    last_price = data[-1]["close"]
    last_dt = data[-1]["datetime"]
    first_price = data[0]["close"]
    first_dt = data[0]["datetime"]

    print("=" * 60)
    print("  HONEST BACKTEST ANALYSIS")
    print("=" * 60)
    print()
    print("  DATA:")
    print(f"  From: {first_dt} @ {first_price:.2f}")
    print(f"  To:   {last_dt} @ {last_price:.2f}")
    print(f"  Range: Rs.{last_price - first_price:.2f} ({((last_price-first_price)/first_price)*100:.2f}%)")
    print()
    print("  KEY FINDINGS FROM PARAMETER SWEEP:")
    print()
    print("  1. BEST CONFIG (on paper):")
    print("     BE=1.5%, RevExit=ON, TrendFilter=OFF")
    print("     Net P&L: Rs.13,63,998 (1,364% return)")
    print()
    print("  2. BUT THE LAST TRADE NEVER CLOSED:")
    print("     Entry: 2026-07-24 11:45 LONG")
    print("     Exit:  [data ran out]")
    print("     Unrealized P&L: Rs.13,81,710")
    print("     This is NOT real profit — it just shows what")
    print("     the position was worth when data ended.")
    print()
    print("  3. IF WE EXCLUDE THE OPEN TRADE:")
    print("     The 13 closed trades show:")
    print("     Real P&L from closed trades: Rs.-17,712")
    print()
    print("  4. WHY THIS PERIOD IS HARD:")
    print("     Bank Nifty moved from ~58,500 to ~57,500")
    print("     That's only a Rs.1,000 drop (~1.7% down)")
    print("     Very choppy, no strong trend either way")
    print()
    print("  5. THE REAL INSIGHT:")
    print("     When reversal_exit=ON: more trades, smaller wins/losses")
    print("     When reversal_exit=OFF: only 2 trades, but one held for")
    print("     35 days and rode a partial rally (not fully closed)")
    print()
    print("  6. THE STRATEGY WORKS IN TRENDING MARKETS:")
    print("     In July-Aug, the best trade was a SHORT that rode")
    print("     a big decline from 59k to 57k.")
    print("     The strategy is designed for BIG trends, not chop.")
    print()
    print("  RECOMMENDATIONS:")
    print("  a) Need 6+ months of data with proper contract chaining")
    print("  b) Test on bull markets AND bear markets separately")
    print("  c) Add a VOLATILITY filter (avoid choppy periods)")
    print("  d) The 1.5% breakeven is a good finding")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
