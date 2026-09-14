with open('dashboard/dashboard.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('lines_output.txt', 'w', encoding='utf-8') as f:
    for i in range(960, 990):
        line = lines[i]
        # Replace problematic chars
        clean = line.replace('\u20b9', 'Rs').replace('\u25cf', '*')
        f.write(f"{i+1}: {clean}")
