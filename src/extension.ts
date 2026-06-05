import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { execSync, execFile } from 'child_process';
import * as https from 'https';
import * as os from 'os';

const homeDir = os.homedir();
const SCRATCH_DIR = path.join(homeDir, '.gemini', 'antigravity-ide', 'scratch', 'antigravity-orchestrator').replace(/\\/g, '/');
const isWindows = process.platform === 'win32';
const JULES_BIN = path.join(SCRATCH_DIR, 'bin', isWindows ? 'jules.exe' : 'jules').replace(/\\/g, '/');
const PROJECTS_FILE = path.join(SCRATCH_DIR, "projects.json");
const SETTINGS_FILE = path.join(SCRATCH_DIR, "settings.json");
const INSTRUCTIONS_FILE = path.join(SCRATCH_DIR, "instructions.json");

const DEFAULT_SETTINGS = {
    gemini: "",
    github: "",
    jules: "",
    root: path.join(homeDir, 'projects').replace(/\\/g, '/')
};

// Helper JSON readers
function readJson(filePath: string, defaultValue: any) {
    if (!fs.existsSync(filePath)) {
        return defaultValue;
    }
    try {
        const content = fs.readFileSync(filePath, 'utf-8');
        return JSON.parse(content);
    } catch {
        return defaultValue;
    }
}

function writeJson(filePath: string, data: any) {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf-8');
}

function httpsGet(url: string, headers: any): Promise<string> {
    return new Promise((resolve, reject) => {
        const parsedUrl = new URL(url);
        const options = {
            hostname: parsedUrl.hostname,
            path: parsedUrl.pathname + parsedUrl.search,
            method: 'GET',
            headers
        };
        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => resolve(data));
        });
        req.on('error', (e) => reject(e));
        req.end();
    });
}

function httpsPost(url: string, headers: any, body: string): Promise<string> {
    return new Promise((resolve, reject) => {
        const parsedUrl = new URL(url);
        const options = {
            hostname: parsedUrl.hostname,
            path: parsedUrl.pathname + parsedUrl.search,
            method: 'POST',
            headers
        };
        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', () => resolve(data));
        });
        req.on('error', (e) => reject(e));
        req.write(body);
        req.end();
    });
}

// Git Helper
function getGitBranch(projectPath: string): string {
    try {
        const branch = execSync('git branch --show-current', { cwd: projectPath, encoding: 'utf-8' });
        return branch.trim() || 'main';
    } catch {
        return 'main';
    }
}

