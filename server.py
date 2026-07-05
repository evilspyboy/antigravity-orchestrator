import os
import sys
import re
import json
import shutil
import subprocess
import asyncio
import urllib.request
import urllib.error
from datetime import datetime
from typing import List, Optional
import sys
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(background_poll_sessions())
    yield

if "--mcp" in sys.argv:
    # Dummy mock FastAPI app so we don't import fastapi/uvicorn
    class DummyApp:
        def get(self, *args, **kwargs):
            return lambda func: func
        def post(self, *args, **kwargs):
            return lambda func: func
        def put(self, *args, **kwargs):
            return lambda func: func
        def delete(self, *args, **kwargs):
            return lambda func: func
    app = DummyApp()
    
    class DummyHTTPException(Exception):
        def __init__(self, status_code, detail=None):
            self.status_code = status_code
            self.detail = detail
        def __str__(self):
            return f"HTTP {self.status_code}: {self.detail}"
            
    HTTPException = DummyHTTPException
    HTMLResponse = None
    FastAPI = None
    
    # Dummy mock Pydantic BaseModel to store parsed arguments
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__
else:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel
    app = FastAPI(title="Antigravity Orchestrator Backend", lifespan=lifespan)

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

class MergeLocalInput(BaseModel):
    target_branch: Optional[str] = None

class CommitPushInput(BaseModel):
    project: str
    commit_message: str

class SyncLocalInput(BaseModel):
    project: str
    base_branch: Optional[str] = "main"
    delete_branch: Optional[str] = None

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

class TestNotificationInput(BaseModel):
    conv_id: str
    title: str
    message: str

@app.post("/api/test_notification")
def test_notification(input_data: TestNotificationInput):
    home_dir = os.path.expanduser("~")
    agentapi_exe = os.path.join(home_dir, "AppData", "Local", "Programs", "Antigravity IDE", "resources", "app", "extensions", "antigravity", "bin", "language_server_windows_x64.exe")
    if not os.path.exists(agentapi_exe):
        return {"error": "agentapi binary not found"}
        
    clean_content = input_data.message.replace("\n", " ")
    cli_content = f"[{input_data.title}] - {clean_content}"
    cmd = [agentapi_exe, "agentapi", "send-message", str(input_data.conv_id), cli_content]
    
    env = os.environ.copy()
    try:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "capture_output": True,
            "text": True,
            "env": env,
            "timeout": 15
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            
        res = subprocess.run(cmd, **kwargs)
        if res.returncode == 0:
            return {"success": True, "output": res.stdout, "workspace": "Current Workspace"}
        else:
            return {"error": f"Failed with code {res.returncode}. Output: {res.stdout} {res.stderr}"}
    except Exception as e:
        return {"error": str(e)}

# API: Projects
@app.get("/api/projects")
def get_projects():
    projects = read_json(PROJECTS_FILE, [])
    # Sync git branches on retrieval
    for p in projects:
        if os.path.exists(p["path"]):
            p["branch"] = get_git_branch(p["path"])
            p["connected"] = True
            # Dynamically resolve GitHub repository
            try:
                import subprocess
                remote_url = subprocess.check_output(
                    ["git", "config", "--get", "remote.origin.url"],
                    cwd=p["path"],
                    stderr=subprocess.DEVNULL,
                    text=True
                ).strip()
                r = ""
                if remote_url:
                    import re
                    match = re.search(r"(?:github\.com[:/])([^/]+/[^/]+?)(?:\.git)?$", remote_url)
                    if match:
                        r = match.group(1)
                p["githubRepo"] = r
            except Exception:
                p["githubRepo"] = ""
        else:
            p["connected"] = False
            p["githubRepo"] = ""
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
def map_cli_status_to_api_state(cli_status: str, current_api_state: str) -> str:
    cli_status_lower = cli_status.lower().strip()
    if not cli_status_lower:
        return current_api_state
    
    if "awaiting plan" in cli_status_lower:
        return "AWAITING_PLAN_APPROVAL"
    elif "planning" in cli_status_lower:
        return "PLANNING"
    elif "feedback" in cli_status_lower or "awaiting user" in cli_status_lower:
        return "AWAITING_USER_FEEDBACK"
    elif "running" in cli_status_lower:
        return "IN_PROGRESS"
    elif "completed" in cli_status_lower or "succeeded" in cli_status_lower:
        return "COMPLETED"
    elif "failed" in cli_status_lower:
        return "FAILED"
    elif "cancelled" in cli_status_lower:
        return "CANCELLED"
    
    return current_api_state

def get_cli_session_statuses() -> dict:
    settings = read_json(SETTINGS_FILE, {})
    env = os.environ.copy()
    if settings.get("jules"):
        env["JULES_API_KEY"] = settings["jules"]
    env["CI"] = "true"
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    
    statuses = {}
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
            lines = result.stdout.splitlines()
            for line in lines:
                if not line.strip():
                    continue
                parts = re.split(r'\s{2,}', line.strip())
                if not parts:
                    continue
                sid = parts[0]
                if not sid.isdigit():
                    continue
                
                status = ""
                if len(parts) >= 5:
                    status = parts[4]
                statuses[sid] = status
    except Exception as e:
        print(f"Error getting CLI session statuses: {e}", file=sys.stderr)
    return statuses


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
            # 30 seconds cache validity
            if time.time() - cache_time < 30:
                cache_valid = True
        except Exception as ce:
            print("Error reading cache:", ce, file=sys.stderr)
            
    if cache_valid and "sessions" in cached_data:
        parsed_all = cached_data["sessions"]
        print("Using cached Jules sessions", file=sys.stderr)
    else:
        print("Fetching fresh sessions from Jules API", file=sys.stderr)
        cli_statuses = get_cli_session_statuses()
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
                            
                            # Override status if CLI reports different status
                            if sid in cli_statuses:
                                cli_status = cli_statuses[sid]
                                new_state = map_cli_status_to_api_state(cli_status, state)
                                if new_state != state:
                                    print(f"Overriding state for session {sid} from {state} to {new_state} (CLI: {cli_status})", file=sys.stderr)
                                    state = new_state
                                    s["state"] = new_state
                            
                            status = state
                            if state == "AWAITING_PLAN_APPROVAL":
                                status = "AWAITING PLAN APPROVAL"
                            elif state == "AWAITING_USER_FEEDBACK" and not s.get("archived", False):
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
 
