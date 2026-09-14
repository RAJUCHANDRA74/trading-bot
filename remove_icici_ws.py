import asyncio, json, sys

async def remove_icici():
    try:
        import websockets
    except ImportError:
        print("websockets not installed locally - trying VPS WebSocket directly via HTTP API")
        # Alternative: check if engine has an HTTP command endpoint
        import urllib.request
        # The engine has a WebSocket handler - we need to use WebSocket
        print("WebSocket required but not available. Use SSH approach.")
        return

    VPS_WS = "ws://157.230.47.84:8766"
    print(f"Connecting to {VPS_WS}...")

    try:
        async with websockets.connect(VPS_WS, open_timeout=10, close_timeout=5) as ws:
            print("Connected!")

            # Send remove_position for ICICI
            cmd = {"command": "remove_position", "instrument": "ICICIBANKSEPFUT26"}
            await ws.send(json.dumps(cmd))
            print(f"Sent: {cmd}")

            # Wait for response
            resp = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f"Response: {resp}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(remove_icici())
