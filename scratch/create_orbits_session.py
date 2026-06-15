import os
import subprocess
import json

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
task = (
    "You have autonomy to work on the project. You should not be working directly on the companion apps "
    "they are there for a reference to inform on that the main app needs to support having other apps "
    "be able to connect to it to use the p2p network & shared compute.\n\n"
    "You should do an audit and find what needs to be worked on. You have access to the master spec documents "
    "for guidance or to align to.\n\n"
    "I will add just because something is checked off in the todo doesn't mean it is finished or correctly implemented.\n\n"
    "I am giving you autonomy I expect you to find an issue that needs resolving and present a plan to do it."
)

print("Starting new Jules session...")
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
print("Stderr:", result.stderr)