// Shared Webview Message Router
async function handleWebviewMessage(message: any, webview: vscode.Webview) {
    const { command, method, body, requestId } = message;

    try {
        let responseData: any = null;

        if (command === '/api/projects') {
            if (method === 'GET') {
                const projects = readJson(PROJECTS_FILE, []);
                for (const p of projects) {
                    if (fs.existsSync(p.path)) {
                        p.branch = getGitBranch(p.path);
                        p.connected = true;
                    } else {
                        p.connected = false;
                    }
                }
                responseData = projects;
            } else if (method === 'POST') {
                const projects = readJson(PROJECTS_FILE, []);
                const nameExists = projects.some((p: any) => p.name === body.name);
                if (nameExists) {
                    throw new Error("Project name already exists.");
                }
                if (!fs.existsSync(body.path)) {
                    throw new Error("Project path does not exist on local disk.");
                }
                const newProj = {
                    name: body.name,
                    path: body.path.replace(/\\/g, '/'),
                    branch: getGitBranch(body.path),
                    connected: true,
                    active: projects.length === 0
                };
                projects.push(newProj);
                writeJson(PROJECTS_FILE, projects);
                responseData = { success: true };
            }
        } 
        
        else if (command === '/api/projects/switch') {
            const projects = readJson(PROJECTS_FILE, []);
            let found = false;
            for (const p of projects) {
                if (p.name === body.name) {
                    p.active = true;
                    found = true;
                } else {
                    p.active = false;
                }
            }
            if (!found) {
                throw new Error("Project not found");
            }
            writeJson(PROJECTS_FILE, projects);
            responseData = { success: true };
        } 
        
        else if (command === '/api/settings') {
            if (method === 'GET') {
                responseData = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
            } else if (method === 'POST') {
                writeJson(SETTINGS_FILE, body);
                const envFile = path.join(SCRATCH_DIR, ".env");
                fs.writeFileSync(envFile, `GITHUB_TOKEN=${body.github}\nJULES_API_KEY=${body.jules || ""}\n`, 'utf-8');
                responseData = { success: true };
            }
        } 
        
        else if (command.startsWith('/api/stitch/drafts')) {
            const stitchDir = path.join(SCRATCH_DIR, "stitch");
            const drafts: any[] = [];
            if (fs.existsSync(stitchDir)) {
                const folders = fs.readdirSync(stitchDir);
                for (const f of folders) {
                    const folderPath = path.join(stitchDir, f);
                    if (fs.statSync(folderPath).isDirectory()) {
                        const codeFile = path.join(folderPath, "code.html");
                        const designFile = path.join(folderPath, "DESIGN.md");
                        let codeContent = "";
                        if (fs.existsSync(codeFile)) {
                            codeContent = fs.readFileSync(codeFile, 'utf-8');
                        } else if (fs.existsSync(designFile)) {
                            codeContent = fs.readFileSync(designFile, 'utf-8');
                        }
                        const stat = fs.statSync(folderPath);
                        drafts.push({
                            name: f.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
                            folder_name: f,
                            timestamp: stat.mtime.toISOString().split('T')[0] + ' ' + stat.mtime.toTimeString().split(' ')[0],
                            code: codeContent
                        });
                    }
                }
            }
            responseData = drafts;
        } 
        
        else if (command === '/api/stitch/generate') {
            const timestampStr = new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 14);
            const targetDir = path.join(SCRATCH_DIR, "stitch", `stitch_generated_${timestampStr}`);
            fs.mkdirSync(targetDir, { recursive: true });
            const mockCode = `<!-- Generated UI from prompt: "${body.prompt}" -->\n<div class="p-6 bg-slate-900 border border-slate-800 rounded-xl">\n    <h3 class="text-lg font-bold text-primary">UI Stub: ${body.prompt.slice(0, 30)}...</h3>\n    <p class="text-sm text-on-surface-variant mt-2">Design system parameters imported successfully.</p>\n</div>`;
            fs.writeFileSync(path.join(targetDir, "code.html"), mockCode, 'utf-8');
            responseData = { success: true };
        } 
        
        else if (command === '/api/stitch/export') {
            const projectsList = readJson(PROJECTS_FILE, []);
            const proj = projectsList.find((p: any) => p.name === body.project);
            if (!proj) {
                throw new Error("Target project not found");
            }
            const stitchDir = path.join(SCRATCH_DIR, "stitch");
            if (!fs.existsSync(stitchDir)) {
                throw new Error("No drafts folder exists");
            }
            const subdirs = fs.readdirSync(stitchDir)
                .map(d => path.join(stitchDir, d))
                .filter(d => fs.statSync(d).isDirectory());
            if (subdirs.length === 0) {
                throw new Error("No drafts found to export");
            }
            // Sort by mtime
            subdirs.sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
            const latestDir = subdirs[0];
            let codePath = path.join(latestDir, "code.html");
            if (!fs.existsSync(codePath)) {
                codePath = path.join(latestDir, "DESIGN.md");
                if (!fs.existsSync(codePath)) {
                    throw new Error("No exportable code in draft");
                }
            }
            const destDir = path.join(proj.path, body.target_dir);
            fs.mkdirSync(destDir, { recursive: true });
            const filename = body.format === 'react' ? 'Component.tsx' : 'index.html';
            const destPath = path.join(destDir, filename);
            fs.copyFileSync(codePath, destPath);
            responseData = { success: true, message: `Successfully exported to ${destPath}` };
        } 
        
        else if (command === '/api/jules/repos') {
            const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
            const apiKey = settings.jules || "";
            const env = { ...process.env };
            if (apiKey) {
                env["JULES_API_KEY"] = apiKey;
            }
            env["CI"] = "true";
            env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1";
            
            responseData = await new Promise((resolve, reject) => {
                const { execFile } = require('child_process');
                execFile(JULES_BIN, ["remote", "list", "--repo"], { env, stdio: ['ignore', 'pipe', 'pipe'] } as any, (error: any, stdout: string, stderr: string) => {
                    if (error) {
                        reject(new Error(stderr || stdout || error.message));
                    } else {
                        const repos = stdout.trim().split(/\r?\n/).map(r => r.trim()).filter(Boolean);
                        resolve(repos);
                    }
                });
            });
        }

        else if (command.startsWith('/api/jules/sessions')) {
            if (command === '/api/jules/sessions/archive') {
                const archivedFile = path.join(SCRATCH_DIR, 'archived_sessions.json');
                const archived = readJson(archivedFile, []);
                if (!archived.includes(body.session_id)) {
                    archived.push(body.session_id);
                    writeJson(archivedFile, archived);
                }
                responseData = { success: true };
            } 
            
            else if (command === '/api/jules/sessions/unarchive') {
                const archivedFile = path.join(SCRATCH_DIR, 'archived_sessions.json');
                let archived = readJson(archivedFile, []);
                archived = archived.filter((id: string) => id !== body.session_id);
                writeJson(archivedFile, archived);
                responseData = { success: true };
            }

            else if (command === '/api/jules/sessions' && method === 'POST') {
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                const env = { ...process.env };
                if (apiKey) {
                    env["JULES_API_KEY"] = apiKey;
                }
                env["CI"] = "true";
                env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1";
                
                responseData = await new Promise((resolve, reject) => {
                    execFile(JULES_BIN, ["new", "--repo", body.repo, body.task], { env, stdio: ['ignore', 'pipe', 'pipe'] } as any, (error: any, stdout: string, stderr: string) => {
                        if (error) {
                            reject(new Error(stderr || stdout || error.message));
                        } else {
                            resolve({ success: true, message: stdout.trim() });
                        }
                    });
                });
            }
            
            else if (command.includes('/logs')) {
                const sessionId = command.split('/')[4];
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                if (!apiKey) {
                    throw new Error("Jules API key not configured.");
                }
                const url = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}/activities`;
                const responseText = await httpsGet(url, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                const data = JSON.parse(responseText);
                const logs: string[] = [];
                for (const act of data.activities || []) {
                    const time = act.createTime ? new Date(act.createTime).toLocaleTimeString() : "";
                    const prefix = time ? `[${time}]` : "";
                    if (act.agentMessaged && act.agentMessaged.agentMessage) {
                        logs.push(`${prefix} Jules: ${act.agentMessaged.agentMessage}`);
                    } else if (act.userMessaged && act.userMessaged.userMessage) {
                        logs.push(`${prefix} User: ${act.userMessaged.userMessage}`);
                    } else if (act.progressUpdated) {
                        const title = act.progressUpdated.title || "";
                        const desc = act.progressUpdated.description || "";
                        logs.push(`${prefix} Progress: ${title}${desc ? ' - ' + desc : ''}`);
                    } else if (act.planGenerated) {
                        logs.push(`${prefix} Plan Generated.`);
                    } else if (act.planApproved) {
                        logs.push(`${prefix} Plan Approved.`);
                    }
                }
                if (logs.length === 0) {
                    logs.push("[info] No activities logged yet.");
                }
                responseData = { logs };
            } else if (command.includes('/patch')) {
                const sessionId = command.split('/')[4];
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const env = { 
                    ...process.env, 
                    JULES_API_KEY: settings.jules || "",
                    CI: "true",
                    CLOUDSDK_CORE_DISABLE_PROMPTS: "1"
                };
                
                const { exec } = require('child_process');
                const output: string = await new Promise((resolve, reject) => {
                    exec(`"${JULES_BIN}" remote pull --session ${sessionId}`, { cwd: SCRATCH_DIR, env, timeout: 20000, shell: true }, (error: any, stdout: string, stderr: string) => {
                        if (error) {
                            reject(new Error(stderr || stdout || error.message));
                        } else {
                            resolve(stdout);
                        }
                    });
                });
                responseData = { patch: output };
            } else if (command.includes('/apply')) {
                const sessionId = command.split('/')[4];
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                if (!apiKey) {
                    throw new Error("Jules API key not configured.");
                }

                // 1. Fetch session details from Google API to determine the repository source
                const sessionUrl = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}`;
                const sessionText = await httpsGet(sessionUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                const sessionData = JSON.parse(sessionText);
                
                let repoName = "";
                const source = sessionData.sourceContext?.source || "";
                if (source.startsWith("sources/github/")) {
                    const repoParts = source.replace("sources/github/", "").split("/");
                    repoName = repoParts[repoParts.length - 1]; // e.g. "CityConnect"
                }

                const projectsList = readJson(PROJECTS_FILE, []);
                // Match project by name (case-insensitive) or ending path segment
                let proj = projectsList.find((p: any) => 
                    p.name.toLowerCase() === repoName.toLowerCase() || 
                    p.path.toLowerCase().endsWith("/" + repoName.toLowerCase()) ||
                    p.path.toLowerCase().endsWith("\\" + repoName.toLowerCase())
                );
                
                if (!proj && body && body.project) {
                    proj = projectsList.find((p: any) => p.name === body.project);
                }

                const targetCwd = (proj && fs.existsSync(proj.path)) ? proj.path : null;
                if (!targetCwd) {
                    throw new Error(`Local project directory for repository "${repoName || 'unknown'}" is not registered or does not exist locally. Please register and clone it first.`);
                }
                
                const env = { 
                    ...process.env, 
                    JULES_API_KEY: apiKey,
                    CI: "true",
                    CLOUDSDK_CORE_DISABLE_PROMPTS: "1"
                };
                
                const { exec } = require('child_process');
                const output: string = await new Promise((resolve, reject) => {
                    exec(`"${JULES_BIN}" remote pull --session ${sessionId} --apply`, { cwd: targetCwd, env, timeout: 30000, shell: true }, (error: any, stdout: string, stderr: string) => {
                        if (error) {
                            reject(new Error(stderr || stdout || error.message));
                        } else {
                            resolve(stdout);
                        }
                    });
                });
                responseData = { message: `Successfully applied patch to ${proj.name}: ${output}` };
            } else if (command.includes('/plan')) {
                const sessionId = command.split('/')[4];
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                if (!apiKey) {
                    throw new Error("Jules API key not configured.");
                }
                const url = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}/activities`;
                const responseText = await httpsGet(url, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                const data = JSON.parse(responseText);
                let planSteps = null;
                for (const act of data.activities || []) {
                    if (act.planGenerated && act.planGenerated.plan) {
                        planSteps = act.planGenerated.plan.steps || [];
                        break;
                    }
                }
                if (!planSteps) {
                    throw new Error("No plan found in session activities.");
                }
                responseData = { success: true, steps: planSteps };
            } else if (command.includes('/approve')) {
                const sessionId = command.split('/')[4];
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                if (!apiKey) {
                    throw new Error("Jules API key not configured.");
                }
                const url = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}:approvePlan`;
                const responseText = await httpsPost(url, { 
                    "x-goog-api-key": apiKey, 
                    "Content-Type": "application/json", 
                    "Accept": "application/json" 
                }, "{}");
                responseData = { success: true, response: JSON.parse(responseText) };
            } else if (command.includes('/monitor')) {
                const sessionId = command.split('/')[4];
                const scriptPath = path.join(SCRATCH_DIR, "poll_session.py");
                const { spawn } = require('child_process');
                
                // Spawn poll_session.py in background
                const child = spawn('python', [scriptPath, sessionId]);
                
                child.stdout.on('data', (data: any) => {
                    console.log(`[Jules Monitor stdout]: ${data}`);
                });
                
                child.on('close', (code: number) => {
                    if (code === 0) {
                        vscode.window.showInformationMessage(`Jules Session ${sessionId} completed successfully!`);
                    } else if (code === 1) {
                        vscode.window.showErrorMessage(`Jules Session ${sessionId} failed.`);
                    } else if (code === 2) {
                        vscode.window.showInformationMessage(`Jules Session ${sessionId} is awaiting plan approval or user feedback.`, "View Plan").then(selection => {
                            if (selection === "View Plan") {
                                vscode.commands.executeCommand('antigravity-orchestrator.openDashboard');
                            }
                        });
                    }
                });
                responseData = { success: true, message: `Monitoring session ${sessionId} in background.` };
            } else if (command.includes('/git-status')) {
                const sessionId = command.split('/')[4];
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                const githubToken = settings.github || "";
                if (!apiKey) {
                    throw new Error("Jules API key not configured.");
                }

                // 1. Fetch session details to get the source repo and branches
                const sessionUrl = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}`;
                const sessionText = await httpsGet(sessionUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                const sessionData = JSON.parse(sessionText);

                // Extract base/head branches and repository details
                const source = sessionData.sourceContext?.source || "";
                let owner = "evilspyboy";
                let repoName = "Orbits"; // defaults
                if (source.startsWith("sources/github/")) {
                    const parts = source.replace("sources/github/", "").split("/");
                    if (parts.length >= 2) {
                        owner = parts[0];
                        repoName = parts[1];
                    }
                }

                // Find base branch
                let baseRef = sessionData.sourceContext?.githubRepoContext?.startingBranch || "main";

                // Find head branch from outputs (PR or changeset)
                let headRef: string | null = null;
                const prsInfo: any[] = [];
                const outputs = sessionData.outputs || [];
                for (const out of outputs) {
                    if (out.pullRequest) {
                        const pr = out.pullRequest;
                        const prUrl = pr.url || "";
                        const match = prUrl.match(/pull\/(\d+)/);
                        const prNum = match ? match[1] : "unknown";

                        let state = "closed";
                        let merged = false;
                        let statusText = "Status Unknown";
                        if (githubToken && prNum !== "unknown") {
                            const ghUrl = `https://api.github.com/repos/${owner}/${repoName}/pulls/${prNum}`;
                            const ghHeaders = {
                                "Accept": "application/vnd.github+json",
                                "User-Agent": "Antigravity-Orchestrator",
                                "Authorization": `Bearer ${githubToken}`
                            };
                            try {
                                const ghText = await httpsGet(ghUrl, ghHeaders);
                                const ghData = JSON.parse(ghText);
                                if (ghData.message) {
                                    statusText = "Created (Auth scopes required)";
                                } else {
                                    state = ghData.state || "closed";
                                    merged = ghData.merged || false;
                                    if (state === "open") {
                                        statusText = "Open";
                                    } else {
                                        statusText = merged ? "Merged" : "Closed";
                                    }
                                }
                            } catch (ghe: any) {
                                console.error("GitHub API pull request check failed:", ghe);
                                statusText = "Created (Auth scopes required)";
                            }
                        } else {
                            statusText = "Created";
                        }

                        prsInfo.push({
                            number: prNum,
                            url: prUrl,
                            status_text: statusText
                        });
                        if (pr.headRef) {
                            headRef = pr.headRef;
                        }
                        if (pr.baseRef) {
                            baseRef = pr.baseRef;
                        }
                    }
                }

                // If no head_ref found in PR, check changeset
                if (!headRef) {
                    for (const out of outputs) {
                        if (out.changeSet) {
                            headRef = `feat-${repoName.toLowerCase()}-base-${sessionId}`;
                            break;
                        }
                    }
                }

                // If still no head_ref, try a sensible fallback
                if (!headRef) {
                    headRef = `feat-${repoName.toLowerCase()}-base-${sessionId}`;
                }

                // 2. Local status: is local branch active?
                const projectsList = readJson(PROJECTS_FILE, []);
                let proj = projectsList.find((p: any) => 
                    p.name.toLowerCase() === repoName.toLowerCase() || 
                    p.path.toLowerCase().replace(/\\/g, "/").endsWith("/" + repoName.toLowerCase())
                );

                let isLocalActive = false;
                let localProjectRegistered = false;
                let localCurrentBranch: string | null = null;
                if (proj) {
                    localProjectRegistered = true;
                    const localPath = proj.path;
                    if (fs.existsSync(localPath)) {
                        try {
                            const branchRes = execSync("git branch --show-current", { cwd: localPath, encoding: 'utf-8', timeout: 5000 });
                            localCurrentBranch = branchRes.trim();
                            isLocalActive = (localCurrentBranch === headRef);
                        } catch {
                            // ignore
                        }
                    }
                }

                // 3. Branch comparison: ahead/behind count
                let compareStatus = "unknown";
                let aheadBy = 0;
                let behindBy = 0;
                let statusMessage = "";

                if (githubToken && headRef) {
                    const compareUrl = `https://api.github.com/repos/${owner}/${repoName}/compare/${baseRef}...${headRef}`;
                    const ghHeaders = {
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "Antigravity-Orchestrator",
                        "Authorization": `Bearer ${githubToken}`
                    };
                    try {
                        const compText = await httpsGet(compareUrl, ghHeaders);
                        const compData = JSON.parse(compText);
                        if (compData.message) {
                            if (compData.message.toLowerCase() === "not found") {
                                compareStatus = "deleted";
                                statusMessage = "Branch deleted or merged on remote";
                            } else {
                                compareStatus = "error";
                                statusMessage = `GitHub Compare API error: ${compData.message}`;
                            }
                        } else {
                            compareStatus = compData.status || "unknown";
                            aheadBy = compData.ahead_by || 0;
                            behindBy = compData.behind_by || 0;

                            if (compareStatus === "ahead") {
                                statusMessage = `Ahead by ${aheadBy} commit${aheadBy > 1 ? 's' : ''}`;
                            } else if (compareStatus === "behind") {
                                statusMessage = `Behind by ${behindBy} commit${behindBy > 1 ? 's' : ''}`;
                            } else if (compareStatus === "diverged") {
                                statusMessage = `Diverged (Ahead by ${aheadBy}, Behind by ${behindBy})`;
                            } else if (compareStatus === "identical") {
                                statusMessage = "Identical/Up to date";
                            }
                        }
                    } catch (ce: any) {
                        compareStatus = "error";
                        statusMessage = ce.message || String(ce);
                    }
                }

                // Local fallback for comparison if GitHub API failed or was unauthorized, and repo exists locally
                if ((compareStatus === "unknown" || compareStatus === "error") && proj && fs.existsSync(proj.path) && headRef) {
                    try {
                        execSync(`git show-ref --verify refs/heads/${headRef}`, { cwd: proj.path, stdio: 'ignore', timeout: 5000 });
                        const aheadRes = execSync(`git rev-list --count ${baseRef}..${headRef}`, { cwd: proj.path, encoding: 'utf-8', timeout: 5000 }).trim();
                        const behindRes = execSync(`git rev-list --count ${headRef}..${baseRef}`, { cwd: proj.path, encoding: 'utf-8', timeout: 5000 }).trim();
                        
                        aheadBy = parseInt(aheadRes) || 0;
                        behindBy = parseInt(behindRes) || 0;

                        if (aheadBy > 0 && behindBy > 0) {
                            compareStatus = "diverged";
                            statusMessage = `Diverged locally (Ahead by ${aheadBy}, Behind by ${behindBy})`;
                        } else if (aheadBy > 0) {
                            compareStatus = "ahead";
                            statusMessage = `Ahead locally by ${aheadBy} commit${aheadBy > 1 ? 's' : ''}`;
                        } else if (behindBy > 0) {
                            compareStatus = "behind";
                            statusMessage = `Behind locally by ${behindBy} commit${behindBy > 1 ? 's' : ''}`;
                        } else {
                            compareStatus = "identical";
                            statusMessage = "Identical locally";
                        }
                    } catch {
                        // ignore
                    }
                }

                responseData = {
                    head_ref: headRef,
                    base_ref: baseRef,
                    prs: prsInfo,
                    is_local_active: isLocalActive,
                    local_project_registered: localProjectRegistered,
                    local_current_branch: localCurrentBranch,
                    compare_status: compareStatus,
                    ahead_by: aheadBy,
                    behind_by: behindBy,
                    status_message: statusMessage
                };
            } else {
                try {
                    const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                    const apiKey = settings.jules || "";
                    if (!apiKey) {
                        throw new Error("Jules API key not configured.");
                    }

                    // 1. Fetch sessions from Google API
                    const url = "https://jules.googleapis.com/v1alpha/sessions";
                    const responseText = await httpsGet(url, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                    const data = JSON.parse(responseText);
                    const parsed = [];
                    const archivedFile = path.join(SCRATCH_DIR, 'archived_sessions.json');
                    const archived = readJson(archivedFile, []);
                    const showArchived = command.includes('show_archived=true');

                    for (const s of data.sessions || []) {
                        const sid = s.id;
                        if (!showArchived && archived.includes(sid)) {
                            continue;
                        }
                        const state = s.state || "UNKNOWN";
                        const title = s.title || "No Title";
                        
                        // Extract repo from sourceContext.source
                        let repo = "Other/Unmapped Repos";
                        const source = s.sourceContext?.source || "";
                        if (source.startsWith("sources/github/")) {
                            repo = source.replace("sources/github/", "");
                        }

                        // Determine last active friendly string
                        let lastActive = "Unknown";
                        if (s.updateTime) {
                            const diffMs = Date.now() - new Date(s.updateTime).getTime();
                            const diffMin = Math.floor(diffMs / 60000);
                            if (diffMin < 1) {
                                lastActive = "Just now";
                            } else if (diffMin < 60) {
                                lastActive = `${diffMin}m ago`;
                            } else {
                                const diffHr = Math.floor(diffMin / 60);
                                if (diffHr < 24) {
                                    lastActive = `${diffHr}h ${diffMin % 60}m ago`;
                                } else {
                                    const diffDays = Math.floor(diffHr / 24);
                                    lastActive = `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
                                }
                            }
                        }

                        // Determine detailed status
                        let status = state;
                        if (state === "AWAITING_USER_FEEDBACK") {
                            try {
                                const actUrl = `https://jules.googleapis.com/v1alpha/sessions/${sid}/activities`;
                                const actText = await httpsGet(actUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                                const actData = JSON.parse(actText);
                                const activities = actData.activities || [];
                                
                                let lastSig = null;
                                for (let i = activities.length - 1; i >= 0; i--) {
                                    const act = activities[i];
                                    if (act.planGenerated) {
                                        lastSig = "planGenerated";
                                        break;
                                    } else if (act.planApproved) {
                                        lastSig = "planApproved";
                                        break;
                                    } else if (act.agentMessaged) {
                                        lastSig = "agentMessaged";
                                        break;
                                    }
                                }
                                if (lastSig === "planGenerated") {
                                    status = "AWAITING PLAN APPROVAL";
                                } else {
                                    status = "AWAITING USER FEEDBACK";
                                }
                            } catch (e) {
                                status = "AWAITING USER FEEDBACK";
                            }
                        }

                        parsed.push({
                            id: sid,
                            task: title,
                            repo: repo,
                            status: status.toUpperCase(),
                            logs: [`Last active: ${lastActive}`],
                            is_archived: archived.includes(sid)
                        });
                    }
                    responseData = parsed;
                } catch (error: any) {
                    console.error("Jules API error in extension host:", error);
                    responseData = [
                        { 
                            id: "Error", 
                            task: "Jules API Error: " + (error.message || error), 
                            repo: "System Error", 
                            status: "FAILED", 
                            logs: [
                                error.stack || "No stack trace available",
                                "Please check if the Jules API key in Settings is valid."
                            ] 
                        }
                    ];
                }
            }
    } else if (command === '/api/jules/auth-status') {
            try {
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const env = { 
                    ...process.env, 
                    JULES_API_KEY: settings.jules || "",
                    CI: "true",
                    CLOUDSDK_CORE_DISABLE_PROMPTS: "1"
                };
                // Check if user is logged into jules by executing session list.
                // If it fails with "did you forget to login?", it throws an error.
                execSync(`"${JULES_BIN}" remote list --session`, { timeout: 15000, encoding: 'utf-8', env });
                responseData = { logged_in: true };
            } catch (e: any) {
                // If output contains auth failure message, we are logged out.
                responseData = { logged_in: false };
            }
        }

        else if (command === '/api/jules/login') {
            // Open a terminal and run jules login
            const terminal = vscode.window.createTerminal("Jules Authentication");
            terminal.show();
            terminal.sendText("jules login");
            responseData = { success: true };
        }

        else if (command === '/api/knowledge/patterns') {
            responseData = [
                { name: "Glassmorphism Card styling", usage_count: 3, last_sync: "Just now", code: ".glass-card { background: rgba(15, 23, 42, 0.4); backdrop-filter: blur(12px); border: 1px solid rgba(70, 69, 84, 0.6); }" },
                { name: "OAuth2 FastAPI Handler", usage_count: 2, last_sync: "1 hour ago", code: "from fastapi.security import OAuth2PasswordBearer\noauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')" }
            ];
        }

        else if (command === '/api/instructions') {
            if (method === 'GET') {
                responseData = readJson(INSTRUCTIONS_FILE, []);
            } else if (method === 'POST') {
                const instructions = readJson(INSTRUCTIONS_FILE, []);
                if (body.id) {
                    const idx = instructions.findIndex((inst: any) => inst.id === body.id);
                    if (idx !== -1) {
                        instructions[idx] = { ...instructions[idx], ...body };
                    } else {
                        instructions.push(body);
                    }
                } else {
                    const newInst = {
                        id: 'inst_' + Math.random().toString(36).substring(7),
                        timestamp: new Date().toISOString().replace('T', ' ').substring(0, 19),
                        status: 'RUNNING',
                        ...body
                    };
                    instructions.push(newInst);
                }
                writeJson(INSTRUCTIONS_FILE, instructions);
                responseData = { success: true };
            }
        }

        // Send response back to webview
        webview.postMessage({
            requestId,
            data: responseData
        });

    } catch (err: any) {
        webview.postMessage({
            requestId,
            error: err.message || 'Unknown error occurred in extension host'
        });
    }
}

