"""Remove ICICIBANKSEPFUT26 position from paper trading DB on VPS."""
import sqlite3, os

db_path = '/root/trading-bot/sartrader/data/paper_trades.db'
print(f"DB path: {db_path}")
print(f"Exists: {os.path.exists(db_path)}")

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Show current positions
    print("\n--- Positions before ---")
    rows = cur.execute("SELECT symbol, side, entry_price, qty, pnl FROM positions").fetchall()
    for r in rows:
        print(r)

    # Find ICICI positions
    icici = cur.execute("SELECT rowid, symbol, side FROM positions WHERE symbol LIKE '%ICICI%'").fetchall()
    print(f"\nICICI positions found: {icici}")

    # Delete ICICI positions
    deleted = cur.execute("DELETE FROM positions WHERE symbol LIKE '%ICICI%'").rowcount
    print(f"Deleted {deleted} rows from positions")

    # Also check/watchlist for ICICI
    wl_rows = cur.execute("SELECT rowid, symbol FROM watchlist WHERE symbol LIKE '%ICICI%'").fetchall()
    print(f"ICICI in watchlist: {wl_rows}")
    if wl_rows:
        cur.execute("DELETE FROM watchlist WHERE symbol LIKE '%ICICI%'")
        print("Deleted from watchlist too")

    conn.commit()

    # Show after
    print("\n--- Positions after ---")
    rows = cur.execute("SELECT symbol, side, entry_price, qty, pnl FROM positions").fetchall()
    for r in rows:
        print(r)

    conn.close()
else:
    # Try alternate path
    alt = '/home/sartrader/trading-bot/sartrader/data/paper_trades.db'
    print(f"Try alternate: {alt}, exists: {os.path.exists(alt)}")
    if os.path.exists(alt):
        conn = sqlite3.connect(alt)
        cur = conn.cursor()
        rows = cur.execute("SELECT symbol, side, entry_price, qty, pnl FROM positions").fetchall()
        print("Positions:")
        for r in rows:
            print(r)
        icici = cur.execute("DELETE FROM positions WHERE symbol LIKE '%ICICI%'").rowcount
        print(f"Deleted {icici} rows")
        conn.commit()
        conn.close()