@app.post("/api/jules/sessions/{session_id}/checkout")
def checkout_jules_branch(session_id: str):
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
        
    # Fetch session details to get the remote feature branch (head_ref)
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
        repo_name = repo_parts[-1]
        
    projects_list = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects_list if (
        p["name"].lower() == repo_name.lower() or
        p["path"].lower().replace("\\", "/").endswith("/" + repo_name.lower())
    )), None)
    
    target_cwd = proj["path"] if (proj and os.path.exists(proj["path"])) else None
    if not target_cwd:
        raise HTTPException(status_code=400, detail=f"Local project directory for repository '{repo_name or 'unknown'}' not found. Please register and clone it first.")
        
    # Find head branch from outputs (PR or changeset)
    head_ref = None
    outputs = session_data.get("outputs", [])
    for out in outputs:
        if "pullRequest" in out and "headRef" in out["pullRequest"]:
            head_ref = out["pullRequest"]["headRef"]
            break
            
    if not head_ref:
        for out in outputs:
            if "changeSet" in out:
                head_ref = f"feat-{repo_name.lower()}-base-{session_id}"
                break
                
    if not head_ref:
        head_ref = f"feat-{repo_name.lower()}-base-{session_id}"
        
    try:
        # 1. Fetch remote branches (wrap in try/except to avoid blocking if credentials/network hangs)
        try:
            subprocess.run(["git", "fetch", "origin"], cwd=target_cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception as fe:
            print(f"Warning: git fetch origin failed or timed out: {fe}", file=sys.stderr)
        
        # 2. Checkout the branch
        res = subprocess.run(["git", "checkout", head_ref], cwd=target_cwd, capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            # Try to checkout origin/head_ref explicitly as a new branch
            res_b = subprocess.run(["git", "checkout", "-b", head_ref, f"origin/{head_ref}"], cwd=target_cwd, capture_output=True, text=True, timeout=15)
            if res_b.returncode != 0:
                # Fallback: remote branch doesn't exist yet (not published).
                # Create a local branch and pull the changeset directly from the Jules API.
                res_local = subprocess.run(["git", "checkout", "-b", head_ref], cwd=target_cwd, capture_output=True, text=True, timeout=15)
                if res_local.returncode != 0:
                    subprocess.run(["git", "checkout", head_ref], cwd=target_cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                
                env = os.environ.copy()
                if api_key:
                    env["JULES_API_KEY"] = api_key
                env["CI"] = "true"
                env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
                
                res_pull = subprocess.run(
                    [JULES_BIN, "remote", "pull", "--session", session_id, "--apply"],
                    cwd=target_cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if res_pull.returncode != 0:
                    raise HTTPException(status_code=500, detail=f"Jules remote pull failed: {res_pull.stderr or res_pull.stdout}")
                
        invalidate_sessions_cache()
        return {"success": True, "message": f"Checked out branch '{head_ref}' and applied Jules changes locally.", "branch": head_ref}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/sessions/{session_id}/merge-local")
def merge_local_branch(session_id: str, input_data: MergeLocalInput):
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
        
    # Fetch session details to get the source repo and base branch (base_ref)
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
        repo_name = repo_parts[-1]
        
    projects_list = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects_list if (
        p["name"].lower() == repo_name.lower() or
        p["path"].lower().replace("\\", "/").endswith("/" + repo_name.lower())
    )), None)
    
    target_cwd = proj["path"] if (proj and os.path.exists(proj["path"])) else None
    if not target_cwd:
        raise HTTPException(status_code=400, detail=f"Local project directory for repository '{repo_name or 'unknown'}' not found.")
        
    base_ref = session_data.get("sourceContext", {}).get("githubRepoContext", {}).get("startingBranch", "main") or "main"
    target_branch = input_data.target_branch or base_ref
    
    try:
        # Fetch first to ensure we have target branch updates
        subprocess.run(["git", "fetch", "origin", target_branch], cwd=target_cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        
        # Run merge
        res = subprocess.run(["git", "merge", f"origin/{target_branch}"], cwd=target_cwd, capture_output=True, text=True, timeout=20)
        
        if res.returncode == 0:
            invalidate_sessions_cache()
            return {"success": True, "conflict": False, "message": f"Successfully merged origin/{target_branch} into current branch."}
        else:
            # Check for unmerged files (conflict detection)
            conf_res = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=target_cwd,
                capture_output=True,
                text=True,
                timeout=5
            )
            conflicts = [line.strip() for line in conf_res.stdout.strip().split("\n") if line.strip()]
            if conflicts:
                return {
                    "success": False,
                    "conflict": True,
                    "conflicted_files": conflicts,
                    "message": "Merge conflicts detected. Please resolve conflict markers in the listed files."
                }
            else:
                raise HTTPException(status_code=500, detail=res.stderr or res.stdout)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/sessions/commit-push")
def git_commit_push(input_data: CommitPushInput):
    projects_list = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects_list if p["name"] == input_data.project), None)
    
    target_cwd = proj["path"] if (proj and os.path.exists(proj["path"])) else None
    if not target_cwd:
        raise HTTPException(status_code=400, detail=f"Local project directory for project '{input_data.project}' not found.")
        
    try:
        branch_res = subprocess.run(["git", "branch", "--show-current"], cwd=target_cwd, capture_output=True, text=True, timeout=5)
        if branch_res.returncode != 0 or not branch_res.stdout.strip():
            raise HTTPException(status_code=500, detail="Could not determine current active git branch.")
        branch = branch_res.stdout.strip()
        
        subprocess.run(["git", "add", "."], cwd=target_cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        
        res_commit = subprocess.run(["git", "commit", "-m", input_data.commit_message], cwd=target_cwd, capture_output=True, text=True, timeout=10)
        if res_commit.returncode != 0:
            if "nothing to commit" in res_commit.stdout.lower() or "nothing to commit" in res_commit.stderr.lower():
                pass
            else:
                raise HTTPException(status_code=500, detail=res_commit.stderr or res_commit.stdout)
                
        settings = read_json(SETTINGS_FILE, {})
        github_token = settings.get("github")
        
        res_push = subprocess.run(["git", "push", "origin", branch], cwd=target_cwd, capture_output=True, text=True, timeout=20)
        if res_push.returncode != 0 and github_token:
            get_url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=target_cwd, capture_output=True, text=True, timeout=5)
            if get_url.returncode == 0:
                url = get_url.stdout.strip()
                if url.startswith("https://github.com/"):
                    auth_url = url.replace("https://github.com/", f"https://{github_token}@github.com/")
                    res_push = subprocess.run(["git", "push", auth_url, branch], cwd=target_cwd, capture_output=True, text=True, timeout=20)
                    
        if res_push.returncode != 0:
            raise HTTPException(status_code=500, detail=res_push.stderr or res_push.stdout)
            
        invalidate_sessions_cache()
        return {"success": True, "message": f"Successfully committed and pushed branch '{branch}' to origin."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/sessions/sync-local")
def git_sync_local(input_data: SyncLocalInput):
    projects_list = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects_list if p["name"] == input_data.project), None)
    
    target_cwd = proj["path"] if (proj and os.path.exists(proj["path"])) else None
    if not target_cwd:
        raise HTTPException(status_code=400, detail=f"Local project directory for project '{input_data.project}' not found.")
        
    base_branch = input_data.base_branch or "main"
    
    try:
        res_co = subprocess.run(["git", "checkout", base_branch], cwd=target_cwd, capture_output=True, text=True, timeout=15)
        if res_co.returncode != 0:
            raise HTTPException(status_code=500, detail=res_co.stderr or res_co.stdout)
            
        res_pull = subprocess.run(["git", "pull", "origin", base_branch], cwd=target_cwd, capture_output=True, text=True, timeout=20)
        if res_pull.returncode != 0:
            raise HTTPException(status_code=500, detail=res_pull.stderr or res_pull.stdout)
            
        deleted_message = ""
        if input_data.delete_branch:
            res_del = subprocess.run(["git", "branch", "-d", input_data.delete_branch], cwd=target_cwd, capture_output=True, text=True, timeout=10)
            if res_del.returncode == 0:
                deleted_message = f" Local branch '{input_data.delete_branch}' deleted."
            else:
                res_del_f = subprocess.run(["git", "branch", "-D", input_data.delete_branch], cwd=target_cwd, capture_output=True, text=True, timeout=10)
                if res_del_f.returncode == 0:
                    deleted_message = f" Local branch '{input_data.delete_branch}' force-deleted."
                else:
                    deleted_message = f" Warning: Failed to delete local branch '{input_data.delete_branch}': {res_del_f.stderr or res_del.stderr}."
                    
        invalidate_sessions_cache()
        return {"success": True, "message": f"Successfully checked out and pulled '{base_branch}'.{deleted_message}"}
    except HTTPException:
        raise
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
    is_merging = False
    conflicts = []
    if proj:
        local_project_registered = True
        local_path = proj["path"]
        if os.path.exists(local_path):
            is_merging = os.path.exists(os.path.join(local_path, ".git", "MERGE_HEAD"))
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
            try:
                conf_res = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=U"],
                    cwd=local_path,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if conf_res.returncode == 0:
                    conflicts = [line.strip() for line in conf_res.stdout.strip().split("\n") if line.strip()]
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
        "status_message": status_message,
        "is_merging": is_merging,
        "conflicts": conflicts
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

