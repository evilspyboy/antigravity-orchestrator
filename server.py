import os
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
ARCHIVED_SESSIONS_FILE = os.path.join(SCRATCH_DIR, "archived_sessions.json")

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

class ArchiveInput(BaseModel):
    session_id: str

class CreateSessionInput(BaseModel):
    repo: str
    task: str
    branch: Optional[str] = "main"

# Helper to run Git branch detection
def get_git_branch(path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True
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
def get_jules_sessions(project: str, show_archived: bool = False):
    import urllib.request
    settings = read_json(SETTINGS_FILE, {})
    api_key = settings.get("jules")
    if not api_key:
        raise HTTPException(status_code=400, detail="Jules API key not configured")
    
    url = "https://jules.googleapis.com/v1alpha/sessions"
    req = urllib.request.Request(
        url,
        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            parsed = []
            archived = read_json(ARCHIVED_SESSIONS_FILE, [])
            
            for s in data.get("sessions", []):
                sid = s.get("id")
                if not show_archived and sid in archived:
                    continue
                state = s.get("state", "UNKNOWN")
                title = s.get("title", "No Title")
                
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
                        print("Error parsing timestamp:", te)
                        last_active = update_time_str
                
                status = state
                if state == "AWAITING_USER_FEEDBACK":
                    act_url = f"https://jules.googleapis.com/v1alpha/sessions/{sid}/activities"
                    act_req = urllib.request.Request(
                        act_url,
                        headers={"x-goog-api-key": api_key, "Accept": "application/json"}
                    )
                    try:
                        with urllib.request.urlopen(act_req) as act_resp:
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
                
                parsed.append({
                    "id": sid,
                    "task": title,
                    "repo": repo,
                    "status": status.upper(),
                    "logs": [f"Last active: {last_active}"],
                    "is_archived": sid in archived
                })
            return parsed
    except Exception as e:
        print("Jules API error:", e)
        return [
            {
                "id": "Error",
                "task": f"Jules API error: {str(e)}",
                "repo": "System Error",
                "status": "FAILED",
                "logs": ["Check if Jules API key in Settings is valid."]
            }
        ]

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
        with urllib.request.urlopen(req) as response:
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
        with urllib.request.urlopen(req) as resp:
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
        with urllib.request.urlopen(req) as resp:
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
                    with urllib.request.urlopen(gh_req) as gh_resp:
                        gh_data = json.loads(gh_resp.read().decode('utf-8'))
                        state = gh_data.get("state", "closed")
                        merged = gh_data.get("merged", False)
                        if state == "open":
                            status_text = "Open"
                        else:
                            status_text = "Merged" if merged else "Closed"
                except Exception as ghe:
                    print("GitHub API pull request check failed:", ghe)
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
            with urllib.request.urlopen(comp_req) as comp_resp:
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
                capture_output=True,
                timeout=5
            )
            if check_branch.returncode == 0:
                ahead_res = subprocess.run(
                    ["git", "rev-list", "--count", f"{base_ref}..{head_ref}"],
                    cwd=proj["path"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                behind_res = subprocess.run(
                    ["git", "rev-list", "--count", f"{head_ref}..{base_ref}"],
                    cwd=proj["path"],
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
        with urllib.request.urlopen(req) as response:
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
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            return {"success": True, "response": data}
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=e.code, detail=f"Google API Error: {e.read().decode('utf-8')}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/sessions/{session_id}/monitor")
def monitor_jules_session(session_id: str):
    try:
        script_path = os.path.join(SCRATCH_DIR, "poll_session.py")
        import sys
        subprocess.Popen([sys.executable, script_path, session_id])
        return {"success": True, "message": f"Started background monitoring for session {session_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start monitor: {str(e)}")

@app.post("/api/jules/sessions/archive")
def archive_jules_session(input_data: ArchiveInput):
    try:
        archived = read_json(ARCHIVED_SESSIONS_FILE, [])
        if input_data.session_id not in archived:
            archived.append(input_data.session_id)
            write_json(ARCHIVED_SESSIONS_FILE, archived)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jules/sessions/unarchive")
def unarchive_jules_session(input_data: ArchiveInput):
    try:
        archived = read_json(ARCHIVED_SESSIONS_FILE, [])
        if input_data.session_id in archived:
            archived.remove(input_data.session_id)
            write_json(ARCHIVED_SESSIONS_FILE, archived)
        return {"success": True}
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

@app.post("/api/jules/sessions/archive")
def archive_session(input_data: ArchiveInput):
    archived = read_json(ARCHIVED_SESSIONS_FILE, [])
    if input_data.session_id not in archived:
        archived.append(input_data.session_id)
        write_json(ARCHIVED_SESSIONS_FILE, archived)
    return {"success": True}

@app.post("/api/jules/sessions/unarchive")
def unarchive_session(input_data: ArchiveInput):
    archived = read_json(ARCHIVED_SESSIONS_FILE, [])
    if input_data.session_id in archived:
        archived.remove(input_data.session_id)
        write_json(ARCHIVED_SESSIONS_FILE, archived)
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
            shell=True
        )
        if result.returncode == 0:
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
                        "properties": {}
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
                    name="archive_session",
                    description="Archive a completed/failed Jules session by its ID to hide it from the active dashboard.",
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
                    name="unarchive_session",
                    description="Unarchive a previously archived Jules session by its ID to restore it to the active dashboard.",
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
                )
            ]


        @mcp_server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            if name == "list_sessions":
                try:
                    sessions = get_jules_sessions(project="")
                    return [TextContent(type="text", text=json.dumps(sessions, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error listing sessions: {str(e)}")]
            elif name == "get_git_status":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    status = get_jules_git_status(session_id)
                    return [TextContent(type="text", text=json.dumps(status, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting git status: {str(e)}")]
            elif name == "get_session_logs":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    logs = get_jules_logs(session_id)
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
                    
                    result = subprocess.run(
                        [JULES_BIN, "new", "--repo", repo, task],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        env=env,
                        shell=False
                    )
                    if result.returncode == 0:
                        return [TextContent(type="text", text=f"Success: {result.stdout.strip()}")]
                    else:
                        return [TextContent(type="text", text=f"Error (exit code {result.returncode}): {result.stderr or result.stdout}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error creating session: {str(e)}")]
            elif name == "archive_session":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    archived = read_json(ARCHIVED_SESSIONS_FILE, [])
                    if session_id not in archived:
                        archived.append(session_id)
                        write_json(ARCHIVED_SESSIONS_FILE, archived)
                    return [TextContent(type="text", text=f"Success: Session {session_id} archived")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error archiving session: {str(e)}")]
            elif name == "unarchive_session":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    archived = read_json(ARCHIVED_SESSIONS_FILE, [])
                    if session_id in archived:
                        archived.remove(session_id)
                        write_json(ARCHIVED_SESSIONS_FILE, archived)
                    return [TextContent(type="text", text=f"Success: Session {session_id} unarchived")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error unarchiving session: {str(e)}")]
            elif name == "list_repos":
                try:
                    repos = get_jules_repos()
                    return [TextContent(type="text", text=json.dumps(repos, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error listing repos: {str(e)}")]
            elif name == "approve_plan":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    res = approve_jules_plan(session_id)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error approving plan: {str(e)}")]
            elif name == "apply_patch":
                session_id = arguments.get("session_id")
                project = arguments.get("project")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    res = apply_jules_patch(session_id, ApplyInput(project=project) if project else None)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error applying patch: {str(e)}")]
            elif name == "get_session_plan":
                session_id = arguments.get("session_id")
                if not session_id:
                    return [TextContent(type="text", text="Error: session_id is required")]
                try:
                    res = get_jules_plan(session_id)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting session plan: {str(e)}")]
            elif name == "get_auth_status":
                try:
                    res = get_jules_auth_status()
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting auth status: {str(e)}")]
            elif name == "jules_login":
                try:
                    res = jules_login()
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error running jules login: {str(e)}")]
            elif name == "list_stitch_drafts":
                project = arguments.get("project", "")
                try:
                    res = get_stitch_drafts(project=project)
                    return [TextContent(type="text", text=f"Success: {json.dumps(res, indent=2)}")]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error listing stitch drafts: {str(e)}")]
            elif name == "generate_stitch_stub":
                prompt = arguments.get("prompt")
                project = arguments.get("project")
                if not prompt or not project:
                    return [TextContent(type="text", text="Error: prompt and project are required")]
                try:
                    res = generate_ui_stub(GenerateUIInput(prompt=prompt, project=project))
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
                    res = export_stitch_design(ExportInput(project=project, target_dir=target_dir, format=fmt))
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
                    res = save_instruction(InstructionInput(
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
                    res = get_instructions()
                    return [TextContent(type="text", text=json.dumps(res, indent=2))]
                except Exception as e:
                    return [TextContent(type="text", text=f"Error getting instructions: {str(e)}")]
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        async def run_mcp_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())

        asyncio.run(run_mcp_stdio())
    else:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8000)
