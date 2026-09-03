"""
Simple HTTP server to capture Zerodha request token.
Run this script, visit the login URL, and the script will automatically capture the token.
"""
import http.server
import socketserver
import urllib.parse
import json
import sys
import os
import webbrowser

# Load config
config_path = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")
with open(config_path, 'r') as f:
    config = json.load(f)

API_KEY = config['api_key']
API_SECRET = config['api_secret']

# Login URL
LOGIN_URL = f"https://kite.zerodha.com/connect/login?api_key={API_KEY}&v=3"

PORT = 3000
CAPTURED_TOKEN = None

class MyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global CAPTURED_TOKEN
        
        if 'callback' in self.path:
            # Parse the URL
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            
            if 'request_token' in params:
                CAPTURED_TOKEN = params['request_token'][0]
                
                # Save token to file
                config['request_token'] = CAPTURED_TOKEN
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                
                # Send success response
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                response = """
                <html><body>
                <h1 style='color:green;'>SUCCESS!</h1>
                <p>Request token captured: {}</p>
                <p>You can close this browser window.</p>
                <p>Now go back to the terminal and the token will be processed automatically.</p>
                </body></html>
                """.format(CAPTURED_TOKEN[:20] + "...")
                self.wfile.write(response.encode())
                print(f"\n[SUCCESS] Request token captured: {CAPTURED_TOKEN[:30]}...")
                
                # Stop server
                import threading
                threading.Event().set()
                return
        
        # Default response
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        response = """
        <html><body>
        <h1>Waiting for Zerodha login...</h1>
        <p>Please complete the login on your browser.</p>
        </body></html>
        """
        self.wfile.write(response.encode())

def run_server():
    global PORT
    with socketserver.TCPServer(("", PORT), MyHandler) as httpd:
        print(f"\n[SERVER] Server running at http://localhost:{PORT}")
        print(f"[SERVER] Waiting for Zerodha callback...")
        print(f"\n[NEXT STEP] Visit this URL in your browser:")
        print(f"\n  {LOGIN_URL}\n")
        httpd.serve_forever()

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  ZERODHA REQUEST TOKEN CAPTURER")
    print("="*60)
    print(f"\n[INFO] API Key: {API_KEY}")
    print(f"[INFO] Server Port: {PORT}")
    run_server()
