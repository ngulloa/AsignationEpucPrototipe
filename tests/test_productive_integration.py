"""End-to-end checks for the productive application composition."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from backend.composition import build_application_service
from backend.contracts import AcademicErrorCode, AcademicFormData
from frontend.frontend_main import LOGIN_SCREEN, MENU_SCREEN
from main import build_production_application_window
from persistence.paths import ProjectPaths


def test_direct_application_service_rejects_invalid_academic_catalog_values(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    application = build_application_service(paths=paths)
    application.register_user("persona.sintetica", "1234")
    invalid = AcademicFormData(
        name="Persona sintética",
        rut="12.345.678-5",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=20,
        status="Estado inventado",
    )

    result = application.save_academic(invalid)

    assert result.error_code is AcademicErrorCode.INVALID_STATUS
    assert application.list_academics() == []
    assert [option.key for option in application.academic_catalogs().statuses] == [
        "Activo",
        "Inactivo",
        "Sabático",
        "Terminado",
    ]


def test_real_window_authenticates_and_logout_clears_backend_session(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    setup = build_application_service(paths=paths)
    setup.register_user("persona.sintetica", "1234")
    setup.logout()

    window = build_production_application_window(paths=paths)
    qtbot.addWidget(window)
    window.show()
    window.login_view.username_input.setText("persona.sintetica")
    window.login_view.password_input.setText("1234")
    qtbot.mouseClick(window.login_view.login_button, Qt.MouseButton.LeftButton)

    assert window.current_screen == MENU_SCREEN
    assert window.authenticated_username == "persona.sintetica"
    qtbot.mouseClick(
        window.main_menu_view.header.logout_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.current_screen == LOGIN_SCREEN
    assert window.authenticated_username == ""
