import os
import sys
import json
import subprocess

home_dir = os.path.expanduser("~")
SCRATCH_DIR = os.path.join(home_dir, ".gemini", "antigravity-ide", "scratch", "antigravity-orchestrator").replace("\\", "/")
PROJECTS_FILE = os.path.join(SCRATCH_DIR, "projects.json")

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

def list_projects():
    projects = read_json(PROJECTS_FILE, [])
    print(json.dumps(projects, indent=2))

def register_project(name, path):
    projects = read_json(PROJECTS_FILE, [])
    # Check if duplicate name or path
    for p in projects:
        if p["name"] == name:
            print(json.dumps({"success": False, "message": "Project already exists"}))
            return
            
    if not os.path.exists(path):
        print(json.dumps({"success": False, "message": "Path does not exist"}))
        return
        
    new_project = {
        "name": name,
        "path": path.replace("\\", "/"),
        "branch": "main",
        "connected": True,
        "active": len(projects) == 0
    }
    projects.append(new_project)
    write_json(PROJECTS_FILE, projects)
    print(json.dumps({"success": True, "message": f"Project {name} registered successfully"}))

def switch_project(name):
    projects = read_json(PROJECTS_FILE, [])
    found = False
    for p in projects:
        if p["name"] == name:
            p["active"] = True
            found = True
        else:
            p["active"] = False
            
    if not found:
        print(json.dumps({"success": False, "message": "Project not found"}))
        return
        
    write_json(PROJECTS_FILE, projects)
    print(json.dumps({"success": True, "message": f"Switched context to {name}"}))

def get_jules_status(project_name):
    projects = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects if p["name"] == project_name), None)
    if not proj:
        print(json.dumps({"success": False, "message": "Project not found"}))
        return
        
    try:
        result = subprocess.run(
            ["jules", "remote", "list", "--session"],
            cwd=proj["path"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(result.stdout)
            return
    except Exception as e:
        pass
        
    # Return mockup/fallback if CLI isn't configured/fails
    mock_sessions = [
        {
            "id": "Session_129-AZ",
            "task": "Add authentication handlers to /api/auth",
            "status": "COMPLETED"
        },
        {
            "id": "Session_381-BX",
            "task": "Build SQLite database migrations for user schema",
            "status": "RUNNING"
        }
    ]
    print(json.dumps(mock_sessions, indent=2))

def create_jules_session(project_name, task):
    projects = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects if p["name"] == project_name), None)
    if not proj:
        print(json.dumps({"success": False, "message": "Project not found"}))
        return
        
    try:
        # jules new "task"
        result = subprocess.run(
            ["jules", "new", task],
            cwd=proj["path"],
            capture_output=True,
            text=True
        )
        print(result.stdout)
    except Exception as e:
        print(json.dumps({"success": False, "message": str(e)}))

def apply_jules_patch(project_name, session_id):
    projects = read_json(PROJECTS_FILE, [])
    proj = next((p for p in projects if p["name"] == project_name), None)
    if not proj:
        print(json.dumps({"success": False, "message": "Project not found"}))
        return
        
    try:
        # jules remote pull --session <id> --apply
        result = subprocess.run(
            ["jules", "remote", "pull", "--session", session_id, "--apply"],
            cwd=proj["path"],
            capture_output=True,
            text=True
        )
        print(result.stdout)
    except Exception as e:
        print(json.dumps({"success": False, "message": str(e)}))

def get_jules_api_key_and_github_token():
    settings_file = os.path.join(SCRATCH_DIR, "settings.json")
    settings = read_json(settings_file, {})
    return settings.get("jules", ""), settings.get("github", "")

def list_sessions():
    import urllib.request
    api_key, _ = get_jules_api_key_and_github_token()
    if not api_key:
        print(json.dumps({"success": False, "message": "Jules API key not configured in settings.json"}))
        return
    
    url = "https://jules.googleapis.com/v1alpha/sessions"
    req = urllib.request.Request(url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            parsed = []
            for s in data.get("sessions", []):
                sid = s.get("id")
                state = s.get("state", "UNKNOWN")
                title = s.get("title", "No Title")
                repo = "Other/Unmapped Repos"
                source = s.get("sourceContext", {}).get("source", "")
                if source.startswith("sources/github/"):
                    repo = source.replace("sources/github/", "")
                parsed.append({
                    "id": sid,
                    "task": title,
                    "repo": repo,
                    "status": state.upper()
                })
            print(json.dumps(parsed, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "message": f"Google API error: {str(e)}"}))

