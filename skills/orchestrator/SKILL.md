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

- **Prefer MCP Native Tools Over Custom Scripts/Shell Commands**: ALWAYS prioritize calling the Model Context Protocol (MCP) server `antigravity-orchestrator` tools directly. Do NOT write custom Python scripts, run shell commands, or generate scratch code to fetch session metadata, logs, git status, or to parse API payloads unless it is specifically for running project tests or compilation.
- **Jules is Cloud-Based — Do NOT Search the Local File System**: Jules sessions and resources are stored in the cloud. Do NOT attempt to search the user's local hard drive, run local search commands (like find or grep), or locate folders named after the repository you are querying.
  - The **only exception** is if the repository in question is the *currently open repository* in the active IDE workspace.
  - Otherwise, assume there is no local folder, and rely *strictly* on MCP tools (`get_repo_file`, `list_sessions`, `get_session_details`, `get_git_status`, etc.) to query files and details.
- **Execution Context**: Always identify which repository is the active target before performing operations. Use `switch_project` to change context.
- **Isolation**: Keep project code and environment variables strictly separate. Never read files from Project A while in the execution context of Project B, unless using the `search_cross_project_patterns` tool to bridge generic design styles.
- **Jules CLI**: Interfacing with Jules should be done via `orchestrator_cli.py` to ensure commands are run in the appropriate project working directories and outputs are handled in structured JSON.

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

- **Proactive Session Feedback & Context Gathering**: If a Jules session is in `AWAITING USER FEEDBACK` or `AWAITING PLAN APPROVAL` status:
  - Do not ask the user generic questions or stop immediately.
  - Proactively use `get_session_logs` to inspect the exact question or task the session agent is blocked on.
  - Use `get_repo_file` to fetch relevant remote specification files (such as `docs/PLAN.md`, `README.md`, or source code files).
  - Analyze the requirements and present a proposed response or plan recommendation to the user.
  - **Do Not Send Messages Directly Without Explicit User Approval**: Before sending any message or feedback to a Jules session using `send_session_message`, you must present the exact proposed text to the user in chat and wait for their explicit approval.
  - **One Task at a Time (Jules Scope Splitting)**: Jules agents perform best when focused on a single narrow task. Do not overload a session with additional scope. Instruct the Jules agent to perform the immediate task, and tell it to update the project's own `PLAN.md` or `TODO.md` to log any additional scope items (such as secondary security mitigations, advanced authentication, or configuration flags) as backlog items for future sessions.

## MCP Native Tools

If the Model Context Protocol (MCP) server `antigravity-orchestrator` is connected, you should prioritize calling the following tools directly using native model MCP tool calls instead of executing python scripts in the shell:

- **`antigravity-orchestrator/list_sessions`**:
  Retrieves a list of all active and completed Jules sessions.
  
- **`antigravity-orchestrator/get_git_status` `session_id`**:
  Retrieves detailed git comparison, local checkout, and pull request details for the session.

- **`antigravity-orchestrator/get_session_logs` `session_id`**:
  Retrieves activity and agent message logs for the session.

- **`antigravity-orchestrator/create_session` `repo` `task`**:
  Creates a new Jules session for a specific GitHub repository and task description.
  
- **`antigravity-orchestrator/archive_session` `session_id`**:
  Archives a completed/failed Jules session by its ID to hide it from the active dashboard.

- **`antigravity-orchestrator/unarchive_session` `session_id`**:
  Unarchives a previously archived Jules session by its ID to restore it to the active dashboard.

- **`antigravity-orchestrator/list_repos`**:
  Lists all repositories registered in Jules.

- **`antigravity-orchestrator/approve_plan` `session_id`**:
  Approves the proposed engineering plan for a session so Jules starts coding.

- **`antigravity-orchestrator/checkout_branch` `session_id` `branch_name` `project`**:
  Checks out a git branch in the local repository workspace for a Jules session or target branch/project.

- **`antigravity-orchestrator/merge_branch_locally` `target_branch` `session_id` `project`**:
  Attempts to merge a target branch (like 'main') into the current branch locally. Returns conflicted files if there are conflicts.

- **`antigravity-orchestrator/git_commit_and_push` `project` `commit_message`**:
  Stages all changes, commits them, and pushes the current branch to origin.

- **`antigravity-orchestrator/sync_local` `project` `base_branch` `delete_branch`**:
  Syncs the local project workspace by checking out a base branch, pulling origin, and optionally deleting the local feature branch.

- **`antigravity-orchestrator/get_session_plan` `session_id`**:
  Fetches the list of plan steps generated for a given session.

- **`antigravity-orchestrator/get_session_details` `session_id`**:
  Fetch the complete details of a specific Jules session by its ID, including the repository name, short title, and the full, uncut original instruction/prompt text.

- **`antigravity-orchestrator/get_auth_status`**:
  Checks whether the local Jules CLI is logged in.

- **`antigravity-orchestrator/jules_login`**:
  Launches the interactive login flow for Jules in a new command shell window.

