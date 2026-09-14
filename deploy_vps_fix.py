#!/usr/bin/env python3
"""Deploy fixed files to VPS: git pull + direct SFTP upload + restart."""
import paramiko
import os

VPS_HOST = "157.230.47.84"
VPS_USER = "root"
VPS_PASS = "CHIKANI@123c"
LOCAL_DIR = r"C:\Users\Rajkumar\.minimax-agent\projects\trading-bot"

def run():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {VPS_HOST}...")
    client.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)

    # 1. Git pull on VPS
    print("Git pull on VPS...")
    stdin, stdout, stderr = client.exec_command(
        "cd /home/sartrader/trading-bot && git pull origin main 2>&1"
    )
    pull_out = stdout.read().decode()
    pull_err = stderr.read().decode()
    print("PULL OUT:", pull_out)
    if pull_err:
        print("PULL ERR:", pull_err)

    # 2. SFTP upload dashboard.js and engine.py
    print("SFTP upload...")
    sftp = client.open_sftp()

    # dashboard.js
    local_dashboard = os.path.join(LOCAL_DIR, "dashboard", "dashboard.js")
    remote_dashboard = "/home/sartrader/trading-bot/dashboard/dashboard.js"
    sftp.put(local_dashboard, remote_dashboard)
    print(f"Uploaded: {local_dashboard} -> {remote_dashboard}")

    # engine.py
    local_engine = os.path.join(LOCAL_DIR, "sartrader", "engine.py")
    remote_engine = "/home/sartrader/trading-bot/sartrader/engine.py"
    sftp.put(local_engine, remote_engine)
    print(f"Uploaded: {local_engine} -> {remote_engine}")

    sftp.close()

    # 3. Restart sartrader service
    print("Restarting sartrader service...")
    stdin, stdout, stderr = client.exec_command(
        "systemctl restart sartrader 2>&1"
    )
    svc_out = stdout.read().decode()
    svc_err = stderr.read().decode()
    print("SVC OUT:", svc_out)
    if svc_err:
        print("SVC ERR:", svc_err)

    # Verify status
    stdin, stdout, stderr = client.exec_command(
        "systemctl status sartrader --no-pager 2>&1 | head -20"
    )
    print("STATUS:", stdout.read().decode())

    client.close()
    print("Done!")

if __name__ == "__main__":
    run()
