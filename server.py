import os
import sys
import re
import json
import shutil
import subprocess
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Antigravity Orchestrator Backend")

# File paths
home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
is_windows = os.name == 'nt'
JULES_BIN = os.path.join(SCRATCH_DIR, "bin", "jules.exe" if is_windows else "jules")
PROJECTS_FILE = os.path.join(SCRATCH_DIR, "projects.json")
SETTINGS_FILE = os.path.join(SCRATCH_DIR, "settings.json")
INSTRUCTIONS_FILE = os.path.join(SCRATCH_DIR, "instructions.json")
DELETED_SESSIONS_FILE = os.path.join(SCRATCH_DIR, "deleted_sessions.json")
DELETED_SESSIONS_DB_FILE = os.path.join(SCRATCH_DIR, "deleted_sessions_db.json")
SESSIONS_CACHE_FILE = os.path.join(SCRATCH_DIR, "sessions_cache.json")

def invalidate_sessions_cache():
    if os.path.exists(SESSIONS_CACHE_FILE):
        try:
            os.remove(SESSIONS_CACHE_FILE)
            print("Invalidated sessions cache.", file=sys.stderr)
        except Exception as e:
            print(f"Error invalidating sessions cache: {e}", file=sys.stderr)


# Legacy migration from archived -> deleted
try:
    legacy_list = os.path.join(SCRATCH_DIR, "archived_sessions.json")
    legacy_db = os.path.join(SCRATCH_DIR, "archived_sessions_db.json")
    if os.path.exists(legacy_list) and not os.path.exists(DELETED_SESSIONS_FILE):
        shutil.copy2(legacy_list, DELETED_SESSIONS_FILE)
    if os.path.exists(legacy_db) and not os.path.exists(DELETED_SESSIONS_DB_FILE):
        shutil.copy2(legacy_db, DELETED_SESSIONS_DB_FILE)
except Exception as migration_err:
    print("Migration warning:", migration_err, file=sys.stderr)


DEFAULT_SETTINGS = {
    "gemini": "",
    "github": "",
    "jules": "",
    "root": os.path.join(home_dir, "projects").replace("\\", "/")
}

# Helpers to read/write JSON files
def read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return default

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# Models
class ProjectInput(BaseModel):
    name: str
    path: str

class SwitchProjectInput(BaseModel):
    name: str

class SettingsInput(BaseModel):
    github: str
    jules: Optional[str] = ""
    root: str

class GenerateUIInput(BaseModel):
    prompt: str
    project: str

class ExportInput(BaseModel):
    project: str
    target_dir: str
    format: str

class ApplyInput(BaseModel):
    project: Optional[str] = None

class DeleteSessionInput(BaseModel):
    session_id: str
    purge_local_cache: Optional[bool] = False
    confirm_active_delete: Optional[bool] = False


class CreateSessionInput(BaseModel):
    repo: str
    task: str
    branch: Optional[str] = "main"

class MessageInput(BaseModel):
    prompt: str

class RepoFileInput(BaseModel):
    path: str
    repo: Optional[str] = None
    session_id: Optional[str] = None

class MergePRInput(BaseModel):
    session_id: Optional[str] = None
    repo: Optional[str] = None
    pr_number: Optional[int] = None

# Helper to run Git branch detection
def get_git_branch(path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=True,
            timeout=5
        )
        return result.stdout.strip() or "main"
    except Exception:
        return "main"

# Static Index Page
@app.get("/", response_class=HTMLResponse)
def get_index():
    index_path = os.path.join(SCRATCH_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="index.html not found")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()

# API: Projects
@app.get("/api/projects")
def get_projects():
    projects = read_json(PROJECTS_FILE, [])
    # Sync git branches on retrieval
    for p in projects:
        if os.path.exists(p["path"]):
            p["branch"] = get_git_branch(p["path"])
            p["connected"] = True
        else:
            p["connected"] = False
    return projects

@app.post("/api/projects")
def add_project(input_data: ProjectInput):
    projects = read_json(PROJECTS_FILE, [])
    
    # Check if duplicate name or path
    for p in projects:
        if p["name"] == input_data.name:
            raise HTTPException(status_code=400, detail="Project name already exists")
    
    # Check if path exists
    if not os.path.exists(input_data.path):
        raise HTTPException(status_code=400, detail="Project local path does not exist")
        
    new_project = {
        "name": input_data.name,
        "path": input_data.path.replace("\\", "/"),
        "branch": get_git_branch(input_data.path),
        "connected": True,
        "active": len(projects) == 0  # Activate first registered project
    }
    
    projects.append(new_project)
    write_json(PROJECTS_FILE, projects)
    return {"success": True}

@app.post("/api/projects/switch")
def switch_project(input_data: SwitchProjectInput):
    projects = read_json(PROJECTS_FILE, [])
    found = False
    for p in projects:
        if p["name"] == input_data.name:
            p["active"] = True
            found = True
        else:
            p["active"] = False
            
    if not found:
        raise HTTPException(status_code=404, detail="Project not found")
        
    write_json(PROJECTS_FILE, projects)
    return {"success": True}

# API: Settings
@app.get("/api/settings")
def get_settings():
    return read_json(SETTINGS_FILE, DEFAULT_SETTINGS)

@app.post("/api/settings")
def save_settings(input_data: SettingsInput):
    write_json(SETTINGS_FILE, input_data.model_dump())
    # Try updating the active workspace environment variable if possible
    # We can also write to a local .env file in the scratch folder
    env_file = os.path.join(SCRATCH_DIR, ".env")
    with open(env_file, "w") as f:
        f.write(f"GITHUB_TOKEN={input_data.github}\n")
        f.write(f"JULES_API_KEY={input_data.jules or ''}\n")
    return {"success": True}

# API: Stitch Drafts & Export
@app.get("/api/stitch/drafts")
def get_stitch_drafts(project: str):
    # Scan the local stitch folder
    stitch_dir = os.path.join(SCRATCH_DIR, "stitch")
    drafts = []
    if not os.path.exists(stitch_dir):
        return drafts
        
    for name in os.listdir(stitch_dir):
        folder_path = os.path.join(stitch_dir, name)
        if os.path.isdir(folder_path):
            code_file = os.path.join(folder_path, "code.html")
            design_file = os.path.join(folder_path, "DESIGN.md")
            
            code_content = ""
            if os.path.exists(code_file):
                with open(code_file, "r", encoding="utf-8") as f:
                    code_content = f.read()
            elif os.path.exists(design_file):
                with open(design_file, "r", encoding="utf-8") as f:
                    code_content = f.read()
                    
            stat = os.stat(folder_path)
            timestamp = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            
            drafts.append({
                "name": name.replace("_", " ").title(),
                "folder_name": name,
                "timestamp": timestamp,
                "code": code_content
            })
    return drafts

@app.post("/api/stitch/generate")
def generate_ui_stub(input_data: GenerateUIInput):
    # Create a mock draft directory simulating Stitch UI creation
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"stitch_generated_{timestamp_str}"
    target_dir = os.path.join(SCRATCH_DIR, "stitch", folder_name)
    os.makedirs(target_dir, exist_ok=True)
    
    mock_code = f"""<!-- Generated UI from prompt: "{input_data.prompt}" -->
<div class="p-6 bg-slate-900 border border-slate-800 rounded-xl">
    <h3 class="text-lg font-bold text-primary">UI Stub: {input_data.prompt[:30]}...</h3>
    <p class="text-sm text-on-surface-variant mt-2">Design system parameters imported successfully.</p>
</div>
"""
    with open(os.path.join(target_dir, "code.html"), "w", encoding="utf-8") as f:
        f.write(mock_code)
        
    return {"success": True}

