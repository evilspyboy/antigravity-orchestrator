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

def test_url(url, label):
    print(f"\n=== Testing: {label} ===")
    print(f"URL: {url}")
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            sessions = data.get("sessions", [])
            print(f"Sessions returned: {len(sessions)}")
            print(f"NextPageToken present: {'nextPageToken' in data}")
            states = {}
            for s in sessions:
                state = s.get("state", "UNKNOWN")
                states[state] = states.get(state, 0) + 1
            print("States distribution:", states)
            
            # Print a few samples (id, title, state, createTime)
            for s in sessions[:3]:
                print(f"  - ID: {s.get('id')}, State: {s.get('state')}, Created: {s.get('createTime')}, Title: {s.get('title', 'No Title')[:40]}")
    except Exception as e:
        print("Error:", e)
        if hasattr(e, "read"):
            print("Details:", e.read().decode('utf-8'))

# Test default list
test_url("https://jules.googleapis.com/v1alpha/sessions?pageSize=100", "Default list (no filters)")

# Test different filter options
test_url("https://jules.googleapis.com/v1alpha/sessions?pageSize=100&filter=state=%22COMPLETED%22", "Filter state=COMPLETED")
test_url("https://jules.googleapis.com/v1alpha/sessions?pageSize=100&filter=state=%22SUCCEEDED%22", "Filter state=SUCCEEDED")
test_url("https://jules.googleapis.com/v1alpha/sessions?pageSize=100&filter=state=%22FAILED%22", "Filter state=FAILED")
test_url("https://jules.googleapis.com/v1alpha/sessions?pageSize=100&filter=archived=true", "Filter archived=true")
