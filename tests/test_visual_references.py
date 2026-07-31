"""Integrity and reproducibility checks for pending visual candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtGui import QImageReader

from tests.visual_capture import capture_views

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIRECTORY = PROJECT_ROOT / "docs" / "visual-reference-candidates"


def _manifest(directory: Path) -> dict[str, object]:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def test_visual_candidates_are_pending_and_match_manifest() -> None:
    manifest = _manifest(REFERENCE_DIRECTORY)
    assert manifest["review_status"] == "pending_human_review"
    captures = manifest["captures"]
    assert isinstance(captures, list)
    assert len(captures) == 17
    assert {item["resolution"] for item in captures} >= {
        "820x640",
        "1280x900",
    }

    for item in captures:
        path = REFERENCE_DIRECTORY / str(item["file"])
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        width, height = (int(value) for value in str(item["resolution"]).split("x"))
        assert QImageReader(str(path)).size().toTuple() == (width, height)


def test_visual_capture_is_reproducible_offscreen(tmp_path: Path) -> None:
    capture_views(tmp_path)

    expected = _manifest(REFERENCE_DIRECTORY)
    regenerated = _manifest(tmp_path)
    assert regenerated == expected
