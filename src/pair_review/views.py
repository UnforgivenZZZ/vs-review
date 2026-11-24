from __future__ import annotations

import html
import json
import secrets
from importlib import resources
from pathlib import Path
from typing import Any

from pygments import lex
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token

from .core import split_lines


def escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True).replace("&#x27;", "&#39;")


def _lexer(path: str):
    try:
        return get_lexer_for_filename(Path(path).name, stripnl=False, ensurenl=False)
    except Exception:
        return TextLexer(stripnl=False, ensurenl=False)


def language(path: str) -> str:
    lexer = _lexer(path)
    return lexer.aliases[0] if lexer.aliases else "plaintext"


def _token_class(token_type: Any) -> str | None:
    if token_type in Comment:
        return "hljs-comment"
    if token_type in Keyword:
        return "hljs-keyword"
    if token_type in String:
        return "hljs-string"
    if token_type in Number:
        return "hljs-number"
    if token_type in Name.Function or token_type in Name.Builtin:
        return "hljs-title"
    if token_type in Name.Class or token_type in Name.Namespace:
        return "hljs-type"
    if token_type in Name.Variable or token_type in Name.Attribute or token_type in Name.Property:
        return "hljs-variable"
    if token_type in Name.Decorator or token_type in Operator.Word:
        return "hljs-keyword"
    if token_type in Token.Literal:
        return "hljs-literal"
    return None


def highlight_lines(text: str, path: str) -> list[str]:
    result = [""]
    active_class: str | None = None

    def append(value: str) -> None:
        if not value:
            return
        escaped = escape(value)
        result[-1] += f'<span class="{active_class}">{escaped}</span>' if active_class else escaped

    def newline() -> None:
        if active_class:
            result[-1] += "</span>"
        result.append(f'<span class="{active_class}">' if active_class else "")

    for token_type, value in lex(text, _lexer(path)):
        token_class = _token_class(token_type)
        if token_class != active_class:
            if active_class:
                result[-1] += "</span>"
            if token_class:
                result[-1] += f'<span class="{token_class}">'
            active_class = token_class
        parts = value.split("\n")
        for index, part in enumerate(parts):
            if index:
                newline()
            append(part.rstrip("\r") if index < len(parts) - 1 else part)
    if active_class:
        result[-1] += "</span>"
    return result


def _media(name: str) -> str:
    return resources.files("pair_review").joinpath("media", name).read_text(encoding="utf-8")


