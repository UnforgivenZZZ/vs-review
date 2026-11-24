from __future__ import annotations

import argparse
import math
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import core

mcp = FastMCP(
    "pair-review",
    instructions=(
        "Propose complete candidate files and collaborate through published review feedback. "
        "These tools never expose reviewer drafts and never accept or reject changes."
    ),
)
_workspace: Path | None = None


def root() -> Path:
    if _workspace is None:
        raise RuntimeError("Pair Review workspace is not configured")
    return _workspace


def _candidate(candidate: str) -> Path:
    workspace = root().resolve()
    path = Path(candidate)
    resolved = (workspace / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise ValueError("Candidate must be inside the workspace") from None
    return resolved


@mcp.tool()
def propose(target: str, candidate: str, title: str = "Agent proposal", agent: str = "qwen-code") -> dict[str, Any]:
    """Create an immutable one-file proposal without modifying the target source file."""
    candidate_path = _candidate(candidate)
    after = core.read_text(candidate_path)
    if after is None:
        raise ValueError("Candidate file missing")
    return core.submit(root(), target, after, title, agent)


@mcp.tool()
def revise(proposal_id: str, candidate: str, title: str | None = None, agent: str | None = None) -> dict[str, Any]:
    """Refresh an existing proposal in place while preserving its complete discussion history."""
    candidate_path = _candidate(candidate)
    after = core.read_text(candidate_path)
    if after is None:
        raise ValueError("Candidate file missing")
    return core.revise(root(), proposal_id, after, title, agent)


@mcp.tool()
def feedback(proposal_id: str) -> dict[str, Any]:
    """Read only submitted decisions and published comments for a proposal."""
    return core.feedback(root(), proposal_id)


@mcp.tool()
def wait(proposal_id: str, timeout: float = 60, since: str | None = None, next_only: bool = True) -> dict[str, Any]:
    """Wait for the next published revision; a timeout is not approval or feedback."""
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Timeout must be a nonnegative number")
    initial = core.feedback(root(), proposal_id)
    baseline = since or initial["revision"]
    deadline = time.monotonic() + timeout
    result = initial
    while (next_only or not result["complete"]) and result["revision"] == baseline and time.monotonic() < deadline:
        time.sleep(0.5)
        result = core.feedback(root(), proposal_id)
    changed = result["revision"] != baseline or (not next_only and result["complete"])
    return {**result, "waitStatus": "update" if changed else "timeout", "timedOut": not changed}


@mcp.tool()
def progress(
    proposal_id: str,
    summary: str,
    hunk: str = "general",
    thread_id: str | None = None,
    agent: str = "qwen-code",
) -> dict[str, Any]:
    """Publish a short reasoning/progress summary without changing review feedback or source files."""
    return core.progress(root(), proposal_id, summary, hunk, thread_id, agent)


@mcp.tool()
def clear_progress(proposal_id: str, hunk: str = "general", thread_id: str | None = None, agent: str = "qwen-code") -> dict[str, Any]:
    """Clear an unfinished summary when no formal reply will be sent."""
    return {"events": core.clear_activity(root(), proposal_id, hunk, agent, thread_id)}


@mcp.tool()
def reply(proposal_id: str, hunk: str, body: str, agent: str = "qwen-code") -> dict[str, Any]:
    """Reply to a hunk or general discussion; use reply_thread for inline discussions."""
    return core.comment(root(), proposal_id, hunk, body, agent)


@mcp.tool()
def reply_thread(proposal_id: str, thread_id: str, body: str, agent: str = "qwen-code") -> dict[str, Any]:
    """Reply to an existing published inline thread while preserving its source anchor."""
    return core.reply_thread(root(), proposal_id, thread_id, body, agent)


def main() -> None:
    global _workspace
    parser = argparse.ArgumentParser(description="Pair Review MCP server")
    parser.add_argument("--workspace", required=True)
    arguments = parser.parse_args()
    _workspace = Path(arguments.workspace).resolve()
    if not _workspace.is_dir():
        parser.error("Workspace root does not exist")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
