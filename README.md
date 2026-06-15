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

## MCP Native Tools

The extension exposes the following 22 native Model Context Protocol (MCP) tools to the IDE and the AI Agent:

### Jules Session Management
- **`list_sessions` (`repo_filter`?, `limit`?, `sort_ascending`?, `show_archived`?, `show_deleted`?)**: Retrieves a list of all active and completed Jules sessions. Supports repository filtering, count limiting, sorting, archived session loading (optional), and deleted local history cache inclusion.
- **`create_session` (`repo`, `task`)**: Creates a new Jules session for a specific GitHub repository and task description.
- **`get_session_plan` (`session_id`)**: Fetches the list of plan steps generated for a given session.
- **`approve_plan` (`session_id`)**: Approves the proposed engineering plan for a session so Jules starts coding.
- **`checkout_branch` (`session_id`?, `branch_name`?, `project`?)**: Checks out a git branch in the local repository workspace for a Jules session or target branch/project.
- **`merge_branch_locally` (`target_branch`, `session_id`?, `project`?)**: Attempts to merge a target branch (like 'main') into the current branch locally. Returns conflicted files if there are conflicts.
- **`git_commit_and_push` (`project`, `commit_message`)**: Stages all changes, commits them, and pushes the current branch to origin.
- **`sync_local` (`project`, `base_branch`?, `delete_branch`?)**: Syncs the local project workspace by checking out a base branch, pulling origin, and optionally deleting the local feature branch.
- **`get_git_status` (`session_id`)**: Retrieves detailed git comparison (ahead/behind counts), local checkout status, and Pull Request statuses for a given session ID.
- **`get_session_logs` (`session_id`)**: Fetches full activity logs and conversation history for a given session.
- **`delete_session` (`session_id`, `purge_local_cache`?, `confirm_active_delete`?)**: Deletes a Jules session remotely. If `purge_local_cache` is `false` (default), caches a copy of the prompt, plan, logs, and patch in local history before remote deletion. If `confirm_active_delete` is `false` (default), deleting active/running sessions will be blocked and return a safety warning to prevent accidental task abortion.
- **`merge_pr` (`session_id`?, `repo`?, `pr_number`?)**: Merges a Pull Request on GitHub. Can resolve repository and PR details automatically using `session_id`.
- **`get_auth_status`**: Checks whether the local Jules CLI is logged in.
- **`jules_login`**: Launches the interactive login flow for Jules in a new command shell window.
- **`list_repos`**: Lists all repositories registered and available in Jules.
- **`send_session_message` (`session_id`, `message`)**: Send a chat message or feedback to an active Jules session to answer a question or provide further instructions.
- **`get_repo_file` (`path`, `repo`?, `session_id`?)**: Read the contents of a file (such as a specification markdown sheet, README, or source code file) from a remote GitHub repository. Using session_id resolves the repository automatically.

### Stitch Design System
- **`list_stitch_drafts` (`project`?)**: Scans the stitch directory for mock HTML UI designs.
- **`generate_stitch_stub` (`prompt`, `project`)**: Generates a mock design component from a prompt.
- **`export_stitch_design` (`project`, `target_dir`, `format`)**: Exports a design layout to a path in one of your registered projects.

### Instructions Logging
- **`log_instruction` (`project`, `instruction`, `id`?, `status`?, `jules_session_id`?)**: Logs or updates a high-level task/instruction in the orchestrator.
- **`get_instructions`**: Retrieves the list of active/logged instructions.
- **`delete_instruction` (`id`)**: Deletes a logged high-level task/instruction by its unique ID (e.g. 'inst_xxxxxx').

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
