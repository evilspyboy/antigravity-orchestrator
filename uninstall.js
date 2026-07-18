const fs = require('fs');
const path = require('path');
const os = require('os');

const homeDir = os.homedir();
const configDir = path.join(homeDir, '.gemini', 'config');
const agentsMdPath = path.join(configDir, 'AGENTS.md');
const pluginDir = path.join(homeDir, '.gemini', 'config', 'plugins', 'antigravity-orchestrator');
const mcpConfigPath = path.join(homeDir, '.gemini', 'antigravity-ide', 'mcp_config.json');
const mcpDir = path.join(homeDir, '.gemini', 'antigravity-ide', 'mcp', 'antigravity-orchestrator');

// 1. Clean up global AGENTS.md rules
if (fs.existsSync(agentsMdPath)) {
    try {
        let content = fs.readFileSync(agentsMdPath, 'utf-8');
        const ruleHeaderIndex = content.indexOf("# Antigravity Orchestrator Guidelines");
        if (ruleHeaderIndex !== -1) {
            content = content.substring(0, ruleHeaderIndex).trim() + "\n";
            fs.writeFileSync(agentsMdPath, content, 'utf-8');
            console.log('Successfully cleaned up global AGENTS.md rules.');
        }
    } catch (err) {
        console.error('Failed to clean up global AGENTS.md:', err);
    }
}

// 2. Clean up synced plugin/skills directory
if (fs.existsSync(pluginDir)) {
    try {
        fs.rmSync(pluginDir, { recursive: true, force: true });
        console.log('Successfully removed synced orchestrator plugin directory.');
    } catch (err) {
        console.error('Failed to remove plugin directory:', err);
    }
}

// 3. Clean up MCP schemas directory
if (fs.existsSync(mcpDir)) {
    try {
        fs.rmSync(mcpDir, { recursive: true, force: true });
        console.log('Successfully removed MCP schemas directory.');
    } catch (err) {
        console.error('Failed to remove MCP schemas directory:', err);
    }
}

// 4. Remove MCP server registration from mcp_config.json
if (fs.existsSync(mcpConfigPath)) {
    try {
        const content = fs.readFileSync(mcpConfigPath, 'utf-8');
        const config = JSON.parse(content);
        if (config.mcpServers && config.mcpServers['antigravity-orchestrator']) {
            delete config.mcpServers['antigravity-orchestrator'];
            fs.writeFileSync(mcpConfigPath, JSON.stringify(config, null, 2), 'utf-8');
            console.log('Successfully removed MCP server registration from mcp_config.json.');
        }
    } catch (err) {
        console.error('Failed to update mcp_config.json:', err);
    }
}