@app.post("/api/stitch/export")
def export_stitch_design(input_data: ExportInput):
    projects = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects if p["name"] == input_data.project), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Target project not found")
        
    # Get recent draft
    stitch_dir = os.path.join(SCRATCH_DIR, "stitch")
    if not os.path.exists(stitch_dir):
        raise HTTPException(status_code=400, detail="No drafts folder exists")
        
    subdirs = [os.path.join(stitch_dir, d) for d in os.listdir(stitch_dir) if os.path.isdir(os.path.join(stitch_dir, d))]
    if not subdirs:
        raise HTTPException(status_code=400, detail="No drafts found to export")
        
    # Take the latest modified directory
    latest_dir = max(subdirs, key=os.path.getmtime)
    code_path = os.path.join(latest_dir, "code.html")
    if not os.path.exists(code_path):
        # Fallback to DESIGN.md
        code_path = os.path.join(latest_dir, "DESIGN.md")
        if not os.path.exists(code_path):
            raise HTTPException(status_code=400, detail="No exportable code in draft")
            
    # Copy to target directory in project
    dest_dir = os.path.join(proj["path"], input_data.target_dir)
    os.makedirs(dest_dir, exist_ok=True)
    
    filename = "Component.tsx" if input_data.format == "react" else "index.html"
    dest_path = os.path.join(dest_dir, filename)
    shutil.copy(code_path, dest_path)
    
    return {"success": True, "message": f"Successfully exported to {dest_path}"}

# API: Jules Sessions Wrapper
@app.get("/api/jules/sessions")
def get_jules_sessions(
    project: str = "",
    show_deleted: bool = False,
    show_archived: bool = False,
    repo_filter: Optional[str] = None,
    limit: Optional[int] = None,
    sort_ascending: bool = False
):
    import urllib.request
    import time
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
    
    deleted = read_json(DELETED_SESSIONS_FILE, [])
    
    # Check cache
    cache_valid = False
    cached_data = {}
    if os.path.exists(SESSIONS_CACHE_FILE):
        try:
            cached_data = read_json(SESSIONS_CACHE_FILE, {})
            cache_time = cached_data.get("timestamp", 0)
            # 10 minutes cache validity
            if time.time() - cache_time < 600:
                cache_valid = True
        except Exception as ce:
            print("Error reading cache:", ce, file=sys.stderr)
            
    if cache_valid and "sessions" in cached_data:
        parsed_all = cached_data["sessions"]
        print("Using cached Jules sessions", file=sys.stderr)
    else:
        print("Fetching fresh sessions from Jules API", file=sys.stderr)
        parsed_all = []
        seen_ids = set()
        # Always fetch both live and archived to populate cache fully
        filters_to_fetch = ["", "archived=true"]
        try:
            for f_val in filters_to_fetch:
                next_page_token = ""
                while True:
                    url = "https://jules.googleapis.com/v1alpha/sessions?pageSize=100"
                    if f_val:
                        url += f"&filter={f_val}"
                    if next_page_token:
                        url += f"&pageToken={next_page_token}"
                    
                    req = urllib.request.Request(
                        url,
                        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=20) as response:
                        data = json.loads(response.read().decode('utf-8'))
                        sessions_page = data.get("sessions", [])
                        
                        for s in sessions_page:
                            sid = s.get("id")
                            if sid in seen_ids:
                                continue
                            seen_ids.add(sid)
                            state = s.get("state", "UNKNOWN")
                            
                            repo = "Other/Unmapped Repos"
                            source = s.get("sourceContext", {}).get("source", "")
                            if source.startswith("sources/github/"):
                                repo = source.replace("sources/github/", "")
                            
                            # Friendly time ago for last active
                            last_active = "Unknown"
                            update_time_str = s.get("updateTime")
                            if update_time_str:
                                try:
                                    clean_time_str = re.sub(r'\.\d+Z$', 'Z', update_time_str)
                                    if clean_time_str.endswith('Z'):
                                        clean_time_str = clean_time_str[:-1] + '+00:00'
                                    dt = datetime.fromisoformat(clean_time_str)
                                    diff = datetime.now(dt.tzinfo) - dt
                                    diff_min = int(diff.total_seconds() / 60)
                                    if diff_min < 1:
                                        last_active = "Just now"
                                    elif diff_min < 60:
                                        last_active = f"{diff_min}m ago"
                                    else:
                                        diff_hr = diff_min // 60
                                        if diff_hr < 24:
                                            last_active = f"{diff_hr}h {diff_min % 60}m ago"
                                        else:
                                            diff_days = diff_hr // 24
                                            last_active = f"{diff_days} day{'s' if diff_days > 1 else ''} ago"
                                except Exception as te:
                                    print("Error parsing timestamp:", te, file=sys.stderr)
                                    last_active = update_time_str
                            
                            status = state
                            if state == "AWAITING_USER_FEEDBACK" and not s.get("archived", False):
                                act_url = f"https://jules.googleapis.com/v1alpha/sessions/{sid}/activities"
                                act_req = urllib.request.Request(
                                    act_url,
                                    headers={"x-goog-api-key": api_key, "Accept": "application/json"}
                                )
                                try:
                                    with urllib.request.urlopen(act_req, timeout=10) as act_resp:
                                        act_data = json.loads(act_resp.read().decode('utf-8'))
                                        activities = act_data.get("activities", [])
                                        last_sig = None
                                        for act in reversed(activities):
                                            if "planGenerated" in act:
                                                last_sig = "planGenerated"
                                                break
                                            elif "planApproved" in act:
                                                last_sig = "planApproved"
                                                break
                                            elif "agentMessaged" in act:
                                                last_sig = "agentMessaged"
                                                break
                                        
                                        if last_sig == "planGenerated":
                                            status = "AWAITING PLAN APPROVAL"
                                        else:
                                            status = "AWAITING USER FEEDBACK"
                                except Exception:
                                    status = "AWAITING USER FEEDBACK"
                            
                            parsed_all.append({
                                "id": sid,
                                "task": s.get("title") or s.get("prompt") or "No Title",
                                "repo": repo,
                                "status": status.upper(),
                                "logs": [f"Last active: {last_active}"],
                                "is_deleted": False, # Will be set on output filter
                                "raw": s
                            })
                        
                        next_page_token = data.get("nextPageToken", "")
                        if not next_page_token or not sessions_page:
                            break
            # Save to cache
            write_json(SESSIONS_CACHE_FILE, {
                "timestamp": time.time(),
                "sessions": parsed_all
            })
        except Exception as e:
            print("Jules API error during fetch:", e, file=sys.stderr)
            # If fetch failed but we have stale cache, fallback to it
            if "sessions" in cached_data:
                parsed_all = cached_data["sessions"]
                print("Falling back to stale cached sessions due to API error", file=sys.stderr)
            else:
                raise e

    # Apply filter on output
    parsed = []
    for s in parsed_all:
        sid = s["id"]
        is_archived = s["raw"].get("archived", False)
        
        # Filter archived sessions if not requested
        if is_archived and not show_archived:
            continue
            
        # Filter deleted sessions if not requested
        is_deleted = sid in deleted
        if is_deleted and not show_deleted:
            continue
            
        # Clone session and update is_deleted flag
        sc = dict(s)
        sc["is_deleted"] = is_deleted
        parsed.append(sc)

    # Apply repo filter
    if repo_filter:
        parsed = [s for s in parsed if repo_filter.lower() in s.get("repo", "").lower()]
        
    if show_deleted:
        db = read_json(DELETED_SESSIONS_DB_FILE, {})
        for sid, cached in db.items():
            if any(p["id"] == sid for p in parsed):
                continue
            repo_name = cached.get("repo", "")
            if repo_filter and repo_filter.lower() not in repo_name.lower():
                continue
            # Also check if it matches show_archived setting
            is_archived = cached.get("raw", {}).get("archived", False)
            if is_archived and not show_archived:
                continue
            parsed.append({
                "id": sid,
                "task": cached.get("task", "No Title"),
                "repo": repo_name,
                "status": cached.get("status", "COMPLETED").upper(),
                "logs": cached.get("logs", []),
                "is_deleted": True,
                "raw": cached.get("raw", {})
            })

    # Sort sessions
    def get_create_time(session):
        ct = session.get("raw", {}).get("createTime")
        if ct:
            try:
                clean = re.sub(r'\.\d+Z$', 'Z', ct)
                if clean.endswith('Z'):
                    clean = clean[:-1] + '+00:00'
                return datetime.fromisoformat(clean)
            except:
                pass
        return datetime.min
        
    parsed.sort(key=get_create_time, reverse=not sort_ascending)
    
    if limit is not None and limit > 0:
        parsed = parsed[:limit]
        
    return parsed


