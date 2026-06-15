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

url = "https://jules.googleapis.com/v1alpha/sessions?pageSize=100"
req = urllib.request.Request(
    url,
    headers={"x-goog-api-key": api_key, "Accept": "application/json"}
)

try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        sessions = data.get("sessions", [])
        print(f"Total sessions fetched from API: {len(sessions)}")
        
        orbits_sessions = []
        for s in sessions:
            source = s.get("sourceContext", {}).get("source", "")
            title = s.get("title", "")
            prompt = s.get("prompt", "")
            sid = s.get("id")
            
            # Check if orbits is mentioned in source, title or prompt
            is_orbits = "orbits" in source.lower() or "orbits" in title.lower() or "orbits" in prompt.lower()
            if is_orbits:
                orbits_sessions.append(s)
        
        print(f"Found {len(orbits_sessions)} Orbits sessions.")
        for s in orbits_sessions:
            print("-" * 40)
            print(f"ID: {s.get('id')}")
            print(f"Title: {s.get('title')}")
            print(f"State: {s.get('state')}")
            print(f"Created: {s.get('createTime')}")
            print(f"Updated: {s.get('updateTime')}")
            print(f"Source: {s.get('sourceContext', {}).get('source')}")
except Exception as e:
    print("Error:", e)
