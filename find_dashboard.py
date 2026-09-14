#!/usr/bin/env python3
import paramiko

HOST = '157.230.47.84'
USER = 'root'
PASSWORD = 'CHIKANI@123c'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, password=PASSWORD, timeout=30)
stdin, stdout, stderr = client.exec_command('find /home/sartrader -name "dashboard.js" 2>/dev/null')
for line in stdout: print(line.strip())
client.close()
