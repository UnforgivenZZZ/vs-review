---
name: pair-review
description: Use Pair Review when the user asks for proposal-first coding, candidate review, VS Code approval, or says to use pair-review; submit complete candidates through MCP and collaborate only on published feedback without editing reviewed source files.
---

# Pair Review

Submit complete candidates through the `pair-review` MCP server for review in the user's current VS Code window. The available MCP tools are `propose`, `feedback`, `wait`, `reply`, and `reply_thread`.

## Propose one logical change

1. Confirm that the `pair-review` MCP server is connected. If it is unavailable, ask the user to install or enable the extension rather than falling back to direct source edits.
2. Read the current source file and write the **complete modified file** under `.pair-review/candidates/` in the project. Keep each proposal focused on one understandable logical change.
3. Call `propose`: `target` is the project-relative source path, `candidate` is the complete candidate path, `title` describes the intent, and `agent` is the current agent name.
4. Return the proposal ID, target, and purpose. The VS Code extension automatically opens the review panel and full diff. Do not run `code`, `code -n`, or `open -a`, and do not switch workspaces.

A candidate's existence is not authorization. Keep source files unchanged until reviewer submission. Tests, formatters, and other scripts must not bypass review by writing targets.

## Wait for published feedback

1. Call `feedback` to obtain a `revision`, then call `wait` with `timeout: 60`, that revision as `since`, and `next_only: true`.
2. `waitStatus: "timeout"` only means that no new message arrived. Continue waiting; never interpret it as approval. Keep waiting for follow-up questions even after every hunk has a decision, until the user explicitly asks you to stop or the execution environment cannot continue. State clearly when you are no longer waiting.
3. Act only on submitted decisions and published comments returned by `feedback`. Accept/Reject drafts, `inlineDrafts`, and `state` are private to the reviewer. Do not read, modify, or act on them.
4. The user may submit one hunk at a time and may withdraw previously submitted decisions. Read `feedback` and the current source file again before continuing any change.

## Reply and revise

- When a comment contains `threadId`, call `reply_thread` to respond in the exact discussion. Use `side`, `startLine`, `endLine`, and `quotedCode` to understand its code location. Use `reply` for panel hunks or the general discussion.
- Answer questions first, then decide whether a new candidate is needed. After replying, read `feedback` again for the new revision and continue waiting. Your own replies are not new user tasks.
- For a revision, reread the current source, create a new complete candidate, and call `propose`. Identify the superseded proposal in the title and remind the user to review the new proposal rather than accepting an outdated one. Keep old proposals and their discussions independent.
- When multiple proposals remain active, poll each proposal's `feedback` in turn so questions in older threads are not missed.

Without a concrete development task, wait for the user instead of choosing code changes yourself.
