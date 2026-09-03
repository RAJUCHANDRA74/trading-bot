"""
================================================================================
M-STOCK API - AUTHENTICATION DIAGNOSTIC
================================================================================
Tests all known M-Stock Type B auth endpoints to find working flow.
================================================================================
"""

import json
import os
import sys
import requests
import hashlib
import hmac
import base64

# Load config
config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path, 'r') as f:
    config = json.load(f)

CLIENT_CODE = config['client_code']   # MA1116489
API_SECRET = config['api_secret']    # fMxt3m1A0XdOr15zCj7Zc32BEiEqbjUqf4ODOBtzNMo=
PASSWORD   = config.get('password', 'RAJ123RAJ@r2')
API_URL   = "https://api.mstock.trade"

HEADERS_BASE = {
    "X-Mirae-Version": "1",
    "Content-Type": "application/json"
}


def test_endpoint(method, path, payload=None, headers=None, description=""):
    """Test a single API endpoint and return result."""
    url = f"{API_URL}{path}"
    h = dict(HEADERS_BASE)
    if headers:
        h.update(headers)

    print(f"\n{'='*60}")
    print(f"TEST: {description}")
    print(f"URL:  {method.upper()} {url}")
    if payload:
        print(f"BODY: {json.dumps(payload, indent=2)}")
    print('-'*60)

    try:
        if method.upper() == "GET":
            r = requests.get(url, headers=h, timeout=30)
        else:
            r = requests.post(url, json=payload, headers=h, timeout=30)

        print(f"STATUS: {r.status_code}")
        print(f"BODY:   {r.text[:800]}")

        try:
            data = r.json()
            return {"ok": True, "status": r.status_code, "data": data}
        except:
            return {"ok": False, "status": r.status_code, "error": r.text}

    except Exception as e:
        print(f"ERROR: {e}")
        return {"ok": False, "error": str(e)}


def generate_checksum(client_code, request_token, api_secret):
    """Generate checksum for session token request."""
    message = f"{client_code}:{request_token}"
    checksum = hmac.new(
        api_secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return checksum


def main():
    print("="*60)
    print("  M-STOCK API - AUTH DIAGNOSTIC")
    print("="*60)
    print(f"Client Code: {CLIENT_CODE}")
    print(f"API Secret:  {API_SECRET[:15]}...")
    print(f"Password:    {PASSWORD[:4]}****")

    results = {}

    # -------------------------------------------------------------------------
    # TEST 1: Login with password only
    # -------------------------------------------------------------------------
    results['login_password'] = test_endpoint(
        "POST",
        "/openapi/typeb/connect/login",
        payload={
            "clientCode": CLIENT_CODE,
            "password": PASSWORD
        },
        description="Login with clientCode + password"
    )

    # -------------------------------------------------------------------------
    # TEST 2: Login with state field
    # -------------------------------------------------------------------------
    results['login_with_state'] = test_endpoint(
        "POST",
        "/openapi/typeb/connect/login",
        payload={
            "clientCode": CLIENT_CODE,
            "password": PASSWORD,
            "state": "api_flow"
        },
        description="Login with clientCode + password + state"
    )

    # -------------------------------------------------------------------------
    # TEST 3: Login requesting request_token
    # -------------------------------------------------------------------------
    results['login_req_token'] = test_endpoint(
        "POST",
        "/openapi/typeb/connect/login",
        payload={
            "clientCode": CLIENT_CODE,
            "password": PASSWORD,
            "getSessionToken": True
        },
        description="Login with getSessionToken=true"
    )

    # -------------------------------------------------------------------------
    # TEST 4: Session token with password as request_token
    # -------------------------------------------------------------------------
    checksum = generate_checksum(CLIENT_CODE, PASSWORD, API_SECRET)
    results['session_password'] = test_endpoint(
        "POST",
        "/openapi/typeb/session/token",
        payload={
            "request_token": PASSWORD,
            "api_key": CLIENT_CODE,
            "checksum": checksum
        },
        headers={"X-PrivateKey": CLIENT_CODE},
        description="Session token with password as request_token"
    )

    # -------------------------------------------------------------------------
    # TEST 5: Session token with empty/blank request_token
    # -------------------------------------------------------------------------
    checksum_blank = generate_checksum(CLIENT_CODE, "", API_SECRET)
    results['session_empty'] = test_endpoint(
        "POST",
        "/openapi/typeb/session/token",
        payload={
            "request_token": "",
            "api_key": CLIENT_CODE,
            "checksum": checksum_blank
        },
        headers={"X-PrivateKey": CLIENT_CODE},
        description="Session token with empty request_token"
    )

    # -------------------------------------------------------------------------
    # TEST 6: TOTP Verify (will fail without valid session, but shows endpoint)
    # -------------------------------------------------------------------------
    results['verify_totp'] = test_endpoint(
        "POST",
        "/openapi/typeb/session/verifytotp",
        payload={
            "clientCode": CLIENT_CODE,
            "totpCode": "000000"
        },
        headers={"X-PrivateKey": CLIENT_CODE},
        description="TOTP verify (expected fail - no valid session)"
    )

    # -------------------------------------------------------------------------
    # TEST 7: Login with totp field (direct TOTP)
    # -------------------------------------------------------------------------
    results['login_totp'] = test_endpoint(
        "POST",
        "/openapi/typeb/connect/login",
        payload={
            "clientCode": CLIENT_CODE,
            "password": PASSWORD,
            "totp": "000000"
        },
        description="Login with clientCode + password + totp (000000 test)"
    )

    # -------------------------------------------------------------------------
    # TEST 8: Generate OTP endpoint
    # -------------------------------------------------------------------------
    results['generate_otp'] = test_endpoint(
        "POST",
        "/openapi/typeb/connect/generateotp",
        payload={
            "clientCode": CLIENT_CODE,
            "password": PASSWORD
        },
        description="Generate OTP endpoint"
    )

    # -------------------------------------------------------------------------
    # TEST 9: Verify OTP endpoint
    # -------------------------------------------------------------------------
    results['verify_otp'] = test_endpoint(
        "POST",
        "/openapi/typeb/connect/verifyotp",
        payload={
            "clientCode": CLIENT_CODE,
            "otp": "123456"
        },
        description="Verify OTP endpoint (will fail without real OTP)"
    )

    # -------------------------------------------------------------------------
    # TEST 10: Just checksum endpoint
    # -------------------------------------------------------------------------
    results['checksum_only'] = test_endpoint(
        "POST",
        "/openapi/typeb/session/checksum",
        payload={
            "clientCode": CLIENT_CODE
        },
        headers={"X-PrivateKey": CLIENT_CODE},
        description="Get checksum challenge"
    )

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    print("\n" + "="*60)
    print("  DIAGNOSTIC SUMMARY")
    print("="*60)

    for name, result in results.items():
        status = "✓ OK" if result.get('ok') else f"✗ HTTP {result.get('status', 'ERR')}"
        data = result.get('data', {})
        if isinstance(data, dict):
            msg = data.get('message', '')[:50]
            stat = data.get('status')
            print(f"  {name:25s} {status} | {stat} | {msg}")
        else:
            print(f"  {name:25s} {status}")

    print("\n[NOTE] If you see 'totp field is required', the API expects")
    print("        TOTP authentication. You need the TOTP secret from")
    print("        the M-Stock API key management page.")


if __name__ == "__main__":
    main()
