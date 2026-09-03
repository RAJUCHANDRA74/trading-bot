"""
================================================================================
M-STOCK API - TOTP AUTHENTICATION
================================================================================
M-Stock Type B API with TOTP enabled.
Flow:
1. Generate session token with checksum
2. Verify TOTP to get access token
================================================================================
"""

import json
import os
import requests
import hashlib
import hmac
import pyotp
import time

# Load config
config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path, 'r') as f:
    config = json.load(f)

CLIENT_CODE = config['client_code']   # MA1116489
API_SECRET = config['api_secret']    # fMxt3m1A0XdOr15zCj7Zc32BEiEqbjUqf4ODOBtzNMo=
API_URL = "https://api.mstock.trade"


def generate_totp(secret):
    """Generate TOTP code from the API secret."""
    # The API secret is base64 encoded, decode it first
    try:
        # Try decoding as base64
        decoded = base64.b32decode(secret, casefold=True)
        totp = pyotp.TOTP(decoded)
        return totp.now()
    except:
        # If base64 decoding fails, use the secret directly
        totp = pyotp.TOTP(secret)
        return totp.now()


def generate_checksum(client_code, request_token, api_secret):
    """Generate checksum for session token request."""
    message = f"{client_code}:{request_token}"
    checksum = hmac.new(
        api_secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return checksum


def step1_generate_request_token():
    """
    Step 1: Generate request token using API credentials.
    """
    print("\n" + "="*60)
    print("  M-STOCK API - STEP 1: GENERATE REQUEST TOKEN")
    print("="*60)
    
    # Generate TOTP as the request token
    totp_code = generate_totp(API_SECRET)
    print(f"\n[INFO] TOTP Code Generated: {totp_code}")
    
    # Generate checksum
    checksum = generate_checksum(CLIENT_CODE, totp_code, API_SECRET)
    print(f"[INFO] Checksum: {checksum[:20]}...")
    
    url = f"{API_URL}/openapi/typeb/session/token"
    
    headers = {
        "X-Mirae-Version": "1",
        "Content-Type": "application/json",
        "X-PrivateKey": CLIENT_CODE
    }
    
    payload = {
        "request_token": totp_code,
        "api_key": CLIENT_CODE,
        "checksum": checksum
    }
    
    try:
        print("\n[STEP 1] Sending session token request...")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        print(f"[RESPONSE] Status: {response.status_code}")
        print(f"[RESPONSE] Body: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == True:
                resp_data = data.get('data', {})
                if isinstance(resp_data, list) and len(resp_data) > 0:
                    request_token = resp_data[0].get('request_token', '')
                    return request_token
                elif isinstance(resp_data, dict):
                    request_token = resp_data.get('request_token', '')
                    return request_token
            else:
                print(f"[ERROR] {data.get('message', 'Unknown error')}")
                return None
        else:
            print(f"[ERROR] HTTP {response.status_code}")
            print(f"[ERROR] {response.text}")
            return None
            
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def step2_verify_totp(request_token):
    """
    Step 2: Verify TOTP to get access token.
    """
    print("\n" + "="*60)
    print("  M-STOCK API - STEP 2: VERIFY TOTP")
    print("="*60)
    
    # Generate TOTP code for verification
    totp_code = generate_totp(API_SECRET)
    print(f"\n[INFO] TOTP Code: {totp_code}")
    
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
        print("\n[STEP 2] Verifying TOTP...")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        print(f"[RESPONSE] Status: {response.status_code}")
        print(f"[RESPONSE] Body: {response.text[:800]}")
        
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
                
                print(f"\n[SUCCESS] Access Token received!")
                print(f"[TOKEN] {access_token[:30]}...")
                
                # Save to config
                config['access_token'] = access_token
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                
                print(f"\n[SAVED] Access token saved!")
                return access_token
            else:
                print(f"[ERROR] {data.get('message', 'Unknown error')}")
                return None
        else:
            print(f"[ERROR] HTTP {response.status_code}")
            print(f"[ERROR] {response.text}")
            return None
            
    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def test_connection():
    """Test the API connection."""
    print("\n" + "="*60)
    print("  M-STOCK API - TEST CONNECTION")
    print("="*60)
    
    if not config.get('access_token'):
        print("[ERROR] No access token found.")
        return False
    
    access_token = config['access_token']
    
    url = f"{API_URL}/openapi/typeb/user/fundsummary"
    
    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {access_token}",
        "X-PrivateKey": CLIENT_CODE
    }
    
    try:
        print("\n[TEST] Fetching fund summary...")
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            print(f"[SUCCESS] Connected!")
            print(f"\n[DATA] {json.dumps(data, indent=2)[:1500]}")
            return True
        else:
            print(f"[ERROR] HTTP {response.status_code}")
            print(f"[ERROR] {response.text}")
            return False
            
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


# ================================================================================
# MAIN
# ================================================================================
if __name__ == "__main__":
    import base64
    
    print("\n" + "="*60)
    print("  M-STOCK API - TOTP AUTHENTICATION")
    print("="*60)
    print(f"\nClient Code: {CLIENT_CODE}")
    print(f"API Secret:  {API_SECRET[:10]}...")
    print("="*60)
    
    # Step 1: Generate request token
    request_token = step1_generate_request_token()
    
    if request_token:
        # Step 2: Verify TOTP
        access_token = step2_verify_totp(request_token)
        
        if access_token:
            print("\n" + "="*60)
            print("  AUTHENTICATION SUCCESSFUL!")
            print("="*60)
            
            # Test connection
            test_connection()
        else:
            print("\n[ERROR] Failed to get access token.")
    else:
        print("\n[ERROR] Failed to generate request token.")
        print("\n[HELP] Possible issues:")
        print("  1. TOTP secret might be incorrect")
        print("  2. API secret format might be different")
        print("  3. Check if TOTP is properly linked to your account")
