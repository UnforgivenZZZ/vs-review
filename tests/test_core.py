from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from pair_review import core


def test_propose_does_not_touch_target_and_decisions_are_independent(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "ONE\ntwo\nthree\nFOUR\n")
    assert core.read_text(workspace / "a.txt") == "one\ntwo\nthree\nfour\n"
    assert proposal["hunks"] == ["h1", "h2"]
    core.decide(workspace, proposal["id"], "h2", "accepted")
    core.decide(workspace, proposal["id"], "h1", "rejected")
    assert core.read_text(workspace / "a.txt") == "one\ntwo\nthree\nFOUR\n"
    assert core.feedback(workspace, proposal["id"])["complete"] is True
    with pytest.raises(ValueError, match="already"):
        core.decide(workspace, proposal["id"], "h2", "accepted")


def test_conflict_never_overwrites_unrelated_work(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "new")
    (workspace / "a.txt").write_text("user edit", encoding="utf-8")
    with pytest.raises(ValueError, match="Conflict"):
        core.decide(workspace, proposal["id"], "h1", "accepted")
    assert core.read_text(workspace / "a.txt") == "user edit"


def test_comments_persist_without_deciding(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "new")
    core.comment(workspace, proposal["id"], "h1", "Why?", "reviewer", 1)
    core.comment(workspace, proposal["id"], "h1", "Because…", "qwen")
    result = core.feedback(workspace, proposal["id"])
    assert len(result["comments"]) == 2
    assert result["hunks"][0]["status"] == "pending"


@pytest.mark.parametrize("target,after", [("new.txt", "hello"), ("empty.txt", "")])
def test_new_files_stay_absent_until_accepted(workspace: Path, target: str, after: str):
    proposal = core.submit(workspace, target, after)
    assert core.read_text(workspace / target) is None
    core.decide(workspace, proposal["id"], "h1", "accepted")
    assert core.read_text(workspace / target) == after


def test_rejecting_new_file_leaves_it_absent(workspace: Path):
    proposal = core.submit(workspace, "new.txt", "hello")
    core.decide(workspace, proposal["id"], "h1", "rejected")
    assert core.read_text(workspace / "new.txt") is None


def test_path_traversal_reserved_paths_and_symlinks_are_rejected(workspace: Path):
    with pytest.raises(ValueError, match="traversal"):
        core.submit(workspace, "../escape", "x")
    with pytest.raises(ValueError, match="Reserved"):
        core.submit(workspace, ".git/config", "x")
    (workspace / "link").symlink_to(workspace / "a.txt")
    with pytest.raises(ValueError, match="Symlink"):
        core.submit(workspace, "link", "x")


def test_proposal_tampering_is_detected(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "ONE\ntwo\nthree\nFOUR\n")
    core.decide(workspace, proposal["id"], "h1", "rejected")
    file = Path(proposal["file"])
    data = json.loads(file.read_text(encoding="utf-8"))
    data["after"] = "tampered"
    file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="changed after"):
        core.feedback(workspace, proposal["id"])


@pytest.mark.parametrize(
    "before,after",
    [
        ("a\r\nb\r\n", "A\r\nb\r\n"),
        ("你好\n", "你好"),
        ("\ufeffa", "\ufeffb"),
        ("a\n" * 1800, "b\n" * 1800),
        ("", "x"),
        ("x", ""),
    ],
)
def test_text_roundtrip(workspace: Path, before: str, after: str):
    (workspace / "a.txt").write_text(before, encoding="utf-8", newline="")
    proposal = core.submit(workspace, "a.txt", after)
    loaded = core.load(workspace, proposal["id"])
    assert core.render(loaded, {hunk["id"]: "accepted" for hunk in loaded["hunks"]}) == after
    for hunk in loaded["hunks"]:
        core.decide(workspace, proposal["id"], hunk["id"], "accepted")
    assert core.read_text(workspace / "a.txt") == after


def test_interrupted_accept_recovers_from_committed_file(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "new")
    loaded = core.load(workspace, proposal["id"])
    current_state = core.state(workspace, loaded)
    current_state["transaction"] = {"before": loaded["before"], "after": "new", "hunk": "h1"}
    core.json_write(core.state_path(workspace, proposal["id"]), current_state)
    (workspace / "a.txt").write_text("new", encoding="utf-8")
    assert core.feedback(workspace, proposal["id"])["hunks"][0]["status"] == "accepted"