// Sidebar Webview View Provider
class OrchestratorWebviewViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'antigravity-orchestrator-explorer';

    constructor() {}

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ) {

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [vscode.Uri.file(SCRATCH_DIR)]
        };

        const indexHtmlPath = path.join(SCRATCH_DIR, 'index.html');
        if (fs.existsSync(indexHtmlPath)) {
            let htmlContent = fs.readFileSync(indexHtmlPath, 'utf-8');
            // Inject sidebar-mode styling hook
            htmlContent = htmlContent.replace('<body class="font-body-md">', '<body class="font-body-md sidebar-mode">');
            webviewView.webview.html = htmlContent;
        } else {
            webviewView.webview.html = `<h3>Error: index.html not found.</h3>`;
        }

        // Listen for messages from sidebar webview
        webviewView.webview.onDidReceiveMessage(
            async (message) => {
                await handleWebviewMessage(message, webviewView.webview);
            }
        );
    }
}

function syncSkills(extensionPath: string) {
    try {
        const homeDir = os.homedir();
        const targetPluginDir = path.join(homeDir, '.gemini', 'config', 'plugins', 'antigravity-orchestrator');
        
        const sourcePluginJson = path.join(extensionPath, 'plugin.json');
        const sourceSkillsDir = path.join(extensionPath, 'skills');
        
        if (!fs.existsSync(sourcePluginJson)) {
            console.log('No plugin.json found in extension bundle, skipping skill sync.');
            return;
        }

        console.log(`Syncing skills to target: ${targetPluginDir}`);
        
        // Copy plugin.json
        fs.mkdirSync(targetPluginDir, { recursive: true });
        fs.copyFileSync(sourcePluginJson, path.join(targetPluginDir, 'plugin.json'));
        
        // Recursively copy skills
        if (fs.existsSync(sourceSkillsDir)) {
            const copyDir = (src: string, dest: string) => {
                fs.mkdirSync(dest, { recursive: true });
                const entries = fs.readdirSync(src, { withFileTypes: true });
                for (const entry of entries) {
                    const srcPath = path.join(src, entry.name);
                    const destPath = path.join(dest, entry.name);
                    if (entry.isDirectory()) {
                        copyDir(srcPath, destPath);
                    } else {
                        fs.copyFileSync(srcPath, destPath);
                    }
                }
            };
            copyDir(sourceSkillsDir, path.join(targetPluginDir, 'skills'));
        }
        console.log('Successfully synced Antigravity Orchestrator skills!');
    } catch (err: any) {
        console.error('Failed to sync skills:', err);
    }
}

