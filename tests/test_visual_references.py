"""Deterministic offscreen capture checks without stored generated images."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtGui import QImageReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _manifest(directory: Path) -> dict[str, object]:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def test_visual_capture_has_complete_self_consistent_manifest(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, "-m", "tests.visual_capture", str(tmp_path)],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
    manifest = _manifest(tmp_path)
    assert manifest["review_status"] == "pending_human_review"
    captures = manifest["captures"]
    assert isinstance(captures, list)
    assert len(captures) == 17
    assert {item["resolution"] for item in captures} >= {
        "820x640",
        "1280x900",
    }

    for item in captures:
        path = tmp_path / str(item["file"])
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        width, height = (int(value) for value in str(item["resolution"]).split("x"))
        assert QImageReader(str(path)).size().toTuple() == (width, height)
