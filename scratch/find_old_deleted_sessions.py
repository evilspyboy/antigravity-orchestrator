import json
import os
from datetime import datetime

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
DB_FILE = os.path.join(SCRATCH_DIR, "deleted_sessions_db.json")

if not os.path.exists(DB_FILE):
    print("Database file not found!")
    exit(1)

with open(DB_FILE, "r", encoding="utf-8") as f:
    db = json.load(f)

# Filter for Orbits sessions
orbits_sessions = []
for sid, session in db.items():
    repo = session.get("repo", "")
    # Check if repo matches orbits
    if "orbits" in repo.lower():
        # Get creation time from raw session data if available, or last updated
        raw = session.get("raw", {})
        create_time_str = raw.get("createTime") or raw.get("updateTime")
        
        # Fallback if no timestamp in raw
        create_time = datetime.min
        if create_time_str:
            try:
                # Strip fractional seconds and 'Z' to parse simply
                clean_ts = create_time_str.split(".")[0].replace("Z", "")
                if "T" in clean_ts:
                    create_time = datetime.fromisoformat(clean_ts)
            except Exception as e:
                print(f"Warning: could not parse timestamp {create_time_str} for session {sid}: {e}")
        
        orbits_sessions.append({
            "id": sid,
            "task": session.get("task", "No Title"),
            "repo": repo,
            "create_time": create_time,
            "create_time_str": create_time_str or "Unknown"
        })

print(f"Found {len(orbits_sessions)} archived Orbits sessions in local cache.")

# Sort by creation time (oldest first)
orbits_sessions.sort(key=lambda s: s["create_time"])

print("\nAll archived Orbits sessions sorted by age (oldest first):")
for i, s in enumerate(orbits_sessions):
    print(f"{i+1}. ID: {s['id']}, Created: {s['create_time_str']}, Task: {s['task'][:60]}...")

# Extract 10 oldest
oldest_10 = orbits_sessions[:10]
print(f"\nThe 10 oldest archived Orbits sessions to purge:")
for s in oldest_10:
    print(f"  - ID: {s['id']}, Created: {s['create_time_str']}, Task: {s['task'][:50]}")

# Print list of IDs to make it easy to use
print("\nJSON list of IDs:")
print(json.dumps([s["id"] for s in oldest_10]))
