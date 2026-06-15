import os
import json
import urllib.request

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
SETTINGS_FILE = os.path.join(SCRATCH_DIR, "settings.json")

with open(SETTINGS_FILE, "r") as f:
    settings = json.load(f)
api_key = settings.get("jules")

session_id = "4245299970056730421"
url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
req = urllib.request.Request(
    url,
    headers={"x-goog-api-key": api_key, "Accept": "application/json"},
    method="DELETE"
)
try:
    with urllib.request.urlopen(req) as resp:
        print("Success:", resp.read().decode('utf-8'))
except Exception as e:
    print("Error:", e)
