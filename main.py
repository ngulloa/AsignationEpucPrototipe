"""Executable composition root for the local persistent PySide6 application."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from backend.composition import build_application_service
from backend.frontend_controller import PersistentFrontendController
from frontend.frontend_main import MainWindow, build_frontend_window
from persistence.settings_repository import load_application_settings


def build_production_application_window(*, paths: object | None = None) -> MainWindow:
    """Compose the unchanged frontend with the productive local backend."""
    application = (
        build_application_service()
        if paths is None
        else build_application_service(paths=paths)  # type: ignore[arg-type]
    )
    controller = PersistentFrontendController(application)
    settings = load_application_settings()
    return build_frontend_window(controller=controller, settings=settings)


def build_application_window(*, paths: object | None = None) -> MainWindow:
    """Build the application with its persistent backend."""
    return build_production_application_window(paths=paths)


def main() -> int:
    application = QApplication.instance()
    if application is None:
        application = QApplication(sys.argv)
    window = build_application_window()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
