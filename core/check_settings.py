"""Check Woolworths settings for login/auth config."""
import json
from curl_cffi import requests as r

resp = r.get(
    "https://www.woolworths.com.au/apis/ui/settings",
    impersonate="chrome131",
    timeout=30,
)
data = resp.json()
print(f"Total settings: {len(data)}")

# Search for login/auth related settings
keywords = ["login", "auth", "token", "session", "identity", "signin", "Login", "Auth"]
for item in data:
    name = str(item.get("Name", ""))
    group = str(item.get("Group", ""))
    value = str(item.get("Value", ""))
    combined = f"{group} {name} {value}".lower()
    if any(kw in combined for kw in keywords):
        print(f"  [{group}] {name} = {value[:200]}")

# Print all unique groups
groups = sorted(set(str(item.get("Group", "")) for item in data))
print(f"\nGroups ({len(groups)}):")
for g in groups:
    print(f"  {g}")
