from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pair_review import core
from pair_review.bridge import ReviewBridge


def test_bridge_uses_same_python_review_engine(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "ONE\ntwo\nthree\nfour\n")
    bridge = ReviewBridge(workspace)
    loaded = bridge.handle("load", {"id": proposal["id"]})
    assert loaded["path"] == "a.txt"
    assert loaded["hunks"][0]["id"] == "h1"
    assert "Submit all reviews" in loaded["html"]
    bridge.handle("draft", {"id": proposal["id"], "hunk": "h1", "value": {"decision": "accepted", "body": "review"}})
    assert core.read_text(workspace / "a.txt") == "one\ntwo\nthree\nfour\n"
    result = bridge.handle("submitReview", {"id": proposal["id"], "scope": "h1"})
    assert result["feedback"]["hunks"][0]["status"] == "accepted"
    assert core.read_text(workspace / "a.txt") == "ONE\ntwo\nthree\nfour\n"
    snapshot = bridge.handle("snapshot", {"id": proposal["id"], "kind": "resolved"})
    assert snapshot == {"text": "ONE\ntwo\nthree\nfour\n", "language": "text", "path": "a.txt"}


def test_json_lines_bridge_process(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "new")
    process = subprocess.Popen(
        [sys.executable, "-m", "pair_review.bridge", "--workspace", str(workspace)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"id": 1, "method": "reviewState", "params": {"id": proposal["id"]}}) + "\n")
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        assert response["id"] == 1
        assert response["result"]["feedback"]["hunks"][0]["status"] == "pending"
        process.stdin.write(json.dumps({"id": 2, "method": "not-a-method", "params": {"id": proposal["id"]}}) + "\n")
        process.stdin.flush()
        error = json.loads(process.stdout.readline())
        assert error["id"] == 2
        assert "Unknown bridge method" in error["error"]["message"]
    finally:
        process.terminate()
        process.wait(timeout=10)
