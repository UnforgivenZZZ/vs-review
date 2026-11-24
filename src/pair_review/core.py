from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

LIMIT = 1024 * 1024
UUID_RE = re.compile(r"^[a-f0-9-]{36}$")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def split_lines(text: str) -> list[str]:
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def safe(root: str | Path, relative: str, internal: bool = False) -> Path:
    _assert(
        isinstance(relative, str)
        and bool(relative)
        and "\\" not in relative
        and "\0" not in relative
        and ":" not in relative,
        "Invalid relative path",
    )
    parts = relative.split("/")
    _assert(all(part and part not in (".", "..") for part in parts), "Path traversal is not allowed")
    _assert(internal or not any(part.lower() in (".git", ".pair-review") for part in parts), "Reserved path")
    target = Path(root).resolve()
    for part in parts:
        target = target / part
        try:
            target.lstat()
            _assert(not target.is_symlink(), "Symlinks are not supported")
        except FileNotFoundError:
            pass
    return target


def read_text(file: str | Path) -> str | None:
    path = Path(file)
    try:
        _assert(path.stat().st_size <= LIMIT, "Text file exceeds 1 MiB")
        data = path.read_bytes()
        text = data.decode("utf-8", errors="strict")
        _assert("\0" not in text, "Binary files are not supported")
        return text
    except FileNotFoundError:
        return None


