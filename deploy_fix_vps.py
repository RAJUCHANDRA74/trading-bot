#!/usr/bin/env python3
"""Deploy fixed dashboard.js to VPS via SFTP + restart service."""
import paramiko, os, sys

HOST = '157.230.47.84'
PORT = 22
USER = 'root'
PASSWORD = 'CHIKANI@123c'
LOCAL_DASHBOARD_JS = r'C:\Users\Rajkumar\.minimax-agent\projects\trading-bot\dashboard\dashboard.js'
VPS_PATH = '/home/sartrader/trading-bot/dashboard/dashboard.js'

print("Connecting to VPS...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASSWORD, timeout=30)

# Upload dashboard.js
print(f"Uploading {LOCAL_DASHBOARD_JS} -> {VPS_PATH} ...")
local_size = os.path.getsize(LOCAL_DASHBOARD_JS)
print(f"  Local size: {local_size:,} bytes")

sftp = client.open_sftp()
# Remove old file first, then upload fresh
try:
    sftp.remove(VPS_PATH)
    print(f"  Removed old {VPS_PATH}")
except IOError:
    print(f"  No existing file at {VPS_PATH}")

sftp.put(LOCAL_DASHBOARD_JS, VPS_PATH)

# Verify remote size
remote_size = sftp.stat(VPS_PATH).st_size
print(f"  Remote size: {remote_size:,} bytes")

if remote_size != local_size:
    print(f"  WARNING: Size mismatch! {remote_size} vs {local_size}")
else:
    print("  Upload verified OK")

sftp.close()

# Restart service
print("Restarting sartrader service...")
stdin, stdout, stderr = client.exec_command('sudo systemctl restart sartrader 2>&1')
exit_code = stdout.channel.recv_exit_status()
output = stdout.read().decode()
err = stderr.read().decode()
print(f"  Exit code: {exit_code}")
if output.strip(): print(f"  stdout: {output.strip()}")
if err.strip():   print(f"  stderr: {err.strip()}")

# Check service status
stdin, stdout, stderr = client.exec_command('sudo systemctl is-active sartrader 2>&1')
status = stdout.read().decode().strip()
print(f"  Service status: {status}")

# Get PID
stdin, stdout, stderr = client.exec_command('pgrep -f "python.*sartrader.engine" 2>&1')
pid = stdout.read().decode().strip()
print(f"  Engine PID: {pid}")

client.close()
print("\nDone!")
