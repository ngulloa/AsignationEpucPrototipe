"""Integration checks for the persistent application composition."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

import main as application_main
from backend.frontend_controller import PersistentFrontendController
from frontend.frontend_main import LOGIN_SCREEN
from persistence.paths import ProjectPaths

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    existing_path = environment.get("PYTHONPATH")
    project_path = str(PROJECT_ROOT)
    environment["PYTHONPATH"] = (
        project_path
        if not existing_path
        else os.pathsep.join((project_path, existing_path))
    )
    return environment


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_importing_main_has_no_application_window_file_or_output(
    tmp_path: Path,
) -> None:
    script = """
from PySide6.QtWidgets import QApplication

assert QApplication.instance() is None
import main
assert QApplication.instance() is None
assert QApplication.topLevelWidgets() == []
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
    assert completed.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_composition_uses_persistent_controller_and_starts_at_login(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    window = application_main.build_application_window(paths=ProjectPaths(tmp_path))
    qtbot.addWidget(window)

    assert isinstance(window.controller, PersistentFrontendController)
    assert window.current_screen == LOGIN_SCREEN
    assert window.authenticated_username == ""
    assert list(tmp_path.iterdir()) == []


def test_main_reuses_application_runs_event_loop_once_and_returns_exit_code(
    qtbot: QtBot,
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application_before = QApplication.instance()
    built_windows: list[object] = []
    exec_calls: list[QApplication] = []
    real_builder = application_main.build_application_window

    def tracked_builder():
        window = real_builder()
        built_windows.append(window)
        return window

    def controlled_exec(application: QApplication) -> int:
        exec_calls.append(application)
        return 37

    monkeypatch.setattr(application_main, "build_application_window", tracked_builder)
    monkeypatch.setattr(QApplication, "exec", controlled_exec)

    assert application_main.main() == 37
    assert QApplication.instance() is application_before is qapp
    assert exec_calls == [qapp]
    assert len(built_windows) == 1
    assert built_windows[0].isVisible()
    qtbot.addWidget(built_windows[0])


def test_productive_window_construction_does_not_create_files(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    window = application_main.build_application_window(paths=ProjectPaths(tmp_path))
    qtbot.addWidget(window)
    assert list(tmp_path.iterdir()) == []


def test_frontend_and_main_do_not_import_persistence_or_git_implementations() -> None:
    production_paths = sorted((PROJECT_ROOT / "frontend").rglob("*.py"))
    forbidden = {
        "persistence",
        "backend.git_sync",
        "backend.authentication",
        "backend.approval",
    }
    for path in production_paths:
        imports = _imported_modules(path)
        assert not any(
            module in forbidden or module.startswith("persistence.")
            for module in imports
        ), path

    main_imports = _imported_modules(PROJECT_ROOT / "main.py")
    assert "persistence.settings_repository" in main_imports
    assert "backend.git_sync" not in main_imports

    for path in (PROJECT_ROOT / "frontend" / "views").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "open(" not in source
        assert "subprocess" not in source
        assert "git " not in source.lower()


def test_frontend_contains_no_filesystem_or_json_access() -> None:
    forbidden_imports = {"json", "pathlib", "os", "subprocess"}
    forbidden_fragments = ("open(", ".read_text(", ".write_text(")
    for path in sorted((PROJECT_ROOT / "frontend").rglob("*.py")):
        imports = _imported_modules(path)
        assert imports.isdisjoint(forbidden_imports), path
        source = path.read_text(encoding="utf-8")
        assert not any(fragment in source for fragment in forbidden_fragments), path


def test_productive_frontend_has_no_absolute_workspace_path() -> None:
    for path in (
        PROJECT_ROOT / "main.py",
        *sorted((PROJECT_ROOT / "frontend").rglob("*.py")),
    ):
        assert "/home/" not in path.read_text(encoding="utf-8")
