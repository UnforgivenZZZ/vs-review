from __future__ import annotations

from pair_review import core
from pair_review.views import highlight_lines, render_html


def test_multiline_syntax_tokens_survive_diff_slicing():
    javascript = highlight_lines('/* start\n comment */\nconst userName = "hello"; // comment\n', "a.js")
    assert "hljs-comment" in javascript[1]
    assert "hljs-keyword" in javascript[2]
    assert "hljs-string" in javascript[2]
    assert "userName" in javascript[2]
    assert "hljs-comment" in javascript[2]
    python = highlight_lines('def greet(user):\n    # note\n    return "Hi"\n', "a.py")
    assert "hljs-keyword" in python[0]
    assert "hljs-comment" in python[1]
    assert "hljs-string" in python[2]
    assert "<script>" not in "".join(highlight_lines("<script>alert(1)</script>", "a.txt"))


def test_review_html_escapes_metadata_and_contains_full_controls():
    proposal = {
        "id": "demo",
        "title": "Review <script>alert(1)</script>",
        "path": "example.ts",
        "agent": "qwen",
        "before": "const value = 1;\n",
        "after": "const value = 2;\n",
    }
    proposal["hunks"] = core.diff(proposal["before"], proposal["after"])
    feedback = {"id": "demo", "hunks": [{"id": "h1", "status": "pending"}], "comments": [], "revision": "1"}
    page = render_html(proposal, {"decisions": {}}, feedback)
    assert "Review &lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "Review <script>alert(1)</script>" not in page
    for label in ("Submit all reviews", "Full proposed file", "Compare full files", "Submitted result", "Send comment"):
        assert label in page
    assert "hljs-keyword" in page