def test_randomized_diffs_reconstruct_both_versions():
    randomizer = random.Random(19)
    for _ in range(300):
        before = "".join(f"{randomizer.randrange(6)}\n" for _ in range(randomizer.randrange(18)))
        after = "".join(f"{randomizer.randrange(6)}\n" for _ in range(randomizer.randrange(18)))
        proposal = {"before": before, "after": after, "hunks": core.diff(before, after)}
        assert core.render(proposal, {}) == before
        assert core.render(proposal, {}, True) == after


def test_drafts_do_not_change_feedback_or_target(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "ONE\ntwo\nthree\nFOUR\n")
    before = core.feedback(workspace, proposal["id"])
    core.draft(workspace, proposal["id"], "h1", {"decision": "accepted", "body": "question", "line": 1})
    core.draft(workspace, proposal["id"], "h2", {"decision": "rejected", "body": ""})
    assert core.feedback(workspace, proposal["id"]) == before
    assert core.read_text(workspace / "a.txt") == "one\ntwo\nthree\nfour\n"
    core.draft(workspace, proposal["id"], "h1", {"decision": None, "body": ""})
    core.discard_draft(workspace, proposal["id"], "h2")
    assert core.feedback(workspace, proposal["id"]) == before


def test_scoped_submit_publishes_only_selected_draft(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "ONE\ntwo\nthree\nFOUR\n")
    core.draft(workspace, proposal["id"], "h1", {"decision": "accepted", "body": "first"})
    core.draft(workspace, proposal["id"], "h2", {"decision": "rejected", "body": "second"})
    core.submit_review(workspace, proposal["id"], "h1")
    result = core.feedback(workspace, proposal["id"])
    assert [hunk["status"] for hunk in result["hunks"]] == ["accepted", "pending"]
    assert [comment["body"] for comment in result["comments"]] == ["first"]
    assert core.read_text(workspace / "a.txt") == "ONE\ntwo\nthree\nfour\n"
    remaining = core.state(workspace, core.load(workspace, proposal["id"]))
    assert remaining["drafts"]["h2"]["body"] == "second"


def test_submit_all_and_withdraw_decisions(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "ONE\ntwo\nthree\nFOUR\n")
    for hunk in ("h1", "h2"):
        core.draft(workspace, proposal["id"], hunk, {"decision": "accepted", "body": ""})
    core.draft(workspace, proposal["id"], "general", {"body": "reviewed"})
    core.submit_review(workspace, proposal["id"])
    assert core.read_text(workspace / "a.txt") == "ONE\ntwo\nthree\nFOUR\n"
    for hunk in ("h1", "h2"):
        core.draft(workspace, proposal["id"], hunk, {"decision": None, "body": ""})
    core.submit_review(workspace, proposal["id"])
    assert core.feedback(workspace, proposal["id"])["complete"] is False
    assert core.read_text(workspace / "a.txt") == "one\ntwo\nthree\nfour\n"
    with pytest.raises(ValueError, match="No draft"):
        core.submit_review(workspace, proposal["id"])


def test_conflict_preserves_all_drafts_and_allows_comment_only_review(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "new")
    core.draft(workspace, proposal["id"], "h1", {"decision": "accepted", "body": "private"})
    before = core.feedback(workspace, proposal["id"])
    (workspace / "a.txt").write_text("other edits", encoding="utf-8")
    with pytest.raises(ValueError, match="Conflict"):
        core.submit_review(workspace, proposal["id"])
    assert core.feedback(workspace, proposal["id"]) == before
    assert core.state(workspace, core.load(workspace, proposal["id"]))["drafts"]["h1"]["body"] == "private"
    core.draft(workspace, proposal["id"], "h1", {"body": "needs rebase"})
    core.submit_review(workspace, proposal["id"], "h1")
    assert core.feedback(workspace, proposal["id"])["comments"][0]["body"] == "needs rebase"
    assert core.read_text(workspace / "a.txt") == "other edits"


def test_withdrawing_new_file_accept_removes_only_unchanged_file(workspace: Path):
    proposal = core.submit(workspace, "new.txt", "hello")
    core.draft(workspace, proposal["id"], "h1", {"decision": "accepted", "body": ""})
    core.submit_review(workspace, proposal["id"])
    assert core.read_text(workspace / "new.txt") == "hello"
    core.draft(workspace, proposal["id"], "h1", {"decision": None, "body": ""})
    core.submit_review(workspace, proposal["id"])
    assert core.read_text(workspace / "new.txt") is None


