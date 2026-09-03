"""
================================================================================
M-STOCK API - SMS OTP AUTHENTICATION (FIXED)
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

CLIENT_CODE = config['client_code']
API_SECRET = config['api_secret']
API_URL = "https://api.mstock.trade"


def generate_totp_from_secret(secret):
    """Generate TOTP from base64 encoded secret."""
    import pyotp
    try:
        decoded = base64.b32decode(secret.upper(), casefold=True)
        totp = pyotp.TOTP(decoded)
        return totp.now()
    except Exception as e:
        print(f"[TOTP ERROR] {e}")
        return None


def generate_checksum(client_code, request_token, api_secret):
    """Generate checksum."""
    message = f"{client_code}:{request_token}"
    checksum = hmac.new(
        api_secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return checksum


def login_with_password(password):
    """Step 1: Login to get request token."""
    print("\n[STEP 1] Attempting login...")
    
    url = f"{API_URL}/openapi/typeb/connect/login"
    
    headers = {
        "X-Mirae-Version": "1",
        "Content-Type": "application/json"
    }
    
    payload = {
        "clientCode": CLIENT_CODE,
        "password": password,
        "state": "test_state"  # Required field
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"[STATUS] HTTP {response.status_code}")
        print(f"[RESPONSE] {response.text[:600]}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == True:
                print("\n[SUCCESS] Login successful!")
                resp_data = data.get('data', {})
                if isinstance(resp_data, list) and len(resp_data) > 0:
                    return resp_data[0]
                return resp_data
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def generate_session(request_token):
    """Step 2: Generate session with checksum."""
    print("\n[STEP 2] Generating session...")
    
    checksum = generate_checksum(CLIENT_CODE, request_token, API_SECRET)
    
    url = f"{API_URL}/openapi/typeb/session/token"
    
    headers = {
        "X-Mirae-Version": "1",
        "Content-Type": "application/json",
        "X-PrivateKey": CLIENT_CODE
    }
    
    payload = {
        "request_token": request_token,
        "api_key": CLIENT_CODE,
        "checksum": checksum
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"[STATUS] HTTP {response.status_code}")
        print(f"[RESPONSE] {response.text[:800]}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == True:
                resp_data = data.get('data', {})
                
                if isinstance(resp_data, list) and len(resp_data) > 0:
                    request_token = resp_data[0].get('request_token', '')
                elif isinstance(resp_data, dict):
                    request_token = resp_data.get('request_token', '')
                else:
                    request_token = str(resp_data)
                
                print(f"\n[SUCCESS] Session token: {request_token[:30]}...")
                return request_token
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def verify_totp(totp_code):
    """Step 3: Verify TOTP to get access token."""
    print("\n[STEP 3] Verifying TOTP...")
    
    url = f"{API_URL}/openapi/typeb/session/verifytotp"
    
    headers = {
        "X-Mirae-Version": "1",
        "Content-Type": "application/json",
        "X-PrivateKey": CLIENT_CODE
    }
    
    payload = {
        "clientCode": CLIENT_CODE,
        "totpCode": totp_code
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        print(f"[STATUS] HTTP {response.status_code}")
        print(f"[RESPONSE] {response.text[:800]}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == True:
                resp_data = data.get('data', {})
                
                if isinstance(resp_data, list) and len(resp_data) > 0:
                    access_token = resp_data[0].get('jwtToken', '')
                elif isinstance(resp_data, dict):
                    access_token = resp_data.get('jwtToken', '')
                else:
                    access_token = str(resp_data)
                
                print(f"\n[SUCCESS] Access Token: {access_token[:30]}...")
                
                # Save
                config['access_token'] = access_token
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                
                print("[SAVED] Access token saved!")
                return access_token
        return None
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def test_connection():
    """Test the API connection."""
    if not config.get('access_token'):
        return False
    
    access_token = config['access_token']
    url = f"{API_URL}/openapi/typeb/user/fundsummary"
    
    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {access_token}",
        "X-PrivateKey": CLIENT_CODE
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            print("\n[SUCCESS] Connected to M-Stock!")
            data = response.json()
            funds = data.get('data', [])
            if isinstance(funds, list):
                for item in funds:
                    seg = item.get('SEG', 'N/A')
                    avail = item.get('AVAILABLE_BALANCE', '0')
                    print(f"  Segment: {seg} | Balance: Rs.{avail}")
            return True
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


if __name__ == "__main__":
    print("="*60)
    print("  M-STOCK API - AUTHENTICATION")
    print("="*60)
    print(f"Client Code: {CLIENT_CODE}")
    print("="*60)
    
    # Check existing token
    if config.get('access_token'):
        print("\n[INFO] Testing existing token...")
        if test_connection():
            print("\n[SUCCESS] Already connected!")
            sys.exit(0)
    
    # Run authentication
    if len(sys.argv) > 1:
        password = sys.argv[1]
        
        # Step 1: Login
        result = login_with_password(password)
        if not result:
            print("\n[FAILED] Login failed")
            sys.exit(1)
        
        # Check if TOTP is required directly
        print("\n[INFO] Login response received")
        print(f"[DATA] {result}")
        
    else:
        print("\n[USAGE] python module_04_sms_auth.py <password>")
