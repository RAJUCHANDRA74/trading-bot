"""
================================================================================
TOTP FORMAT TESTING
================================================================================
Test multiple ways to generate TOTP from the API secret.
"""

import json, base64, pyotp, hashlib, hmac

config_path = "C:/Users/Rajkumar/.minimax-agent/projects/trading-bot/data/config.json"
with open(config_path) as f:
    config = json.load(f)

API_SECRET = config['api_secret']
CLIENT_CODE = config['client_code']

print("API Secret:", API_SECRET)
print("Secret length:", len(API_SECRET))

# Try multiple approaches
attempts = []

# 1. Raw string as TOTP seed
try:
    totp = pyotp.TOTP(API_SECRET)
    code = totp.now()
    attempts.append(("raw_secret", code, "OK"))
    print(f"\n[1] Raw secret TOTP: {code}")
except Exception as e:
    attempts.append(("raw_secret", None, str(e)))
    print(f"\n[1] Raw secret FAILED: {e}")

# 2. Base64 decode then use raw bytes
try:
    decoded = base64.b64decode(API_SECRET)
    totp = pyotp.TOTP(decoded)
    code = totp.now()
    attempts.append(("b64_decoded_bytes", code, "OK"))
    print(f"[2] Base64-decoded bytes TOTP: {code}")
except Exception as e:
    attempts.append(("b64_decoded_bytes", None, str(e)))
    print(f"[2] Base64-decoded FAILED: {e}")

# 3. Base64 decode then base32 encode then TOTP
try:
    import binascii
    decoded = base64.b64decode(API_SECRET)
    b32 = base64.b32encode(decoded).decode()
    totp = pyotp.TOTP(b32)
    code = totp.now()
    attempts.append(("b64->b32", code, "OK"))
    print(f"[3] b64->b32 TOTP: {code}")
except Exception as e:
    attempts.append(("b64->b32", None, str(e)))
    print(f"[3] b64->b32 FAILED: {e}")

# 4. SHA256 hash of secret as seed
try:
    digest = hashlib.sha256(API_SECRET.encode()).digest()
    b32 = base64.b32encode(digest).decode().replace('=', '')
    totp = pyotp.TOTP(b32)
    code = totp.now()
    attempts.append(("sha256->b32", code, "OK"))
    print(f"[4] SHA256->b32 TOTP: {code}")
except Exception as e:
    attempts.append(("sha256->b32", None, str(e)))
    print(f"[4] SHA256->b32 FAILED: {e}")

# 5. HMAC-SHA256 of a fixed message using secret
try:
    msg = "MSTOCKAPI"
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    b32 = base64.b32encode(sig).decode().replace('=', '')
    totp = pyotp.TOTP(b32)
    code = totp.now()
    attempts.append(("hmac->b32", code, "OK"))
    print(f"[5] HMAC->b32 TOTP: {code}")
except Exception as e:
    attempts.append(("hmac->b32", None, str(e)))
    print(f"[5] HMAC->b32 FAILED: {e}")

# 6. Try decoding as base32
try:
    decoded = base64.b32decode(API_SECRET.upper(), casefold=True)
    totp = pyotp.TOTP(API_SECRET.upper())
    code = totp.now()
    attempts.append(("base32_decode", code, "OK"))
    print(f"[6] Base32 decode TOTP: {code}")
except Exception as e:
    attempts.append(("base32_decode", None, str(e)))
    print(f"[6] Base32 FAILED: {e}")

# 7. Check: is it maybe a JWT?
try:
    parts = API_SECRET.split('.')
    if len(parts) == 3:
        print(f"[7] Secret looks like JWT!")
        # Decode JWT payload
        payload = parts[1]
        # Add padding
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += '=' * padding
        decoded = base64.urlsafe_b64decode(payload)
        print(f"    JWT Payload: {decoded}")
except Exception as e:
    print(f"[7] JWT check FAILED: {e}")

# 8. Last 32 chars as potential TOTP secret
try:
    last32 = API_SECRET[-32:]
    totp = pyotp.TOTP(last32)
    code = totp.now()
    attempts.append(("last32_chars", code, "OK"))
    print(f"[8] Last 32 chars TOTP: {code}")
except Exception as e:
    attempts.append(("last32_chars", None, str(e)))
    print(f"[8] Last 32 FAILED: {e}")

# 9. Use client_code:password as TOTP seed
try:
    seed = f"{CLIENT_CODE}:{config.get('password','RAJ123RAJ@r2')}"
    digest = hashlib.sha256(seed.encode()).digest()
    b32 = base64.b32encode(digest).decode().replace('=', '')
    totp = pyotp.TOTP(b32)
    code = totp.now()
    attempts.append(("userid_pwd_hash", code, "OK"))
    print(f"[9] userid:pwd hash TOTP: {code}")
except Exception as e:
    attempts.append(("userid_pwd_hash", None, str(e)))
    print(f"[9] userid:pwd FAILED: {e}")

print("\n" + "="*60)
print(" SUMMARY")
print("="*60)
for name, code, status in attempts:
    tag = "OK" if code else "FAIL"
    print(f"  {name:25s} [{tag}] {code or status}")
