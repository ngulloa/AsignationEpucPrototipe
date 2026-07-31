"""Reproducible offscreen candidates for human visual-reference review."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from backend.contracts import AcademicRecord
from frontend.controller import FakeFrontendController
from frontend.frontend_main import MainWindow, build_frontend_window
from persistence.settings_repository import load_application_settings

VISUAL_FIXTURE = (
    AcademicRecord(
        academic_id="visual-1",
        name="Ana Cifuentes Gatica Cornejo",
        rut="12345678-9",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    ),
    AcademicRecord(
        academic_id="visual-2",
        name="Nicolás Ignacio Ulloa Gatica",
        rut="10999678-9",
        plant="Mixta",
        profile="Docente",
        weekly_hours=40,
        status="Sabático",
    ),
    AcademicRecord(
        academic_id="visual-3",
        name="Nicolás Ignacio Ulloa Gatica",
        rut="10999678-9",
        plant="Mixta",
        profile="Docente",
        weekly_hours=40,
        status="Sabático",
    ),
)


def _capture(
    application: QApplication,
    window: MainWindow,
    output_directory: Path,
    captures: list[dict[str, object]],
    *,
    name: str,
    screen: str,
    state: str,
    prepare: Callable[[], None],
    resolution: tuple[int, int] | None = None,
) -> None:
    prepare()
    if resolution is None:
        dimensions = window.settings.visual.screens[screen]
        resolution = (dimensions.width, dimensions.height)
    window.resize(QSize(*resolution))
    application.processEvents()
    focus_widget = application.focusWidget()
    if focus_widget is not None:
        focus_widget.clearFocus()
    application.processEvents()
    destination = output_directory / f"{name}.png"
    if not window.grab().save(str(destination)):
        raise RuntimeError(f"No se pudo guardar la captura: {name}")
    captures.append(
        {
            "file": destination.name,
            "screen": screen,
            "state": state,
            "resolution": f"{resolution[0]}x{resolution[1]}",
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }
    )


def capture_views(output_directory: Path) -> None:
    application = QApplication.instance() or QApplication([])
    output_directory.mkdir(parents=True, exist_ok=True)
    controller = FakeFrontendController(academics=VISUAL_FIXTURE)
    window = build_frontend_window(
        controller=controller,
        settings=load_application_settings(),
    )
    window.show()
    application.processEvents()
    captures: list[dict[str, object]] = []

    def capture(
        name: str,
        screen: str,
        state: str,
        prepare: Callable[[], None],
        resolution: tuple[int, int] | None = None,
    ) -> None:
        _capture(
            application,
            window,
            output_directory,
            captures,
            name=name,
            screen=screen,
            state=state,
            prepare=prepare,
            resolution=resolution,
        )

    capture("login", "login", "vacío", window.show_login)
    capture("register", "register", "vacío", window.show_registration)

    window.login_view.username_input.setText("propietario")
    window.login_view.password_input.setText("1234")
    window.login_view.submit()
    capture("menu", "menu", "sesión propietaria", window.show_main_menu)
    capture(
        "academic_list_personal",
        "academic_list",
        "tabla personal con registros",
        window.show_academics_list,
    )
    capture(
        "academic_list_personal_820x640",
        "academic_list",
        "tabla personal responsiva",
        window.show_academics_list,
        (820, 640),
    )
    capture(
        "academic_list_personal_1280x900",
        "academic_list",
        "tabla personal ampliada",
        window.show_academics_list,
        (1280, 900),
    )

    def show_shared_tables() -> None:
        window.show_academics_list()
        window.academics_list_view.shared_tables_button.click()

    capture(
        "academic_list_shared",
        "academic_list",
        "selector de tablas compartidas",
        show_shared_tables,
    )

    def show_shared_records() -> None:
        show_shared_tables()
        window.academics_list_view.shared_tables_table.selectRow(0)

    capture(
        "academic_list_shared_records",
        "academic_list",
        "tabla compartida seleccionada",
        show_shared_records,
    )

    def show_shared_edit_form() -> None:
        show_shared_records()
        window.academics_list_view.shared_records_table.selectRow(0)
        window.academics_list_view.edit_selected_button.click()

    capture(
        "academic_form_shared_edit",
        "academic_form",
        "edición de registro compartido",
        show_shared_edit_form,
    )
    capture(
        "academic_form",
        "academic_form",
        "alta vacía",
        window.show_academic_form,
    )
    capture(
        "approval",
        "approval",
        "solicitudes pendientes",
        window.show_approvals,
    )

    def show_preselected_error() -> None:
        window.show_academic_form()
        window.show_error_notification("Rut inválido.")

    capture(
        "error_notification",
        "error_notification",
        "clasificación predeterminada sin texto libre",
        show_preselected_error,
    )
    capture(
        "update",
        "update",
        "resumen estable",
        window.show_update,
    )
    capture(
        "alerts",
        "alerts",
        "detalle estructurado disponible",
        window.show_alerts,
    )

    def show_rut_error() -> None:
        window.show_academic_form()
        form = window.academic_form_view
        form.name_input.setText("Académico de prueba")
        form.rut_input.setText("11111111-1")
        form.submit()

    capture(
        "academic_form_rut_registered",
        "academic_form",
        "error de RUT duplicado",
        show_rut_error,
    )

    def show_update_error() -> None:
        window.show_update()
        window.update_view.update_name_input.setText("error")
        window.update_view.submit()

    capture(
        "update_error",
        "update",
        "error controlado",
        show_update_error,
    )

    def show_shared_access_denied() -> None:
        window.logout()
        window.login_view.username_input.setText("usuario.demo")
        window.login_view.password_input.setText("1234")
        window.login_view.submit()
        show_shared_records()
        window.academics_list_view.shared_records_table.selectRow(0)
        window.academics_list_view._edit_selected()

    capture(
        "academic_list_shared_access_denied",
        "academic_list",
        "edición compartida denegada",
        show_shared_access_denied,
    )

    manifest = {
        "schema_version": 1,
        "review_status": "pending_human_review",
        "deterministic_environment": "Qt offscreen; datos FakeFrontendController",
        "comparison": {
            "penpot": (
                "Comparación visual realizada con 01_Wireframes.pdf y los tres "
                "PNG exportados en design.prototipe; se conserva jerarquía, color, "
                "tipografía, superficies y distribución de 1280x900."
            ),
            "existing_references": (
                "No se encontró un conjunto previo de referencias finales aprobadas."
            ),
            "decision": "Candidatas; no aprobadas hasta revisión humana.",
        },
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
