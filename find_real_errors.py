# Replace optional chaining for esprima compatibility check only
import re

with open(r'C:\Users\Rajkumar\.minimax-agent\projects\trading-bot\dashboard\dashboard.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace ?.X (optional property access) -> .X
tmp = re.sub(r'\?\.(?=[A-Za-z_$])', '.', content)
# Replace ?.[ (optional bracket access) -> [
tmp = re.sub(r'\?\.\[', '[', tmp)
# Replace ?.( (optional call) -> .(
tmp = re.sub(r'\?\.\(', '.(', tmp)

with open(r'C:\Users\Rajkumar\.minimax-agent\projects\trading-bot\dashboard\dashboard_tmp.js', 'w', encoding='utf-8') as f:
    f.write(tmp)

# Count replacements
orig_oc = content.count('?.')
tmp_oc = tmp.count('?.')
print(f"Original optional chaining: {orig_oc}")
print(f"Remaining after fix: {tmp_oc}")
print("Written tmp file")
