from __future__ import annotations

from pathlib import Path

import pytest

from pair_review import core


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    return tmp_path


def make_proposal(root: Path, after: str = "ONE\ntwo\nthree\nFOUR\n", target: str = "a.txt") -> dict:
    return core.submit(root, target, after)