function registerMcpServer(extensionPath: string) {
    try {
        const homeDir = os.homedir();
        const mcpConfigPath = path.join(homeDir, '.gemini', 'antigravity-ide', 'mcp_config.json');
        
        // 1. Detect Python command
        let pythonCmd = 'python';
        try {
            execSync('python --version', { stdio: 'ignore' });
        } catch {
            try {
                execSync('python3 --version', { stdio: 'ignore' });
                pythonCmd = 'python3';
            } catch {
                // Default fallback
            }
        }

        // 2. Read existing config
        let config: any = { mcpServers: {} };
        if (fs.existsSync(mcpConfigPath)) {
            try {
                const content = fs.readFileSync(mcpConfigPath, 'utf-8');
                config = JSON.parse(content);
            } catch {
                // Ignore parsing errors and start fresh
            }
        }
        if (!config.mcpServers) {
            config.mcpServers = {};
        }

        // 3. Update orchestrator config
        const serverScriptPath = path.join(extensionPath, 'server.py').replace(/\\/g, '/');
        config.mcpServers['antigravity-orchestrator'] = {
            command: pythonCmd,
            args: [
                serverScriptPath,
                '--mcp'
            ]
        };

        // 4. Save updated config
        const mcpConfigDir = path.dirname(mcpConfigPath);
        if (!fs.existsSync(mcpConfigDir)) {
            fs.mkdirSync(mcpConfigDir, { recursive: true });
        }
        fs.writeFileSync(mcpConfigPath, JSON.stringify(config, null, 2), 'utf-8');
        console.log('Successfully registered Antigravity Orchestrator MCP server!');
    } catch (err: any) {
        console.error('Failed to register MCP server:', err);
    }
}

