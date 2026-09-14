$ErrorActionPreference = 'Stop'
$ssh = New-Object System.Net.SshClient.SshClient('157.230.47.84', 22, 'root', 'CHIKANI@123c')
$ssh.Connect()
$cmd = @"
grep -n 'sectorMap\|"OTHER"\|"Auto"\|"PSU Bank"' /root/trading-bot/dashboard/dashboard.js | head -20
echo '---'
grep -n 'prev_top\|prev_bottom\|sector.*infer\|positions_state\[inst\]' /root/trading-bot/sartrader/engine.py | head -30
echo '---'
grep -n 'getQuote\|TATAMOTORS\|ASHOKLEY' /root/trading-bot/dashboard/dashboard.js | head -20
"@

$stream = $ssh.CreateShellStream('xterm', 80, 40, 800, 600, 1024)
$stream.Write($cmd + "`n")
Start-Sleep 3
$output = $stream.Read()
Write-Host $output
$stream.Close()
$ssh.Disconnect()
