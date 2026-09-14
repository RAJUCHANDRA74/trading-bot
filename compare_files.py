import os

disk_path = 'C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard/dashboard.js'
fetched_path = 'C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/dashboard.js_fetched.txt'

disk = open(disk_path, 'rb').read()
fetched = open(fetched_path, 'rb').read()

print(f"Disk: {len(disk)} bytes")
print(f"Fetched: {len(fetched)} bytes")
print(f"Match: {disk == fetched}")

if disk != fetched:
    diffs = []
    for i in range(min(len(disk), len(fetched))):
        if disk[i] != fetched[i]:
            diffs.append(i)
            if len(diffs) <= 5:
                ctx_d = disk[max(0,i-10):i+10]
                ctx_f = fetched[max(0,i-10):i+10]
                print(f"  First diff at byte {i}: disk={disk[i]!r} fetched={fetched[i]!r}")
                print(f"    Disk context: {ctx_d!r}")
                print(f"    Fetched context: {ctx_f!r}")
    if len(diffs) < len(disk) and len(fetched) > len(disk):
        print(f"  Fetched is {len(fetched) - len(disk)} bytes LONGER")
    elif len(disk) > len(fetched):
        print(f"  Disk is {len(disk) - len(fetched)} bytes LONGER")

# Also check: what's at the VERY start of both files?
print(f"\nDisk first 20 bytes: {disk[:20]!r}")
print(f"Fetched first 20 bytes: {fetched[:20]!r}")

# Check: does fetched have a BOM?
if fetched.startswith(b'\xef\xbb\xbf'):
    print("Fetched has UTF-8 BOM!")
elif fetched.startswith(b'\xff\xfe'):
    print("Fetched has UTF-16 LE BOM!")
elif fetched.startswith(b'\xfe\xff'):
    print("Fetched has UTF-16 BE BOM!")

# Check last 20 bytes
print(f"\nDisk last 20 bytes: {disk[-20:]!r}")
print(f"Fetched last 20 bytes: {fetched[-20:]!r}")
