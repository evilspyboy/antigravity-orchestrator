import os
import json
import re
import urllib.request

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
SETTINGS_FILE = os.path.join(SCRATCH_DIR, "settings.json")
ARCHIVED_SESSIONS_FILE = os.path.join(SCRATCH_DIR, "archived_sessions.json")

print("SCRATCH_DIR:", SCRATCH_DIR)
print("ARCHIVED_SESSIONS_FILE:", ARCHIVED_SESSIONS_FILE)

if os.path.exists(ARCHIVED_SESSIONS_FILE):
    with open(ARCHIVED_SESSIONS_FILE, "r") as f:
        archived = json.load(f)
    print("Archived Sessions List:", archived)
else:
    print("Archived sessions file does not exist!")
    archived = []

if os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "r") as f:
        settings = json.load(f)
    api_key = settings.get("jules")
else:
    print("Settings file does not exist!")
    api_key = None

if api_key:
    url = "https://jules.googleapis.com/v1alpha/sessions?pageSize=100"
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            print("\nFetched sessions count:", len(data.get("sessions", [])))
            for s in data.get("sessions", []):
                sid = s.get("id")
                name = s.get("name")
                state = s.get("state")
                title = s.get("title")
                is_match = sid in archived
                if "42452" in str(sid) or "42452" in str(name):
                    print(f"\n--- FOUND TARGET SESSION ---")
                    print(f"ID: {sid} (type: {type(sid)})")
                    print(f"Name: {name}")
                    print(f"Title: {title}")
                    print(f"State: {state}")
                    print(f"Is in archived list: {is_match}")
                    print(f"Details on comparison:")
                    print(f"  sid == '4245299970056730421': {sid == '4245299970056730421'}")
                    print(f"  sid in archived: {sid in archived}")
                    for item in archived:
                        print(f"  Comparing sid '{sid}' (len {len(str(sid))}) with archived item '{item}' (len {len(str(item))}): {sid == item}")
    except Exception as e:
        print("Error fetching sessions:", e)
else:
    print("No Jules API key found in settings.")