def render_html(
    proposal: dict[str, Any],
    state: dict[str, Any],
    feedback: dict[str, Any],
    activity: list[dict[str, Any]] | None = None,
) -> str:
    nonce = secrets.token_urlsafe(18)
    before = highlight_lines(proposal["before"] or "", proposal["path"])
    after = highlight_lines(proposal["after"], proposal["path"])

    def form(hunk: str) -> str:
        return (
            f'<div class="draft"><label for="body-{hunk}">Review comment (draft)</label>'
            f'<input id="line-{hunk}" data-hunk="{hunk}" data-field="line" type="number" min="1" placeholder="Proposed line (optional)">'
            f'<textarea id="body-{hunk}" data-hunk="{hunk}" data-field="body" maxlength="20000" placeholder="Write a comment. Send comment sends only this message; Submit also publishes the selected decision."></textarea>'
            f'<button class="primary" data-action="send" data-hunk="{hunk}">Send comment</button></div>'
        )

    offset = 0
    changes: list[str] = []
    total_changes = len(proposal["hunks"])
    for index, hunk in enumerate(proposal["hunks"], start=1):
        added = len(split_lines(hunk["text"]))
        start = hunk["start"] + offset
        offset += added - (hunk["end"] - hunk["start"])

        def rows(first: int, count: int, source: list[str], kind: str) -> str:
            sign = "+" if kind == "add" else "−"
            return "".join(
                f'<div class="line {kind}"><span class="gutter">{first + index + 1}</span><code>{sign} {source[first + index]}</code></div>'
                for index in range(count)
            )

        removed = rows(hunk["start"], hunk["end"] - hunk["start"], before, "remove")
        inserted = rows(start, added, after, "add")
        empty = "" if inserted or hunk["old"] else "<i>Create empty file</i>"
        hunk_id = hunk["id"]
        change_label = f"Change {index} of {total_changes}" if total_changes > 1 else "File change"
        changes.append(
            f'<section class="change-card" id="section-{hunk_id}"><header class="change-header"><b>{change_label} · original L{hunk["start"] + 1}</b><span id="status-{hunk_id}"></span></header>'
            f'<details open><summary>Show changed lines · {escape(language(proposal["path"]))}</summary><div class="diff">{removed}{inserted}{empty}</div></details>'
            f'<div class="actions"><button data-action="source" data-hunk="{hunk_id}">View in full file</button>'
            f'<button data-action="accept" data-hunk="{hunk_id}">Accept</button><button data-action="reject" data-hunk="{hunk_id}">Reject</button>'
            f'<button data-action="undo" data-hunk="{hunk_id}">Undo decision</button><button data-action="discard" data-hunk="{hunk_id}">Discard draft</button>'
            f'<button class="primary" data-action="submit" data-hunk="{hunk_id}">Submit this change</button></div>'
            f'<div class="activity" id="activity-{hunk_id}"></div><div class="comments" id="comments-{hunk_id}"></div>'
            f'<div class="inline-drafts" id="inline-drafts-{hunk_id}"></div>{form(hunk_id)}</section>'
        )

    changes.append(
        '<section class="change-card" id="section-general"><header class="change-header"><b>Proposal discussion</b></header>'
        '<div class="activity" id="activity-general"></div><div class="comments" id="comments-general"></div>'
        '<div class="inline-drafts" id="inline-drafts-general"></div>'
        + form("general")
        + '<div class="actions"><button data-action="discard" data-hunk="general">Discard draft</button>'
        '<button class="primary" data-action="submit" data-hunk="general">Submit discussion</button></div></section>'
    )
    initial = json.dumps(
        {
            "feedback": feedback,
            "drafts": state.get("drafts", {}),
            "inlineDrafts": state.get("inlineDrafts", {}),
            "activity": activity or [],
        },
        ensure_ascii=False,
    ).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    css = _media("review.css")
    client = _media("review.js")
    file_actions = (
        '<div class="file-actions"><button data-action="diff">Compare full files</button>'
        '<button data-action="source">Full proposed file</button><button data-action="resolved">Submitted result</button></div>'
    )
    return (
        "<!doctype html><html><head><meta charset=\"UTF-8\">"
        f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'nonce-{nonce}\'; script-src \'nonce-{nonce}\';">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><style nonce="{nonce}">{css}</style></head><body>'
        '<div class="eyebrow">PAIR REVIEW · DRAFT → SUBMIT → DISCUSS</div>'
        f'<h1>{escape(proposal["title"])}</h1><p class="proposal-meta">Agent: {escape(proposal["agent"])} · immutable candidate snapshot</p>'
        '<p class="hint">Accept and Reject stay as drafts until Submit. Comments can stay in the review or be sent individually with Send comment. In Compare full files, use the line gutter + to comment directly.</p>'
        '<div class="toolbar"><button class="primary" data-action="submit" data-hunk="all">Submit all reviews</button><span id="draft-count"></span></div>'
        '<p id="notice" role="status" aria-live="polite"></p>'
        f'<main class="file-group" data-file="{escape(proposal["path"])}"><header class="file-header"><div><div class="file-kicker">FILE CHANGE</div>'
        f'<b class="file-path">{escape(proposal["path"])}</b><span class="file-count">{total_changes} change{"s" if total_changes != 1 else ""}</span></div>{file_actions}</header>'
        '<div class="file-body">' + "".join(changes) + '</div></main>'
        f'<script nonce="{nonce}">const initial={initial};{client}</script></body></html>'
    )
