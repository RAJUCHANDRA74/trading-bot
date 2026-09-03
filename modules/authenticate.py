"""
================================================================================
ZERODHA KITE API AUTHENTICATION
================================================================================
This script generates your access token for the Zerodha Kite API.

STEP 1: Run this script
STEP 2: Visit the login URL shown
STEP 3: Login with your Zerodha credentials
STEP 4: You will be redirected to a URL with a "request_token"
STEP 5: Copy the request_token from the URL
STEP 6: Paste it below when asked
STEP 7: Your access token will be saved automatically!
================================================================================
"""

import sys
import json
import os
from kiteconnect import KiteConnect

# Load config
config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path, 'r') as f:
    config = json.load(f)

API_KEY = config['api_key']
API_SECRET = config['api_secret']

print("\n" + "="*60)
print("  ZERODHA KITE API - AUTHENTICATION")
print("="*60)
print(f"\nAPI Key: {API_KEY}")

# Initialize Kite
kite = KiteConnect(api_key=API_KEY)

# Generate login URL
login_url = kite.login_url()
print(f"\n[STEP 1] Visit this URL to login:")
print(f"\n{login_url}\n")

# Ask for request token
print("="*60)
print("[STEP 2] After login, you will be redirected to:")
print("   http://localhost:3000/callback?request_token=XXXXX")
print("")
print("[STEP 3] Copy the request_token from the URL")
print("")
request_token = input("[STEP 4] Paste your request_token here: ").strip()

if not request_token:
    print("Error: Request token is required!")
    sys.exit(1)

print(f"\nRequest token received: {request_token[:10]}...")

# Generate session
print("\n[STEP 5] Generating access token...")
try:
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]

    print(f"\nSuccess! Access token generated!")
    print(f"Access token: {access_token[:20]}...")

    # Save to config
    config['access_token'] = access_token
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)

    print(f"\n[STEP 6] Access token saved to {config_path}")

    print("\n" + "="*60)
    print("  AUTHENTICATION COMPLETE!")
    print("="*60)
    print("\nYou can now use the trading bot!")
    print("Run: python modules/module_03_broker_execution.py")

except Exception as e:
    print(f"\nError generating token: {e}")
    print("\nPossible reasons:")
    print("  - Request token expired (valid for only a few minutes)")
    print("  - Invalid request token")
    print("  - Wrong API secret")
    print("\nPlease run this script again and act quickly!")
