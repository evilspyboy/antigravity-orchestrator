import os
import json
import urllib.request
import urllib.error
import subprocess

SETTINGS_FILE = "settings.json"

def test_github(token):
    if not token or token == "••••••••••••••••":
        print("[GitHub] No token configured.")
        return
        
    print("[GitHub] Testing connectivity...")
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Antigravity-Orchestrator"
        }
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            user_data = json.loads(response.read().decode('utf-8'))
            print(f"[GitHub] Success! Authenticated as: {user_data.get('login')}")
            
            # Fetch repos
            repos_req = urllib.request.Request(
                "https://api.github.com/user/repos?per_page=5&sort=updated",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "Antigravity-Orchestrator"
                }
            )
            with urllib.request.urlopen(repos_req) as repos_resp:
                repos = json.loads(repos_resp.read().decode('utf-8'))
                print("[GitHub] Recent repositories:")
                for r in repos:
                    print(f"  - {r.get('full_name')} ({r.get('html_url')})")
    except urllib.error.HTTPError as e:
        print(f"[GitHub] Auth failed (HTTP {e.code}): {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"[GitHub] Connection error: {e}")

def test_jules(api_key):
    if not api_key:
        print("[Jules] No API key configured. Checking default login...")
    else:
        print("[Jules] Testing connectivity using API key...")
        
    env = os.environ.copy()
    if api_key:
        env["JULES_API_KEY"] = api_key
        
    try:
        result = subprocess.run(
            ["jules", "remote", "list", "--session"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            shell=True
        )
        if result.returncode == 0:
            print("[Jules] Success! Able to list sessions.")
            # Print first few lines of sessions list
            lines = result.stdout.strip().split('\n')
            for line in lines[:5]:
                print(f"  {line}")
        else:
            print(f"[Jules] Failed (Return code {result.returncode}): {result.stderr or result.stdout}")
    except Exception as e:
        print(f"[Jules] Connection/Execution error: {e}")

def main():
    if not os.path.exists(SETTINGS_FILE):
        print(f"Error: {SETTINGS_FILE} not found.")
        return
        
    with open(SETTINGS_FILE, "r") as f:
        settings = json.load(f)
        
    test_github(settings.get("github"))
    test_jules(settings.get("jules"))

if __name__ == "__main__":
    main()