- **`antigravity-orchestrator/list_stitch_drafts` `project`**:
  Scans the stitch directory for mock HTML UI designs.

- **`antigravity-orchestrator/generate_stitch_stub` `prompt` `project`**:
  Generates a mock design component from a prompt.

- **`antigravity-orchestrator/export_stitch_design` `project` `target_dir` `format`**:
  Exports a design layout to a path in one of your registered projects.

- **`antigravity-orchestrator/log_instruction` `project` `instruction` `id` `status` `jules_session_id`**:
  Logs or updates a high-level task/instruction in the orchestrator.

- **`antigravity-orchestrator/get_instructions`**:
  Retrieves the list of active/logged instructions.

- **`antigravity-orchestrator/delete_instruction` `id`**:
  Deletes a logged high-level task/instruction by its unique ID (e.g. 'inst_xxxxxx').

- **`antigravity-orchestrator/send_session_message` `session_id` `message`**:
  Send a chat message or feedback to an active Jules session to answer a question or provide further instructions.

- **`antigravity-orchestrator/get_repo_file` `path` `repo` `session_id`**:
  Read the contents of a file (such as a specification markdown sheet, README, or source code file) from a remote GitHub repository. Requires either a direct repository path ('owner/repo') OR a session_id to resolve the repository automatically.

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
  
- **`checkout_jules_branch` `<project>` `<session_id>`**:
  Checks out the session feature branch in the target local project directory.

- **`list_sessions`**:
  Queries the live Google API to retrieve all current and historical Jules sessions across all repositories.

- **`get_git_status` `<session_id>`**:
  Gets detailed branch comparison (ahead/behind counts), local checked out branch status, and Pull Request statuses for a given session.

- **`get_session_logs` `<session_id>`**:
  Fetches full activity/agent conversation logs for a given session.

- **`search_cross_project_patterns` `<query>`**:
  Searches across all projects for generic helper functions or templates to reuse in the current workspace.

## Programmatic Conflict Resolution Guidelines

When you (the agent) are resolving conflicts between a Jules session's feature branch and the base branch (e.g. `main`):
1. **Checkout the Session Branch**: Use `checkout_branch` with the `session_id` to switch your local workspace to the session's feature branch.
2. **Merge the Base Branch**: Run `merge_branch_locally` with `target_branch` as the base branch (usually `main`).
3. **Handle Conflicts**: If conflicts are returned:
   - Read each conflicted file from the list.
   - Look for Git conflict markers: `<<<<<<<`, `=======`, and `>>>>>>>`.
   - Analyze the conflicting code blocks, decide on the correct resolution (e.g. merging both changes, choosing one side, or rewriting), and rewrite the file cleanly without conflict markers.
4. **Commit and Push**: Run `git_commit_and_push` with the project name and a descriptive commit message. This will push the resolved changes back to origin and update the remote Pull Request.
5. **Merge PR on GitHub**: Call `merge_pr` tool to merge the pull request.
6. **Sync Local Workspace**: Call `sync_local` with the session branch name in `delete_branch` to switch back to `main` and delete the local feature branch.

## Autonomous Audit Loop Management Guidelines

When managing the continuous code audit loops on the `Orbits` repository:
1. **Initialize Task**: Use the exact prompt defined in the "Orbits Autonomous Spec Audit & Code Loop" Knowledge Item to trigger a new session.
2. **Monitor Session via Reactive Wakeup (Do NOT Poll or Monitor Manually)**:
   - Jules sessions are monitored in the background by the Antigravity Orchestrator extension. Do NOT run any python scripts, `schedule` timers, or loop on status checks.
   - After creating a session or responding to a request, simply stop calling tools and wait. The IDE will reactively wake you up with a notification message when:
     - The plan is ready for review (`AWAITING_PLAN_APPROVAL` or `AWAITING_USER_FEEDBACK`).
     - The task is finished (`COMPLETED` or `SUCCEEDED`).
     - The session fails (`FAILED` or `CANCELLED`).
   - When woken up by an `AWAITING_PLAN_APPROVAL` or `AWAITING_USER_FEEDBACK` message: Use `get_session_logs` to fetch logs, formulate your plan/reply, seek the user's approval in chat, call `approve_plan` or `send_session_message`, and then wait again.
   - When woken up by a completion message: Proceed to merge and cycle the session.
3. **Publish and Merge Pull Requests (Using GitHub CLI)**:
   - Check the session's git/PR status. If a remote branch was created (e.g. `feat-<repo>-base-<session_id>`) but a PR is not open on GitHub, use the GitHub CLI tool (`gh pr create --title "Jules: <task_title>" --body "Pull request generated from Jules session <session_id>"`) inside the local repository workspace to open/publish the PR.
   - If the PR is open as a draft, run `gh pr ready` inside the local repository workspace to mark it ready for review.
   - Once the PR is published and open, resolve any conflicts locally, commit and push, and use `merge_pr` to finalize the merge.
4. **Delete and Restart**: Call `delete_session` on the completed session (purging local cache if needed), and immediately create a new session using `create_session` with the exact same instructions to start the loop again.