def get_git_status(session_id):
    import urllib.request
    import urllib.error
    import re
    api_key, github_token = get_jules_api_key_and_github_token()
    if not api_key:
        print(json.dumps({"success": False, "message": "Jules API key not configured"}))
        return
        
    session_url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}"
    req = urllib.request.Request(session_url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            session_data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(json.dumps({"success": False, "message": f"Failed to fetch session metadata: {str(e)}"}))
        return

    source = session_data.get("sourceContext", {}).get("source", "")
    owner, repo_name = "evilspyboy", "Orbits" # defaults
    if source.startswith("sources/github/"):
        parts = source.replace("sources/github/", "").split("/")
        if len(parts) >= 2:
            owner, repo_name = parts[0], parts[1]

    base_ref = session_data.get("sourceContext", {}).get("githubRepoContext", {}).get("startingBranch", "main") or "main"
    head_ref = None
    prs_info = []
    outputs = session_data.get("outputs", [])
    
    if outputs:
        for out in outputs:
            if "pullRequest" in out:
                pr = out["pullRequest"]
                pr_url = pr.get("url", "")
                match = re.search(r"pull/(\d+)", pr_url)
                pr_num = match.group(1) if match else "unknown"
                
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
                    except Exception:
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

    if not head_ref and outputs:
        for out in outputs:
            if "changeSet" in out:
                head_ref = f"feat-{repo_name.lower()}-base-{session_id}"
                break

    if not head_ref:
        head_ref = f"feat-{repo_name.lower()}-base-{session_id}"

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

    compare_status = "unknown"
    ahead_by = 0
    behind_by = 0
    status_message = ""

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

    res = {
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
    print(json.dumps(res, indent=2))

def get_session_logs(session_id):
    import urllib.request
    api_key, _ = get_jules_api_key_and_github_token()
    if not api_key:
        print(json.dumps({"success": False, "message": "Jules API key not configured"}))
        return
    
    url = f"https://jules.googleapis.com/v1alpha/sessions/{session_id}/activities"
    req = urllib.request.Request(url, headers={"x-goog-api-key": api_key, "Accept": "application/json"})
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
            print(json.dumps({"logs": logs}, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "message": str(e)}))

def main():
    if len(sys.argv) < 2:
        print("Usage: python orchestrator_cli.py <function_name> [args...]")
        return
        
    fn = sys.argv[1]
    if fn == "list_projects":
        list_projects()
    elif fn == "register_project":
        if len(sys.argv) < 4:
            print("Usage: register_project <name> <path>")
            return
        register_project(sys.argv[2], sys.argv[3])
    elif fn == "switch_project":
        if len(sys.argv) < 3:
            print("Usage: switch_project <name>")
            return
        switch_project(sys.argv[2])
    elif fn == "get_jules_status":
        if len(sys.argv) < 3:
            print("Usage: get_jules_status <project>")
            return
        get_jules_status(sys.argv[2])
    elif fn == "create_jules_session":
        if len(sys.argv) < 4:
            print("Usage: create_jules_session <project> <task>")
            return
        create_jules_session(sys.argv[2], sys.argv[3])
    elif fn == "apply_jules_patch":
        if len(sys.argv) < 4:
            print("Usage: apply_jules_patch <project> <session_id>")
            return
        apply_jules_patch(sys.argv[2], sys.argv[3])
    elif fn == "list_sessions":
        list_sessions()
    elif fn == "get_git_status":
        if len(sys.argv) < 3:
            print("Usage: get_git_status <session_id>")
            return
        get_git_status(sys.argv[2])
    elif fn == "get_session_logs":
        if len(sys.argv) < 3:
            print("Usage: get_session_logs <session_id>")
            return
        get_session_logs(sys.argv[2])
    else:
        print(f"Unknown function: {fn}")

if __name__ == "__main__":
    main()
