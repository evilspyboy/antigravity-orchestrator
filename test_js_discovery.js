const child_process = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

function discoverAndSend() {
    try {
        console.log("Checking terminal environment variables first...");
        let lsAddr = process.env.ANTIGRAVITY_LS_ADDRESS;
        let csrfToken = process.env.ANTIGRAVITY_CSRF_TOKEN;
        
        console.log(`Initial Environment -> LS_ADDRESS: ${lsAddr}, CSRF_TOKEN: ${csrfToken}`);
        
        // Temporarily clear environment variables to test dynamic fallback lookup
        lsAddr = null;
        csrfToken = null;
        
        console.log("Starting dynamic discovery fallback...");
        
        // 1. Get the PID and command line using our clean CIM query
        const cmdline = child_process.execSync("powershell -Command \"(Get-CimInstance Win32_Process -Filter 'Name = ''language_server_windows_x64.exe'' AND CommandLine LIKE ''%--csrf_token%'' AND NOT CommandLine LIKE ''%--enable_lsp%''') | Select-Object -ExpandProperty CommandLine\"", { encoding: 'utf-8' }).trim();
        const pid = child_process.execSync("powershell -Command \"(Get-CimInstance Win32_Process -Filter 'Name = ''language_server_windows_x64.exe'' AND CommandLine LIKE ''%--csrf_token%'' AND NOT CommandLine LIKE ''%--enable_lsp%''') | Select-Object -ExpandProperty ProcessId\"", { encoding: 'utf-8' }).trim();
        
        console.log(`Found language server PID: ${pid}`);
        
        const csrfMatch = cmdline.match(/--csrf_token\s+([\w-]+)/);
        if (csrfMatch) {
            csrfToken = csrfMatch[1];
        }
        
        const extPortMatch = cmdline.match(/--extension_server_port\s+(\d+)/);
        const extServerPort = extPortMatch ? extPortMatch[1] : '';

        // 2. Find the listening port (excluding the extension server port)
        const portsOut = child_process.execSync(`powershell -Command "Get-NetTCPConnection | Where-Object { $_.OwningProcess -eq ${pid} } | Where-Object { $_.State -eq 'Listen' } | Select-Object -ExpandProperty LocalPort"`, { encoding: 'utf-8' });
        const ports = portsOut.split(/\r?\n/).map(p => p.trim()).filter(p => p);
        
        const grpcPort = ports.find(p => p !== extServerPort) || ports[0];
        if (grpcPort) {
            lsAddr = `localhost:${grpcPort}`;
        }
        
        console.log(`Discovered Address: ${lsAddr}`);
        console.log(`Discovered CSRF Token: ${csrfToken}`);
        
        if (!lsAddr || !csrfToken) {
            throw new Error("Could not discover port or CSRF token dynamically.");
        }
        
        // 4. Send the message
        const localAppData = process.env.LOCALAPPDATA || '';
        const agentapi_exe = path.join(
            localAppData, 
            'Programs', 
            'Antigravity IDE', 
            'resources', 
            'app', 
            'extensions', 
            'antigravity', 
            'bin', 
            'language_server_windows_x64.exe'
        );
        
        let conv_id = null;
        const metadataStr = process.env.ANTIGRAVITY_SOURCE_METADATA;
        if (metadataStr) {
            try {
                const metadata = JSON.parse(metadataStr);
                conv_id = metadata.tool && metadata.tool.conversationId;
            } catch (e) {
                console.error("Error parsing metadata:", e.message);
            }
        }
        
        if (!conv_id) {
            throw new Error("Could not find conversation ID in environment.");
        }
        
        console.log(`Targeting Conversation ID: ${conv_id}`);
        console.log(`Executing agentapi from: ${agentapi_exe}`);
        
        const cli_content = "[System Message] - [SELF TEST] JS Discovery Route Success";
        
        // Construct clean environment with our dynamically discovered variables
        const env = Object.assign({}, process.env);
        env['ANTIGRAVITY_LS_ADDRESS'] = lsAddr;
        env['ANTIGRAVITY_CSRF_TOKEN'] = csrfToken;
        
        // Clear any other conflicting variables
        for (const key of Object.keys(env)) {
            if (key.startsWith('ANTIGRAVITY_') && key !== 'ANTIGRAVITY_LS_ADDRESS' && key !== 'ANTIGRAVITY_CSRF_TOKEN') {
                delete env[key];
            }
        }
        
        const cmd = `"${agentapi_exe}" agentapi send-message "${conv_id}" "${cli_content}"`;
        console.log(`Running CLI Command: ${cmd}`);
        
        const result = child_process.execSync(cmd, { env, encoding: 'utf-8' });
        console.log("Success! Output:\n", result);
        
    } catch (e) {
        console.error("Test failed:", e.message || e);
    }
}

discoverAndSend();
