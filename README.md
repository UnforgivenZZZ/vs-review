# Pair Review MCP 0.4.0

A reimplementation of Pair Review 0.4.0 using **Qwen Skill + Python MCP + a thin VS Code host**. Agents can submit complete candidate files and read published feedback, while reviewers inspect full diffs, discuss individual lines, draft Accept/Reject decisions, and apply changes through Submit in the current VS Code window.

## Architecture

```text
Qwen Skill
   │ Guides proposals, waiting, replies, and revisions
   ▼
Python MCP server ───────┐
 propose / feedback      │ Shares the Python core and .pair-review data
 wait / reply            │
                         ▼
VS Code thin host ── JSON-lines ── Python review bridge
 Webview / native diff          draft / submit / inline comments
 Comments API                   conflict checks / atomic writes
```

All review rules and file writes live in the Python code under `src/pair_review/`. The `vscode/` directory only adapts VS Code APIs. An embedded window and native Comments API require a JavaScript host, but that host does not contain a second review engine.

The MCP server does not expose tools for Accept, Reject, Submit, or modifying review drafts. Agents cannot approve their own changes through MCP.

## Features

- Full original, proposed, and submitted-result previews. The submitted result includes only accepted decisions that have been submitted.
- One immutable candidate snapshot per proposal, with per-hunk Accept, Reject, and Undo.
- Isolation between drafts and submitted feedback, with submission scopes for one hunk, one thread, one comment, or the entire proposal.
- Inline single-line and multi-line discussions on either the original or proposed side, preserving `threadId`, line ranges, side, and `quotedCode`.
- Automatic display of agent `reply_thread` responses in the original thread and review panel without refreshing.
- Independent Send comment actions that do not submit other comments or code decisions.
- Draft preservation when submission conflicts occur, preventing newer user work from being overwritten; safe withdrawal for new files.
- UTF-8, BOM, CRLF, new empty files, a 1 MiB file limit, atomic writes, and interrupted-transaction recovery.
- Full-document syntax highlighting through Pygments, preserving multiline comment and string context when rendering diff fragments.

## Installation

Requirements: Python 3.10+, Node.js 18+, [uv](https://docs.astral.sh/uv/), and VS Code 1.90+ with Comments API support.

### 1. Prepare the Python environment

```bash
uv sync
```

`uv run` also prepares dependencies when the MCP server or VS Code bridge starts for the first time. Set `pairReview.uvPath` in VS Code to use an absolute path to the uv executable.

### 2. Install the Qwen Skill and MCP server

```bash
qwen extensions link "/absolute/path/vs-review"
```

Review the local MCP startup configuration shown by the extension, then restart Qwen Code. The Skill is registered as `vs-review:pair-review`, and the MCP server is named `pair-review`. Start Qwen in the target project; `${workspacePath}` becomes the review root.

### 3. Install the thin VS Code host

```bash
python3 scripts/package.py
```

In VS Code, select **Extensions: Install from VSIX…** and install the generated `dist/pair-review-mcp-0.4.0.vsix`. Qwen and VS Code must open the same project root.

## Usage

Ask the agent directly:

```text
Use pair-review to modify src/example.py and separate reading from parsing.
```

The Skill guides the agent through this workflow:

1. Write a complete candidate under `.pair-review/candidates/`.
2. Call MCP `propose` while leaving the source file unchanged.
3. Open the review panel and full diff automatically in the current VS Code window.
4. Continuously read published feedback through `wait` and respond through `reply` or `reply_thread`.
5. After the reviewer submits, let the Python core apply the accepted hunks. A wait timeout, comment, or draft never constitutes approval.

### MCP tools

| Tool | Purpose |
| --- | --- |
| `propose` | Create a single-file proposal from a complete candidate without modifying the source file |
| `feedback` | Read submitted decisions and published comments |
| `wait` | Wait for feedback after a specified revision and return `waitStatus` |
| `reply` | Reply to a hunk or the general discussion |
| `reply_thread` | Reply to the exact published inline discussion thread |

`wait` defaults to `next_only=true`. `waitStatus="timeout"` means neither approval nor new feedback.

## Data and boundaries

The implementation uses the `.pair-review/proposals/*.dff`, `state/`, `comments/`, and `candidates/` layout. A `.dff` file is JSON containing the complete original and proposed text, not a unified diff. Add `.pair-review/` to the target project's `.gitignore`.

The scope matches 0.4.0: UTF-8 text, one file per proposal, and a maximum file size of 1 MiB. Deletion or rename proposals, binary files, permission changes, and multi-file atomic transactions are not supported. Large, complex diffs may fall back to one hunk. This collaboration workflow cannot prevent other processes from writing files directly.

## Development and verification

```bash
uv sync --extra dev
uv run pytest
npm install --ignore-scripts
npm test
npm run check
npm run test:host
python3 scripts/package.py
```

Tests cover the core state machine, submission scopes, withdrawals and conflicts, inline comments, the MCP stdio handshake, the bridge, and review-page DOM behavior. `test:host` packages the VSIX, installs it into isolated extensions/user-data directories inside the project, and uses a real VS Code Extension Host to verify automatic review, native diffs, inline submission, and source writes. It does not modify your everyday VS Code configuration.

Requirements source: `Pair_Review_Functional_Spec_v0.4.0.pdf`. The original `core.js` and Highlight.js are not bundled. The review engine uses the official Python MCP SDK, Python `difflib`, and Pygments. Non-Python code only adapts VS Code APIs and Webview interactions.
