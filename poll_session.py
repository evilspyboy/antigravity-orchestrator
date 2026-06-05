import os
import sys
import json
import time
import urllib.request
import urllib.error

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
SETTINGS_FILE = os.path.join(SCRATCH_DIR, "settings.json")

def load_api_key():
    if not os.path.exists(SETTINGS_FILE):
        print(f"Error: {SETTINGS_FILE} not found.")
        sys.exit(1)
    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
            return settings.get("jules")
    except Exception as e:
        print(f"Error reading settings: {e}")
        sys.exit(1)

def poll_session(session_id, api_key):
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    
    consecutive_errors = 0
    max_errors = 5
    
    print(f"Monitoring Jules session: {session_id}")
    while True:
        try:
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                state = data.get("state", "UNKNOWN")
                title = data.get("title", "Untitled Task")
                print(f"[{time.strftime('%H:%M:%S')}] Session state: {state}")
                
                if state in ["COMPLETED", "SUCCEEDED"]:
                    print(f"SUCCESS: Jules session {session_id} ({title}) completed successfully.")
                    sys.exit(0)
                elif state in ["FAILED", "ERROR", "CANCELLED"]:
                    print(f"FAILURE: Jules session {session_id} ({title}) transitioned to {state} state.")
                    sys.exit(1)
                elif state == "AWAITING_USER_FEEDBACK":
                    print(f"ATTENTION: Jules session {session_id} ({title}) is awaiting plan approval or user feedback.")
                    sys.exit(2)
                    
                consecutive_errors = 0
        except urllib.error.HTTPError as e:
            consecutive_errors += 1
            print(f"[{time.strftime('%H:%M:%S')}] HTTP Error {e.code} polling session: {e.reason}")
            if consecutive_errors >= max_errors:
                print("Too many consecutive errors. Exiting.")
                sys.exit(3)
        except Exception as e:
            consecutive_errors += 1
            print(f"[{time.strftime('%H:%M:%S')}] Error polling session: {e}")
            if consecutive_errors >= max_errors:
                print("Too many consecutive errors. Exiting.")
                sys.exit(3)
                
        time.sleep(15)

def main():
    if len(sys.argv) < 2:
        print("Usage: python poll_session.py <session_id>")
        sys.argv = [sys.argv[0], "5587882850942119031"] # fallback default for testing if run without args
        
    session_id = sys.argv[1]
    api_key = load_api_key()
    if not api_key:
        print("Error: JULES_API_KEY is not configured in settings.")
        sys.exit(1)
        
    poll_session(session_id, api_key)

if __name__ == "__main__":
    main()
