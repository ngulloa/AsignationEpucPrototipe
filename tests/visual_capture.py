"""Temporary offscreen captures for the five product views."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget

from backend.contracts import AcademicRecord
from frontend.controller import FakeFrontendController
from frontend.frontend_main import MainWindow, build_frontend_window
from persistence.settings_repository import load_application_settings

MINIMUM_SIZE = (720, 600)
LARGE_SIZE = (1280, 900)


def _records() -> tuple[AcademicRecord, ...]:
    return (
        AcademicRecord(
            "synthetic-visual-1",
            "12345678-5",
            "Ana Sintética",
            "Ordinaria",
            "Mixto",
            40,
            "Activo",
        ),
        AcademicRecord(
            "synthetic-visual-2",
            "40000000-K",
            "Segunda persona sintética",
            "Especial",
            "Docente",
            22,
            "Sabático",
        ),
        AcademicRecord(
            "synthetic-visual-3",
            "11000003-0",
            "Registro sintético de jornada negativa",
            "Especial",
            "Standard",
            -4,
            "Inactivo",
        ),
    )


def _capture(
    application: QApplication,
    window: MainWindow,
    output_directory: Path,
    captures: list[dict[str, object]],
    *,
    screen: str,
    state: str,
    size_kind: str,
    prepare: Callable[[], None],
    focus: Callable[[], QWidget],
    resolution: tuple[int, int],
) -> None:
    prepare()
    window.resize(QSize(*resolution))
    focus().setFocus()
    application.processEvents()
    name = f"{screen}_{size_kind}_{resolution[0]}x{resolution[1]}"
    destination = output_directory / f"{name}.png"
    if not window.grab().save(str(destination)):
        raise RuntimeError(f"No se pudo guardar la captura: {name}")
    captures.append(
        {
            "file": destination.name,
            "screen": screen,
            "state": state,
            "size_kind": size_kind,
            "resolution": f"{resolution[0]}x{resolution[1]}",
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }
    )


def capture_views(output_directory: Path) -> None:
    application = QApplication.instance() or QApplication([])
    output_directory.mkdir(parents=True, exist_ok=True)
    records = _records()
    settings = load_application_settings()
    window = build_frontend_window(
        controller=FakeFrontendController(academics=records),
        settings=settings,
    )
    window.show()
    application.processEvents()
    captures: list[dict[str, object]] = []

    def authenticate() -> None:
        window._handle_authenticated("visual.sintetica")

    def prepare_login() -> None:
        window.show_login()

    def prepare_register() -> None:
        window.show_registration()

    def prepare_menu() -> None:
        authenticate()
        window.show_main_menu()
        window.main_menu_view.set_sync_busy(False)

    def prepare_list() -> None:
        authenticate()
        window.show_academics_list()
        window.academics_list_view.table.selectRow(0)

    def prepare_form() -> None:
        authenticate()
        window.show_academic_edit(records[0])

    screens = (
        (
            "login",
            "inicio de sesión vacío",
            prepare_login,
            lambda: window.login_view.username_input,
        ),
        (
            "register",
            "registro de cuenta vacío",
            prepare_register,
            lambda: window.register_view.username_input,
        ),
        (
            "menu",
            "Inicio con cinco acciones",
            prepare_menu,
            lambda: window.main_menu_view.download_button,
        ),
        (
            "academic_list",
            "lista global con filas sintéticas y acciones visibles",
            prepare_list,
            lambda: window.academics_list_view.edit_selected_button,
        ),
        (
            "academic_form",
            "formulario de edición completamente prellenado",
            prepare_form,
            lambda: window.academic_form_view.save_button,
        ),
    )
    for screen, state, prepare, focus in screens:
        dimensions = settings.visual.screens[screen]
        sizes = (
            ("minimum", MINIMUM_SIZE),
            ("configured", (dimensions.width, dimensions.height)),
            ("large", LARGE_SIZE),
        )
        for size_kind, resolution in sizes:
            _capture(
                application,
                window,
                output_directory,
                captures,
                screen=screen,
                state=state,
                size_kind=size_kind,
                prepare=prepare,
                focus=focus,
                resolution=resolution,
            )

    manifest = {
        "schema_version": 1,
        "review_status": "pending_human_review",
        "deterministic_environment": "Qt offscreen; registros sintéticos",
        "captures": captures,
    }
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    window.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args()
    capture_views(arguments.output_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
