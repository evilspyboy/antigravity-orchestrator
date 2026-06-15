import os
import subprocess
import json
import urllib.request
import urllib.error

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
JULES_BIN = os.path.join(SCRATCH_DIR, "bin", "jules.exe" if os.name == 'nt' else "jules")
SETTINGS_FILE = os.path.join(SCRATCH_DIR, "settings.json")

# Read settings
with open(SETTINGS_FILE, "r") as f:
    settings = json.load(f)

env = os.environ.copy()
if settings.get("jules"):
    env["JULES_API_KEY"] = settings["jules"]
env["CI"] = "true"
env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"

repo = "evilspyboy/Orbits"
task = "Test session safety checks"

print("Creating session...")
result = subprocess.run(
    [JULES_BIN, "new", "--repo", repo, task],
    stdin=subprocess.DEVNULL,
    capture_output=True,
    text=True,
    env=env,
    shell=False
)

print("Return code:", result.returncode)
print("Stdout:", result.stdout)

# Extract session ID from stdout
session_id = None
for line in result.stdout.splitlines():
    if line.startswith("ID:"):
        session_id = line.split(":", 1)[1].strip()
        break

if not session_id:
    print("Failed to get session ID")
    exit(1)

print(f"Created session ID: {session_id}")

# Fetch details from API
url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
req = urllib.request.Request(
    url,
    headers={"x-goog-api-key": settings["jules"], "Accept": "application/json"}
)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print("Raw Session Details:")
        print(json.dumps(data, indent=2))
except Exception as e:
    print("API error:", e)
