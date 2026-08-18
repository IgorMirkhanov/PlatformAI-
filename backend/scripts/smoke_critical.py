import json
import urllib.request

openapi = json.load(urllib.request.urlopen("http://127.0.0.1:8000/openapi.json"))
paths = sorted(openapi.get("paths", {}))
print("count", len(paths))
print([p for p in paths if "admin" in p or p.endswith("/bots") or "stats" in p or "deposit" in p])

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/bots",
    data=json.dumps(
        {"name": "Inactive Agent", "platform_type": "TELEGRAM", "use_case": "empty"}
    ).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    print("create", resp.status, resp.read().decode())

stats = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/dashboard/stats")
print("stats", stats.status)
