# Antigravity Orchestrator

> [!NOTE]
> **Project Status:** This project was developed in conjunction with **Gemini v3.5 Flash**. The functionality is not complete nor is it finished, but it is at a functional point.

Antigravity Orchestrator is a VS Code / Antigravity IDE extension designed to coordinate frontend interface generation via Google Stitch and backend code generation via Google Jules across multiple repositories.

It registers a custom native **Model Context Protocol (MCP)** server, provides custom **Agent Skills** for cross-repo management, and features sidebar and full-screen dashboards to monitor active sessions, pull requests, and git diff comparisons.

---

## Features

- **Automatic Skill Synchronization:** Automatically copies included orchestrator skills and configuration to your local `~/.gemini/config/plugins` directory on startup.
- **Dynamic MCP Registration:** Auto-registers the `antigravity-orchestrator` MCP server in the IDE's App Data directory (`mcp_config.json`). Detects standard `python` or `python3` commands dynamically from the system PATH.
- **Git & Session Monitoring:** Seamlessly check pull requests and compare branches (ahead/behind counts) for active coding sessions.
- **User Interface Drafts:** Generate, inspect, and export frontend design drafts built via Google Stitch directly into any of your registered local repositories.

---

## Prerequisites

Ensure you have the following installed on your system:

1. **Python 3.10+** (with system PATH configured).
2. **Node.js & npm** (for extension compilation).
3. **Python Packages:**
   ```bash
   pip install fastapi uvicorn pydantic mcp
   ```

---

## Installation

### 1. Build from Source
1. Clone this repository.
2. Install npm dependencies:
   ```bash
   npm install
   ```
3. Compile the TypeScript files:
   ```bash
   npm run compile
   ```
4. Package the extension to a VSIX bundle:
   ```bash
   npx vsce package
   ```
   *This generates an `antigravity-orchestrator-1.0.0.vsix` file in the root directory.*

### 2. Install VSIX in Antigravity IDE
1. Open the Antigravity IDE.
2. Go to the Extensions panel (`Ctrl+Shift+X`).
3. Click the menu button (`...` in the top right) and select **Install from VSIX...**.
4. Choose the generated `.vsix` file.

Upon installation and next startup, the extension will automatically activate, synchronize its agent skills, and register the MCP server inside the IDE.

---

## Development

- **Watch Mode:** Run `npm run watch` to compile TypeScript changes automatically as you edit.
- **Backend Server:** The Python backend (`server.py`) can run in standalone web server mode via `python server.py` (running on `http://127.0.0.1:8000`) or as an MCP server via `python server.py --mcp` (using stdio transport).
