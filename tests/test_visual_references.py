"""Deterministic offscreen capture checks without stored generated images."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImageReader
from pytestqt.qtbot import QtBot

from backend.academic_service import DUPLICATE_RUT_MESSAGE
from backend.contracts import AcademicErrorCode, AcademicRecord, SubmissionResult
from frontend.controller import FakeFrontendController
from frontend.frontend_main import build_frontend_window
from persistence.settings_repository import load_application_settings

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
    assert len(captures) == 15
    assert {item["size_kind"] for item in captures} == {
        "minimum",
        "configured",
        "large",
    }
    assert {item["screen"] for item in captures} == {
        "login",
        "register",
        "menu",
        "academic_list",
        "academic_form",
    }

    for item in captures:
        path = tmp_path / str(item["file"])
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        width, height = (int(value) for value in str(item["resolution"]).split("x"))
        assert QImageReader(str(path)).size().toTuple() == (width, height)


def test_academic_list_and_form_geometry_at_required_sizes(
    qtbot: QtBot,
    qapp: object,
) -> None:
    record = AcademicRecord(
        "synthetic-visual",
        "12345678-5",
        "Ana Sintética",
        "Ordinaria",
        "Mixto",
        40,
        "Activo",
    )
    window = build_frontend_window(
        FakeFrontendController(academics=(record,)),
        settings=load_application_settings(),
    )
    qtbot.addWidget(window)
    window.show()
    window._handle_authenticated("visual.sintetica")

    def rectangle(widget: object) -> QRect:
        return QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())

    def assert_inside(widget: object) -> None:
        geometry = rectangle(widget)
        assert geometry.left() >= 0 and geometry.top() >= 0
        assert geometry.right() < window.width()
        assert geometry.bottom() < window.height()

    for width, height in ((720, 600), (1080, 768), (1280, 900)):
        window.resize(width, height)
        window.show_academics_list()
        qapp.processEvents()
        view = window.academics_list_view
        header = view.table.horizontalHeader()
        actions_column = view.table.columnCount() - 1
        assert view.table.columnCount() == 7
        assert header.sectionViewportPosition(actions_column) >= 0
        assert (
            header.sectionViewportPosition(actions_column)
            + header.sectionSize(actions_column)
            <= view.table.viewport().width()
        )
        actions = view.table.cellWidget(0, actions_column)
        assert actions is not None and actions.isVisibleTo(view)
        edit_button, delete_button = view.action_buttons[:2]
        assert rectangle(edit_button).right() < rectangle(delete_button).left()
        delete_button.setText("Confirmar")
        assert delete_button.sizeHint().width() <= delete_button.width()
        delete_button.setText("Borrar")
        assert_inside(view.table)
        assert_inside(edit_button)
        assert_inside(delete_button)

        window.show_academic_edit(record)
        qapp.processEvents()
        form = window.academic_form_view
        assert form.name_input.text() == record.name
        assert form.rut_input.text() == record.rut
        assert form.plant_combo.currentData() == record.plant
        assert form.profile_combo.currentData() == record.profile
        assert form.weekly_hours_input.value() == record.weekly_hours
        assert form.status_combo.currentData() == record.status
        for field_name, label in form.field_labels.items():
            assert label.text() == form.settings.texts.field_labels[field_name]
            assert_inside(label)
        for control in (
            form.name_input,
            form.rut_input,
            form.plant_combo,
            form.profile_combo,
            form.weekly_hours_input,
            form.status_combo,
            form.cancel_button,
            form.save_button,
        ):
            assert_inside(control)
        assert (
            rectangle(form.cancel_button).right() < rectangle(form.save_button).left()
        )
        assert form.name_input.fontMetrics().horizontalAdvance(record.name) < (
            form.name_input.width() - 12
        )
        assert form.plant_combo.fontMetrics().horizontalAdvance(
            form.plant_combo.currentText()
        ) < (form.plant_combo.width() - 28)

        form._present_result(
            SubmissionResult(
                False,
                DUPLICATE_RUT_MESSAGE,
                {"rut": DUPLICATE_RUT_MESSAGE},
                error_code=AcademicErrorCode.DUPLICATE_RUT,
            )
        )
        qapp.processEvents()
        assert form.result_label.text() == DUPLICATE_RUT_MESSAGE
        assert form.result_label.isVisibleTo(form)
        assert form.field_error_labels["rut"].isVisibleTo(form)
        assert_inside(form.result_label)
        assert_inside(form.field_error_labels["rut"])
