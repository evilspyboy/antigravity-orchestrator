import os
import sys
import json
import time
import subprocess
import re

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
SETTINGS_FILE = os.path.join(SCRATCH_DIR, "settings.json")

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def load_api_key():
    settings = load_settings()
    return settings.get("jules")

SESSIONS_CACHE_FILE = os.path.join(SCRATCH_DIR, "sessions_cache.json")

def invalidate_cache():
    if os.path.exists(SESSIONS_CACHE_FILE):
        try:
            os.remove(SESSIONS_CACHE_FILE)
            print("Invalidated sessions cache.")
        except Exception as e:
            print(f"Error invalidating cache: {e}")

def get_cli_status(session_id, jules_bin):
    env = os.environ.copy()
    env["JULES_API_KEY"] = load_api_key() or ""
    env["CI"] = "true"
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    
    try:
        output = subprocess.check_output(
            [jules_bin, "remote", "list", "--session"], 
            env=env, 
            timeout=15,
            stdin=subprocess.DEVNULL
        ).decode('utf-8', errors='replace')
        
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = re.split(r'\s{2,}', line)
            if not parts:
                continue
            if parts[0] == str(session_id) and len(parts) >= 5:
                return parts[4].lower().strip()
    except Exception as e:
        print(f"Error reading CLI status: {e}")
    return None

def poll_session(session_id):
    jules_bin = os.path.join(SCRATCH_DIR, "bin", "jules.exe" if os.name == 'nt' else "jules")
    if not os.path.exists(jules_bin):
        print(f"Jules binary not found at {jules_bin}")
        sys.exit(1)
        
    consecutive_errors = 0
    max_errors = 5
    
    print(f"Monitoring Jules session via CLI: {session_id}")
    while True:
        status = get_cli_status(session_id, jules_bin)
        print(f"[{time.strftime('%H:%M:%S')}] CLI status: {status}")
        
        if status:
            consecutive_errors = 0
            if "completed" in status or "succeeded" in status:
                print(f"SUCCESS: Jules session {session_id} completed successfully.")
                invalidate_cache()
                sys.exit(0)
            elif "failed" in status or "error" in status or "cancelled" in status:
                print(f"FAILURE: Jules session {session_id} failed.")
                invalidate_cache()
                sys.exit(1)
            elif "awaiting plan" in status or "feedback" in status or "awaiting user" in status:
                print(f"ATTENTION: Jules session {session_id} is awaiting plan approval or user feedback.")
                invalidate_cache()
                sys.exit(2)
        else:
            consecutive_errors += 1
            if consecutive_errors >= max_errors:
                print("Too many consecutive errors reading CLI status. Exiting.")
                sys.exit(3)
                
        time.sleep(15)

def main():
    if len(sys.argv) < 2:
        print("Usage: python poll_session.py <session_id>")
        sys.argv = [sys.argv[0], "2920478599414523561"] # fallback default for testing if run without args
        
    session_id = sys.argv[1]
    poll_session(session_id)

if __name__ == "__main__":
    main()

