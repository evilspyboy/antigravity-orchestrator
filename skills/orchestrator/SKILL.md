---
name: antigravity-orchestrator
description: >-
  Coordinate development tasks across multiple isolated repositories. Query projects,
  retrieve git branches, manage credentials, scan stitch drafts, and start or apply
  Jules coding sessions.
---

# Antigravity Orchestrator Skill

This skill allows the Antigravity agent to manage multiple repository contexts, query global settings, view design drafts from Stitch, and run asynchronous Jules coding sessions.

## Core Rules

- **Execution Context**: Always identify which repository is the active target before performing operations. Use `switch_project` to change context.
- **Isolation**: Keep project code and environment variables strictly separate. Never read files from Project A while in the execution context of Project B, unless using the `search_cross_project_patterns` tool to bridge generic design styles.
- **Jules CLI**: Interfacing with Jules should be done via `orchestrator_cli.py` to ensure commands are run in the appropriate project working directories and outputs are handled in structured JSON.
- **Local Workspace Verification**: If `local_project_registered` is `false` in `get_git_status` (or if it is not registered in `projects.json`), assume the repository does not exist on the user's local disk. Rely strictly on GitHub and Jules API logs. Do not run filesystem search commands to locate it.

- **Active Instructions Logging**: When the user requests a task (e.g. "do xyz on repo abc"), you must log this instruction into `<homeDir>/.gemini/antigravity-ide/scratch/antigravity-orchestrator/instructions.json` (where `<homeDir>` is the absolute path to the user's home directory) so it displays in the dashboard. Use this format:
  ```json
  [
    {
      "id": "inst_xxxxxx",
      "timestamp": "YYYY-MM-DD HH:MM:SS",
      "project": "RepositoryName",
      "instruction": "High level task details",
      "status": "RUNNING",
      "jules_session_id": "123456"
    }
  ]
  ```
  Update the status (`RUNNING`, `COMPLETED`, `FAILED`) and bind it to a `jules_session_id` as the task progresses.

## MCP Native Tools

If the Model Context Protocol (MCP) server `antigravity-orchestrator` is connected, you should prioritize calling the following tools directly using native model MCP tool calls instead of executing python scripts in the shell:

- **`antigravity-orchestrator/list_sessions`**:
  Retrieves a list of all active and completed Jules sessions.
  
- **`antigravity-orchestrator/get_git_status` `session_id`**:
  Retrieves detailed git comparison, local checkout, and pull request details for the session.

- **`antigravity-orchestrator/get_session_logs` `session_id`**:
  Retrieves activity and agent message logs for the session.

## CLI Usage

All tasks are executed via the wrapper CLI:

```bash
python <homeDir>/.gemini/config/plugins/antigravity-orchestrator/skills/orchestrator/scripts/orchestrator_cli.py <function_name> [arguments...]
```

### Functions

- **`list_projects`**:
  Returns a JSON list of registered projects, their paths, current git branches, and status.
  
- **`register_project` `<name>` `<path>`**:
  Registers a new directory folder as a project.
  
- **`switch_project` `<name>`**:
  Sets the active target project for future commands.
  
- **`get_jules_status` `<project>`**:
  Retrieves active/completed Jules coding tasks for a specific project.
  
- **`create_jules_session` `<project>` `<task_description>`**:
  Spawns a new Jules task in the target repository.
  
- **`apply_jules_patch` `<project>` `<session_id>`**:
  Pulls the completed patch from a Jules session and applies it locally.

- **`list_sessions`**:
  Queries the live Google API to retrieve all current and historical Jules sessions across all repositories.

- **`get_git_status` `<session_id>`**:
  Gets detailed branch comparison (ahead/behind counts), local checked out branch status, and Pull Request statuses for a given session.

- **`get_session_logs` `<session_id>`**:
  Fetches full activity/agent conversation logs for a given session.

- **`search_cross_project_patterns` `<query>`**:
  Searches across all projects for generic helper functions or templates to reuse in the current workspace.
