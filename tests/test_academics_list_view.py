"""Tests for the callback-fed academics list."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from pathlib import Path

from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from backend.contracts import AcademicFormData, AcademicRecord, SubmissionResult
from frontend.controller import FakeFrontendController
from frontend.frontend_main import build_frontend_window
from persistence.settings_repository import load_application_settings

SETTINGS = load_application_settings()


def _unused_callback(_data: AcademicFormData) -> SubmissionResult:
    return SubmissionResult(success=False, message="No utilizado.")


def _record(
    academic_id: str = "academic-1",
    *,
    rut: str = "12345678-5",
) -> AcademicRecord:
    return AcademicRecord(
        academic_id=academic_id,
        rut=rut,
        name="Persona de prueba",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )


def test_empty_provider_is_supported(qtbot: QtBot) -> None:
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=_unused_callback,
        academics_provider=lambda: (),
    )
    qtbot.addWidget(window)
    window.show_academics_list()
    view = window.academics_list_view

    assert view.table.rowCount() == 0
    assert view.empty_label.isVisibleTo(view)
    assert view.count_label.text() == "Registros: 0"
    assert view.academics == ()


def test_provider_populates_six_persistent_fields(qtbot: QtBot) -> None:
    rows = (
        _record(),
        AcademicRecord(
            academic_id="academic-2",
            rut="40000000-K",
            name="Segunda persona de prueba",
            plant="Mixta",
            profile="Docente",
            weekly_hours=30,
            status="Sabático",
        ),
    )
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=_unused_callback,
        academics_provider=lambda: rows,
    )
    qtbot.addWidget(window)
    window.show_academics_list()
    view = window.academics_list_view

    assert view.table.rowCount() == 2
    assert [view.table.item(0, column).text() for column in range(6)] == [
        "Persona de prueba",
        "12345678-5",
        "Ordinaria",
        "Mixto",
        "40",
        "Activo",
    ]
    assert view.table.item(1, 0).text() == "Segunda persona de prueba"
    assert view.table.item(1, 1).text() == "40000000-K"
    assert view.count_label.text() == "Registros: 2"
    assert not view.empty_label.isVisibleTo(view)


def test_provider_is_reloaded_each_time_list_opens(qtbot: QtBot) -> None:
    records: list[AcademicRecord] = []
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        submit_callback=_unused_callback,
        academics_provider=lambda: list(records),
    )
    qtbot.addWidget(window)

    window.show_academics_list()
    assert window.academics_list_view.table.rowCount() == 0

    records.append(_record())
    window.show_main_menu()
    window.show_academics_list()

    assert window.academics_list_view.table.rowCount() == 1


def test_default_window_contains_no_visual_fixture(qtbot: QtBot) -> None:
    window = build_frontend_window(
        FakeFrontendController(), settings=SETTINGS, submit_callback=_unused_callback
    )
    qtbot.addWidget(window)

    assert window.academics_list_view.academics == ()
    assert window.academics_list_view.table.rowCount() == 0


def test_view_construction_never_opens_an_academic_csv(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    settings = SETTINGS
    original_open: Callable[..., object] = builtins.open

    def guarded_open(file: object, *args: object, **kwargs: object) -> object:
        if Path(file).name.lower() == "academic.csv":
            raise AssertionError("La vista no debe abrir archivos CSV.")
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    window = build_frontend_window(
        FakeFrontendController(),
        submit_callback=_unused_callback,
        academics_provider=lambda: (),
        settings=settings,
    )
    qtbot.addWidget(window)
    window.show_academics_list()

    assert window.academics_list_view.table.rowCount() == 0


def test_window_uses_injected_settings_without_any_file_read(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    def forbidden_read(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("El frontend no debe leer archivos al construirse.")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    window = build_frontend_window(
        FakeFrontendController(),
        settings=SETTINGS,
        academics_provider=lambda: (),
    )
    qtbot.addWidget(window)

    assert window.settings is SETTINGS
    assert window.settings.visual.colors["brand_blue"] == "#173F8A"
