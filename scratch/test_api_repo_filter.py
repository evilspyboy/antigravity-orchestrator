import os
import json
import urllib.request

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
SETTINGS_FILE = os.path.join(SCRATCH_DIR, "settings.json")

with open(SETTINGS_FILE, "r") as f:
    settings = json.load(f)
api_key = settings.get("jules")

if not api_key:
    print("API Key not found.")
    exit(1)

def test_filter(filter_str):
    url = f"https://jules.googleapis.com/v1alpha/sessions?pageSize=100&filter={urllib.parse.quote(filter_str)}"
    print(f"\n--- Testing filter: {filter_str} ---")
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            sessions = data.get("sessions", [])
            print(f"Success! Sessions returned: {len(sessions)}")
            for s in sessions[:3]:
                print(f"  - ID: {s.get('id')}, Created: {s.get('createTime')}, Title: {s.get('title')}")
    except Exception as e:
        print(f"Failed: {e}")
        if hasattr(e, "read"):
            print("Details:", e.read().decode('utf-8'))

# Test different potential filters
test_filter('archived=true AND repo="evilspyboy/Orbits"')
test_filter('archived=true AND source="sources/github/evilspyboy/Orbits"')
test_filter('archived=true AND sourceContext.source="sources/github/evilspyboy/Orbits"')
test_filter('archived=true AND sourceContext.source="evilspyboy/Orbits"')
test_filter('sourceContext.source="sources/github/evilspyboy/Orbits"')
