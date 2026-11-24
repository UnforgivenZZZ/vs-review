from __future__ import annotations

import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pair_review import core


async def _exercise(workspace: Path):
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pair_review.mcp_server", "--workspace", str(workspace)],
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {"propose", "revise", "feedback", "wait", "progress", "clear_progress", "reply", "reply_thread"}
            candidate = workspace / ".pair-review/candidates/a.txt"
            candidate.parent.mkdir(parents=True)
            candidate.write_text("new", encoding="utf-8")
            proposed = await session.call_tool(
                "propose",
                {"target": "a.txt", "candidate": ".pair-review/candidates/a.txt", "title": "MCP test", "agent": "pytest"},
            )
            assert not proposed.isError
            proposal = proposed.structuredContent
            assert core.read_text(workspace / "a.txt") == "one\ntwo\nthree\nfour\n"
            initial = await session.call_tool("feedback", {"proposal_id": proposal["id"]})
            revision = initial.structuredContent["revision"]
            timeout = await session.call_tool("wait", {"proposal_id": proposal["id"], "timeout": 0, "since": revision})
            assert timeout.structuredContent["waitStatus"] == "timeout"
            core.comment(workspace, proposal["id"], "h1", "Please explain", "reviewer")
            update = await session.call_tool("wait", {"proposal_id": proposal["id"], "timeout": 0, "since": revision})
            assert update.structuredContent["waitStatus"] == "update"
            thinking = await session.call_tool(
                "progress",
                {"proposal_id": proposal["id"], "hunk": "h1", "summary": "Checking the API contract", "agent": "pytest"},
            )
            assert thinking.structuredContent["summary"] == "Checking the API contract"
            assert core.activity(workspace, proposal["id"])[0]["hunk"] == "h1"
            replied = await session.call_tool(
                "reply",
                {"proposal_id": proposal["id"], "hunk": "h1", "body": "Explanation", "agent": "pytest"},
            )
            assert replied.structuredContent["author"] == "pytest"
            assert core.activity(workspace, proposal["id"]) == []
            inline = core.save_inline_draft(
                workspace,
                proposal["id"],
                {"side": "proposed", "startLine": 1, "endLine": 1},
                "Inline question",
            )
            core.submit_review(workspace, proposal["id"], f"thread:{inline['threadId']}")
            await session.call_tool(
                "progress",
                {"proposal_id": proposal["id"], "thread_id": inline["threadId"], "summary": "Reading the quoted code", "agent": "pytest"},
            )
            threaded = await session.call_tool(
                "reply_thread",
                {"proposal_id": proposal["id"], "thread_id": inline["threadId"], "body": "Inline answer", "agent": "pytest"},
            )
            assert threaded.structuredContent["threadId"] == inline["threadId"]
            assert core.activity(workspace, proposal["id"]) == []
            candidate.write_text("revised", encoding="utf-8")
            revised = await session.call_tool("revise", {"proposal_id": proposal["id"], "candidate": ".pair-review/candidates/a.txt"})
            assert revised.structuredContent["id"] == proposal["id"]
            assert revised.structuredContent["proposalRevision"] == 2
            history = await session.call_tool("feedback", {"proposal_id": proposal["id"]})
            assert len(history.structuredContent["comments"]) == 4
            outside = await session.call_tool("propose", {"target": "a.txt", "candidate": "/outside/candidate"})
            assert outside.isError


def test_mcp_stdio_end_to_end(workspace: Path):
    anyio.run(_exercise, workspace)