@app.post("/api/jules/sessions/{session_id}/notify")
def resend_session_notification(session_id: str):
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    
    session_data = None
    repo = None
    
    # Try fetching fresh details first
    if api_key:
        import urllib.request
        import urllib.error
        url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
        req = urllib.request.Request(
            url,
            headers={"x-goog-api-key": api_key, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                session_data = json.loads(response.read().decode('utf-8'))
                source = session_data.get("sourceContext", {}).get("source", "")
                if source.startswith("sources/github/"):
                    repo = source.replace("sources/github/", "")
                else:
                    repo = "Other/Unmapped Repos"
        except Exception as e:
            print(f"Failed to fetch session {session_id} from API during notify: {e}", file=sys.stderr)
            
    # Fallback to cache if API failed or key not set
    if not session_data:
        cached_data = read_json(SESSIONS_CACHE_FILE, {})
        sessions = cached_data.get("sessions", [])
        session_obj = next((s for s in sessions if s.get("id") == session_id), None)
        if session_obj:
            repo = session_obj.get("repo")
            session_data = session_obj.get("raw", {})
            
    if not session_data or not repo:
        raise HTTPException(status_code=404, detail="Session details not found or cached.")

    # Auto-discover target conversation IDs
    conv_ids = get_target_conversations(session_id, repo)
    if not conv_ids:
        raise HTTPException(status_code=400, detail=f"No matching active conversations found in Antigravity IDE for project '{repo}'.")

    # Format status message
    state = session_data.get("state", "UNKNOWN").upper()
    title = "Jules Session Status"
    friendly_state = state.replace("_", " ").title()
    task_title = session_data.get("title") or session_data.get("prompt") or "Untitled Task"
    
    message_body = (
        f"New update on task in Google Jules!\n\n"
        f"Task: {task_title}\n"
        f"Repo: {repo}\n"
        f"Current State: {friendly_state}\n\n"
        f"Load the antigravity orchestrator mcp and skills if you are not already familiar."
    )
    
    activities = session_data.get("activities", [])
    if state == "AWAITING_PLAN_APPROVAL":
        message_body += "\n\nNote: This session is currently awaiting your plan approval."
    elif state == "AWAITING_USER_FEEDBACK":
        question = None
        for act in reversed(activities):
            if "agentMessaged" in act:
                question = act.get("agentMessaged", {}).get("message")
                break
        if question:
            message_body += f"\n\nQuestion asked by agent:\n{question}"
        else:
            message_body += "\n\nNote: This session is awaiting your feedback."

    # Route message to each matching conversation
    projects = read_json(PROJECTS_FILE, [])
    target_project = next((p for p in projects if p.get("name", "").lower() in repo.lower() or repo.lower() in p.get("name", "").lower()), None)
    target_path = target_project["path"] if target_project else ""

    success_notified = []
    for conv_id in conv_ids:
        try:
            trigger_cli_wakeup(conv_id, title, message_body, target_path)
            success_notified.append(conv_id)
        except Exception as notify_err:
            print(f"Error notifying conversation {conv_id}: {notify_err}", file=sys.stderr)

    if not success_notified:
        raise HTTPException(status_code=500, detail="Failed to route notification to any conversations.")

    return {
        "success": True,
        "message": f"Successfully resent task update to conversation(s): {', '.join(success_notified)}",
        "conversations": success_notified
    }

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

def sync_instructions_to_knowledge(instructions):
    try:
        knowledge_dir = os.path.join(home_dir, ".gemini", "antigravity-ide", "knowledge", "orchestrator_instructions")
        artifacts_dir = os.path.join(knowledge_dir, "artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)

        # 1. Write metadata.json
        metadata = {
            "title": "Active Orchestrator Instructions & Task Logs",
            "summary": "Synchronized list of active developer instructions, guidelines, and task logs registered in the Orchestrator dashboard.",
            "updated_at": datetime.now().isoformat()
        }
        write_json(os.path.join(knowledge_dir, "metadata.json"), metadata)

        # 2. Generate markdown
        md = "# Active Orchestrator Instructions & Task Logs\n\n"
        md += "This file is automatically synchronized from the Antigravity Orchestrator dashboard. It contains active instructions, advice, and task logs for each project.\n\n"

        if not instructions:
            md += "*No active instructions or advice logs found.*\n"
        else:
            # Group by project
            groups = {}
            for inst in instructions:
                proj = inst.get("project", "General")
                if proj not in groups:
                    groups[proj] = []
                groups[proj].append(inst)

            for proj, inst_list in groups.items():
                md += f"## Project: {proj}\n\n"
                for inst in inst_list:
                    status = inst.get("status", "RUNNING")
                    session_id = inst.get("jules_session_id")
                    timestamp = inst.get("timestamp")
                    md += f"### Task/Advice [{status}]\n"
                    if session_id:
                        md += f"- **Linked Session ID:** `{session_id}`\n"
                    if timestamp:
                        md += f"- **Logged At:** {timestamp}\n"
                    md += f"\n**Instruction Details:**\n```text\n{inst.get('instruction')}\n```\n\n---\n\n"

        with open(os.path.join(artifacts_dir, "active_instructions.md"), "w", encoding="utf-8") as f:
            f.write(md)
        print("Successfully synchronized instructions to Antigravity knowledge base.")
    except Exception as e:
        print(f"Failed to sync instructions to knowledge: {e}")

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
    sync_instructions_to_knowledge(instructions)
    return {"success": True}

@app.delete("/api/instructions/{instruction_id}")
def delete_instruction(instruction_id: str):
    instructions = read_json(INSTRUCTIONS_FILE, [])
    new_instructions = [inst for inst in instructions if inst.get("id") != instruction_id]
    if len(new_instructions) < len(instructions):
        write_json(INSTRUCTIONS_FILE, new_instructions)
        sync_instructions_to_knowledge(new_instructions)
        return {"success": True}
    else:
        raise HTTPException(status_code=404, detail="Instruction not found")


def create_session_api(repo: str, task: str, branch: str = "main"):
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if api_key:
        url = "https://jules.googleapis.com/v1alpha/sessions"
        payload = {
            "prompt": task,
            "title": task[:100],
            "sourceContext": {
                "source": f"sources/github/{repo}",
                "githubRepoContext": {
                    "startingBranch": branch or "main"
                }
            },
            "automationMode": "AUTO_CREATE_PR",
            "requirePlanApproval": True
        }
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode('utf-8')
                data = json.loads(body)
                invalidate_sessions_cache()
                return {"success": True, "message": f"Successfully created session {data.get('id')} with AUTO_CREATE_PR.", "session_id": data.get("id")}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            print(f"Jules API HTTP Error {e.code} during session creation: {err_body}", file=sys.stderr)
        except Exception as e:
            print(f"Jules API call failed during session creation: {e}", file=sys.stderr)

    # Fallback to local jules binary invocation
    env = os.environ.copy()
    if api_key:
        env["JULES_API_KEY"] = api_key
    env["CI"] = "true"
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    
    try:
        result = subprocess.run(
            [JULES_BIN, "new", "--repo", repo, task],
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
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))

def log_diagnostic(msg: str):
    import time
    log_file = os.path.join(SCRATCH_DIR, "notifications_diagnostics.log")
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception as e:
        print(f"Failed to write diagnostic log: {e}", file=sys.stderr)

def is_process_matching_repo(repo: str) -> bool:
    repo_name = repo.split("/")[-1] if "/" in repo else repo
    cwd = os.getcwd().replace("\\", "/").lower()
    
    projects = read_json(PROJECTS_FILE, [])
    repo_path = None
    for p in projects:
        p_name = p.get("name", "").lower()
        if p_name == repo_name.lower() or p_name in repo_name.lower() or repo_name.lower() in p_name:
            repo_path = p.get("path", "").replace("\\", "/").lower()
            break
            
    if not repo_path:
        matched = repo_name.lower() in cwd.split("/") or any(part in repo_name.lower() for part in cwd.split("/") if len(part) > 3)
        log_diagnostic(f"Repo {repo_name} not resolved in projects.json. Fallback check against CWD {cwd}: {matched}")
        return matched
        
    matched = (cwd == repo_path or cwd.startswith(repo_path + "/") or repo_path.startswith(cwd + "/"))
    log_diagnostic(f"Checking CWD match: CWD={cwd} RepoPath={repo_path} matched={matched}")
    return matched

def get_conversation_mtime(conv_id: str) -> float:
    subpath = os.path.join(home_dir, ".gemini", "antigravity-ide", "brain", conv_id)
    transcript_path = os.path.join(subpath, ".system_generated", "logs", "transcript.jsonl")
    if os.path.exists(transcript_path):
        try:
            return os.path.getmtime(transcript_path)
        except Exception:
            pass
    try:
        return os.path.getmtime(subpath)
    except Exception:
        return 0.0

def get_target_conversations(session_id: str, repo: str) -> list[str]:
    # 1. Check cache first with timestamp validation
    map_file = os.path.join(SCRATCH_DIR, "session_conv_map.json").replace("\\", "/")
    conv_map = read_json(map_file, {})
    brain_dir = os.path.join(home_dir, ".gemini", "antigravity-ide", "brain").replace("\\", "/")
    
    cached_conv_id = conv_map.get(session_id)
    max_other_mtime = 0.0
    cached_mtime = 0.0
    
    if cached_conv_id:
        cached_path = os.path.join(brain_dir, cached_conv_id).replace("\\", "/")
        if os.path.exists(cached_path):
            cached_mtime = get_conversation_mtime(cached_conv_id)
            
        if os.path.exists(brain_dir):
            try:
                for subdir in os.listdir(brain_dir):
                    if subdir == "tempmediaStorage" or subdir == cached_conv_id:
                        continue
                    t_path = os.path.join(brain_dir, subdir, ".system_generated", "logs", "transcript.jsonl").replace("\\", "/")
                    if os.path.exists(t_path):
                        mt = os.path.getmtime(t_path)
                        if mt > max_other_mtime:
                            max_other_mtime = mt
            except Exception:
                pass
                
        # If the cached conversation is newer than all other conversations, skip traversal
        if cached_mtime >= max_other_mtime:
            log_diagnostic(f"Skipping traversal: cached conversation ID {cached_conv_id} is up to date.")
            return [cached_conv_id]

    # 2. Perform full traversal if cache is stale or missing
    current_workspace_path = os.getcwd().replace("\\", "/").lower()
    log_diagnostic(f"Strictly matching conversations for current workspace: {current_workspace_path}")
    
    matched_convs_with_scores = []
    
    if os.path.exists(brain_dir):
        for subdir in os.listdir(brain_dir):
            if subdir == "tempmediaStorage":
                continue
            subpath = os.path.join(brain_dir, subdir).replace("\\", "/")
            if os.path.isdir(subpath):
                transcript_path = os.path.join(subpath, ".system_generated", "logs", "transcript.jsonl").replace("\\", "/")
                if not os.path.exists(transcript_path):
                    continue
                    
                try:
                    with open(transcript_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    
                    content_lower = "".join(lines).lower()
                    normalized_content = content_lower.replace("\\\\", "/").replace("\\", "/")
                    has_path_mention = current_workspace_path in normalized_content
                                         
                    if not has_path_mention:
                        for fname in os.listdir(subpath):
                            if fname.endswith(".md"):
                                fpath = os.path.join(subpath, fname).replace("\\", "/")
                                with open(fpath, "r", encoding="utf-8") as mf:
                                    m_content = mf.read().lower().replace("\\\\", "/").replace("\\", "/")
                                    if current_workspace_path in m_content:
                                        has_path_mention = True
                                        break
                                        
                    if not has_path_mention:
                        continue
                        
                    mapped_project_name = None
                    for line in reversed(lines):
                        try:
                            data = json.loads(line.strip())
                            step_content = data.get("content", "")
                            if not step_content:
                                continue
                            import re
                            m = re.search(r"Active Document:\s*([^\n\r]+)", step_content)
                            if m:
                                active_doc = m.group(1).replace("\\", "/").lower()
                                if active_doc.startswith(current_workspace_path + "/") or active_doc == current_workspace_path:
                                    mapped_project_name = "current"
                                    break
                        except Exception:
                            continue
                            
                    score = 50
                    if mapped_project_name == "current":
                        score = 100
                        log_diagnostic(f"  Conversation {subdir} PERFECT match (Active Document belongs to current workspace)")
                        
                    if score > 0:
                        mtime = get_conversation_mtime(subdir)
                        matched_convs_with_scores.append({
                            "conv_id": subdir,
                            "score": score,
                            "mtime": mtime
                        })
                except Exception as e:
                    log_diagnostic(f"  ERROR reading conversation {subdir}: {e}")
                    print(f"Error checking files in {subpath}: {e}", file=sys.stderr)
    else:
        log_diagnostic("ERROR: brain_dir does not exist!")
        
    if not matched_convs_with_scores:
        log_diagnostic("No matched conversations found.")
        return []
        
    matched_convs_with_scores.sort(key=lambda x: (x["score"], x["mtime"]), reverse=True)
    log_diagnostic(f"Matched conversations with scores: {matched_convs_with_scores}")
    
    # Return only the single best matched conversation ID
    chosen_conv = matched_convs_with_scores[0]["conv_id"]
    log_diagnostic(f"Choosing conversation for notification: {chosen_conv}")
    
    # Save mapping to cache file
    conv_map[session_id] = chosen_conv
    write_json(map_file, conv_map)
    log_diagnostic(f"Discovered and cached conversation ID {chosen_conv} for session {session_id}")
        
    return [chosen_conv]

def detect_ls_address(workspace_path, agent_api_bin, conv_id):
    if os.name != 'nt':
        return None, None
    import hashlib
    # Normalize path
    path = workspace_path.replace("\\", "/")
    if len(path) >= 2 and path[1] == ":":
        drive = path[0].lower()
        rest = path[2:]
        path = f"{drive}:{rest}"
    
    uri = f"file:///{path.replace(':', '%3A')}"
    
    # Candidate 1: SHA-256 Hash
    h = hashlib.sha256(uri.encode('utf-8')).hexdigest()
    
    # Candidate 2: Sanitized URI
    san = re.sub(r'[^a-zA-Z0-9]', '_', uri)
    san = re.sub(r'_+', '_', san)
    san = san.strip('_')
    
    candidates = [h.lower(), san.lower()]
    
    # Scan running processes via wmic
    cmd = ["wmic", "process", "where", "name='language_server_windows_x64.exe'", "get", "commandline,processid", "/format:list"]
    try:
        res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            stdout = res.stdout
            processes = []
            current = {}
            for line in stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    current[k.strip()] = v.strip()
                if "CommandLine" in current and "ProcessId" in current:
                    processes.append(current)
                    current = {}
            
            # Find the process matching the workspace candidates
            target_proc = None
            for p in processes:
                cl = p.get("CommandLine", "")
                ws_match = re.search(r'--workspace_id\s+(\S+)', cl)
                if ws_match:
                    ws_id = ws_match.group(1).lower()
                    if ws_id in candidates:
                        target_proc = p
                        break
            
            if target_proc:
                cl = target_proc.get("CommandLine", "")
                pid = target_proc.get("ProcessId")
                csrf_match = re.search(r'--csrf_token\s+(\S+)', cl)
                csrf_token = csrf_match.group(1) if csrf_match else None
                port_val = None
                port_match = re.search(r'--extension_server_port\s+(\d+)', cl)
                if port_match:
                    port_val = port_match.group(1)
                
                # Now scan listening ports of this PID using netstat
                netstat_cmd = ["netstat", "-ano"]
                ns_res = subprocess.run(netstat_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
                if ns_res.returncode == 0:
                    candidate_ports = []
                    for line in ns_res.stdout.splitlines():
                        if pid in line and "LISTENING" in line:
                            parts = line.split()
                            if len(parts) >= 2:
                                addr = parts[1]
                                if ":" in addr:
                                    port = addr.split(":")[-1]
                                    # Exclude extension server port itself
                                    if port != port_val and port not in candidate_ports:
                                        candidate_ports.append(port)
                    
                    log_diagnostic(f"  Found candidate ports for PID {pid}: {candidate_ports}")
                    
                    # Test each candidate port to find the gRPC port
                    for port in candidate_ports:
                        test_env = os.environ.copy()
                        test_env["ANTIGRAVITY_LS_ADDRESS"] = f"localhost:{port}"
                        if csrf_token:
                            test_env["ANTIGRAVITY_CSRF_TOKEN"] = csrf_token
                        
                        # Run get-conversation-metadata as a test
                        test_cmd = [agent_api_bin, "get-conversation-metadata", conv_id]
                        try:
                            t_res = subprocess.run(test_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, env=test_env)
                            output_str = (t_res.stdout or "") + (t_res.stderr or "")
                            if t_res.returncode == 0 or "invalid CSRF token" in output_str:
                                return f"localhost:{port}", csrf_token
                        except Exception as e:
                            log_diagnostic(f"  Error testing port {port}: {e}")
    except Exception as e:
        log_diagnostic(f"  Error in detect_ls_address: {e}")
    return None, None

def get_project_path_for_conversation(conv_id: str) -> str:
    projects = read_json(PROJECTS_FILE, [])
    brain_dir = os.path.join(home_dir, ".gemini", "antigravity-ide", "brain")
    conv_dir = os.path.join(brain_dir, conv_id)
    if not os.path.exists(conv_dir):
        return None
        
    transcript_path = os.path.join(conv_dir, ".system_generated", "logs", "transcript.jsonl")
    if os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # Try to find the most recent Cwd or file path in tool calls
            for line in reversed(lines):
                try:
                    data = json.loads(line.strip())
                    tool_calls = data.get("tool_calls", [])
                    for tc in tool_calls:
                        args = tc.get("args", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        if isinstance(args, dict):
                            # Check Cwd, DirectoryPath, AbsolutePath, TargetFile
                            for key in ["Cwd", "DirectoryPath", "AbsolutePath", "TargetFile"]:
                                val = args.get(key)
                                if val and isinstance(val, str):
                                    val = val.strip('"\'')
                                    val_norm = re.sub(r'[\\/]+', '/', val).lower()
                                    for p in projects:
                                        p_path = re.sub(r'[\\/]+', '/', p.get("path", "")).lower()
                                        if p_path and (val_norm.startswith(p_path + "/") or val_norm == p_path):
                                            return p.get("path")
                except Exception:
                    continue

            # Fallback: Try to find the most recent Active Document
            for line in reversed(lines):
                try:
                    data = json.loads(line.strip())
                    step_content = data.get("content", "")
                    if not step_content:
                        continue
                    m = re.search(r"Active Document:\s*([^\n\r]+)", step_content)
                    if m:
                        active_doc = re.sub(r'[\\/]+', '/', m.group(1)).lower()
                        for p in projects:
                            p_path = re.sub(r'[\\/]+', '/', p.get("path", "")).lower()
                            if p_path and (active_doc.startswith(p_path + "/") or active_doc == p_path):
                                return p.get("path")
                except Exception:
                    continue
        except Exception:
            pass
            
    # Fallback to checking mentions
    content_lower = ""
    if os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                content_lower = f.read().lower()
        except Exception:
            pass
            
    for fname in os.listdir(conv_dir):
        if fname.endswith(".md"):
            try:
                with open(os.path.join(conv_dir, fname), "r", encoding="utf-8") as f:
                    content_lower += "\n" + f.read().lower()
            except Exception:
                pass
                
    matched_projects = []
    content_clean = re.sub(r'[\\/]+', '/', content_lower)
    for p in projects:
        p_path = p.get("path", "").replace("\\", "/").lower()
        if not p_path:
            continue
        p_path_norm = re.sub(r'[\\/]+', '/', p_path).lower()
        if p_path_norm in content_clean:
            matched_projects.append(p)
            
    if not matched_projects:
        return None
        
    # If there are multiple matches, prefer non-orchestrator ones if possible
    non_orch = [p for p in matched_projects if p.get("name") != "antigravity-orchestrator"]
    if non_orch:
        non_orch.sort(key=lambda x: len(x.get("path", "")), reverse=True)
        return non_orch[0].get("path")
        
    matched_projects.sort(key=lambda x: len(x.get("path", "")), reverse=True)
    return matched_projects[0].get("path")

def discover_workspace_grpc(target_path: str) -> dict | None:
    try:
        import subprocess
        import json
        import re
        folder_name = os.path.basename(target_path.replace("\\", "/").rstrip("/"))
        if not folder_name:
            folder_name = target_path
            
        ps_cmd = f'Get-CimInstance Win32_Process -Filter "Name = \'language_server_windows_x64.exe\'" | Where-Object {{ $_.CommandLine -like \'*{folder_name}*\' }} | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress'
        res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=5)
        stdout = res.stdout.strip()
        if not stdout:
            return None
            
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, list):
                parsed.sort(key=lambda x: x.get("ProcessId", 0), reverse=True)
                proc_data = parsed[0]
            else:
                proc_data = parsed
        except Exception:
            return None
            
        proc_id = proc_data.get("ProcessId")
        cmdline = proc_data.get("CommandLine", "")
        if not proc_id:
            return None
            
        csrf_match = re.search(r'--csrf_token\s+([\w-]+)', cmdline)
        if not csrf_match:
            return None
        csrf_token = csrf_match.group(1)
        
        netstat_cmd = f'(netstat -ano) | Where-Object {{ $_ -match \'\\s+LISTENING\\s+{proc_id}\\s*$\' }} | ForEach-Object {{ $parts = $_.Trim() -split \'\\s+\'; if ($parts.Length -ge 2) {{ $addr = $parts[1]; $addr.Substring($addr.LastIndexOf(\':\') + 1) }} }} | Select-Object -Unique | ConvertTo-Json -Compress'
        res_ns = subprocess.run(["powershell", "-Command", netstat_cmd], capture_output=True, text=True, timeout=5)
        ns_stdout = res_ns.stdout.strip()
        if not ns_stdout:
            return None
            
        ports = []
        try:
            parsed_ports = json.loads(ns_stdout)
            if isinstance(parsed_ports, list):
                ports = [int(p) for p in parsed_ports]
            else:
                ports = [int(parsed_ports)]
        except Exception:
            try:
                num = int(ns_stdout)
                ports = [num]
            except Exception:
                pass
                
        return {"ports": ports, "csrf_token": csrf_token}
    except Exception as e:
        print(f"Error in discover_workspace_grpc: {e}", file=sys.stderr)
        return None

def trigger_cli_wakeup(conv_id: str, title: str, content: str, target_path: str):
    agent_api_bin = os.path.join(home_dir, ".gemini", "antigravity-ide", "bin", "agentapi.bat" if os.name == 'nt' else "agentapi")
    if not os.path.exists(agent_api_bin):
        log_diagnostic(f"  WARNING: agentapi binary not found at {agent_api_bin}")
        return
        
    log_diagnostic(f"Invoking CLI wakeup to recipient={conv_id}")
    cli_content = f"[{title}] {content}"
    cmd = [agent_api_bin, "send-message", conv_id, cli_content]
    
    env = os.environ.copy()
    
    # Strictly discover ports for the current workspace
    disc = discover_workspace_grpc(os.getcwd())
    ports = []
    csrf_token = None
    if disc:
        ports = disc.get("ports", [])
        csrf_token = disc.get("csrf_token")
        
    if csrf_token:
        env["ANTIGRAVITY_CSRF_TOKEN"] = csrf_token
        
    # Read VSCODE_IPC_HOOK from ipc_hooks.json for safety
    if target_path:
        target_path = target_path.replace("\\", "/").lower()
        ipc_hooks = read_json(os.path.join(SCRATCH_DIR, "ipc_hooks.json"), {})
        entry = ipc_hooks.get(target_path)
        hook = None
        if entry:
            if isinstance(entry, dict):
                hook = entry.get("ipc_hook")
            else:
                hook = entry
        if hook:
            env["VSCODE_IPC_HOOK"] = hook
            
    # Try all ports
    if ports:
        for port in ports:
            env_with_port = env.copy()
            env_with_port["ANTIGRAVITY_LS_ADDRESS"] = f"localhost:{port}"
            try:
                log_diagnostic(f"  Trying port {port} for wakeup...")
                res = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env_with_port
                )
                if res.returncode == 0:
                    log_diagnostic(f"  CLI wakeup success on port {port}: {res.stdout.strip()}")
                    return
                else:
                    log_diagnostic(f"  Port {port} failed. stdout: {res.stdout.strip()} | stderr: {res.stderr.strip()}")
            except Exception as port_err:
                log_diagnostic(f"  Port {port} exception: {port_err}")
                
    # Fallback to standard environment variables
    log_diagnostic("  Discovery failed or ports did not succeed. Falling back to active env/ipc_hooks...")
    if target_path:
        target_path = target_path.replace("\\", "/").lower()
        ipc_hooks = read_json(os.path.join(SCRATCH_DIR, "ipc_hooks.json"), {})
        entry = ipc_hooks.get(target_path)
        hook = None
        ls_addr = None
        if entry:
            if isinstance(entry, dict):
                hook = entry.get("ipc_hook")
                ls_addr = entry.get("ls_address")
            else:
                hook = entry
        if hook:
            env["VSCODE_IPC_HOOK"] = hook
        if ls_addr:
            env["ANTIGRAVITY_LS_ADDRESS"] = ls_addr
            
    try:
        res = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            env=env
        )
        if res.returncode == 0:
            log_diagnostic(f"  CLI wakeup success: {res.stdout.strip()}")
        else:
            log_diagnostic(f"  CLI wakeup failed with exit code {res.returncode}. stdout: {res.stdout.strip()} | stderr: {res.stderr.strip()}")
    except Exception as e:
        log_diagnostic(f"  ERROR executing CLI command: {e}")

def check_and_wakeup_unread_conversations():
    brain_dir = os.path.join(home_dir, ".gemini", "antigravity-ide", "brain")
    if not os.path.exists(brain_dir):
        return
        
    for conv_id in os.listdir(brain_dir):
        if conv_id == "tempmediaStorage":
            continue
        conv_dir = os.path.join(brain_dir, conv_id)
        if not os.path.isdir(conv_dir):
            continue
            
        messages_dir = os.path.join(conv_dir, ".system_generated", "messages")
        if not os.path.exists(messages_dir):
            continue
            
        read_file = os.path.join(messages_dir, "read.json")
        read_msgs = {}
        if os.path.exists(read_file):
            try:
                read_msgs = read_json(read_file, {})
            except Exception:
                pass
                
        # Find any unread message
        has_unread = False
        unread_title = "Jules Session Status Update"
        unread_content = "There are pending updates in your Jules session."
        repo = None
        
        for fname in os.listdir(messages_dir):
            if fname.endswith(".json") and fname != "read.json" and fname != "cursor.json":
                msg_id = fname[:-5]
                if msg_id not in read_msgs:
                    try:
                        with open(os.path.join(messages_dir, fname), "r", encoding="utf-8") as f:
                            m_data = json.load(f)
                            # Skip low priority / hidden notice messages
                            if m_data.get("hideFromUser") or m_data.get("priority") == "MESSAGE_PRIORITY_LOW":
                                continue
                            has_unread = True
                            unread_title = m_data.get("renderDetails", {}).get("messageTitle", unread_title)
                            unread_content = m_data.get("content", unread_content)
                            repo = m_data.get("repo")
                    except Exception:
                        pass
                    if has_unread:
                        break
                    
        if has_unread:
            if not repo:
                # Fallback: try to extract repo from content string
                match = re.search(r"for repo '([^']+)'", unread_content)
                if match:
                    repo = match.group(1)
            
            target_path = None
            if repo:
                projects = read_json(PROJECTS_FILE, [])
                for p in projects:
                    p_name = p.get("name", "").lower()
                    if p_name == repo.split("/")[-1].lower() or p_name in repo.lower() or repo.lower() in p_name:
                        target_path = p.get("path", "").replace("\\", "/").lower()
                        break
            
            if not target_path:
                target_path = get_project_path_for_conversation(conv_id)
                
            if target_path:
                log_diagnostic(f"Found unread messages in conversation {conv_id} matching project path {target_path} (repo: {repo}). Retrying wakeup.")
                trigger_cli_wakeup(conv_id, unread_title, unread_content, target_path)
            else:
                log_diagnostic(f"Found unread messages in conversation {conv_id} but could not resolve project path.")

async def notify_agent_for_session(session_id: str, repo: str, state: str, session_data: dict):
    import uuid
    log_diagnostic(f"Processing notification event for session={session_id} repo={repo} state={state}")
    
    # Restrict session notifications to only the active project workspace
    projects = read_json(PROJECTS_FILE, [])
    active_project = None
    for p in projects:
        if p.get("active"):
            active_project = p
            break
            
    if active_project:
        repo_name = repo.split("/")[-1] if "/" in repo else repo
        p_name = active_project.get("name", "").lower()
        if not (p_name == repo_name.lower() or p_name in repo_name.lower() or repo_name.lower() in p_name):
            log_diagnostic(f"Skipping notification write because session repo '{repo}' does not match active project '{active_project.get('name')}'")
            return
            
    # Bypass CWD match check. Since all server instances share session_states.json,
    # the first instance to poll and find a change will notify the matching active conversation
    # regardless of the process's working directory.
    conv_ids = get_target_conversations(session_id, repo)
    if not conv_ids:
        log_diagnostic(f"Skipping notification write because no conversations matched.")
        print(f"No target conversation found for session {session_id} ({repo}) matching local project path. Skipping notification.", file=sys.stderr)
        return
        
    title = f"Jules Session Status Update"
    content = f"Jules session {session_id} for repo '{repo}' transitioned to status {state}."
    
    pr_number = None
    outputs = session_data.get("outputs", [])
    for out in outputs:
        if isinstance(out, dict) and out.get("type") == "PULL_REQUEST":
            pr_number = out.get("pullRequest", {}).get("number")
            break
            
    if state == "AWAITING_PLAN_APPROVAL":
        title = f"Jules Session: Plan Generated"
        content = f"Jules session {session_id} for repo '{repo}' is awaiting your plan approval."
    elif state == "AWAITING_USER_FEEDBACK":
        # Check if there is an open question
        activities = session_data.get("activities", [])
        question = None
        for act in reversed(activities):
            if "agentMessaged" in act:
                question = act.get("agentMessaged", {}).get("message")
                break
        if question:
            title = f"Jules Session: Question Asked"
            content = f"Jules session {session_id} for repo '{repo}' has a question for you:\n\n{question}"
        else:
            title = f"Jules Session: Awaiting User Feedback"
            content = f"Jules session {session_id} for repo '{repo}' is awaiting your feedback."
    elif state in ["COMPLETED", "SUCCEEDED"]:
        title = f"Jules Session: Completed Successfully"
        content = f"Jules session {session_id} for repo '{repo}' completed successfully."
        if pr_number:
            content += f" Created Pull Request #{pr_number}."
    elif state in ["FAILED", "CANCELLED", "ERROR"]:
        title = f"Jules Session: Failed"
        content = f"Jules session {session_id} for repo '{repo}' transitioned to state {state}."
        
    # Write message files for the targeted local conversations
    for conv_id in conv_ids:
        brain_dir = os.path.join(home_dir, ".gemini", "antigravity-ide", "brain")
        messages_dir = os.path.join(brain_dir, conv_id, ".system_generated", "messages")
        os.makedirs(messages_dir, exist_ok=True)
        
        msg_id = str(uuid.uuid4())
        msg = {
            "messageId": msg_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "sender": "antigravity-orchestrator",
            "priority": "MESSAGE_PRIORITY_HIGH",
            "renderDetails": {
                "messageTitle": title
            },
            "content": content,
            "repo": repo
        }
        
        msg_file = os.path.join(messages_dir, f"{msg_id}.json")
        try:
            with open(msg_file, "w", encoding="utf-8") as f:
                json.dump(msg, f)
            log_diagnostic(f"  Successfully wrote message file {msg_file}. Content summary: '{title}'")
            print(f"Sent notification to conversation {conv_id}: {title} (Session {session_id})", file=sys.stderr)
        except Exception as e:
            log_diagnostic(f"  ERROR writing message file {msg_file}: {e}")
            print(f"Failed to write message file {msg_file}: {e}", file=sys.stderr)

        # Resolve target project path to find VSCODE_IPC_HOOK
        projects = read_json(PROJECTS_FILE, [])
        target_path = None
        for p in projects:
            p_name = p.get("name", "").lower()
            if p_name == repo.split("/")[-1].lower() or p_name in repo.lower() or repo.lower() in p_name:
                target_path = p.get("path", "").replace("\\", "/").lower()
                break
                
        # Trigger reactive wakeup via the official agentapi CLI tool
        trigger_cli_wakeup(conv_id, title, content, target_path)

async def background_poll_sessions():
    log_diagnostic("Background session polling task started.")
    print("Background session polling started...", file=sys.stderr)
    SESSION_STATES_FILE = os.path.join(SCRATCH_DIR, "session_states.json")

    while True:
        try:
            settings = await asyncio.to_thread(read_json, SETTINGS_FILE, {})
            api_key = settings.get("jules")
            if not api_key:
                await asyncio.sleep(15)
                continue

            url = "https://jules.googleapis.com/v1alpha/sessions?pageSize=50"
            req = urllib.request.Request(
                url,
                headers={"x-goog-api-key": api_key, "Accept": "application/json"}
            )
            
            def fetch_sessions():
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        return json.loads(resp.read().decode('utf-8'))
                except Exception as e:
                    log_diagnostic(f"HTTP error fetching sessions: {e}")
                    print(f"Error fetching sessions in background poll: {e}", file=sys.stderr)
                    return None

            data = await asyncio.to_thread(fetch_sessions)
            if not data:
                await asyncio.sleep(15)
                continue

            sessions = data.get("sessions", [])
            cli_statuses = await asyncio.to_thread(get_cli_session_statuses)
            states_db = await asyncio.to_thread(read_json, SESSION_STATES_FILE, {})
            
            db_changed = False
            for s in sessions:
                sid = s.get("id")
                state = s.get("state", "UNKNOWN").upper()
                if sid in cli_statuses:
                    cli_status = cli_statuses[sid]
                    new_state = map_cli_status_to_api_state(cli_status, state)
                    if new_state != state:
                        log_diagnostic(f"Background poll overriding state for session {sid} from {state} to {new_state} (CLI: {cli_status})")
                        state = new_state
                        s["state"] = new_state
                source = s.get("sourceContext", {}).get("source", "")
                repo = source.replace("sources/github/", "") if source.startswith("sources/github/") else "Other/Unmapped Repos"
                
                notifiable_states = ["COMPLETED", "SUCCEEDED", "FAILED", "CANCELLED", "ERROR", 
                                     "AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK"]
                
                if state not in notifiable_states:
                    if sid not in states_db:
                        states_db[sid] = {
                            "state": state,
                            "notified_states": []
                        }
                        db_changed = True
                    elif states_db[sid]["state"] != state:
                        states_db[sid]["state"] = state
                        db_changed = True
                    continue
                
                if sid in states_db:
                    session_info = states_db[sid]
                    notified = session_info.get("notified_states", [])
                    if state not in notified:
                        log_diagnostic(f"Session state transition detected for session {sid}: {session_info.get('state')} -> {state}")
                        await notify_agent_for_session(sid, repo, state, s)
                        notified.append(state)
                        session_info["state"] = state
                        session_info["notified_states"] = notified
                        db_changed = True
                else:
                    create_time_str = s.get("createTime")
                    should_notify = True
                    if create_time_str:
                        try:
                            if create_time_str.endswith('Z'):
                                create_time_str = create_time_str[:-1] + '+00:00'
                            create_time = datetime.fromisoformat(create_time_str)
                            now_utc = datetime.now(create_time.tzinfo)
                            age_seconds = (now_utc - create_time).total_seconds()
                            if age_seconds > 3600:
                                should_notify = False
                        except Exception as e:
                            print(f"Error parsing create time {create_time_str}: {e}", file=sys.stderr)
                    
                    if should_notify:
                        log_diagnostic(f"New session detected requiring notification: {sid} state: {state}")
                        await notify_agent_for_session(sid, repo, state, s)
                        states_db[sid] = {
                            "state": state,
                            "notified_states": [state]
                        }
                    else:
                        log_diagnostic(f"Historical session detected. Skipping initial notification: {sid} state: {state}")
                        states_db[sid] = {
                            "state": state,
                            "notified_states": notifiable_states
                        }
                    db_changed = True

            # Sync instructions status with Jules session states
            try:
                instructions = await asyncio.to_thread(read_json, INSTRUCTIONS_FILE, [])
                instructions_changed = False
                
                for inst in instructions:
                    jsid = inst.get("jules_session_id")
                    if jsid:
                        # Find the session in sessions list
                        session_obj = next((s for s in sessions if str(s.get("id")) == str(jsid)), None)
                        if session_obj:
                            s_state = session_obj.get("state", "UNKNOWN").upper()
                            
                            # Map jules session state to instruction status
                            target_status = "RUNNING"
                            if s_state in ["COMPLETED", "SUCCEEDED"]:
                                target_status = "COMPLETED"
                            elif s_state in ["FAILED", "ERROR", "CANCELLED"]:
                                target_status = "FAILED"
                            elif s_state == "AWAITING_USER_FEEDBACK":
                                # To distinguish AWAITING_PLAN_APPROVAL vs AWAITING_USER_FEEDBACK,
                                # we can check if there is a plan Generated activity.
                                try:
                                    act_url = f"https://jules.googleapis.com/v1alpha/sessions/{jsid}/activities"
                                    act_req = urllib.request.Request(
                                        act_url,
                                        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
                                    )
                                    def fetch_acts():
                                        try:
                                            with urllib.request.urlopen(act_req, timeout=5) as resp:
                                                return json.loads(resp.read().decode('utf-8'))
                                        except Exception:
                                            return {}
                                    act_data = await asyncio.to_thread(fetch_acts)
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
                                        target_status = "PLANNING"
                                    else:
                                        target_status = "AWAITING_USER_FEEDBACK"
                                except Exception:
                                    target_status = "AWAITING_USER_FEEDBACK"
                            elif s_state in ["PLANNING", "AWAITING_PLAN_APPROVAL"]:
                                target_status = "PLANNING"
                                
                            if inst.get("status") != target_status:
                                inst["status"] = target_status
                                instructions_changed = True
                                log_diagnostic(f"Synced instruction {inst.get('id')} status to {target_status} matching session {jsid} state {s_state}")
                
                if instructions_changed:
                    await asyncio.to_thread(write_json, INSTRUCTIONS_FILE, instructions)
                    await asyncio.to_thread(sync_instructions_to_knowledge, instructions)
            except Exception as inst_ex:
                log_diagnostic(f"Error syncing instructions: {inst_ex}")

            if db_changed:
                                await asyncio.to_thread(write_json, SESSION_STATES_FILE, states_db)
                                invalidate_sessions_cache()

            # Disabled periodic unread conversation scanner to prevent CPU spikes and context deadlines.
            # try:
            #     await asyncio.to_thread(check_and_wakeup_unread_conversations)
            # except Exception as unread_ex:
            #     log_diagnostic(f"Error checking unread conversations: {unread_ex}")
            pass

        except Exception as ex:
            log_diagnostic(f"Loop Exception: {ex}")
            print(f"Error in background session polling loop: {ex}", file=sys.stderr)
        
        await asyncio.sleep(15)

# (FastAPI startup logic moved to lifespan handler at the top of file)

@app.post("/api/jules/sessions")
def create_session(input_data: CreateSessionInput):
    return create_session_api(input_data.repo, input_data.task, input_data.branch)

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
                            },
                            "branch": {
                                "type": "string",
                                "description": "Optional: Starting branch to fork the session from. Defaults to 'main'."
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
                    name="checkout_branch",
                    description="Fetch and checkout a Jules session branch or standard branch in the local registered project workspace.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The unique ID of the Jules session. Resolves the branch name automatically."
                            },
                            "branch_name": {
                                "type": "string",
                                "description": "Optional: Specific branch name to checkout if session_id is not provided."
                            },
                            "project": {
                                "type": "string",
                                "description": "Optional: Name of the local registered project. If omitted, resolved from session context."
                            }
                        }
                    }
                ),
                Tool(
                    name="merge_branch_locally",
                    description="Merge another branch (e.g. main or a session branch) into the current checked out branch. Returns conflict details if there are merge conflicts.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "target_branch": {
                                "type": "string",
                                "description": "Optional: The target branch to merge into the current branch (e.g. 'main'). Defaults to the session's base branch."
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Optional: Resolves target branch from a session ID (merges main into session branch)."
                            },
                            "project": {
                                "type": "string",
                                "description": "Optional: Name of the local registered project."
                            }
                        }
                    }
                ),
                Tool(
                    name="git_commit_and_push",
                    description="Stage all local modifications, commit with the provided message, and push the branch to origin.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Name of the local registered project."
                            },
                            "commit_message": {
                                "type": "string",
                                "description": "The commit message describing the resolution."
                            }
                        },
                        "required": ["project", "commit_message"]
                    }
                ),
                Tool(
                    name="sync_local",
                    description="Sync the local reference copy with origin (checkout base branch like main/master, pull latest changes, and optionally delete a local feature branch).",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project": {
                                "type": "string",
                                "description": "Name of the local registered project."
                            },
                            "base_branch": {
                                "type": "string",
                                "description": "Optional: The base branch to switch to and pull (e.g. 'main'). Defaults to 'main'."
                            },
                            "delete_branch": {
                                "type": "string",
                                "description": "Optional: The name of the local feature branch to delete after pulling main."
                            }
                        },
                        "required": ["project"]
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
                    name="delete_instruction",
                    description="Deletes a logged high-level task/instruction by its unique ID (e.g. 'inst_xxxxxx')",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "The unique ID of the instruction to delete"
                            }
                        },
                        "required": ["id"]
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
                branch = arguments.get("branch", "main")
                if not repo or not task:
                    return [TextContent(type="text", text="Error: repo and task are required")]
                try:
                    res = await run_with_timeout(create_session_api, repo, task, branch, timeout=30.0)
                    return [TextContent(type="text", text=json.dumps(res, indent=2))]
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
            elif name == "checkout_branch":
                session_id = arguments.get("session_id")
                branch_name = arguments.get("branch_name")
                project = arguments.get("project")
                
                try:
                    if session_id:
                        res = await run_with_timeout(checkout_jules_branch, session_id, timeout=90.0)
                        return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                    elif branch_name and project:
                        projects_list = read_json(PROJECTS_FILE, [])
                        proj = next((p for p in projects_list if p["name"] == project), None)
                        target_cwd = proj["path"] if (proj and os.path.exists(proj["path"])) else None
                        if not target_cwd:
                            return [TextContent(type="text", text=f"Error: Project '{project}' not found locally.")]
                            
                        def run_co():
                            subprocess.run(["git", "fetch", "origin"], cwd=target_cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                            return subprocess.run(["git", "checkout", branch_name], cwd=target_cwd, capture_output=True, text=True, timeout=15)
                            
                        res = await run_with_timeout(run_co, timeout=45.0)
                        if res.returncode == 0:
                            return [TextContent(type="text", text=f"Success: Checked out branch '{branch_name}' in project '{project}'.")]
                        else:
                            return [TextContent(type="text", text=f"Error: {res.stderr or res.stdout}")]
                    else:
                        return [TextContent(type="text", text="Error: Either 'session_id' OR both 'branch_name' and 'project' must be provided.")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error checking out branch: {str(e)}")]
                    
            elif name == "merge_branch_locally":
                target_branch = arguments.get("target_branch")
                session_id = arguments.get("session_id")
                project = arguments.get("project")
                
                try:
                    if session_id:
                        res = await run_with_timeout(merge_local_branch, session_id, MergeLocalInput(target_branch=target_branch), timeout=45.0)
                        return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                    elif target_branch and project:
                        projects_list = read_json(PROJECTS_FILE, [])
                        proj = next((p for p in projects_list if p["name"] == project), None)
                        target_cwd = proj["path"] if (proj and os.path.exists(proj["path"])) else None
                        if not target_cwd:
                            return [TextContent(type="text", text=f"Error: Project '{project}' not found locally.")]
                            
                        def run_merge():
                            subprocess.run(["git", "fetch", "origin", target_branch], cwd=target_cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                            res = subprocess.run(["git", "merge", f"origin/{target_branch}"], cwd=target_cwd, capture_output=True, text=True, timeout=20)
                            if res.returncode == 0:
                                return {"success": True, "conflict": False}
                            else:
                                conf_res = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=target_cwd, capture_output=True, text=True, timeout=5)
                                conflicts = [line.strip() for line in conf_res.stdout.strip().split("\n") if line.strip()]
                                if conflicts:
                                    return {"success": False, "conflict": True, "conflicted_files": conflicts}
                                else:
                                    return {"success": False, "conflict": False, "error": res.stderr or res.stdout}
                                    
                        res = await run_with_timeout(run_merge, timeout=45.0)
                        return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                    else:
                        return [TextContent(type="text", text="Error: Either 'session_id' OR both 'target_branch' and 'project' must be provided.")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error merging branch: {str(e)}")]
                    
            elif name == "git_commit_and_push":
                project = arguments.get("project")
                commit_message = arguments.get("commit_message")
                if not project or not commit_message:
                    return [TextContent(type="text", text="Error: 'project' and 'commit_message' are required.")]
                try:
                    res = await run_with_timeout(git_commit_push, CommitPushInput(project=project, commit_message=commit_message), timeout=45.0)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error committing/pushing changes: {str(e)}")]
                    
            elif name == "sync_local":
                project = arguments.get("project")
                base_branch = arguments.get("base_branch", "main")
                delete_branch = arguments.get("delete_branch")
                if not project:
                    return [TextContent(type="text", text="Error: 'project' is required.")]
                try:
                    res = await run_with_timeout(git_sync_local, SyncLocalInput(project=project, base_branch=base_branch, delete_branch=delete_branch), timeout=45.0)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error syncing local repository: {str(e)}")]
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
                            
                            # Override status if CLI reports different status
                            cli_statuses = get_cli_session_statuses()
                            state = session_data.get("state", "UNKNOWN")
                            if session_id in cli_statuses:
                                cli_status = cli_statuses[session_id]
                                new_state = map_cli_status_to_api_state(cli_status, state)
                                if new_state != state:
                                    state = new_state
                                    session_data["state"] = new_state
                            
                            return {
                                "id": session_data.get("id"),
                                "repo": repo,
                                "title": session_data.get("title", "No Title"),
                                "description": session_data.get("prompt", ""),
                                "prompt": session_data.get("prompt", ""),
                                "state": state,
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
            elif name == "delete_instruction":
                inst_id = arguments.get("id")
                if not inst_id:
                    return [TextContent(type="text", text="Error: 'id' is required")]
                try:
                    res = await run_with_timeout(delete_instruction, inst_id)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error deleting instruction: {str(e)}")]
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
            asyncio.create_task(background_poll_sessions())
            async with stdio_server() as (read_stream, write_stream):
                await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())

        asyncio.run(run_mcp_stdio())
    else:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8000)
