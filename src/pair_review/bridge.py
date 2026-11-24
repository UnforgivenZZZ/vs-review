from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import core
from .views import language, render_html


class ReviewBridge:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("Workspace root does not exist")

    def _proposal(self, proposal_id: str) -> dict[str, Any]:
        return core.load(self.root, proposal_id)

    def _review_state(self, proposal_id: str) -> dict[str, Any]:
        proposal = self._proposal(proposal_id)
        current_state = core.state(self.root, proposal)
        return {
            "feedback": core.feedback(self.root, proposal_id),
            "drafts": current_state.get("drafts", {}),
            "inlineDrafts": current_state.get("inlineDrafts", {}),
        }

    def handle(self, method: str, params: dict[str, Any]) -> Any:
        proposal_id = params.get("id", "")
        if method == "load":
            proposal = self._proposal(proposal_id)
            current_state = core.state(self.root, proposal)
            current_feedback = core.feedback(self.root, proposal_id)
            return {
                "id": proposal_id,
                "path": proposal["path"],
                "language": language(proposal["path"]),
                "hunks": [
                    {"id": hunk["id"], "start": hunk["start"], "end": hunk["end"], "added": len(core.split_lines(hunk["text"]))}
                    for hunk in proposal["hunks"]
                ],
                "html": render_html(proposal, current_state, current_feedback),
            }
        if method == "snapshot":
            proposal = self._proposal(proposal_id)
            kind = params.get("kind")
            if kind not in ("original", "proposed", "resolved"):
                raise ValueError("Unknown preview kind")
            current_state = core.state(self.root, proposal)
            snapshots = {
                "original": proposal["before"] or "",
                "proposed": proposal["after"],
                "resolved": core.render(proposal, current_state["decisions"]) or "",
            }
            return {"text": snapshots[kind], "language": language(proposal["path"]), "path": proposal["path"]}
        if method == "reviewState":
            return self._review_state(proposal_id)
        if method == "draft":
            core.draft(self.root, proposal_id, params["hunk"], params["value"])
            return self._review_state(proposal_id)
        if method == "discard":
            core.discard_draft(self.root, proposal_id, params["hunk"])
            return self._review_state(proposal_id)
        if method == "sendComment":
            core.draft(self.root, proposal_id, params["hunk"], params["value"])
            core.send_draft_comment(self.root, proposal_id, params["hunk"])
            current_state = core.state(self.root, self._proposal(proposal_id))
            return {**self._review_state(proposal_id), "hunk": params["hunk"], "draft": current_state.get("drafts", {}).get(params["hunk"])}
        if method == "submitReview":
            core.submit_review(self.root, proposal_id, params.get("scope", "all"))
            return self._review_state(proposal_id)
        if method == "saveInlineDraft":
            item = core.save_inline_draft(self.root, proposal_id, params["anchor"], params["body"], params.get("options"))
            return {"item": item, **self._review_state(proposal_id)}
        if method == "discardInlineDraft":
            core.discard_inline_draft(self.root, proposal_id, params["draftId"])
            return self._review_state(proposal_id)
        raise ValueError("Unknown bridge method")


def serve(root: str | Path) -> None:
    bridge = ReviewBridge(root)
    for line in sys.stdin:
        request_id: Any = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            result = bridge.handle(request["method"], request.get("params") or {})
            response = {"id": request_id, "result": result}
        except Exception as error:
            response = {"id": request_id, "error": {"message": str(error)}}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local VS Code bridge for Pair Review")
    parser.add_argument("--workspace", required=True)
    arguments = parser.parse_args()
    try:
        serve(arguments.workspace)
    except BrokenPipeError:
        return


if __name__ == "__main__":
    main()