def test_batch_transaction_recovery_commits_state_and_comments(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "new")
    core.draft(workspace, proposal["id"], "h1", {"decision": "accepted", "body": "review"})
    loaded = core.load(workspace, proposal["id"])
    current_state = core.state(workspace, loaded)
    next_state = {
        **current_state,
        "decisions": {"h1": "accepted"},
        "drafts": {},
        "publishedComments": [{"id": "test", "hunk": "h1", "author": "reviewer", "body": "review", "at": "2026-01-01"}],
    }
    current_state["transaction"] = {"before": loaded["before"], "after": "new", "nextState": next_state}
    core.json_write(core.state_path(workspace, proposal["id"]), current_state)
    (workspace / "a.txt").write_text("new", encoding="utf-8")
    result = core.feedback(workspace, proposal["id"])
    assert result["hunks"][0]["status"] == "accepted"
    assert result["comments"][0]["body"] == "review"


def test_send_comment_preserves_accept_and_other_private_drafts(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "ONE\ntwo\nthree\nFOUR\n")
    core.draft(workspace, proposal["id"], "h1", {"decision": "accepted", "body": "Question now", "line": 1})
    core.draft(workspace, proposal["id"], "h2", {"decision": "rejected", "body": "Keep private"})
    core.send_draft_comment(workspace, proposal["id"], "h1")
    result = core.feedback(workspace, proposal["id"])
    current_state = core.state(workspace, core.load(workspace, proposal["id"]))
    assert result["comments"][0]["body"] == "Question now"
    assert result["hunks"][0]["status"] == "pending"
    assert current_state["drafts"]["h1"]["decision"] == "accepted"
    assert current_state["drafts"]["h2"]["body"] == "Keep private"


def test_inline_threads_keep_anchors_and_publish_independently(workspace: Path):
    before = "// heading\nconst first = 1;\nconst stable = 2;\nconst last = 3;\n"
    after = "// heading\nconst first = 10;\nconst stable = 2;\nconst last = 30;\n"
    (workspace / "a.ts").write_text(before, encoding="utf-8")
    proposal = core.submit(workspace, "a.ts", after)
    original_feedback = core.feedback(workspace, proposal["id"])
    first = core.save_inline_draft(workspace, proposal["id"], {"side": "original", "startLine": 2, "endLine": 3}, "Why change this range?")
    second = core.save_inline_draft(workspace, proposal["id"], {"side": "proposed", "startLine": 4, "endLine": 4}, "Another thread")
    assert first["hunk"] == "h1"
    assert "first = 1" in first["quotedCode"]
    assert core.feedback(workspace, proposal["id"]) == original_feedback
    core.submit_review(workspace, proposal["id"], f"thread:{first['threadId']}")
    result = core.feedback(workspace, proposal["id"])
    assert [comment["body"] for comment in result["comments"]] == ["Why change this range?"]
    assert result["hunks"][0]["status"] == "pending"
    response = core.reply_thread(workspace, proposal["id"], first["threadId"], "Because of the API", "qwen")
    for field in ("threadId", "side", "startLine", "endLine", "quotedCode", "hunk"):
        assert response[field] == first[field]
    core.save_inline_draft(workspace, proposal["id"], second, "Reworded", {"draftId": second["id"], "threadId": second["threadId"]})
    core.discard_inline_draft(workspace, proposal["id"], second["id"])
    assert len(core.state(workspace, core.load(workspace, proposal["id"]))["inlineDrafts"]) == 0


def test_invalid_inline_ranges_and_unpublished_replies_are_rejected(workspace: Path):
    proposal = core.submit(workspace, "a.txt", "ONE\ntwo\nthree\nfour\n")
    with pytest.raises(ValueError, match="range"):
        core.save_inline_draft(workspace, proposal["id"], {"side": "proposed", "startLine": 0, "endLine": 1}, "bad")
    draft = core.save_inline_draft(workspace, proposal["id"], {"side": "original", "startLine": 2, "endLine": 2}, "draft")
    with pytest.raises(ValueError, match="cannot change"):
        core.save_inline_draft(workspace, proposal["id"], {"side": "proposed", "startLine": 2, "endLine": 2}, "moved", {"threadId": draft["threadId"]})
    with pytest.raises(ValueError, match="Unknown published"):
        core.reply_thread(workspace, proposal["id"], draft["threadId"], "too early")
