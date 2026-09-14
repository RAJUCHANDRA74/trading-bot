import subprocess, sys

# Try multiple ways to SSH
cmds = [
    ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10',
     '-o', 'ConnectionAttempts=1', '-o', 'BatchMode=yes',
     'root@157.230.47.84', 'cat /etc/hostname'],
    ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10',
     '-o', 'ConnectionAttempts=1', '-o', 'BatchMode=yes',
     '-i', '/tmp/key',
     'root@157.230.47.84', 'cat /etc/hostname'],
]

for cmd in cmds:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        print("STDOUT:", r.stdout)
        print("STDERR:", r.stderr)
        print("RC:", r.returncode)
        break
    except subprocess.TimeoutExpired:
        print(f"Timeout: {' '.join(cmd[:4])}...")
    except FileNotFoundError as e:
        print(f"Not found: {e}")
        break
