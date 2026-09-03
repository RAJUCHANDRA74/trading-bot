import base64, json, time

with open('data/config.json') as f:
    cfg = json.load(f)

token = cfg['access_token']
parts = token.split('.')
if len(parts) == 3:
    payload_b64 = parts[1]
    padding = 4 - len(payload_b64) % 4
    if padding < 4:
        payload_b64 += '=' * padding
    payload = base64.b64decode(payload_b64)
    data = json.loads(payload)
    print('Token payload:', json.dumps(data, indent=2))
    exp = data.get('exp')
    iat = data.get('iat')
    now = time.time()
    if exp:
        print('Expires:', time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exp)))
        print('Expired:', now > exp)
    if iat:
        print('Issued:', time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(iat)))