function registerMcpSchemas() {
    try {
        const homeDir = os.homedir();
        const mcpDir = path.join(homeDir, '.gemini', 'antigravity-ide', 'mcp', 'antigravity-orchestrator');
        if (!fs.existsSync(mcpDir)) {
            fs.mkdirSync(mcpDir, { recursive: true });
        }

        const schemas = [
            {
                name: "list_sessions",
                filename: "list_sessions.json",
                description: "List all active and completed Jules sessions across all projects",
                parameters: {
                    type: "object",
                    properties: {}
                }
            },
            {
                name: "get_git_status",
                filename: "get_git_status.json",
                description: "Get detailed branch comparison (ahead/behind counts), local checkout status (local_project_registered will be false if no local copy exists on the user's system), and Pull Request statuses for a given session ID.",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session (e.g. 5509702878084354010)"
                        }
                    },
                    required: ["session_id"]
                }
            },
            {
                name: "get_session_logs",
                filename: "get_session_logs.json",
                description: "Fetch full activity logs and conversation history for a given session ID.",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session"
                        }
                    },
                    required: ["session_id"]
                }
            },
            {
                name: "create_session",
                filename: "create_session.json",
                description: "Create a new Jules session for a specific GitHub repository and task description.",
                parameters: {
                    type: "object",
                    properties: {
                        repo: {
                            type: "string",
                            description: "The GitHub repository in 'owner/repo' format (e.g. 'evilspyboy/SignVerify')"
                        },
                        task: {
                            type: "string",
                            description: "The task prompt or instructions for Jules"
                        }
                    },
                    required: ["repo", "task"]
                }
            },
            {
                name: "archive_session",
                filename: "archive_session.json",
                description: "Archive a completed/failed Jules session by its ID to hide it from the active dashboard.",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session"
                        }
                    },
                    required: ["session_id"]
                }
            },
            {
                name: "unarchive_session",
                filename: "unarchive_session.json",
                description: "Unarchive a previously archived Jules session by its ID to restore it to the active dashboard.",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session"
                        }
                    },
                    required: ["session_id"]
                }
            },
            {
                name: "list_repos",
                filename: "list_repos.json",
                description: "List all repositories registered with Jules",
                parameters: {
                    type: "object",
                    properties: {}
                }
            },
            {
                name: "approve_plan",
                filename: "approve_plan.json",
                description: "Approve the proposed engineering plan for a session so Jules starts coding",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session"
                        }
                    },
                    required: ["session_id"]
                }
            },
            {
                name: "apply_patch",
                filename: "apply_patch.json",
                description: "Pulls and applies the completed session patch to the local registered project path",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session"
                        },
                        project: {
                            type: "string",
                            description: "Optional name of the local project if it doesn't match the repository name"
                        }
                    },
                    required: ["session_id"]
                }
            },
            {
                name: "get_session_plan",
                filename: "get_session_plan.json",
                description: "Fetches the list of plan steps generated for a given session",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session"
                        }
                    },
                    required: ["session_id"]
                }
            },
            {
                name: "get_auth_status",
                filename: "get_auth_status.json",
                description: "Checks whether the local Jules CLI is logged in",
                parameters: {
                    type: "object",
                    properties: {}
                }
            },
            {
                name: "jules_login",
                filename: "jules_login.json",
                description: "Launches the interactive login flow for Jules in a new command shell window",
                parameters: {
                    type: "object",
                    properties: {}
                }
            },
            {
                name: "list_stitch_drafts",
                filename: "list_stitch_drafts.json",
                description: "Scans the stitch directory for mock HTML UI designs",
                parameters: {
                    type: "object",
                    properties: {
                        project: {
                            type: "string",
                            description: "Optional name of project to filter drafts (currently ignored)"
                        }
                    }
                }
            },
            {
                name: "generate_stitch_stub",
                filename: "generate_stitch_stub.json",
                description: "Generates a mock design component from a prompt",
                parameters: {
                    type: "object",
                    properties: {
                        prompt: {
                            type: "string",
                            description: "Text describing the UI component to generate"
                        },
                        project: {
                            type: "string",
                            description: "Local project name to generate under"
                        }
                    },
                    required: ["prompt", "project"]
                }
            },
            {
                name: "export_stitch_design",
                filename: "export_stitch_design.json",
                description: "Exports a design layout to a path in one of your registered projects",
                parameters: {
                    type: "object",
                    properties: {
                        project: {
                            type: "string",
                            description: "Local target project name"
                        },
                        target_dir: {
                            type: "string",
                            description: "Subdirectory path in project to copy code to (e.g. 'src/components')"
                        },
                        format: {
                            type: "string",
                            description: "Export format ('react' or 'html')"
                        }
                    },
                    required: ["project", "target_dir", "format"]
                }
            },
            {
                name: "log_instruction",
                filename: "log_instruction.json",
                description: "Logs or updates a high-level task/instruction in the orchestrator",
                parameters: {
                    type: "object",
                    properties: {
                        project: {
                            type: "string",
                            description: "Name of the project repository (e.g. 'Orbits')"
                        },
                        instruction: {
                            type: "string",
                            description: "High level task details/prompt requested"
                        },
                        id: {
                            type: "string",
                            description: "Optional unique instruction ID (e.g. 'inst_xxxxxx') to update an existing task"
                        },
                        status: {
                            type: "string",
                            description: "Optional status: 'RUNNING', 'COMPLETED', 'FAILED', 'PLANNING'"
                        },
                        jules_session_id: {
                            type: "string",
                            description: "Optional unique Jules session ID linked to the task"
                        }
                    },
                    required: ["project", "instruction"]
                }
            },
            {
                name: "get_instructions",
                filename: "get_instructions.json",
                description: "Retrieves the list of active/logged instructions",
                parameters: {
                    type: "object",
                    properties: {}
                }
            }
        ];

        for (const schema of schemas) {
            const filePath = path.join(mcpDir, schema.filename);
            const content = {
                name: schema.name,
                description: schema.description,
                parameters: schema.parameters
            };
            fs.writeFileSync(filePath, JSON.stringify(content), 'utf-8');
        }
        console.log('Successfully registered Antigravity Orchestrator MCP schemas!');
    } catch (err: any) {
        console.error('Failed to register MCP schemas:', err);
    }
}

