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

// Log analysis function removed. We rely purely on process.env

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

function httpsDelete(url: string, headers: any): Promise<string> {
    return new Promise((resolve, reject) => {
        const parsedUrl = new URL(url);
        const options = {
            hostname: parsedUrl.hostname,
            path: parsedUrl.pathname + parsedUrl.search,
            method: 'DELETE',
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

function httpsPut(url: string, headers: any, body: string): Promise<string> {
    return new Promise((resolve, reject) => {
        const parsedUrl = new URL(url);
        const options = {
            hostname: parsedUrl.hostname,
            path: parsedUrl.pathname + parsedUrl.search,
            method: 'PUT',
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

function getCliSessionStatuses(): Record<string, string> {
    const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
    const env = { 
        ...process.env, 
        JULES_API_KEY: settings.jules || "",
        CI: "true",
        CLOUDSDK_CORE_DISABLE_PROMPTS: "1"
    };
    const statuses: Record<string, string> = {};
    try {
        const stdout = execSync(`"${JULES_BIN}" remote list --session`, { timeout: 15000, encoding: 'utf-8', env });
        const lines = stdout.split(/\r?\n/);
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            if (!line) {
                continue;
            }
            const parts = line.split(/\s{2,}/);
            if (parts.length === 0) {
                continue;
            }
            const sid = parts[0];
            if (!/^\d+$/.test(sid)) {
                continue;
            }
            let status = "";
            if (parts.length >= 5) {
                status = parts[4];
            }
            statuses[sid] = status;
        }
        try {
            const logFile = path.join(SCRATCH_DIR, "webview_requests.log");
            fs.appendFileSync(logFile, `[${new Date().toISOString()}] CLI_SUCCESS: getCliSessionStatuses successfully retrieved statuses: ${JSON.stringify(statuses)}\n`, 'utf-8');
        } catch (le) {}
    } catch (e: any) {
        console.error("Error fetching CLI session statuses in extension:", e);
        try {
            const logFile = path.join(SCRATCH_DIR, "webview_requests.log");
            fs.appendFileSync(logFile, `[${new Date().toISOString()}] CLI_ERROR: Error fetching CLI session statuses: ${e.message || e}\nStack: ${e.stack || ''}\n`, 'utf-8');
        } catch (le) {}
    }
    return statuses;
}

function mapCliStatusToApiState(cliStatus: string, currentApiState: string): string {
    const statusLower = cliStatus.toLowerCase().trim();
    if (!statusLower) {
        return currentApiState;
    }
    if (statusLower.includes("awaiting plan")) {
        return "AWAITING_PLAN_APPROVAL";
    } else if (statusLower.includes("planning")) {
        return "PLANNING";
    } else if (statusLower.includes("feedback") || statusLower.includes("awaiting user")) {
        return "AWAITING_USER_FEEDBACK";
    } else if (statusLower.includes("running")) {
        return "IN_PROGRESS";
    } else if (statusLower.includes("completed") || statusLower.includes("succeeded")) {
        return "COMPLETED";
    } else if (statusLower.includes("failed")) {
        return "FAILED";
    } else if (statusLower.includes("cancelled")) {
        return "CANCELLED";
    }
    return currentApiState;
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

function syncInstructionsToKnowledge(instructions: any[]) {
    try {
        const knowledgeDir = path.join(homeDir, '.gemini', 'antigravity-ide', 'knowledge', 'orchestrator_instructions');
        const artifactsDir = path.join(knowledgeDir, 'artifacts');
        if (!fs.existsSync(artifactsDir)) {
            fs.mkdirSync(artifactsDir, { recursive: true });
        }

        const metadata = {
            title: "Active Orchestrator Instructions & Task Logs",
            summary: "Synchronized list of active developer instructions, guidelines, and task logs registered in the Orchestrator dashboard.",
            updated_at: new Date().toISOString()
        };
        fs.writeFileSync(path.join(knowledgeDir, 'metadata.json'), JSON.stringify(metadata, null, 2), 'utf-8');

        let md = `# Active Orchestrator Instructions & Task Logs\n\n`;
        md += `This file is automatically synchronized from the Antigravity Orchestrator dashboard. It contains active instructions, advice, and task logs for each project.\n\n`;

        if (instructions.length === 0) {
            md += `*No active instructions or advice logs found.*\n`;
        } else {
            const groups: { [key: string]: any[] } = {};
            for (const inst of instructions) {
                const proj = inst.project || 'General';
                if (!groups[proj]) {
                    groups[proj] = [];
                }
                groups[proj].push(inst);
            }

            for (const proj of Object.keys(groups)) {
                md += `## Project: ${proj}\n\n`;
                for (const inst of groups[proj]) {
                    md += `### Task/Advice [${inst.status || 'RUNNING'}]\n`;
                    if (inst.jules_session_id) {
                        md += `- **Linked Session ID:** \`${inst.jules_session_id}\`\n`;
                    }
                    if (inst.timestamp) {
                        md += `- **Logged At:** ${inst.timestamp}\n`;
                    }
                    md += `\n**Instruction Details:**\n\`\`\`text\n${inst.instruction}\n\`\`\`\n\n---\n\n`;
                }
            }
        }

        fs.writeFileSync(path.join(artifactsDir, 'active_instructions.md'), md, 'utf-8');
        console.log('Successfully synchronized instructions to Antigravity knowledge base.');
    } catch (err) {
        console.error('Failed to sync instructions to knowledge:', err);
    }
}

// Shared Webview Message Router
async function handleWebviewMessage(message: any, webview: vscode.Webview) {
    const { command, method, body, requestId } = message;
    const logFile = path.join(SCRATCH_DIR, "webview_requests.log");
    try {
        fs.appendFileSync(logFile, `[${new Date().toISOString()}] Received command="${command}" method="${method}" body=${JSON.stringify(body)}\n`, 'utf-8');
    } catch (e) {}

    // Auto-register current IPC hook if in workspace
    try {
        const folders = vscode.workspace.workspaceFolders;
        if (folders && folders.length > 0) {
            const workspacePath = folders[0].uri.fsPath.replace(/\\/g, '/').toLowerCase();
            const ipcHook = process.env.VSCODE_IPC_HOOK;
            const lsAddr = process.env.ANTIGRAVITY_LS_ADDRESS;
            if (ipcHook || lsAddr) {
                const hooksFile = path.join(SCRATCH_DIR, "ipc_hooks.json");
                const hooks = readJson(hooksFile, {});
                const currentEntry = hooks[workspacePath] || {};
                if (currentEntry.ipc_hook !== ipcHook || currentEntry.ls_address !== lsAddr) {
                    hooks[workspacePath] = {
                        ipc_hook: ipcHook || "",
                        ls_address: lsAddr || ""
                    };
                    writeJson(hooksFile, hooks);
                }
            }
        }
    } catch {}

    try {
        let responseData: any = null;

        if (command === '/api/test_notification') {
            const { conv_id, title, message: msg } = body;
            const clean_content = msg.replace(/\n/g, " ");
            const cli_content = `[${title}] - ${clean_content}`;
            
            const homeDir = os.homedir();
            const agentapi_exe = path.join(homeDir, "AppData", "Local", "Programs", "Antigravity IDE", "resources", "app", "extensions", "antigravity", "bin", "language_server_windows_x64.exe");
            
            if (!fs.existsSync(agentapi_exe)) {
                throw new Error("agentapi binary not found");
            }
            
            const cmd = `"${agentapi_exe}" agentapi send-message "${conv_id}" "${cli_content}"`;
            const env = Object.assign({}, process.env);
            
            let lsAddr = env.ANTIGRAVITY_LS_ADDRESS;
            let csrfToken = env.ANTIGRAVITY_CSRF_TOKEN;
            
            if (!lsAddr || !csrfToken) {
                try {
                    fs.appendFileSync(logFile, `[${new Date().toISOString()}] [V2] Info: Missing Env, starting dynamic WQL discovery\n`, 'utf-8');
                    const cmdline = execSync("powershell -Command \"(Get-CimInstance Win32_Process -Filter 'Name = ''language_server_windows_x64.exe'' AND CommandLine LIKE ''%--csrf_token%'' AND NOT CommandLine LIKE ''%--enable_lsp%''') | Select-Object -ExpandProperty CommandLine\"", { encoding: 'utf-8' }).trim();
                    const pid = execSync("powershell -Command \"(Get-CimInstance Win32_Process -Filter 'Name = ''language_server_windows_x64.exe'' AND CommandLine LIKE ''%--csrf_token%'' AND NOT CommandLine LIKE ''%--enable_lsp%''') | Select-Object -ExpandProperty ProcessId\"", { encoding: 'utf-8' }).trim();
                    
                    if (pid && cmdline) {
                        const csrfMatch = cmdline.match(/--csrf_token\s+([\w-]+)/);
                        if (csrfMatch) {
                            csrfToken = csrfMatch[1];
                        }
                        
                        const extPortMatch = cmdline.match(/--extension_server_port\s+(\d+)/);
                        const extServerPort = extPortMatch ? extPortMatch[1] : '';
                        
                        const portsOut = execSync(`powershell -Command "Get-NetTCPConnection | Where-Object { $_.OwningProcess -eq ${pid} } | Where-Object { $_.State -eq 'Listen' } | Select-Object -ExpandProperty LocalPort"`, { encoding: 'utf-8' });
                        const ports = portsOut.split(/\r?\n/).map(p => p.trim()).filter(p => p);
                        const grpcPort = ports.find(p => p !== extServerPort) || ports[0];
                        if (grpcPort) {
                            lsAddr = `localhost:${grpcPort}`;
                        }
                        fs.appendFileSync(logFile, `[${new Date().toISOString()}] [V2] Discovered dynamically -> LS_ADDRESS: ${lsAddr}, CSRF_TOKEN: ${csrfToken}\n`, 'utf-8');
                    }
                } catch (e: any) {
                    try {
                        fs.appendFileSync(logFile, `[${new Date().toISOString()}] [V2] ERROR during dynamic discovery: ${e.message}\n`, 'utf-8');
                    } catch (err) {}
                }
            }
            
            if (!lsAddr || !csrfToken) {
                try {
                    fs.appendFileSync(logFile, `[${new Date().toISOString()}] [V2] ERROR: ANTIGRAVITY_LS_ADDRESS or ANTIGRAVITY_CSRF_TOKEN missing and discovery failed\n`, 'utf-8');
                } catch (e) {}
                throw new Error("Missing LS Address or CSRF Token in process.env and discovery failed");
            }

            // Write resolved values back to the env object so the CLI inherits them
            env.ANTIGRAVITY_LS_ADDRESS = lsAddr;
            env.ANTIGRAVITY_CSRF_TOKEN = csrfToken;
            
            try {
                fs.appendFileSync(logFile, `[${new Date().toISOString()}] DEBUG: LS_ADDRESS=${lsAddr}, CSRF_TOKEN=${csrfToken}\n`, 'utf-8');
            } catch (e) {}

            try {
                const result = execSync(cmd, { env, encoding: 'utf-8', timeout: 15000 });
                try {
                    fs.appendFileSync(logFile, `[${new Date().toISOString()}] [V2] SUCCESS executing test message command\n`, 'utf-8');
                } catch (e) {}
                responseData = { success: true, output: result, workspace: "Current Workspace" };
            } catch (e: any) {
                try {
                    fs.appendFileSync(logFile, `[${new Date().toISOString()}] [V2] ERROR executing test message command: ${e.message}\nSTDOUT: ${e.stdout}\nSTDERR: ${e.stderr}\n`, 'utf-8');
                } catch (err) {}
                throw e;
            }
        }
        else if (command === '/api/projects') {
            if (method === 'GET') {
                const projects = readJson(PROJECTS_FILE, []);
                for (const p of projects) {
                    if (fs.existsSync(p.path)) {
                        p.branch = getGitBranch(p.path);
                        p.connected = true;
                        
                        // Dynamically resolve GitHub repository associated with the project path
                        try {
                            const { execSync } = require('child_process');
                            const remoteUrl = execSync('git config --get remote.origin.url', { cwd: p.path, encoding: 'utf-8' }).trim();
                            let r = "";
                            if (remoteUrl) {
                                const match = remoteUrl.match(/(?:github\.com[:\/])([^\/]+\/[^\/]+?)(?:\.git)?$/i);
                                if (match) {
                                    r = match[1];
                                }
                            }
                            p.githubRepo = r;
                        } catch {
                            p.githubRepo = "";
                        }
                    } else {
                        p.connected = false;
                        p.githubRepo = "";
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
            if (command === '/api/jules/sessions/delete') {
                const sessionId = body.session_id;
                const purge = body.purge_local_cache || false;
                const confirmActiveDelete = body.confirm_active_delete || false;

                const deletedFile = path.join(SCRATCH_DIR, 'deleted_sessions.json');
                const deletedDbFile = path.join(SCRATCH_DIR, 'deleted_sessions_db.json');
                const deletedList = readJson(deletedFile, []);
                const deletedDb = readJson(deletedDbFile, {});

                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";

                // Check session status before deleting/pre-fetching
                let sessionState = "UNKNOWN";
                let sessionRaw: any = null;
                if (apiKey) {
                    try {
                        const sessionUrl = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}`;
                        const sessionText = await httpsGet(sessionUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                        sessionRaw = JSON.parse(sessionText);
                        sessionState = (sessionRaw.state || "UNKNOWN").toUpperCase();
                    } catch (err: any) {
                        if (err.message && err.message.includes("404")) {
                            sessionState = "DELETED_REMOTELY";
                        } else {
                            console.error("Error checking session state during delete:", err);
                        }
                    }
                }

                const inactiveStates = ["SUCCEEDED", "COMPLETED", "FAILED", "CANCELLED", "DELETED_REMOTELY", "UNKNOWN"];
                if (!inactiveStates.includes(sessionState) && !confirmActiveDelete) {
                    throw new Error(`WARNING_ACTIVE_SESSION: Session ${sessionId} is currently active (${sessionState}). Deleting it will abort the active task. Please confirm deletion.`);
                }

                // 1. Fetch metadata before remote deletion (only if NOT purging, and not already cached)
                if (!purge && apiKey && !deletedDb[sessionId]) {
                    try {
                        // 1.1 Fetch details (reuse sessionRaw if already fetched)
                        if (!sessionRaw) {
                            const sessionUrl = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}`;
                            const sessionText = await httpsGet(sessionUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                            sessionRaw = JSON.parse(sessionText);
                        }

                        // 1.2 Fetch activities / logs
                        const actUrl = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}/activities`;
                        const actText = await httpsGet(actUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                        const actData = JSON.parse(actText);
                        const activities = actData.activities || [];

                        // Parse logs
                        const logs: string[] = [];
                        for (const act of activities) {
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

                        // Parse plan
                        let planSteps = [];
                        for (const act of activities) {
                            if (act.planGenerated && act.planGenerated.plan) {
                                planSteps = act.planGenerated.plan.steps || [];
                                break;
                            }
                        }

                        // 1.3 Pull patch
                        let patchContent = "";
                        const source = sessionRaw.sourceContext?.source || "";
                        let repoName = "";
                        if (source.startsWith("sources/github/")) {
                            const repoParts = source.replace("sources/github/", "").split("/");
                            repoName = repoParts[repoParts.length - 1];
                        }

                        const projectsList = readJson(PROJECTS_FILE, []);
                        const proj = projectsList.find((p: any) => 
                            p.name.toLowerCase() === repoName.toLowerCase() || 
                            p.path.toLowerCase().endsWith("/" + repoName.toLowerCase()) ||
                            p.path.toLowerCase().endsWith("\\" + repoName.toLowerCase())
                        );

                        const targetCwd = (proj && fs.existsSync(proj.path)) ? proj.path : SCRATCH_DIR;
                        const env = { 
                            ...process.env, 
                            JULES_API_KEY: apiKey,
                            CI: "true",
                            CLOUDSDK_CORE_DISABLE_PROMPTS: "1"
                        };

                        const { exec } = require('child_process');
                        try {
                            const pulledPatch: string = await new Promise((resolve, reject) => {
                                exec(`"${JULES_BIN}" remote pull --session ${sessionId}`, { cwd: targetCwd, env, timeout: 15000, shell: true }, (error: any, stdout: string, stderr: string) => {
                                    if (error) {
                                        reject(new Error(stderr || stdout || error.message));
                                    } else {
                                        resolve(stdout);
                                    }
                                });
                            });
                            patchContent = pulledPatch;
                        } catch (err: any) {
                            console.error("Patch pull error during delete pre-fetch:", err);
                        }

                        const repo = source.startsWith("sources/github/") ? source.replace("sources/github/", "") : "Other/Unmapped Repos";
                        deletedDb[sessionId] = {
                            id: sessionId,
                            task: sessionRaw.title || sessionRaw.prompt || "No Title",
                            repo: repo,
                            status: (sessionRaw.state || "COMPLETED").toUpperCase(),
                            prompt: sessionRaw.prompt || "",
                            logs: logs,
                            plan: { steps: planSteps },
                            patch: patchContent,
                            raw: sessionRaw
                        };
                        writeJson(deletedDbFile, deletedDb);
                    } catch (fe: any) {
                        console.error("Failed to pre-fetch session details before deleting:", fe);
                    }
                }

                // 2. Perform remote deletion (always attempt)
                if (apiKey) {
                    try {
                        const deleteUrl = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}`;
                        await httpsDelete(deleteUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                    } catch (err) {
                        console.error("Failed to delete session remotely in extension:", err);
                    }
                }

                // 3. Post-delete local cache adjustments
                if (purge) {
                    const updatedList = deletedList.filter((id: string) => id !== sessionId);
                    writeJson(deletedFile, updatedList);
                    if (deletedDb[sessionId]) {
                        delete deletedDb[sessionId];
                        writeJson(deletedDbFile, deletedDb);
                    }
                    responseData = { success: true, message: `Session ${sessionId} permanently deleted remotely and purged from local history cache.` };
                } else {
                    if (!deletedList.includes(sessionId)) {
                        deletedList.push(sessionId);
                        writeJson(deletedFile, deletedList);
                    }
                    responseData = { success: true, message: `Session ${sessionId} deleted remotely and saved in history cache.` };
                }
            }

            else if (command === '/api/jules/sessions' && method === 'POST') {
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                const repo = body.repo;
                const task = body.task;
                const branch = body.branch || "main";
                
                if (apiKey) {
                    const url = "https://jules.googleapis.com/v1alpha/sessions";
                    const payload = JSON.stringify({
                        prompt: task,
                        title: task.slice(0, 100),
                        sourceContext: {
                            source: `sources/github/${repo}`,
                            githubRepoContext: {
                                startingBranch: branch
                            }
                        },
                        automationMode: "AUTO_CREATE_PR",
                        requirePlanApproval: true
                    });
                    try {
                        const responseText = await httpsPost(url, {
                            "x-goog-api-key": apiKey,
                            "Content-Type": "application/json",
                            "Accept": "application/json"
                        }, payload);
                        const data = JSON.parse(responseText);
                        responseData = { success: true, message: `Successfully created session ${data.id} with AUTO_CREATE_PR.`, session_id: data.id };
                    } catch (apiErr: any) {
                        console.error("API session creation failed, falling back to CLI:", apiErr);
                    }
                }
                
                if (!responseData) {
                    const env = { ...process.env };
                    if (apiKey) {
                        env["JULES_API_KEY"] = apiKey;
                    }
                    env["CI"] = "true";
                    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1";
                    
                    responseData = await new Promise((resolve, reject) => {
                        execFile(JULES_BIN, ["new", "--repo", repo, task], { env, stdio: ['ignore', 'pipe', 'pipe'] } as any, (error: any, stdout: string, stderr: string) => {
                            if (error) {
                                reject(new Error(stderr || stdout || error.message));
                            } else {
                                resolve({ success: true, message: stdout.trim() });
                            }
                        });
                    });
                }
            }
            
            else if (command.includes('/logs')) {
                const sessionId = command.split('/')[4];
                const deletedDbFile = path.join(SCRATCH_DIR, 'deleted_sessions_db.json');
                const deletedDb = readJson(deletedDbFile, {});
                if (deletedDb[sessionId]) {
                    responseData = { logs: deletedDb[sessionId].logs || ["[info] No activities logged yet."] };
                } else {
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
                }
            } else if (command.includes('/checkout')) {
                const sessionId = command.split('/')[4];
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                if (!apiKey) {
                    throw new Error("Jules API key not configured.");
                }

                const sessionUrl = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}`;
                const sessionText = await httpsGet(sessionUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                const sessionData = JSON.parse(sessionText);
                
                let repoName = "";
                const source = sessionData.sourceContext?.source || "";
                if (source.startsWith("sources/github/")) {
                    const repoParts = source.replace("sources/github/", "").split("/");
                    repoName = repoParts[repoParts.length - 1];
                }

                const projectsList = readJson(PROJECTS_FILE, []);
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
                    throw new Error(`Local project directory for repository "${repoName || 'unknown'}" is not registered or does not exist locally.`);
                }

                let headRef: string | null = null;
                const outputs = sessionData.outputs || [];
                for (const out of outputs) {
                    if (out.pullRequest && out.pullRequest.headRef) {
                        headRef = out.pullRequest.headRef;
                        break;
                    }
                }
                if (!headRef) {
                    for (const out of outputs) {
                        if (out.changeSet) {
                            headRef = `feat-${repoName.toLowerCase()}-base-${sessionId}`;
                            break;
                        }
                    }
                }
                if (!headRef) {
                    headRef = `feat-${repoName.toLowerCase()}-base-${sessionId}`;
                }

                const { execSync } = require('child_process');
                try {
                    try {
                        execSync("git fetch origin", { cwd: targetCwd, timeout: 10000 });
                    } catch (fe) {
                        console.warn("git fetch origin failed or timed out:", fe);
                    }
                    try {
                        execSync(`git checkout ${headRef}`, { cwd: targetCwd, timeout: 15000 });
                    } catch {
                        try {
                            execSync(`git checkout -b ${headRef} origin/${headRef}`, { cwd: targetCwd, timeout: 15000 });
                        } catch (remoteErr) {
                            // Fallback: branch does not exist on remote yet.
                            // Create local branch and pull/apply via Jules CLI
                            try {
                                execSync(`git checkout -b ${headRef}`, { cwd: targetCwd, timeout: 15000 });
                            } catch {
                                execSync(`git checkout ${headRef}`, { cwd: targetCwd, timeout: 15000 });
                            }
                            const env = { 
                                ...process.env, 
                                JULES_API_KEY: apiKey,
                                CI: "true",
                                CLOUDSDK_CORE_DISABLE_PROMPTS: "1"
                            };
                            execSync(`"${JULES_BIN}" remote pull --session ${sessionId} --apply`, { cwd: targetCwd, env, timeout: 30000 });
                        }
                    }
                    responseData = { success: true, message: `Checked out branch '${headRef}' and applied Jules changes locally.`, branch: headRef };
                } catch (err: any) {
                    throw new Error(`Git checkout failed: ${err.message}`);
                }
            } else if (command.includes('/merge-local')) {
                const sessionId = command.split('/')[4];
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const apiKey = settings.jules || "";
                if (!apiKey) {
                    throw new Error("Jules API key not configured.");
                }

                const sessionUrl = `https://jules.googleapis.com/v1alpha/sessions/${sessionId}`;
                const sessionText = await httpsGet(sessionUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                const sessionData = JSON.parse(sessionText);
                
                let repoName = "";
                const source = sessionData.sourceContext?.source || "";
                if (source.startsWith("sources/github/")) {
                    const repoParts = source.replace("sources/github/", "").split("/");
                    repoName = repoParts[repoParts.length - 1];
                }

                const projectsList = readJson(PROJECTS_FILE, []);
                let proj = projectsList.find((p: any) => 
                    p.name.toLowerCase() === repoName.toLowerCase() || 
                    p.path.toLowerCase().endsWith("/" + repoName.toLowerCase()) ||
                    p.path.toLowerCase().endsWith("\\" + repoName.toLowerCase())
                );
                
                const targetCwd = (proj && fs.existsSync(proj.path)) ? proj.path : null;
                if (!targetCwd) {
                    throw new Error(`Local project directory for repository "${repoName || 'unknown'}" is not registered or does not exist locally.`);
                }

                const baseRef = sessionData.sourceContext?.githubRepoContext?.startingBranch || "main";
                const targetBranch = body.target_branch || baseRef;

                const { execSync } = require('child_process');
                try {
                    execSync(`git fetch origin ${targetBranch}`, { cwd: targetCwd, timeout: 20000 });
                    try {
                        execSync(`git merge origin/${targetBranch}`, { cwd: targetCwd, timeout: 20000 });
                        responseData = { success: true, conflict: false, message: `Merged origin/${targetBranch} successfully.` };
                    } catch (mergeErr) {
                        try {
                            const diffOutput = execSync("git diff --name-only --diff-filter=U", { cwd: targetCwd, encoding: 'utf-8', timeout: 5000 });
                            const conflicts = diffOutput.trim().split(/\r?\n/).map((f: string) => f.trim()).filter(Boolean);
                            if (conflicts.length > 0) {
                                responseData = {
                                    success: false,
                                    conflict: true,
                                    conflicted_files: conflicts,
                                    message: "Merge conflicts detected. Please resolve conflict markers in the listed files."
                                };
                            } else {
                                throw mergeErr;
                            }
                        } catch {
                            throw mergeErr;
                        }
                    }
                } catch (err: any) {
                    throw new Error(`Merge failed: ${err.message}`);
                }
            } else if (command === '/api/jules/sessions/commit-push') {
                const projectsList = readJson(PROJECTS_FILE, []);
                const proj = projectsList.find((p: any) => p.name === body.project);
                const targetCwd = (proj && fs.existsSync(proj.path)) ? proj.path : null;
                if (!targetCwd) {
                    throw new Error(`Local project directory for project "${body.project}" not found.`);
                }

                const { execSync } = require('child_process');
                try {
                    const branch = execSync("git branch --show-current", { cwd: targetCwd, encoding: 'utf-8', timeout: 5000 }).trim();
                    if (!branch) {
                        throw new Error("Could not determine current active git branch.");
                    }

                    execSync("git add .", { cwd: targetCwd, timeout: 10000 });

                    try {
                        execSync(`git commit -m "${body.commit_message}"`, { cwd: targetCwd, timeout: 10000 });
                    } catch (commitErr: any) {
                        const status = execSync("git status", { cwd: targetCwd, encoding: 'utf-8' });
                        if (!status.includes("nothing to commit")) {
                            throw commitErr;
                        }
                    }

                    const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                    const token = settings.github || "";

                    try {
                        execSync(`git push origin ${branch}`, { cwd: targetCwd, timeout: 20000 });
                    } catch (pushErr) {
                        if (token) {
                            try {
                                const url = execSync("git remote get-url origin", { cwd: targetCwd, encoding: 'utf-8' }).trim();
                                if (url.startsWith("https://github.com/")) {
                                    const authUrl = url.replace("https://github.com/", `https://${token}@github.com/`);
                                    execSync(`git push ${authUrl} ${branch}`, { cwd: targetCwd, timeout: 20000 });
                                } else {
                                    throw pushErr;
                                }
                            } catch {
                                throw pushErr;
                            }
                        } else {
                            throw pushErr;
                        }
                    }

                    responseData = { success: true, message: `Successfully committed and pushed branch '${branch}' to origin.` };
                } catch (err: any) {
                    throw new Error(`Commit & Push failed: ${err.message}`);
                }
            } else if (command === '/api/jules/sessions/sync-local') {
                const projectsList = readJson(PROJECTS_FILE, []);
                const proj = projectsList.find((p: any) => p.name === body.project);
                const targetCwd = (proj && fs.existsSync(proj.path)) ? proj.path : null;
                if (!targetCwd) {
                    throw new Error(`Local project directory for project "${body.project}" not found.`);
                }

                const baseBranch = body.base_branch || "main";
                const { execSync } = require('child_process');
                try {
                    execSync(`git checkout ${baseBranch}`, { cwd: targetCwd, timeout: 15000 });
                    execSync(`git pull origin ${baseBranch}`, { cwd: targetCwd, timeout: 20000 });

                    let deletedMessage = "";
                    if (body.delete_branch) {
                        try {
                            execSync(`git branch -d ${body.delete_branch}`, { cwd: targetCwd, timeout: 5000 });
                            deletedMessage = ` Local branch '${body.delete_branch}' deleted.`;
                        } catch {
                            try {
                                execSync(`git branch -D ${body.delete_branch}`, { cwd: targetCwd, timeout: 5000 });
                                deletedMessage = ` Local branch '${body.delete_branch}' force-deleted.`;
                            } catch (e: any) {
                                deletedMessage = ` Warning: Failed to delete local branch '${body.delete_branch}': ${e.message}`;
                            }
                        }
                    }
                    responseData = { success: true, message: `Successfully checked out and pulled '${baseBranch}'.${deletedMessage}` };
                } catch (err: any) {
                    throw new Error(`Sync local failed: ${err.message}`);
                }
            } else if (command === '/api/jules/pulls/merge') {
                const settings = readJson(SETTINGS_FILE, DEFAULT_SETTINGS);
                const githubToken = settings.github || "";
                const apiKey = settings.jules || "";
                
                let repo = body.repo;
                let prNumber = body.pr_number;
                
                if (!repo || !prNumber) {
                    if (!body.session_id) {
                        throw new Error("Either 'session_id' or both 'repo' and 'pr_number' must be provided.");
                    }
                    if (!apiKey) {
                        throw new Error("Jules API key not configured to resolve session.");
                    }
                    
                    const sessionUrl = `https://jules.googleapis.com/v1alpha/sessions/${body.session_id}`;
                    const sessionText = await httpsGet(sessionUrl, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                    const sessionData = JSON.parse(sessionText);
                    
                    if (!repo) {
                        const source = sessionData.sourceContext?.source || "";
                        if (source.startsWith("sources/github/")) {
                            repo = source.replace("sources/github/", "");
                        } else {
                            throw new Error(`Could not resolve repository from session source: ${source}`);
                        }
                    }
                    
                    if (!prNumber) {
                        const outputs = sessionData.outputs || [];
                        for (const out of outputs) {
                            if (out.pullRequest && out.pullRequest.url) {
                                const match = out.pullRequest.url.match(/pull\/(\d+)/);
                                if (match) {
                                    prNumber = parseInt(match[1]);
                                    break;
                                }
                            }
                        }
                        if (!prNumber) {
                            throw new Error("Could not find an active Pull Request in session outputs.");
                        }
                    }
                }
                
                if (!githubToken) {
                    throw new Error("GitHub token not configured in settings.");
                }
                
                const ghUrl = `https://api.github.com/repos/${repo}/pulls/${prNumber}/merge`;
                const payload = JSON.stringify({
                    commit_title: `Merge pull request #${prNumber} from Jules session`,
                    merge_method: "merge"
                });
                
                const responseText = await httpsPut(ghUrl, {
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "Antigravity-Orchestrator",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "Authorization": `Bearer ${githubToken}`,
                    "Content-Type": "application/json"
                }, payload);
                
                const resData = JSON.parse(responseText);
                responseData = { success: true, merged: true, message: resData.message || "Pull request merged successfully" };
            } else if (command === '/open-file') {
                const projectsList = readJson(PROJECTS_FILE, []);
                const proj = projectsList.find((p: any) => p.name === body.project);
                const targetCwd = (proj && fs.existsSync(proj.path)) ? proj.path : null;
                if (!targetCwd) {
                    throw new Error(`Local project directory for project "${body.project}" not found.`);
                }
                const fullPath = path.join(targetCwd, body.file_path);
                if (fs.existsSync(fullPath)) {
                    vscode.workspace.openTextDocument(fullPath).then(doc => {
                        vscode.window.showTextDocument(doc);
                    });
                    responseData = { success: true };
                } else {
                    throw new Error(`File does not exist: ${body.file_path}`);
                }
            } else if (command === '/show-confirm') {
                const selection = await vscode.window.showWarningMessage(body.message, "Yes", "No");
                responseData = { confirmed: selection === "Yes" };
            } else if (command === '/show-alert') {
                if (body.type === 'error') {
                    await vscode.window.showErrorMessage(body.message);
                } else {
                    await vscode.window.showInformationMessage(body.message);
                }
                responseData = { success: true };
            } else if (command.includes('/plan')) {
                const sessionId = command.split('/')[4];
                const deletedDbFile = path.join(SCRATCH_DIR, 'deleted_sessions_db.json');
                const deletedDb = readJson(deletedDbFile, {});
                if (deletedDb[sessionId]) {
                    responseData = { success: true, steps: deletedDb[sessionId].plan?.steps || [] };
                } else {
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
                }
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

                    // 1. Fetch sessions from Google API (both active and archived)
                    const parsed: any[] = [];
                    const deletedFile = path.join(SCRATCH_DIR, 'deleted_sessions.json');
                    const deleted = readJson(deletedFile, []);
                    const showDeleted = command.includes('show_deleted=true');

                    const sessionsList: any[] = [];
                    const seenIds = new Set<string>();
                    const filters = ["", "archived=true"];

                    for (const filterVal of filters) {
                        let nextPageToken = "";
                        do {
                            let url = "https://jules.googleapis.com/v1alpha/sessions?pageSize=100";
                            if (filterVal) {
                                url += `&filter=${filterVal}`;
                            }
                            if (nextPageToken) {
                                url += `&pageToken=${nextPageToken}`;
                            }
                            try {
                                const responseText = await httpsGet(url, { "x-goog-api-key": apiKey, "Accept": "application/json" });
                                const data = JSON.parse(responseText);
                                for (const s of data.sessions || []) {
                                    if (!seenIds.has(s.id)) {
                                        seenIds.add(s.id);
                                        sessionsList.push(s);
                                    }
                                }
                                nextPageToken = data.nextPageToken || "";
                            } catch (err) {
                                console.error("Error fetching sessions from jules API:", err);
                                nextPageToken = "";
                            }
                        } while (nextPageToken);
                    }

                    const cliStatuses = getCliSessionStatuses();
                    for (const s of sessionsList) {
                        const sid = s.id;
                        const isArchived = s.archived || false;
                        const isDeleted = deleted.includes(sid);

                        // If not showing deleted history, hide locally deleted and remotely archived sessions
                        if (!showDeleted && (isDeleted || isArchived)) {
                            continue;
                        }

                        let state = s.state || "UNKNOWN";
                        if (cliStatuses[sid]) {
                            const newState = mapCliStatusToApiState(cliStatuses[sid], state);
                            if (newState !== state) {
                                state = newState;
                                s.state = newState;
                            }
                        }

                        const title = s.title || s.prompt || "No Title";
                        
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
                        if (state === "AWAITING_PLAN_APPROVAL") {
                            status = "AWAITING PLAN APPROVAL";
                        } else if (state === "AWAITING_USER_FEEDBACK" && !isArchived) {
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
                            is_deleted: isDeleted || isArchived
                        });
                    }

                    if (showDeleted) {
                        const deletedDbFile = path.join(SCRATCH_DIR, 'deleted_sessions_db.json');
                        const db = readJson(deletedDbFile, {});
                        for (const sid of Object.keys(db)) {
                            if (!parsed.some((p: any) => p.id === sid)) {
                                const cached = db[sid];
                                parsed.push({
                                    id: sid,
                                    task: cached.task || "No Title",
                                    repo: cached.repo || "",
                                    status: (cached.status || "COMPLETED").toUpperCase(),
                                    logs: cached.logs || [],
                                    is_deleted: true
                                });
                            }
                        }
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

        else if (command.startsWith('/api/instructions')) {
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
                syncInstructionsToKnowledge(instructions);
                responseData = { success: true };
            } else if (method === 'DELETE') {
                const parts = command.split('/');
                const id = parts[parts.length - 1];
                const instructions = readJson(INSTRUCTIONS_FILE, []);
                const filtered = instructions.filter((inst: any) => inst.id !== id);
                writeJson(INSTRUCTIONS_FILE, filtered);
                syncInstructionsToKnowledge(filtered);
                responseData = { success: true };
            }
        }

        // Send response back to webview
        try {
            fs.appendFileSync(logFile, `[${new Date().toISOString()}] SUCCESS command="${command}"\n`, 'utf-8');
        } catch (e) {}
        webview.postMessage({
            requestId,
            data: responseData
        });

    } catch (err: any) {
        try {
            fs.appendFileSync(logFile, `[${new Date().toISOString()}] ERROR command="${command}": ${err.message || err}\n`, 'utf-8');
        } catch (e) {}
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
            // Inject current workspace path
            const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "";
            const escapedPath = workspacePath.replace(/\\/g, '/');
            htmlContent = htmlContent.replace('<head>', `<head>\n    <script>window.IDE_WORKSPACE_PATH = "${escapedPath}";</script>`);
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
                '-u',
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

        // Clean up legacy schemas
        try {
            const legacySchema = path.join(mcpDir, 'apply_patch.json');
            if (fs.existsSync(legacySchema)) {
                fs.unlinkSync(legacySchema);
            }
        } catch (err) {
            console.error('Failed to clean up legacy apply_patch schema:', err);
        }

        const schemas = [
            {
                name: "list_sessions",
                filename: "list_sessions.json",
                description: "List all active and completed Jules sessions across all projects",
                parameters: {
                    type: "object",
                    properties: {
                        show_deleted: {
                            type: "boolean",
                            description: "Optional: If true, includes deleted sessions from the local history cache."
                        },
                        show_archived: {
                            type: "boolean",
                            description: "Optional: If true, includes archived sessions (which may take longer to retrieve due to pagination)."
                        },
                        repo_filter: {
                            type: "string",
                            description: "Optional: Repository name filter (case-insensitive substring match)."
                        },
                        limit: {
                            type: "integer",
                            description: "Optional: Maximum number of sessions to return."
                        },
                        sort_ascending: {
                            type: "boolean",
                            description: "Optional: If true, returns oldest sessions first. If false, returns newest first."
                        }
                    }
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
                        },
                        branch: {
                            type: "string",
                            description: "Optional: Starting branch to fork the session from. Defaults to 'main'."
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
                name: "delete_session",
                filename: "delete_session.json",
                description: "Delete a Jules session remotely and optionally purge its local history cache.",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session"
                        },
                        purge_local_cache: {
                            type: "boolean",
                            description: "If true, permanently deletes the session from the local history cache. If false, only deletes it remotely and keeps a local history cache."
                        },
                        confirm_active_delete: {
                            type: "boolean",
                            description: "If true, allows deleting active/running sessions. If false, deleting active sessions will fail with a warning."
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
                name: "checkout_branch",
                filename: "checkout_branch.json",
                description: "Checks out a git branch in the local repository workspace for a Jules session or target branch/project.",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "Optional: The unique ID of the Jules session. Resolves project and branch automatically."
                        },
                        branch_name: {
                            type: "string",
                            description: "Optional: The target branch name to check out."
                        },
                        project: {
                            type: "string",
                            description: "Optional: The local registered project name."
                        }
                    }
                }
            },
            {
                name: "merge_branch_locally",
                filename: "merge_branch_locally.json",
                description: "Attempts to merge a target branch (like 'main' or another session's branch) into the current branch locally. Returns conflicted files if there are conflicts.",
                parameters: {
                    type: "object",
                    properties: {
                        target_branch: {
                            type: "string",
                            description: "The name of the branch to merge (e.g. 'main' or another session's feature branch)."
                        },
                        session_id: {
                            type: "string",
                            description: "Optional: The unique ID of the Jules session to merge into. Resolves local project and current branch automatically."
                        },
                        project: {
                            type: "string",
                            description: "Optional: The local registered project name."
                        }
                    },
                    required: ["target_branch"]
                }
            },
            {
                name: "git_commit_and_push",
                filename: "git_commit_and_push.json",
                description: "Stages all changes, commits them, and pushes the current branch to origin.",
                parameters: {
                    type: "object",
                    properties: {
                        project: {
                            type: "string",
                            description: "Name of the local registered project."
                        },
                        commit_message: {
                            type: "string",
                            description: "Commit message for the changes."
                        }
                    },
                    required: ["project", "commit_message"]
                }
            },
            {
                name: "sync_local",
                filename: "sync_local.json",
                description: "Syncs the local project workspace by checking out a base branch, pulling origin, and optionally deleting the local feature branch.",
                parameters: {
                    type: "object",
                    properties: {
                        project: {
                            type: "string",
                            description: "Name of the local registered project."
                        },
                        base_branch: {
                            type: "string",
                            description: "Optional: The base branch to switch to and pull (e.g. 'main'). Defaults to 'main'."
                        },
                        delete_branch: {
                            type: "string",
                            description: "Optional: The name of the local feature branch to delete after pulling main."
                        }
                    },
                    required: ["project"]
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
                name: "get_session_details",
                filename: "get_session_details.json",
                description: "Fetch the complete details of a specific Jules session by its ID, including the repository name, short title, and the full, uncut original instruction/prompt text.",
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
            },
            {
                name: "delete_instruction",
                filename: "delete_instruction.json",
                description: "Deletes a logged high-level task/instruction by its unique ID (e.g. 'inst_xxxxxx')",
                parameters: {
                    type: "object",
                    properties: {
                        id: {
                            type: "string",
                            description: "The unique ID of the instruction to delete"
                        }
                    },
                    required: ["id"]
                }
            },
            {
                name: "send_session_message",
                filename: "send_session_message.json",
                description: "Send a chat message or feedback to an active Jules session to answer a question or provide further instructions.",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "The unique ID of the Jules session"
                        },
                        message: {
                            type: "string",
                            description: "The message or feedback prompt to send to the Jules agent"
                        }
                    },
                    required: ["session_id", "message"]
                }
            },
            {
                name: "get_repo_file",
                filename: "get_repo_file.json",
                description: "Read the contents of a file (such as a specification markdown sheet, README, or source code file) from a remote GitHub repository. Requires either a direct repository path ('owner/repo') OR a session_id to resolve the repository automatically.",
                parameters: {
                    type: "object",
                    properties: {
                        path: {
                            type: "string",
                            description: "The path to the file within the repository (e.g. 'README.md' or 'docs/PLAN.md')"
                        },
                        repo: {
                            type: "string",
                            description: "Optional: The GitHub repository in 'owner/repo' format (e.g. 'evilspyboy/SignVerify')"
                        },
                        session_id: {
                            type: "string",
                            description: "Optional: The unique ID of the Jules session. If provided and 'repo' is omitted, the repository will be automatically resolved from the session context."
                        }
                    },
                    required: ["path"]
                }
            },
            {
                name: "merge_pr",
                filename: "merge_pr.json",
                description: "Merge a pull request. Requires a session_id (which automatically resolves the repository and PR number from the session metadata) OR a repo name and pr_number.",
                parameters: {
                    type: "object",
                    properties: {
                        session_id: {
                            type: "string",
                            description: "Optional: The unique ID of the Jules session. Resolves repo and pr_number automatically."
                        },
                        repo: {
                            type: "string",
                            description: "Optional: The GitHub repository in 'owner/repo' format."
                        },
                        pr_number: {
                            type: "integer",
                            description: "Optional: The Pull Request number."
                        }
                    }
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
    try {
        fs.writeFileSync(path.join(SCRATCH_DIR, "env_debug.json"), JSON.stringify(process.env, null, 2), 'utf-8');
    } catch {}
    
    // Legacy migration from archived -> deleted
    try {
        const legacyList = path.join(SCRATCH_DIR, 'archived_sessions.json');
        const legacyDb = path.join(SCRATCH_DIR, 'archived_sessions_db.json');
        const newList = path.join(SCRATCH_DIR, 'deleted_sessions.json');
        const newDb = path.join(SCRATCH_DIR, 'deleted_sessions_db.json');
        if (fs.existsSync(legacyList) && !fs.existsSync(newList)) {
            fs.copyFileSync(legacyList, newList);
        }
        if (fs.existsSync(legacyDb) && !fs.existsSync(newDb)) {
            fs.copyFileSync(legacyDb, newDb);
        }
    } catch (err) {
        console.error('Migration warning:', err);
    }
    
    // Sync skills from extension bundle to user's config on startup
    syncSkills(context.extensionPath);
    
    // Auto-register MCP server inside user's mcp_config.json
    registerMcpServer(context.extensionPath);
    
    // Register all MCP tool schemas
    registerMcpSchemas();

    // Register active IPC hook for workspace matching
    try {
        const folders = vscode.workspace.workspaceFolders;
        if (folders && folders.length > 0) {
            const workspacePath = folders[0].uri.fsPath.replace(/\\/g, '/').toLowerCase();
            const ipcHook = process.env.VSCODE_IPC_HOOK;
            const lsAddr = process.env.ANTIGRAVITY_LS_ADDRESS;
            if (ipcHook || lsAddr) {
                const hooksFile = path.join(SCRATCH_DIR, "ipc_hooks.json");
                const hooks = readJson(hooksFile, {});
                hooks[workspacePath] = {
                    ipc_hook: ipcHook || "",
                    ls_address: lsAddr || ""
                };
                writeJson(hooksFile, hooks);
                console.log(`Registered IPC hook and LS address for workspace path: ${workspacePath}`);
            }
        }
    } catch (err) {
        console.error('Failed to register active IPC hook:', err);
    }

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
            let htmlContent = fs.readFileSync(indexHtmlPath, 'utf-8');
            // Inject current workspace path
            const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "";
            const escapedPath = workspacePath.replace(/\\/g, '/');
            htmlContent = htmlContent.replace('<head>', `<head>\n    <script>window.IDE_WORKSPACE_PATH = "${escapedPath}";</script>`);
            panel.webview.html = htmlContent;
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
