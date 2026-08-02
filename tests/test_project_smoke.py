"""Smoke tests for import safety and the executable application entry point."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMPORTABLE_MODULES = (
    "main",
    "frontend.frontend_main",
    "frontend.navigation",
    "frontend.settings",
    "frontend.views.login_view",
    "frontend.views.register_view",
    "frontend.views.main_menu_view",
    "frontend.views.academics_list_view",
    "frontend.views.academic_form_view",
    "backend.contracts",
    "backend.authentication",
    "backend.git_sync",
    "persistence.paths",
    "persistence.user_repository",
    "persistence.csv_academic_repository",
)


def _project_environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    project_path = str(PROJECT_ROOT)
    environment["PYTHONPATH"] = (
        project_path
        if not existing_path
        else os.pathsep.join((project_path, existing_path))
    )
    return environment


@pytest.mark.parametrize("module_name", IMPORTABLE_MODULES)
def test_module_import_has_no_side_effects(
    module_name: str,
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=tmp_path,
        env=_project_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_main_entry_point_shows_window_and_exits_cleanly_offscreen(
    tmp_path: Path,
) -> None:
    script = f"""
import runpy

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

application = QApplication([])


def verify_window_and_exit():
    visible_windows = [
        window
        for window in QApplication.topLevelWidgets()
        if window.isVisible()
    ]
    application.exit(0 if len(visible_windows) == 1 else 91)


QTimer.singleShot(0, verify_window_and_exit)
runpy.run_path({str(PROJECT_ROOT / "main.py")!r}, run_name="__main__")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=_project_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