export function activate(context: vscode.ExtensionContext) {
    console.log('Antigravity Orchestrator extension is now active!');
    
    // Sync skills from extension bundle to user's config on startup
    syncSkills(context.extensionPath);
    
    // Auto-register MCP server inside user's mcp_config.json
    registerMcpServer(context.extensionPath);
    
    // Register all MCP tool schemas
    registerMcpSchemas();

    // 1. Register full-screen dashboard command
    let disposable = vscode.commands.registerCommand('antigravity-orchestrator.openDashboard', () => {
        const panel = vscode.window.createWebviewPanel(
            'antigravityOrchestrator',
            'Antigravity Orchestrator',
            vscode.ViewColumn.One,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [vscode.Uri.file(SCRATCH_DIR)]
            }
        );

        const indexHtmlPath = path.join(SCRATCH_DIR, 'index.html');
        if (fs.existsSync(indexHtmlPath)) {
            panel.webview.html = fs.readFileSync(indexHtmlPath, 'utf-8');
        } else {
            panel.webview.html = `<h3>Error: index.html not found.</h3>`;
        }

        panel.webview.onDidReceiveMessage(
            async (message) => {
                await handleWebviewMessage(message, panel.webview);
            },
            undefined,
            context.subscriptions
        );
    });

    context.subscriptions.push(disposable);

    // 2. Register native sidebar explorer panel
    const provider = new OrchestratorWebviewViewProvider();
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(OrchestratorWebviewViewProvider.viewType, provider)
    );
}

export function deactivate() {}