@app.get("/api/jules/repos")
def get_jules_repos():
    settings = read_json(SETTINGS_FILE, {})
    env = os.environ.copy()
    if settings.get("jules"):
        env["JULES_API_KEY"] = settings["jules"]
    env["CI"] = "true"
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    
    try:
        result = subprocess.run(
            [JULES_BIN, "remote", "list", "--repo"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            shell=True
        )
        if result.returncode == 0:
            repos = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
            return repos
        else:
            raise HTTPException(status_code=500, detail=result.stderr or result.stdout)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jules/auth-status")
def get_jules_auth_status():
    settings = read_json(SETTINGS_FILE, {})
    env = os.environ.copy()
    if settings.get("jules"):
        env["JULES_API_KEY"] = settings["jules"]
    env["CI"] = "true"
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    try:
        result = subprocess.run(
            [JULES_BIN, "remote", "list", "--session"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
            shell=True
        )
        if result.returncode == 0:
            return {"logged_in": True}
    except Exception:
        pass
    return {"logged_in": False}

@app.post("/api/jules/login")
def jules_login():
    try:
        subprocess.Popen(["cmd.exe", "/c", "start", "jules", "login"])
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start login: {str(e)}")

@app.get("/api/jules/sessions/{session_id}/logs")
def get_jules_logs(session_id: str):
    db = read_json(DELETED_SESSIONS_DB_FILE, {})
    if session_id in db:
        return {"logs": db[session_id].get("logs", ["[info] No activities logged yet."])}
        
    import urllib.request
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
    
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}/activities"
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            logs = []
            for act in data.get("activities", []):
                time_str = act.get("createTime", "")
                time_part = time_str.split("T")[-1][:8] if "T" in time_str else ""
                prefix = f"[{time_part}]" if time_part else ""
                
                if "agentMessaged" in act and "agentMessage" in act["agentMessaged"]:
                    logs.append(f"{prefix} Jules: {act['agentMessaged']['agentMessage']}")
                elif "userMessaged" in act and "userMessage" in act["userMessaged"]:
                    logs.append(f"{prefix} User: {act['userMessaged']['userMessage']}")
                elif "progressUpdated" in act:
                    title = act["progressUpdated"].get("title", "")
                    desc = act["progressUpdated"].get("description", "")
                    logs.append(f"{prefix} Progress: {title}" + (f" - {desc}" if desc else ""))
                elif "planGenerated" in act:
                    logs.append(f"{prefix} Plan Generated.")
                elif "planApproved" in act:
                    logs.append(f"{prefix} Plan Approved.")
            
            if not logs:
                logs.append("[info] No activities logged yet.")
            return {"logs": logs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
 
@app.get("/api/jules/sessions/{session_id}/patch")
def get_jules_patch(session_id: str):
    db = read_json(DELETED_SESSIONS_DB_FILE, {})
    if session_id in db:
        return {"patch": db[session_id].get("patch", "")}
        
    settings = read_json(SETTINGS_FILE, {})
    env = os.environ.copy()
    if settings.get("jules"):
        env["JULES_API_KEY"] = settings["jules"]
    env["CI"] = "true"
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    
    try:
        result = subprocess.run(
            [JULES_BIN, "remote", "pull", "--session", session_id],
            cwd=SCRATCH_DIR,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            shell=True
        )
        if result.returncode == 0:
            return {"patch": result.stdout}
        else:
            raise HTTPException(status_code=500, detail=result.stderr or result.stdout)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/sessions/{session_id}/apply")
def apply_jules_patch(session_id: str, input_data: Optional[ApplyInput] = None):
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
        
    # 1. Fetch session details to get the source repo
    import urllib.request
    session_url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
    req = urllib.request.Request(session_url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            session_data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch session metadata: {str(e)}")
        
    repo_name = ""
    source = session_data.get("sourceContext", {}).get("source", "")
    if source.startswith("sources/github/"):
        repo_parts = source.replace("sources/github/", "").split("/")
        repo_name = repo_parts[-1] # e.g. "CityConnect"
        
    projects_list = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects_list if (
        p["name"].lower() == repo_name.lower() or
        p["path"].lower().replace("\\", "/").endswith("/" + repo_name.lower())
    )), None)
    
    if not proj and input_data and input_data.project:
        proj = next((p for p in projects_list if p["name"] == input_data.project), None)
        
    target_cwd = proj["path"] if (proj and os.path.exists(proj["path"])) else None
    if not target_cwd:
        raise HTTPException(status_code=400, detail=f"Local project directory for repository '{repo_name or 'unknown'}' not found. Please register and clone it first.")
        
    env = os.environ.copy()
    env["JULES_API_KEY"] = api_key
    env["CI"] = "true"
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    
    try:
        result = subprocess.run(
            [JULES_BIN, "remote", "pull", "--session", session_id, "--apply"],
            cwd=target_cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            shell=True
        )
        if result.returncode == 0:
            invalidate_sessions_cache()
            return {"message": f"Successfully applied patch to {proj['name']}: {result.stdout}"}
        else:
            raise HTTPException(status_code=500, detail=result.stderr or result.stdout)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jules/sessions/{session_id}/git-status")
def get_jules_git_status(session_id: str):
    import urllib.request
    import urllib.error
    import re
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    github_token = settings.get("github")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")

    # 1. Fetch session details to get the source repo and branches
    session_url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
    req = urllib.request.Request(session_url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            session_data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch session metadata: {str(e)}")

    # Extract base/head branches and repository details
    source = session_data.get("sourceContext", {}).get("source", "")
    owner, repo_name = "evilspyboy", "Orbits" # defaults
    if source.startswith("sources/github/"):
        parts = source.replace("sources/github/", "").split("/")
        if len(parts) >= 2:
            owner, repo_name = parts[0], parts[1]

    # Find base branch
    base_ref = session_data.get("sourceContext", {}).get("githubRepoContext", {}).get("startingBranch", "main") or "main"

    # Find head branch from outputs (PR or changeset)
    head_ref = None
    prs_info = []
    outputs = session_data.get("outputs", [])
    for out in outputs:
        if "pullRequest" in out:
            pr = out["pullRequest"]
            pr_url = pr.get("url", "")
            match = re.search(r"pull/(\d+)", pr_url)
            pr_num = match.group(1) if match else "unknown"
            
            # Fetch status from GitHub API
            state = "closed"
            merged = False
            status_text = "Status Unknown"
            if github_token and pr_num != "unknown":
                gh_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_num}"
                gh_headers = {
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "Antigravity-Orchestrator",
                    "Authorization": f"Bearer {github_token}"
                }
                gh_req = urllib.request.Request(gh_url, headers=gh_headers)
                try:
                    with urllib.request.urlopen(gh_req, timeout=15) as gh_resp:
                        gh_data = json.loads(gh_resp.read().decode('utf-8'))
                        state = gh_data.get("state", "closed")
                        merged = gh_data.get("merged", False)
                        if state == "open":
                            status_text = "Open"
                        else:
                            status_text = "Merged" if merged else "Closed"
                except Exception as ghe:
                    print("GitHub API pull request check failed:", ghe, file=sys.stderr)
                    status_text = "Created (Auth scopes required)"
            else:
                status_text = "Created"

            prs_info.append({
                "number": pr_num,
                "url": pr_url,
                "status_text": status_text
            })
            if "headRef" in pr:
                head_ref = pr["headRef"]
            if "baseRef" in pr:
                base_ref = pr["baseRef"]

    # If no head_ref found in PR, check changeset
    if not head_ref:
        for out in outputs:
            if "changeSet" in out:
                head_ref = f"feat-{repo_name.lower()}-base-{session_id}"
                break

    # If still no head_ref, try a sensible fallback
    if not head_ref:
        head_ref = f"feat-{repo_name.lower()}-base-{session_id}"

    # 2. Local status: is local branch active?
    projects_list = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects_list if (
        p["name"].lower() == repo_name.lower() or
        p["path"].lower().replace("\\", "/").endswith("/" + repo_name.lower())
    )), None)

    is_local_active = False
    local_project_registered = False
    local_current_branch = None
    if proj:
        local_project_registered = True
        local_path = proj["path"]
        if os.path.exists(local_path):
            try:
                branch_res = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=local_path,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if branch_res.returncode == 0:
                    local_current_branch = branch_res.stdout.strip()
                    is_local_active = (local_current_branch == head_ref)
            except Exception:
                pass

    # 3. Branch comparison: ahead/behind count
    compare_status = "unknown"
    ahead_by = 0
    behind_by = 0
    status_message = ""

    # Try GitHub API first
    if github_token and head_ref:
        compare_url = f"https://api.github.com/repos/{owner}/{repo_name}/compare/{base_ref}...{head_ref}"
        gh_headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Antigravity-Orchestrator",
            "Authorization": f"Bearer {github_token}"
        }
        comp_req = urllib.request.Request(compare_url, headers=gh_headers)
        try:
            with urllib.request.urlopen(comp_req, timeout=15) as comp_resp:
                comp_data = json.loads(comp_resp.read().decode('utf-8'))
                compare_status = comp_data.get("status", "unknown")
                ahead_by = comp_data.get("ahead_by", 0)
                behind_by = comp_data.get("behind_by", 0)
                
                if compare_status == "ahead":
                    status_message = f"Ahead by {ahead_by} commit{'s' if ahead_by > 1 else ''}"
                elif compare_status == "behind":
                    status_message = f"Behind by {behind_by} commit{'s' if behind_by > 1 else ''}"
                elif compare_status == "diverged":
                    status_message = f"Diverged (Ahead by {ahead_by}, Behind by {behind_by})"
                elif compare_status == "identical":
                    status_message = "Identical/Up to date"
        except urllib.error.HTTPError as he:
            if he.code == 404:
                compare_status = "deleted"
                status_message = "Branch deleted or merged on remote"
            else:
                compare_status = "error"
                status_message = f"GitHub Compare API error: {he.reason}"
        except Exception as ce:
            compare_status = "error"
            status_message = str(ce)

    # Local fallback for comparison if GitHub API failed or was unauthorized, and repo exists locally
    if compare_status in ["unknown", "error"] and proj and os.path.exists(proj["path"]) and head_ref:
        try:
            check_branch = subprocess.run(
                ["git", "show-ref", "--verify", f"refs/heads/{head_ref}"],
                cwd=proj["path"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=5
            )
            if check_branch.returncode == 0:
                ahead_res = subprocess.run(
                    ["git", "rev-list", "--count", f"{base_ref}..{head_ref}"],
                    cwd=proj["path"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                behind_res = subprocess.run(
                    ["git", "rev-list", "--count", f"{head_ref}..{base_ref}"],
                    cwd=proj["path"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if ahead_res.returncode == 0 and behind_res.returncode == 0:
                    ahead_by = int(ahead_res.stdout.strip())
                    behind_by = int(behind_res.stdout.strip())
                    if ahead_by > 0 and behind_by > 0:
                        compare_status = "diverged"
                        status_message = f"Diverged locally (Ahead by {ahead_by}, Behind by {behind_by})"
                    elif ahead_by > 0:
                        compare_status = "ahead"
                        status_message = f"Ahead locally by {ahead_by} commit{'s' if ahead_by > 1 else ''}"
                    elif behind_by > 0:
                        compare_status = "behind"
                        status_message = f"Behind locally by {behind_by} commit{'s' if behind_by > 1 else ''}"
                    else:
                        compare_status = "identical"
                        status_message = "Identical locally"
        except Exception:
            pass

    return {
        "head_ref": head_ref,
        "base_ref": base_ref,
        "prs": prs_info,
        "is_local_active": is_local_active,
        "local_project_registered": local_project_registered,
        "local_current_branch": local_current_branch,
        "compare_status": compare_status,
        "ahead_by": ahead_by,
        "behind_by": behind_by,
        "status_message": status_message
    }

@app.get("/api/jules/sessions/{session_id}/plan")
def get_jules_plan(session_id: str):
    db = read_json(DELETED_SESSIONS_DB_FILE, {})
    if session_id in db:
        return {"success": True, "steps": db[session_id].get("plan", {}).get("steps", [])}
        
    import urllib.request
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
    
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}/activities"
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            for act in data.get("activities", []):
                if "planGenerated" in act and "plan" in act["planGenerated"]:
                    return {"success": True, "steps": act["planGenerated"]["plan"].get("steps", [])}
            raise HTTPException(status_code=404, detail="No plan found in activities")
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=e.code, detail=f"Google API Error: {e.read().decode('utf-8')}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/sessions/{session_id}/approve")
def approve_jules_plan(session_id: str):
    import urllib.request
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
    
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}:approvePlan"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            invalidate_sessions_cache()
            return {"success": True, "response": data}
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=e.code, detail=f"Google API Error: {e.read().decode('utf-8')}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/sessions/{session_id}/message")
def send_jules_message(session_id: str, input_data: MessageInput):
    import urllib.request
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
    
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}:sendMessage"
    payload = json.dumps({"prompt": input_data.prompt}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8') or "{}")
            invalidate_sessions_cache()
            return {"success": True, "response": data}
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=e.code, detail=f"Google API Error: {e.read().decode('utf-8')}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/repos/file")
def get_repo_file_api(input_data: RepoFileInput):
    import urllib.request
    import urllib.error
    
    settings = read_json(SETTINGS_FILE, {})
    github_token = settings.get("github")
    api_key = settings.get("jules")
    
    repo = input_data.repo
    if not repo:
        if not input_data.session_id:
            raise HTTPException(status_code=400, detail="Either 'repo' or 'session_id' must be provided.")
        if not api_key:
            raise HTTPException(status_code=400, detail="Jules API key not configured to resolve session.")
        
        # Resolve repository from session_id
        session_url = f"https://jules.googleapis.com/v1alpha/sessions/{input_data.session_id}"
        req = urllib.request.Request(session_url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                session_data = json.loads(resp.read().decode('utf-8'))
                source = session_data.get("sourceContext", {}).get("source", "")
                if source.startswith("sources/github/"):
                    repo = source.replace("sources/github/", "")
                else:
                    raise HTTPException(status_code=400, detail=f"Could not resolve repository from session source: {source}")
        except urllib.error.HTTPError as e:
            raise HTTPException(status_code=e.code, detail=f"Jules API Error while fetching session: {e.read().decode('utf-8')}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch session metadata: {str(e)}")

    if not repo:
        raise HTTPException(status_code=400, detail="Repository name could not be resolved.")

    # Call GitHub contents API to fetch the file
    gh_url = f"https://api.github.com/repos/{repo}/contents/{input_data.path}"
    headers = {
        "Accept": "application/vnd.github.v3.raw",
        "User-Agent": "Antigravity-Orchestrator"
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    
    req = urllib.request.Request(gh_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode('utf-8')
            return {"content": content}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='replace')
        raise HTTPException(status_code=e.code, detail=f"GitHub API Error: {err_msg or e.reason}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve file from GitHub: {str(e)}")

@app.post("/api/jules/pulls/merge")
def merge_pull_request_api(input_data: MergePRInput):
    import urllib.request
    import urllib.error
    import re
    
    settings = read_json(SETTINGS_FILE, {})
    github_token = settings.get("github")
    api_key = settings.get("jules")
    
    repo = input_data.repo
    pr_number = input_data.pr_number
    
    if not repo or not pr_number:
        if not input_data.session_id:
            raise HTTPException(status_code=400, detail="Either 'session_id' or both 'repo' and 'pr_number' must be provided.")
        if not api_key:
            raise HTTPException(status_code=400, detail="Jules API key not configured to resolve session.")
            
        # 1. Fetch session details to get the source repo and outputs (where the PR is registered)
        session_url = f"https://jules.googleapis.com/v1alpha/sessions/{input_data.session_id}"
        req = urllib.request.Request(session_url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                session_data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            raise HTTPException(status_code=e.code, detail=f"Jules API Error while fetching session: {e.read().decode('utf-8')}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch session metadata: {str(e)}")
            
        if not repo:
            source = session_data.get("sourceContext", {}).get("source", "")
            if source.startswith("sources/github/"):
                repo = source.replace("sources/github/", "")
            else:
                raise HTTPException(status_code=400, detail=f"Could not resolve repository from session source: {source}")
                
        if not pr_number:
            # Look through outputs to find the pull request number
            outputs = session_data.get("outputs", [])
            for out in outputs:
                if "pullRequest" in out:
                    pr = out["pullRequest"]
                    pr_url = pr.get("url", "")
                    match = re.search(r"pull/(\d+)", pr_url)
                    if match:
                        pr_number = int(match.group(1))
                        break
            if not pr_number:
                raise HTTPException(status_code=400, detail="Could not find an active Pull Request in session outputs.")
                
    # 2. Call GitHub Pull Request Merge API
    gh_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Antigravity-Orchestrator",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    else:
        raise HTTPException(status_code=400, detail="GitHub token not configured in settings.")
        
    payload = json.dumps({
        "commit_title": f"Merge pull request #{pr_number} from Jules session",
        "merge_method": "merge"
    }).encode("utf-8")
    
    req = urllib.request.Request(gh_url, data=payload, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            invalidate_sessions_cache()
            return {"success": True, "merged": True, "message": res_data.get("message", "Pull request merged successfully")}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='replace')
        raise HTTPException(status_code=e.code, detail=f"GitHub API Error: {err_msg or e.reason}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to merge pull request: {str(e)}")

@app.post("/api/jules/sessions/{session_id}/monitor")
def monitor_jules_session(session_id: str):
    try:
        script_path = os.path.join(SCRATCH_DIR, "poll_session.py")
        import sys
        subprocess.Popen([sys.executable, script_path, session_id])
        return {"success": True, "message": f"Started background monitoring for session {session_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start monitor: {str(e)}")

@app.post("/api/jules/sessions/delete")
def delete_jules_session(input_data: DeleteSessionInput):
    try:
        session_id = input_data.session_id
        purge = input_data.purge_local_cache or False
        
        deleted_list = read_json(DELETED_SESSIONS_FILE, [])
        deleted_db = read_json(DELETED_SESSIONS_DB_FILE, {})
        
        settings = read_json(SETTINGS_FILE, {})
        api_key = settings.get("jules")

        # Check if the session is currently active
        session_state = "UNKNOWN"
        if api_key:
            import urllib.request
            import urllib.error
            url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
            req = urllib.request.Request(url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    session_raw = json.loads(resp.read().decode('utf-8'))
                    session_state = session_raw.get("state", "UNKNOWN").upper()
            except urllib.error.HTTPError as he:
                if he.code == 404:
                    session_state = "DELETED_REMOTELY"
                else:
                    print("Error checking session state during delete:", he)
            except Exception as fe:
                print("Error checking session state during delete:", fe)

        # If session is active and confirm_active_delete is not set, reject deletion
        inactive_states = ["SUCCEEDED", "COMPLETED", "FAILED", "CANCELLED", "DELETED_REMOTELY", "UNKNOWN"]
        if session_state not in inactive_states and not input_data.confirm_active_delete:
            raise HTTPException(
                status_code=400,
                detail=f"WARNING_ACTIVE_SESSION: Session {session_id} is currently active ({session_state}). Deleting it will abort the active task. Please confirm deletion."
            )
        
        # 1. Fetch metadata before remote deletion (only if NOT purging, and not already cached)
        if not purge and api_key and session_id not in deleted_db:
            try:
                # 1.1 Fetch details
                import urllib.request
                url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
                req = urllib.request.Request(url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
                session_raw = None
                with urllib.request.urlopen(req, timeout=10) as resp:
                    session_raw = json.loads(resp.read().decode('utf-8'))
                
                # 1.2 Fetch activities / logs
                act_url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}/activities"
                act_req = urllib.request.Request(act_url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
                activities_raw = []
                with urllib.request.urlopen(act_req, timeout=10) as resp:
                    act_data = json.loads(resp.read().decode('utf-8'))
                    activities_raw = act_data.get("activities", [])
                
                # Parse logs
                logs = []
                for act in activities_raw:
                    time_str = act.get("createTime", "")
                    time_part = time_str.split("T")[-1][:8] if "T" in time_str else ""
                    prefix = f"[{time_part}]" if time_part else ""
                    if "agentMessaged" in act and "agentMessage" in act["agentMessaged"]:
                        logs.append(f"{prefix} Jules: {act['agentMessaged']['agentMessage']}")
                    elif "userMessaged" in act and "userMessage" in act["userMessaged"]:
                        logs.append(f"{prefix} User: {act['userMessaged']['userMessage']}")
                    elif "progressUpdated" in act:
                        title = act["progressUpdated"].get("title", "")
                        desc = act["progressUpdated"].get("description", "")
                        logs.append(f"{prefix} Progress: {title}" + (f" - {desc}" if desc else ""))
                    elif "planGenerated" in act:
                        logs.append(f"{prefix} Plan Generated.")
                    elif "planApproved" in act:
                        logs.append(f"{prefix} Plan Approved.")
                if not logs:
                    logs.append("[info] No activities logged yet.")
                
                # Parse plan
                plan_steps = []
                for act in activities_raw:
                    if "planGenerated" in act and "plan" in act["planGenerated"]:
                        plan_steps = act["planGenerated"]["plan"].get("steps", [])
                        break
                
                # 1.3 Pull patch using jules CLI (which requires repo directory context, or we can just pull patch)
                patch_content = ""
                # Attempt to find the local project matching this session
                source = session_raw.get("sourceContext", {}).get("source", "") if session_raw else ""
                repo_name = ""
                if source.startswith("sources/github/"):
                    repo_name = source.replace("sources/github/", "").split("/")[-1]
                
                projects = read_json(PROJECTS_FILE, [])
                proj = next((p for p in projects if p["name"].lower() == repo_name.lower()), None)
                cwd = proj["path"] if (proj and os.path.exists(proj["path"])) else SCRATCH_DIR
                
                env = os.environ.copy()
                env["JULES_API_KEY"] = api_key
                env["CI"] = "true"
                env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
                try:
                    result = subprocess.run(
                        [JULES_BIN, "remote", "pull", "--session", session_id],
                        cwd=cwd,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        env=env,
                        shell=True,
                        timeout=15
                    )
                    if result.returncode == 0:
                        patch_content = result.stdout
                except Exception as pe:
                    print("Patch pull error during delete pre-fetch:", pe)
                
                # Cache it
                repo = source.replace("sources/github/", "") if source.startswith("sources/github/") else "Other/Unmapped Repos"
                deleted_db[session_id] = {
                    "id": session_id,
                    "task": session_raw.get("title") or session_raw.get("prompt") or "No Title",
                    "repo": repo,
                    "status": session_raw.get("state", "COMPLETED").upper(),
                    "prompt": session_raw.get("prompt", ""),
                    "logs": logs,
                    "plan": {"steps": plan_steps},
                    "patch": patch_content,
                    "raw": session_raw
                }
                write_json(DELETED_SESSIONS_DB_FILE, deleted_db)
            except Exception as fe:
                print("Failed to pre-fetch session details before deleting:", fe)
        
        # 2. Call remote delete (always attempt)
        if api_key:
            import urllib.request
            delete_url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
            req = urllib.request.Request(
                delete_url,
                headers={"x-goog-api-key": api_key, "Accept": "application/json"},
                method="DELETE"
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    response.read()
            except Exception as e:
                print("Failed to delete session remotely in delete API:", e)
                
        # 3. Post-delete local cache adjustments
        invalidate_sessions_cache()
        if purge:
            if session_id in deleted_list:
                deleted_list.remove(session_id)
                write_json(DELETED_SESSIONS_FILE, deleted_list)
            if session_id in deleted_db:
                del deleted_db[session_id]
                write_json(DELETED_SESSIONS_DB_FILE, deleted_db)
            return {"success": True, "message": f"Session {session_id} permanently deleted remotely and purged from local history cache."}
        else:
            if session_id not in deleted_list:
                deleted_list.append(session_id)
                write_json(DELETED_SESSIONS_FILE, deleted_list)
            return {"success": True, "message": f"Session {session_id} deleted remotely and saved in history cache."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# API: Cross-Repo Knowledge Base Patterns
@app.get("/api/knowledge/patterns")
def get_knowledge_patterns():
    # Scan all project dirs for .md files in their root or /docs directory
    # Aggregates generic styling/helper titles
    projects = read_json(PROJECTS_FILE, [])
    patterns = []
    
    # We populate with standard design system guidelines
    patterns.append({
        "name": "Glassmorphism Card styling",
        "usage_count": len(projects),
        "last_sync": "Just now",
        "code": "/* Glassmorphism CSS styling */\n.glass-card {\n  background: rgba(15, 23, 42, 0.4);\n  backdrop-filter: blur(12px);\n  border: 1px solid rgba(70, 69, 84, 0.6);\n}"
    })
    
    patterns.append({
        "name": "OAuth2 FastAPI Handler",
        "usage_count": 2,
        "last_sync": "1 hour ago",
        "code": "# Generic OAuth2 Security Helper\nfrom fastapi.security import OAuth2PasswordBearer\noauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')"
    })
    
    return patterns

# Parser helper for jules output
def parse_jules_sessions(output: str) -> List[dict]:
    sessions = []
    lines = output.strip().split("\n")
    for line in lines[1:]: # Skip header
        parts = re.split(r'\s{2,}', line.strip())
        if len(parts) >= 2:
            id_val = parts[0]
            task_val = parts[1]
            repo_val = "evilspyboy/Orbits"
            last_active_val = "Unknown"
            status_val = "UNKNOWN"
            
            if len(parts) >= 3:
                repo_val = parts[2]
            
            if len(parts) == 4:
                val = parts[3]
                is_time = any(x in val.lower() for x in ["ago", "day", "hour", "min", "sec", "now", "yesterday"])
                if is_time:
                    last_active_val = val
                    status_val = "UNKNOWN"
                else:
                    status_val = val
            elif len(parts) >= 5:
                last_active_val = parts[3]
                status_val = parts[4]
                
            sessions.append({
                "id": id_val,
                "task": task_val,
                "repo": repo_val,
                "status": status_val.upper(),
                "logs": [f"Last active: {last_active_val}"]
            })
    return sessions

# API: Instructions Log
class InstructionInput(BaseModel):
    id: Optional[str] = None
    project: str
    instruction: str
    status: Optional[str] = "RUNNING"
    jules_session_id: Optional[str] = None

@app.get("/api/instructions")
def get_instructions():
    return read_json(INSTRUCTIONS_FILE, [])

@app.post("/api/instructions")
def save_instruction(input_data: InstructionInput):
    instructions = read_json(INSTRUCTIONS_FILE, [])
    data = input_data.model_dump()
    if data.get("id"):
        idx = next((i for i, inst in enumerate(instructions) if inst["id"] == data["id"]), -1)
        if idx != -1:
            instructions[idx].update({k: v for k, v in data.items() if v is not None})
        else:
            instructions.append(data)
    else:
        import uuid
        data["id"] = "inst_" + uuid.uuid4().hex[:6]
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        instructions.append(data)
    write_json(INSTRUCTIONS_FILE, instructions)
    return {"success": True}


@app.post("/api/jules/sessions")
def create_session(input_data: CreateSessionInput):
    settings = read_json(SETTINGS_FILE, {})
    env = os.environ.copy()
    if settings.get("jules"):
        env["JULES_API_KEY"] = settings["jules"]
    env["CI"] = "true"
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    
    try:
        result = subprocess.run(
            [JULES_BIN, "new", "--repo", input_data.repo, input_data.task],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=env,
            shell=False
        )
        if result.returncode == 0:
            invalidate_sessions_cache()
            return {"success": True, "message": result.stdout.strip()}
        else:
            raise HTTPException(status_code=500, detail=result.stderr or result.stdout)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Antigravity Orchestrator Backend")
    parser.add_argument("--mcp", action="store_true", help="Run as Model Context Protocol (MCP) server")
    args = parser.parse_args()
    
    if args.mcp:
        import asyncio
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent

        mcp_server = Server("antigravity-orchestrator")

        @mcp_server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="list_sessions",
                    description="List all active and completed Jules sessions across all projects",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "show_deleted": {
                                "type": "boolean",
                                "description": "Optional: If true, includes deleted sessions from the local history cache."
                            },
                            "show_archived": {
                                "type": "boolean",
                                "description": "Optional: If true, includes archived sessions."
                            },
                            "repo_filter": {
                                "type": "string",
                                "description": "Optional: Repository name filter (case-insensitive substring match)."
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Optional: Maximum number of sessions to return."
                            },
                            "sort_ascending": {
                                "type": "boolean",
                                "description": "Optional: If true, returns oldest sessions first. If false, returns newest first."
                            }
                        }
                    }
                ),
                Tool(
                    name="get_git_status",
                    description="Get detailed branch comparison (ahead/behind counts), local checkout status (local_project_registered will be false if no local copy exists on the user's system), and Pull Request statuses for a given session ID.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session (e.g. 5509702878084354010)"
                            }
                        },
                        "required": ["session_id"]
                    }
                ),
                Tool(
                    name="get_session_logs",
                    description="Fetch full activity logs and conversation history for a given session ID.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session"
                            }
                        },
                        "required": ["session_id"]
                    }
                ),
                Tool(
                    name="create_session",
                    description="Create a new Jules session for a specific GitHub repository and task description.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "repo": {
                                "type": "string",
                                "description": "The GitHub repository in 'owner/repo' format (e.g. 'evilspyboy/SignVerify')"
                            },
                            "task": {
                                "type": "string",
                                "description": "The task prompt or instructions for Jules"
                            }
                        },
                        "required": ["repo", "task"]
                    }
                ),
                Tool(
                    name="delete_session",
                    description="Delete a Jules session remotely and optionally purge its local history cache.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session"
                            },
                            "purge_local_cache": {
                                "type": "boolean",
                                "description": "If true, permanently deletes the session from the local history cache. If false, only deletes it remotely and keeps a local history cache."
                            },
                            "confirm_active_delete": {
                                "type": "boolean",
                                "description": "If true, allows deleting active/running sessions. If false, deleting active sessions will fail with a warning."
                            }
                        },
                        "required": ["session_id"]
                    }
                ),
                Tool(
                    name="list_repos",
                    description="List all repositories registered with Jules",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="approve_plan",
                    description="Approve the proposed engineering plan for a session so Jules starts coding",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session"
                            }
                        },
                        "required": ["session_id"]
                    }
                ),
                Tool(
                    name="apply_patch",
                    description="Pulls and applies the completed session patch to the local registered project path",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session"
                            },
                            "project": {
                                "type": "string",
                                "description": "Optional name of the local project if it doesn't match the repository name"
                            }
                        },
                        "required": ["session_id"]
                    }
                ),
                Tool(
                    name="get_session_plan",
                    description="Fetches the list of plan steps generated for a given session",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session"
                            }
                        },
                        "required": ["session_id"]
                    }
                ),
                Tool(
                    name="get_session_details",
                    description="Fetch the complete details of a specific Jules session by its ID, including the repository name, short title, and the full, uncut original instruction/prompt text.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session"
                            }
                        },
                        "required": ["session_id"]
                    }
                ),
                Tool(
                    name="get_auth_status",
                    description="Checks whether the local Jules CLI is logged in",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="jules_login",
                    description="Launches the interactive login flow for Jules in a new command shell window",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="list_stitch_drafts",
                    description="Scans the stitch directory for mock HTML UI designs",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Optional name of project to filter drafts (currently ignored)"
                            }
                        }
                    }
                ),
                Tool(
                    name="generate_stitch_stub",
                    description="Generates a mock design component from a prompt",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "Text describing the UI component to generate"
                            },
                            "project": {
                                "type": "string",
                                "description": "Local project name to generate under"
                            }
                        },
                        "required": ["prompt", "project"]
                    }
                ),
                Tool(
                    name="export_stitch_design",
                    description="Exports a design layout to a path in one of your registered projects",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Local target project name"
                            },
                            "target_dir": {
                                "type": "string",
                                "description": "Subdirectory path in project to copy code to (e.g. 'src/components')"
                            },
                            "format": {
                                "type": "string",
                                "description": "Export format ('react' or 'html')"
                            }
                        },
                        "required": ["project", "target_dir", "format"]
                    }
                ),
                Tool(
                    name="log_instruction",
                    description="Logs or updates a high-level task/instruction in the orchestrator",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Name of the project repository (e.g. 'Orbits')"
                            },
                            "instruction": {
                                "type": "string",
                                "description": "High level task details/prompt requested"
                            },
                            "id": {
                                "type": "string",
                                "description": "Optional unique instruction ID (e.g. 'inst_xxxxxx') to update an existing task"
                            },
                            "status": {
                                "type": "string",
                                "description": "Optional status: 'RUNNING', 'COMPLETED', 'FAILED', 'PLANNING'"
                            },
                            "jules_session_id": {
                                "type": "string",
                                "description": "Optional unique Jules session ID linked to the task"
                            }
                        },
                        "required": ["project", "instruction"]
                    }
                ),
                Tool(
                    name="get_instructions",
                    description="Retrieves the list of active/logged instructions",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="send_session_message",
                    description="Send a chat message or feedback to an active Jules session to answer a question or provide further instructions.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session"
                            },
                            "message": {
                                "type": "string",
                                "description": "The message or feedback prompt to send to the Jules agent"
                            }
                        },
                        "required": ["session_id", "message"]
                    }
                ),
                Tool(
                    name="get_repo_file",
                    description="Read the contents of a file (such as a specification markdown sheet, README, or source code file) from a remote GitHub repository. Requires either a direct repository path ('owner/repo') OR a session_id to resolve the repository automatically.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "The path to the file within the repository (e.g. 'README.md' or 'docs/PLAN.md')"
                            },
                            "repo": {
                                "type": "string",
                                "description": "Optional: The GitHub repository in 'owner/repo' format (e.g. 'evilspyboy/SignVerify')"
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Optional: The unique ID of the Jules session. If provided and 'repo' is omitted, the repository will be automatically resolved from the session context."
                            }
                        },
                        "required": ["path"]
                    }
                ),
                Tool(
                    name="merge_pr",
                    description="Merge a pull request. Requires a session_id (which automatically resolves the repository and PR number from the session metadata) OR a repo name and pr_number.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Optional: The unique ID of the Jules session. Resolves repo and pr_number automatically."
                            },
                            "repo": {
                                "type": "string",
                                "description": "Optional: The GitHub repository in 'owner/repo' format."
                            },
                            "pr_number": {
                                "type": "integer",
                                "description": "Optional: The Pull Request number."
                            }
                        }
                    }
                )
            ]


        @mcp_server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            async def run_with_timeout(func, *args, timeout=15.0, **kwargs):
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(func, *args, **kwargs),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    raise Exception(f"Operation timed out after {timeout} seconds")

            if name == "list_sessions":
                show_deleted = arguments.get("show_deleted", False)
                show_archived = arguments.get("show_archived", False)
                repo_filter = arguments.get("repo_filter")
                limit = arguments.get("limit")
                sort_ascending = arguments.get("sort_ascending", False)
                try:
                    sessions = await run_with_timeout(
                        get_jules_sessions,
                        project="",
                        show_deleted=show_deleted,
                        show_archived=show_archived,
                        repo_filter=repo_filter,
                        limit=limit,
                        sort_ascending=sort_ascending,
                        timeout=300.0 if show_archived else 30.0
                    )
                    return [TextContent(type="text", text=json.dumps(sessions, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error listing sessions: {str(e)}")]
            elif name == "get_git_status":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    status = await run_with_timeout(get_jules_git_status, session_id)
                    return [TextContent(type="text", text=json.dumps(status, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting git status: {str(e)}")]
            elif name == "get_session_logs":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    logs = await run_with_timeout(get_jules_logs, session_id)
                    return [TextContent(type="text", text=json.dumps(logs, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting session logs: {str(e)}")]
            elif name == "create_session":
                repo = arguments.get("repo")
                task = arguments.get("task")
                if not repo or not task:
                    return [TextContent(type="text", text="Error: repo and task are required")]
                try:
                    settings = read_json(SETTINGS_FILE, {})
                    env = os.environ.copy()
                    if settings.get("jules"):
                        env["JULES_API_KEY"] = settings["jules"]
                    env["CI"] = "true"
                    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
                    
                    def run_create():
                        return subprocess.run(
                            [JULES_BIN, "new", "--repo", repo, task],
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            text=True,
                            env=env,
                            shell=False
                        )
                    result = await run_with_timeout(run_create, timeout=30.0)
                    if result.returncode == 0:
                        invalidate_sessions_cache()
                        return [TextContent(type="text", text=f"Success: {result.stdout.strip()}")]
                    else:
                        return [TextContent(type="text", text=f"Error (exit code {result.returncode}): {result.stderr or result.stdout}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error creating session: {str(e)}")]
            elif name == "delete_session":
                session_id = arguments.get("session_id")
                purge = arguments.get("purge_local_cache", False)
                confirm_active = arguments.get("confirm_active_delete", False)
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    res = await run_with_timeout(
                        delete_jules_session,
                        DeleteSessionInput(session_id=session_id, purge_local_cache=purge, confirm_active_delete=confirm_active)
                    )
                    return [TextContent(type="text", text=res.get("message", "Success"))]
                except HTTPException as he:
                    return [TextContent(type="text", text=f"Error: {he.detail}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error deleting session: {str(e)}")]
            elif name == "list_repos":
                try:
                    repos = await run_with_timeout(get_jules_repos)
                    return [TextContent(type="text", text=json.dumps(repos, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error listing repos: {str(e)}")]
            elif name == "approve_plan":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    res = await run_with_timeout(approve_jules_plan, session_id)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error approving plan: {str(e)}")]
            elif name == "apply_patch":
                session_id = arguments.get("session_id")
                project = arguments.get("project")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    res = await run_with_timeout(apply_jules_patch, session_id, ApplyInput(project=project) if project else None, timeout=45.0)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error applying patch: {str(e)}")]
            elif name == "get_session_plan":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    res = await run_with_timeout(get_jules_plan, session_id)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting session plan: {str(e)}")]
            elif name == "get_session_details":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    # Check if session is deleted locally
                    db = read_json(DELETED_SESSIONS_DB_FILE, {})
                    if session_id in db:
                        cached = db[session_id]
                        details = {
                            "id": session_id,
                            "repo": cached.get("repo", ""),
                            "title": cached.get("task", "No Title"),
                            "description": cached.get("prompt", ""),
                            "prompt": cached.get("prompt", ""),
                            "state": cached.get("status", "UNKNOWN"),
                            "starting_branch": cached.get("raw", {}).get("sourceContext", {}).get("githubRepoContext", {}).get("startingBranch", "main") or "main",
                            "raw": cached.get("raw", {})
                        }
                        return [TextContent(type="text", text=json.dumps(details, indent=2))]
                        
                    def fetch_details():
                        settings = read_json(SETTINGS_FILE, {})
                        api_key = settings.get("jules")
                        if not api_key:
                            raise Exception("Jules API key not configured")
                        import urllib.request
                        url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
                        req = urllib.request.Request(
                            url,
                            headers={"x-goog-api-key": api_key, "Accept": "application/json"}
                        )
                        with urllib.request.urlopen(req, timeout=15) as response:
                            session_data = json.loads(response.read().decode('utf-8'))
                            repo = "Other/Unmapped Repos"
                            source = session_data.get("sourceContext", {}).get("source", "")
                            if source.startswith("sources/github/"):
                                repo = source.replace("sources/github/", "")
                            return {
                                "id": session_data.get("id"),
                                "repo": repo,
                                "title": session_data.get("title", "No Title"),
                                "description": session_data.get("prompt", ""),
                                "prompt": session_data.get("prompt", ""),
                                "state": session_data.get("state", "UNKNOWN"),
                                "starting_branch": session_data.get("sourceContext", {}).get("githubRepoContext", {}).get("startingBranch", "main") or "main",
                                "raw": session_data
                            }
                    details = await run_with_timeout(fetch_details)
                    return [TextContent(type="text", text=json.dumps(details, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting session details: {str(e)}")]
            elif name == "get_auth_status":
                try:
                    res = await run_with_timeout(get_jules_auth_status)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting auth status: {str(e)}")]
            elif name == "jules_login":
                try:
                    res = await run_with_timeout(jules_login)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error running jules login: {str(e)}")]
            elif name == "list_stitch_drafts":
                project = arguments.get("project", "")
                try:
                    res = await run_with_timeout(get_stitch_drafts, project=project)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error listing stitch drafts: {str(e)}")]
            elif name == "generate_stitch_stub":
                prompt = arguments.get("prompt")
                project = arguments.get("project")
                if not prompt or not project:
                    return [TextContent(type="text", text="Error: prompt and project are required")]
                try:
                    res = await run_with_timeout(generate_ui_stub, GenerateUIInput(prompt=prompt, project=project))
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error generating UI stub: {str(e)}")]
            elif name == "export_stitch_design":
                project = arguments.get("project")
                target_dir = arguments.get("target_dir")
                fmt = arguments.get("format")
                if not project or not target_dir or not fmt:
                    return [TextContent(type="text", text="Error: project, target_dir and format are required")]
                try:
                    res = await run_with_timeout(export_stitch_design, ExportInput(project=project, target_dir=target_dir, format=fmt))
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error exporting stitch design: {str(e)}")]
            elif name == "log_instruction":
                project = arguments.get("project")
                instruction = arguments.get("instruction")
                inst_id = arguments.get("id")
                status = arguments.get("status")
                jules_session_id = arguments.get("jules_session_id")
                if not project or not instruction:
                    return [TextContent(type="text", text="Error: project and instruction are required")]
                try:
                    res = await run_with_timeout(save_instruction, InstructionInput(
                        id=inst_id,
                        project=project,
                        instruction=instruction,
                        status=status,
                        jules_session_id=jules_session_id
                    ))
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error logging instruction: {str(e)}")]
            elif name == "get_instructions":
                try:
                    res = await run_with_timeout(get_instructions)
                    return [TextContent(type="text", text=json.dumps(res, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting instructions: {str(e)}")]
            elif name == "send_session_message":
                session_id = arguments.get("session_id")
                message = arguments.get("message")
                if not session_id or not message:
                    return [TextContent(type="text", text="Error: session_id and message are required")]
                try:
                    res = await run_with_timeout(send_jules_message, session_id, MessageInput(prompt=message))
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error sending message: {str(e)}")]
            elif name == "get_repo_file":
                path = arguments.get("path")
                repo = arguments.get("repo")
                session_id = arguments.get("session_id")
                if not path:
                    return [TextContent(type="text", text="Error: path is required")]
                try:
                    res = await run_with_timeout(get_repo_file_api, RepoFileInput(path=path, repo=repo, session_id=session_id))
                    return [TextContent(type="text", text=res.get("content", ""))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting repo file: {str(e)}")]
            elif name == "merge_pr":
                session_id = arguments.get("session_id")
                repo = arguments.get("repo")
                pr_number = arguments.get("pr_number")
                try:
                    res = await run_with_timeout(merge_pull_request_api, MergePRInput(session_id=session_id, repo=repo, pr_number=pr_number))
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error merging pull request: {str(e)}")]
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]


        async def run_mcp_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())

        asyncio.run(run_mcp_stdio())
    else:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8000)
