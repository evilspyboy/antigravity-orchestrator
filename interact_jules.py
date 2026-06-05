import sys
import json
import urllib.request
import urllib.error

SETTINGS_FILE = "settings.json"

def get_api_key():
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            return settings.get("jules")
    except Exception as e:
        print(f"Error reading settings: {e}")
        return None

def get_activities(session_id):
    api_key = get_api_key()
    if not api_key:
        print("Jules API key not found in settings.json")
        return
    
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}/activities"
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            print(json.dumps(data, indent=2))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Error fetching activities: {e}")

def approve_plan(session_id):
    api_key = get_api_key()
    if not api_key:
        print("Jules API key not found in settings.json")
        return
    
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}:approvePlan"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            print("Plan approved successfully!")
            print(json.dumps(data, indent=2))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Error approving plan: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python interact_jules.py [get_activities | approve_plan] [session_id]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    session_id = sys.argv[2]
    
    if cmd == "get_activities":
        get_activities(session_id)
    elif cmd == "approve_plan":
        approve_plan(session_id)
    else:
        print(f"Unknown command: {cmd}")
