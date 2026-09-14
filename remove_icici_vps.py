import paramiko, sqlite3, os, sys

HOST = '157.230.47.84'
USER = 'root'
PW = 'CHIKANI@123c'
TIMEOUT = 15

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

print(f"Connecting to {HOST}...")
client.connect(HOST, username=USER, password=PW, timeout=TIMEOUT, banner_timeout=TIMEOUT)
print("Connected!")

# Find the database - check both possible paths
stdin, stdout, stderr = client.exec_command('find / -name "paper_trades.db" 2>/dev/null', timeout=10)
paths = [p.strip() for p in stdout.readlines() if p.strip()]
print(f"DB paths found: {paths}")

if not paths:
    print("No DB found!")
    client.close()
    sys.exit(1)

db_path = paths[0]
print(f"Using: {db_path}")

# Read the DB content and find ICICI rows
# Use SFTP to download and process locally
sftp = client.open_sftp()
sftp.get(db_path, '/tmp/paper_trades.db')
sftp.close()

conn = sqlite3.connect('/tmp/paper_trades.db')
cur = conn.cursor()

print("\n--- Positions before ---")
positions = cur.execute("SELECT rowid, symbol, side, entry_price, qty, pnl FROM positions").fetchall()
for p in positions:
    print(p)

icici_rows = cur.execute("SELECT rowid, symbol FROM positions WHERE symbol LIKE '%ICICI%'").fetchall()
print(f"\nICICI rows: {icici_rows}")

deleted = cur.execute("DELETE FROM positions WHERE symbol LIKE '%ICICI%'").rowcount
print(f"Deleted {deleted} positions")

# Also check watchlist table
try:
    wl_rows = cur.execute("SELECT rowid, symbol FROM watchlist WHERE symbol LIKE '%ICICI%'").fetchall()
    print(f"Watchlist ICICI rows: {wl_rows}")
    if wl_rows:
        cur.execute("DELETE FROM watchlist WHERE symbol LIKE '%ICICI%'")
        print("Deleted from watchlist")
except Exception as e:
    print(f"Watchlist check: {e}")

conn.commit()

print("\n--- Positions after ---")
positions = cur.execute("SELECT rowid, symbol, side, entry_price, qty, pnl FROM positions").fetchall()
for p in positions:
    print(p)

conn.close()

# Upload modified DB back
sftp = client.open_sftp()
sftp.put('/tmp/paper_trades.db', db_path)
sftp.close()
print(f"\nUploaded updated DB to {db_path}")

# Restart the service
stdin, stdout, stderr = client.exec_command('systemctl restart sartrader', timeout=10)
print("Restarted sartrader service")
out = stdout.read().decode()
err = stderr.read().decode()
if out: print("STDOUT:", out)
if err: print("STDERR:", err)

client.close()
print("Done!")
