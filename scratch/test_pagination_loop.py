import os
import json
import urllib.request
import time

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
SETTINGS_FILE = os.path.join(SCRATCH_DIR, "settings.json")

with open(SETTINGS_FILE, "r") as f:
    settings = json.load(f)
api_key = settings.get("jules")

if not api_key:
    print("API Key not found.")
    exit(1)

def run_test():
    filters = ["", "archived=true"]
    for f_val in filters:
        print(f"\n--- Testing Filter: '{f_val}' ---")
        next_page_token = ""
        page_num = 1
        total_sessions = 0
        start_time = time.time()
        
        while True:
            url = f"https://jules.googleapis.com/v1alpha/sessions?pageSize=100"
            if f_val:
                url += f"&filter={f_val}"
            if next_page_token:
                url += f"&pageToken={next_page_token}"
            
            print(f"Page {page_num}: Fetching URL {url[:100]}...")
            req = urllib.request.Request(
                url,
                headers={"x-goog-api-key": api_key, "Accept": "application/json"}
            )
            try:
                page_start = time.time()
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    sessions_page = data.get("sessions", [])
                    print(f"  Page {page_num} fetched in {time.time() - page_start:.2f}s. Sessions on page: {len(sessions_page)}")
                    total_sessions += len(sessions_page)
                    
                    next_page_token = data.get("nextPageToken", "")
                    print(f"  NextPageToken: {next_page_token[:30] if next_page_token else 'None'}")
                    
                    if not next_page_token or not sessions_page:
                        break
                    
                    page_num += 1
                    # Guard to prevent absolute infinite loop in test
                    if page_num > 50:
                        print("Guard triggered: page limit exceeded!")
                        break
            except Exception as e:
                print(f"  Error on page {page_num}: {e}")
                break
                
        print(f"Filter '{f_val}' finished. Total sessions: {total_sessions} in {time.time() - start_time:.2f}s")

run_test()