def atomic(file: str | Path, value: str | bytes) -> None:
    path = Path(file)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value.encode("utf-8") if isinstance(value, str) else value
    temporary = path.with_name(path.name + "." + str(uuid.uuid4()) + ".tmp")
    mode = 0o600
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        pass
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def json_write(file: str | Path, value: Any) -> None:
    atomic(file, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def diff(before: str | None, after: str) -> list[dict[str, Any]]:
    a = split_lines(before or "")
    b = split_lines(after)
    prefix = 0
    end_a, end_b = len(a), len(b)
    while prefix < end_a and prefix < end_b and a[prefix] == b[prefix]:
        prefix += 1
    while end_a > prefix and end_b > prefix and a[end_a - 1] == b[end_b - 1]:
        end_a -= 1
        end_b -= 1
    if prefix == end_a and prefix == end_b:
        return [{"id": "h1", "start": 0, "end": 0, "old": "", "text": ""}] if before is None else []

    changed_original = a[prefix:end_a]
    changed_candidate = b[prefix:end_b]
    if (len(changed_original) + 1) * (len(changed_candidate) + 1) > 2_000_000:
        operations = [("replace", 0, len(changed_original), 0, len(changed_candidate))]
    else:
        operations = SequenceMatcher(None, changed_original, changed_candidate, autojunk=False).get_opcodes()

    edits: list[dict[str, Any]] = []
    for operation, old_start, old_end, new_start, new_end in operations:
        if operation == "equal":
            continue
        edits.append(
            {
                "id": f"h{len(edits) + 1}",
                "start": prefix + old_start,
                "end": prefix + old_end,
                "old": "".join(a[prefix + old_start : prefix + old_end]),
                "text": "".join(b[prefix + new_start : prefix + new_end]),
            }
        )
    return edits


def render(proposal: dict[str, Any], decisions: dict[str, str], include_pending: bool = False) -> str | None:
    original = split_lines(proposal["before"] or "")
    cursor = 0
    result: list[str] = []
    for hunk in proposal["hunks"]:
        result.extend(original[cursor : hunk["start"]])
        use_candidate = decisions.get(hunk["id"]) == "accepted" or (include_pending and hunk["id"] not in decisions)
        result.append(hunk["text"] if use_candidate else hunk["old"])
        cursor = hunk["end"]
    result.extend(original[cursor:])
    if proposal["before"] is None and not any(
        decisions.get(hunk["id"]) == "accepted" or (include_pending and hunk["id"] not in decisions)
        for hunk in proposal["hunks"]
    ):
        return None
    return "".join(result)


def submit(root: str | Path, target: str, after: str, title: str = "Agent proposal", agent: str = "terminal-agent") -> dict[str, Any]:
    before = read_text(safe(root, target))
    _assert(isinstance(after, str) and len(after.encode("utf-8")) <= LIMIT and "\0" not in after, "Expected UTF-8 text up to 1 MiB")
    hunks = diff(before, after)
    _assert(bool(hunks), "No changes to propose")
    proposal = {
        "version": 1,
        "id": str(uuid.uuid4()),
        "path": target,
        "title": title,
        "agent": agent,
        "createdAt": _now(),
        "before": before,
        "after": after,
        "hunks": hunks,
    }
    file = safe(root, f".pair-review/proposals/{proposal['id']}.dff", True)
    json_write(file, proposal)
    return {"id": proposal["id"], "file": str(file), "hunks": [hunk["id"] for hunk in hunks]}


def state_path(root: str | Path, proposal_id: str) -> Path:
    return safe(root, f".pair-review/state/{proposal_id}.json", True)


def fingerprint(proposal: dict[str, Any]) -> str:
    return hashlib.sha256(_json_bytes([proposal["id"], proposal["path"], proposal["before"], proposal["after"]])).hexdigest()


def load(root: str | Path, proposal_id: str) -> dict[str, Any]:
    _assert(isinstance(proposal_id, str) and bool(UUID_RE.fullmatch(proposal_id)), "Invalid proposal ID")
    file = safe(root, f".pair-review/proposals/{proposal_id}.dff", True)
    _assert(file.stat().st_size <= LIMIT * 5, "Proposal too large")
    proposal = json.loads(file.read_text(encoding="utf-8"))
    _assert(
        proposal["id"] == proposal_id
        and proposal["version"] == 1
        and (isinstance(proposal["before"], str) or proposal["before"] is None)
        and isinstance(proposal["after"], str),
        "Invalid proposal",
    )
    _assert(
        len((proposal["before"] or "").encode("utf-8")) <= LIMIT
        and len(proposal["after"].encode("utf-8")) <= LIMIT
        and "\0" not in proposal["after"],
        "Invalid text",
    )
    _assert(isinstance(proposal["title"], str) and isinstance(proposal["agent"], str), "Invalid metadata")
    safe(root, proposal["path"])
    proposal["hunks"] = diff(proposal["before"], proposal["after"])
    _assert(bool(proposal["hunks"]), "Empty proposal")
    return proposal


def state(root: str | Path, proposal: dict[str, Any]) -> dict[str, Any]:
    try:
        current_state = json.loads(state_path(root, proposal["id"]).read_text(encoding="utf-8"))
    except FileNotFoundError:
        current_state = {"fingerprint": fingerprint(proposal), "decisions": {}}
    _assert(current_state["fingerprint"] == fingerprint(proposal), "Proposal changed after review began; submit a new proposal")
    if current_state.get("transaction"):
        current = read_text(safe(root, proposal["path"]))
        transaction = current_state["transaction"]
        if current == transaction["after"]:
            if transaction.get("nextState") is not None:
                current_state = transaction["nextState"]
            else:
                current_state["decisions"][transaction["hunk"]] = "accepted"
        else:
            _assert(current == transaction["before"], "Interrupted accept conflicts with workspace; restore the file before retrying")
        current_state.pop("transaction", None)
        json_write(state_path(root, proposal["id"]), current_state)
    return current_state


def decide(root: str | Path, proposal_id: str, hunk_id: str, decision: str) -> dict[str, Any]:
    _assert(decision in ("accepted", "rejected"), "Unknown decision")
    proposal = load(root, proposal_id)
    current_state = state(root, proposal)
    _assert(any(hunk["id"] == hunk_id for hunk in proposal["hunks"]), "Unknown hunk")
    _assert(hunk_id not in current_state["decisions"], "Hunk already decided")
    if decision == "accepted":
        target = safe(root, proposal["path"])
        current = read_text(target)
        _assert(current == render(proposal, current_state["decisions"]), "Conflict: workspace changed. Submit a new proposal from current content.")
        after = render(proposal, {**current_state["decisions"], hunk_id: decision})
        current_state["transaction"] = {"before": current, "after": after, "hunk": hunk_id}
        json_write(state_path(root, proposal_id), current_state)
        _assert(after is not None, "Invalid accepted result")
        atomic(target, after)
        current_state.pop("transaction", None)
    current_state["decisions"][hunk_id] = decision
    json_write(state_path(root, proposal_id), current_state)
    return current_state


def activity_path(root: str | Path, proposal_id: str) -> Path:
    return safe(root, f".pair-review/activity/{proposal_id}.json", True)


def activity(root: str | Path, proposal_id: str) -> list[dict[str, Any]]:
    load(root, proposal_id)
    try:
        document = json.loads(activity_path(root, proposal_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    _assert(document.get("version") == 1 and document.get("proposal") == proposal_id and isinstance(document.get("events"), list), "Invalid activity")
    return document["events"]


def clear_activity(root: str | Path, proposal_id: str, hunk: str, agent: str, thread_id: str | None = None) -> list[dict[str, Any]]:
    events = activity(root, proposal_id)
    remaining = [
        event
        for event in events
        if not (event["agent"] == agent and event["hunk"] == hunk and event.get("threadId") == thread_id)
    ]
    if len(remaining) != len(events):
        json_write(activity_path(root, proposal_id), {"version": 1, "proposal": proposal_id, "events": remaining})
    return remaining


def progress(
    root: str | Path,
    proposal_id: str,
    summary: str,
    hunk: str = "general",
    thread_id: str | None = None,
    agent: str = "qwen-code",
) -> dict[str, Any]:
    proposal = load(root, proposal_id)
    _assert(isinstance(summary, str) and bool(summary.strip()) and len(summary) <= 4_000, "Progress summary must contain 1–4000 characters")
    _assert(isinstance(agent, str) and bool(agent.strip()) and len(agent) <= 100, "Invalid agent name")
    if thread_id is not None:
        parent = next((item for item in feedback(root, proposal_id)["comments"] if item.get("threadId") == thread_id), None)
        _assert(parent is not None, "Unknown published thread")
        hunk = parent["hunk"]
    else:
        _assert(hunk == "general" or any(item["id"] == hunk for item in proposal["hunks"]), "Unknown hunk")
    events = activity(root, proposal_id)
    previous = next(
        (event for event in events if event["agent"] == agent and event["hunk"] == hunk and event.get("threadId") == thread_id),
        None,
    )
    event = {
        "id": previous["id"] if previous else str(uuid.uuid4()),
        "proposal": proposal_id,
        "hunk": hunk,
        "threadId": thread_id,
        "agent": agent,
        "summary": summary,
        "at": _now(),
    }
    remaining = [item for item in events if item["id"] != event["id"]]
    remaining.append(event)
    json_write(activity_path(root, proposal_id), {"version": 1, "proposal": proposal_id, "events": remaining})
    return event


def comment(root: str | Path, proposal_id: str, hunk: str, body: str, author: str = "reviewer", line: int | None = None) -> dict[str, Any]:
    proposal = load(root, proposal_id)
    _assert(hunk == "general" or any(item["id"] == hunk for item in proposal["hunks"]), "Unknown hunk")
    _assert(isinstance(body, str) and bool(body.strip()) and len(body) <= 20_000, "Comment must contain 1–20000 characters")
    _assert(line is None or (isinstance(line, int) and not isinstance(line, bool) and 1 <= line <= len(split_lines(proposal["after"]))), "Invalid proposed line")
    item = {"id": str(uuid.uuid4()), "proposal": proposal_id, "hunk": hunk, "line": line, "body": body, "author": author, "at": _now()}
    json_write(safe(root, f".pair-review/comments/{proposal_id}/{item['id']}.json", True), item)
    clear_activity(root, proposal_id, hunk, author)
    return item


def feedback(root: str | Path, proposal_id: str) -> dict[str, Any]:
    proposal = load(root, proposal_id)
    current_state = state(root, proposal)
    directory = safe(root, f".pair-review/comments/{proposal_id}", True)
    comments: list[dict[str, Any]] = []
    if directory.exists():
        for file in directory.iterdir():
            if UUID_RE.fullmatch(file.stem) and file.suffix == ".json":
                comments.append(json.loads(file.read_text(encoding="utf-8")))
    comments.extend(current_state.get("publishedComments", []))
    comments.sort(key=lambda item: (item["at"], item["id"]))
    result = {
        "id": proposal_id,
        "path": proposal["path"],
        "hunks": [{"id": hunk["id"], "status": current_state["decisions"].get(hunk["id"], "pending")} for hunk in proposal["hunks"]],
        "comments": comments,
        "complete": all(hunk["id"] in current_state["decisions"] for hunk in proposal["hunks"]),
    }
    return {**result, "revision": hashlib.sha256(_json_bytes(result)).hexdigest()}


def draft(root: str | Path, proposal_id: str, hunk: str, value: dict[str, Any]) -> dict[str, Any]:
    proposal = load(root, proposal_id)
    current_state = state(root, proposal)
    _assert(hunk == "general" or any(item["id"] == hunk for item in proposal["hunks"]), "Unknown hunk")
    _assert(isinstance(value, dict), "Invalid draft")
    item: dict[str, Any] = {}
    if "decision" in value:
        _assert(hunk != "general" and value["decision"] in (None, "accepted", "rejected"), "Unknown decision")
        if value["decision"] != current_state["decisions"].get(hunk):
            item["decision"] = value["decision"]
    _assert(isinstance(value.get("body"), str) and len(value["body"]) <= 20_000, "Comment limit: 20000 characters")
    item["body"] = value["body"]
    raw_line = value.get("line")
    if raw_line in (None, ""):
        item["line"] = None
    else:
        try:
            number = float(raw_line)
        except (TypeError, ValueError):
            raise ValueError("Invalid proposed line") from None
        _assert(number.is_integer(), "Invalid proposed line")
        item["line"] = int(number)
    _assert(item["line"] is None or 1 <= item["line"] <= len(split_lines(proposal["after"])), "Invalid proposed line")
    current_state.setdefault("drafts", {})
    if "decision" in item or item["body"].strip():
        current_state["drafts"][hunk] = item
    else:
        current_state["drafts"].pop(hunk, None)
    json_write(state_path(root, proposal_id), current_state)
    return current_state


def discard_draft(root: str | Path, proposal_id: str, hunk: str) -> dict[str, Any]:
    proposal = load(root, proposal_id)
    current_state = state(root, proposal)
    current_state.get("drafts", {}).pop(hunk, None)
    json_write(state_path(root, proposal_id), current_state)
    return current_state


def submit_review(root: str | Path, proposal_id: str, scope: str = "all") -> dict[str, Any]:
    proposal = load(root, proposal_id)
    current_state = state(root, proposal)
    valid_thread_scope = bool(re.fullmatch(r"(thread|comment):[a-f0-9-]{36}", scope))
    _assert(scope in ("all", "general") or any(hunk["id"] == scope for hunk in proposal["hunks"]) or valid_thread_scope, "Unknown review scope")
    keys = [hunk for hunk in current_state.get("drafts", {}) if scope in ("all", hunk)]
    inline_keys = [
        key
        for key, item in current_state.get("inlineDrafts", {}).items()
        if scope in ("all", item["hunk"], f"thread:{item['threadId']}", f"comment:{item['id']}")
    ]
    _assert(bool(keys) or bool(inline_keys), "No draft changes to submit")
    next_state = copy.deepcopy(current_state)
    next_state.setdefault("publishedComments", [])
    for hunk in keys:
        item = next_state["drafts"][hunk]
        if "decision" in item:
            if item["decision"] is None:
                next_state["decisions"].pop(hunk, None)
            else:
                next_state["decisions"][hunk] = item["decision"]
        if item["body"].strip():
            next_state["publishedComments"].append(
                {"id": str(uuid.uuid4()), "proposal": proposal_id, "hunk": hunk, "line": item["line"], "body": item["body"], "author": "reviewer", "at": _now()}
            )
        del next_state["drafts"][hunk]
    for key in inline_keys:
        next_state["publishedComments"].append({**next_state["inlineDrafts"][key], "author": "reviewer", "at": _now()})
        del next_state["inlineDrafts"][key]

    before = render(proposal, current_state["decisions"])
    after = render(proposal, next_state["decisions"])
    if before != after:
        target = safe(root, proposal["path"])
        _assert(read_text(target) == before, "Conflict: workspace changed. Review was not submitted; drafts are preserved.")
        current_state["transaction"] = {"before": before, "after": after, "nextState": next_state}
        json_write(state_path(root, proposal_id), current_state)
        if after is None:
            target.unlink()
        else:
            atomic(target, after)
    json_write(state_path(root, proposal_id), next_state)
    return next_state


def send_draft_comment(root: str | Path, proposal_id: str, hunk: str) -> dict[str, Any]:
    proposal = load(root, proposal_id)
    current_state = state(root, proposal)
    item = current_state.get("drafts", {}).get(hunk)
    _assert(item is not None and bool(item.get("body", "").strip()), "Write a comment before sending")
    published = {"id": str(uuid.uuid4()), "proposal": proposal_id, "hunk": hunk, "line": item["line"], "body": item["body"], "author": "reviewer", "at": _now()}
    current_state.setdefault("publishedComments", []).append(published)
    if "decision" in item:
        current_state["drafts"][hunk] = {**item, "body": "", "line": None}
    else:
        current_state.get("drafts", {}).pop(hunk, None)
    json_write(state_path(root, proposal_id), current_state)
    return published


def validate_anchor(proposal: dict[str, Any], anchor: dict[str, Any]) -> dict[str, Any]:
    _assert(anchor.get("side") in ("original", "proposed"), "Invalid comment side")
    text = proposal["before"] or "" if anchor["side"] == "original" else proposal["after"]
    source = text.split("\n")
    start_line, end_line = anchor.get("startLine"), anchor.get("endLine")
    _assert(
        isinstance(start_line, int)
        and not isinstance(start_line, bool)
        and isinstance(end_line, int)
        and not isinstance(end_line, bool)
        and 1 <= start_line <= end_line <= len(source),
        "Invalid comment range",
    )
    offset = 0
    hits: list[str] = []
    for hunk in proposal["hunks"]:
        count = len(split_lines(hunk["text"]))
        start = hunk["start"] if anchor["side"] == "original" else hunk["start"] + offset
        end = start + (hunk["end"] - hunk["start"] if anchor["side"] == "original" else count)
        if end > start and start_line - 1 < end and end_line - 1 >= start:
            hits.append(hunk["id"])
        offset += count - (hunk["end"] - hunk["start"])
    return {
        "side": anchor["side"],
        "startLine": start_line,
        "endLine": end_line,
        "line": start_line if anchor["side"] == "proposed" else None,
        "hunk": hits[0] if len(hits) == 1 else "general",
        "quotedCode": "\n".join(source[start_line - 1 : end_line]),
    }


def save_inline_draft(root: str | Path, proposal_id: str, anchor: dict[str, Any], body: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    proposal = load(root, proposal_id)
    current_state = state(root, proposal)
    _assert(isinstance(body, str) and bool(body.strip()) and len(body) <= 20_000, "Comment must contain 1–20000 characters")
    location = validate_anchor(proposal, anchor)
    current_state.setdefault("inlineDrafts", {})
    previous = None
    if options.get("draftId"):
        previous = current_state["inlineDrafts"].get(options["draftId"])
        _assert(previous is not None, "Draft no longer exists")
    thread_id = previous["threadId"] if previous else options.get("threadId", str(uuid.uuid4()))
    _assert(isinstance(thread_id, str) and bool(UUID_RE.fullmatch(thread_id)), "Invalid thread ID")
    existing = next(
        (item for item in [*current_state["inlineDrafts"].values(), *feedback(root, proposal_id)["comments"]] if item.get("threadId") == thread_id),
        None,
    )
    if options.get("threadId") or previous:
        _assert(existing is not None, "Thread no longer exists")
        _assert(
            existing["side"] == location["side"] and existing["startLine"] == location["startLine"] and existing["endLine"] == location["endLine"],
            "Thread anchor cannot change",
        )
    item = {
        **location,
        "id": previous["id"] if previous else str(uuid.uuid4()),
        "proposal": proposal_id,
        "threadId": thread_id,
        "body": body,
        "author": "reviewer",
        "at": previous["at"] if previous else _now(),
    }
    current_state["inlineDrafts"][item["id"]] = item
    json_write(state_path(root, proposal_id), current_state)
    return item


def discard_inline_draft(root: str | Path, proposal_id: str, draft_id: str) -> None:
    proposal = load(root, proposal_id)
    current_state = state(root, proposal)
    _assert(draft_id in current_state.get("inlineDrafts", {}), "Draft no longer exists")
    del current_state["inlineDrafts"][draft_id]
    json_write(state_path(root, proposal_id), current_state)


def reply_thread(root: str | Path, proposal_id: str, thread_id: str, body: str, author: str = "agent") -> dict[str, Any]:
    load(root, proposal_id)
    _assert(isinstance(body, str) and bool(body.strip()) and len(body) <= 20_000, "Comment must contain 1–20000 characters")
    parent = next((item for item in feedback(root, proposal_id)["comments"] if item.get("threadId") == thread_id), None)
    _assert(parent is not None, "Unknown published thread")
    item = {
        "id": str(uuid.uuid4()),
        "proposal": proposal_id,
        "threadId": thread_id,
        "hunk": parent["hunk"],
        "side": parent["side"],
        "startLine": parent["startLine"],
        "endLine": parent["endLine"],
        "line": parent["line"],
        "quotedCode": parent["quotedCode"],
        "body": body,
        "author": author,
        "at": _now(),
    }
    json_write(safe(root, f".pair-review/comments/{proposal_id}/{item['id']}.json", True), item)
    clear_activity(root, proposal_id, parent["hunk"], author, thread_id)
    return item
