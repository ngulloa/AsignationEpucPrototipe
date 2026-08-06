"""Offscreen interface tests for the read-only assignments route."""

from __future__ import annotations

import inspect
import json
import os
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except ModuleNotFoundError as error:
    raise unittest.SkipTest("PySide6 no está instalado en este intérprete.") from error

from backend.contracts import (
    AcademicAssignmentsSummary,
    AssignmentListingError,
    AssignmentSummary,
    SubmissionResult,
)
from frontend.contracts import AuthenticationResult, RegistrationResult, UiResult
from frontend.frontend_main import MainWindow
from frontend.navigation import ASSIGNMENTS_SCREEN, MENU_SCREEN, FrontendRoute
from frontend.settings import build_settings
from frontend.style_manager import StyleManager
from frontend.views.assignments_list_view import AssignmentsListView
from persistence.paths import DEFAULT_PATHS
from persistence.settings_repository import load_application_settings


class _Catalogs:
    plants = ()
    profiles = ()
    statuses = ()

    @staticmethod
    def profiles_for_plant(_plant_key):
        return ()


class _FakeController:
    def __init__(self, assignment_responses=()) -> None:
        self.assignment_responses = list(assignment_responses)
        self.assignment_calls = 0
        self.logout_calls = 0

    def academic_catalogs(self):
        return _Catalogs()

    @staticmethod
    def authenticate(_request):
        return AuthenticationResult(True, "ok", username="ada")

    @staticmethod
    def register_user(_request):
        return RegistrationResult(True, "ok", username="ada")

    def list_academics(self):
        return ()

    def list_assignments_by_academic(self):
        self.assignment_calls += 1
        if not self.assignment_responses:
            return ()
        response = self.assignment_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def logout(self):
        self.logout_calls += 1

    @staticmethod
    def submit_academic(_data, _overwrite_confirmation=None):
        return SubmissionResult(True, "ok")

    @staticmethod
    def update_academic(_academic_id, _data):
        return SubmissionResult(True, "ok")

    @staticmethod
    def delete_academic(_academic_id):
        return SubmissionResult(True, "ok")

    @staticmethod
    def download_information():
        return UiResult(True, "ok")

    @staticmethod
    def upload_information():
        return UiResult(True, "ok")

    @staticmethod
    def list_active_academics():
        return ()

    @staticmethod
    def list_periods():
        return ()

    @staticmethod
    def list_courses():
        return ()

    @staticmethod
    def list_offerings(_period_id, _course_id):
        return ()


def _assignment(
    assignment_id: str = "assignment-1",
    *,
    course_code: str = "PSI101",
    course_name: str = "Psicología General",
    points: str = "4.50",
) -> AssignmentSummary:
    return AssignmentSummary(
        assignment_id=assignment_id,
        period_id="period-2026",
        period_label="2026 · Primer semestre",
        type_code="COURSE",
        type_name="Curso",
        classification_code="DOM",
        classification_name="Docencia ordinaria",
        status_code="PENDING",
        status_name="Pendiente",
        course_code=course_code,
        course_name=course_name,
        section_code="01",
        nrc="10001",
        calculated_points=Decimal(points),
        latest_authorized_points=None,
        displayed_points=Decimal(points),
        contributes_to_total=True,
    )


def _summary(
    assignments=(),
    *,
    name: str = "Ada Lovelace",
    total: str = "0",
) -> AcademicAssignmentsSummary:
    return AcademicAssignmentsSummary(
        academic_id="academic-1",
        name=name,
        rut="12.345.678-5",
        assignments=tuple(assignments),
        total_points=Decimal(total),
    )


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        cls.settings = load_application_settings()


class MainMenuAssignmentsTestCase(QtTestCase):
    def setUp(self) -> None:
        self.window = MainWindow(_FakeController(), self.settings)
        self.menu = self.window.main_menu_view

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()

    def test_assignments_button_is_enabled_outside_synchronization(self) -> None:
        self.assertTrue(self.menu.assignments_button.isEnabled())

    def test_assignments_button_emits_its_own_signal(self) -> None:
        emissions = []
        self.menu.assignments_requested.connect(lambda: emissions.append(True))
        self.menu.assignments_button.click()
        self.assertEqual(emissions, [True])

    def test_assignments_button_is_disabled_during_synchronization(self) -> None:
        self.menu.set_sync_busy(True, "download")
        self.assertFalse(self.menu.assignments_button.isEnabled())

    def test_assignments_button_is_reenabled_after_synchronization(self) -> None:
        self.menu.set_sync_busy(True, "upload")
        self.menu.set_sync_busy(False)
        self.assertTrue(self.menu.assignments_button.isEnabled())


class AssignmentsViewTestCase(QtTestCase):
    def setUp(self) -> None:
        self.view = AssignmentsListView(
            self.settings,
            StyleManager(self.settings.visual),
        )

    def tearDown(self) -> None:
        self.view.close()
        self.view.deleteLater()

    def test_renders_academic_without_assignments(self) -> None:
        self.view.set_assignments((_summary(),))
        self.assertEqual(self.view.table.item(0, 2).text(), "Sin asignaciones")
        self.assertEqual(self.view.table.item(0, 3).text(), "0.00")

    def test_renders_multiple_assignments_on_separate_lines(self) -> None:
        assignments = (_assignment(), _assignment("assignment-2", points="2.00"))
        self.view.set_assignments((_summary(assignments, total="6.50"),))
        rendered = self.view.table.item(0, 2).text()
        self.assertEqual(len(rendered.splitlines()), 2)
        self.assertIn("PSI101 Psicología General", rendered)
        self.assertIn("2026 · Primer semestre", rendered)

    def test_uses_total_delivered_by_dto(self) -> None:
        self.view.set_assignments(
            (_summary((_assignment(points="1.00"),), total="9.25"),)
        )
        self.assertEqual(self.view.table.item(0, 3).text(), "9.25")

    def test_warning_indicator_is_grey_and_inactive(self) -> None:
        self.view.set_assignments((_summary(),))
        indicator = self.view.warning_indicators[0]
        self.assertEqual(indicator.property("warningState"), "inactive")
        self.assertIn(
            self.settings.visual.colors["neutral_gray_500"],
            StyleManager(self.settings.visual).stylesheet(),
        )
        self.assertTrue(indicator.accessibleName())

    def test_warning_indicator_has_no_action(self) -> None:
        self.view.set_assignments((_summary(),))
        indicator = self.view.warning_indicators[0]
        self.assertIsInstance(indicator, QLabel)
        self.assertFalse(indicator.findChildren(QPushButton))
        self.assertTrue(
            indicator.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        )

    def test_long_text_does_not_raise(self) -> None:
        long_text = "Curso con nombre extenso " * 100
        summary = _summary((_assignment(course_name=long_text),), name=long_text)
        self.view.set_assignments((summary,))
        self.assertEqual(self.view.table.rowCount(), 1)

    def test_empty_result_leaves_controlled_empty_table(self) -> None:
        self.view.set_assignments(())
        self.assertEqual(self.view.table.rowCount(), 0)
        self.assertTrue(
            self.view.empty_label.isVisibleTo(self.view)
            or self.view.empty_label.isVisible()
        )

    def test_view_has_no_direct_file_access(self) -> None:
        source = inspect.getsource(inspect.getmodule(AssignmentsListView))
        self.assertNotIn("import csv", source)
        self.assertNotIn("import json", source)
        self.assertNotIn("Path(", source)
        self.assertNotIn("open(", source)

    def test_visual_configuration_contains_assignments_dimensions(self) -> None:
        dimensions = self.settings.visual.screens[ASSIGNMENTS_SCREEN]
        self.assertGreaterEqual(dimensions.width, 720)
        self.assertGreaterEqual(dimensions.height, 600)
        self.assertEqual(len(self.settings.texts.assignment_table_headers), 5)

    def test_previous_schema_v1_configuration_remains_loadable(self) -> None:
        visual = json.loads(
            DEFAULT_PATHS.frontend_visual_settings_path.read_text(encoding="utf-8")
        )
        texts = json.loads(
            DEFAULT_PATHS.frontend_text_settings_path.read_text(encoding="utf-8")
        )
        visual["screens"].pop("assignments")
        texts["screen_titles"].pop("assignments")
        texts.pop("assignment_table_headers")
        for key in (
            "no_assignment_academics",
            "no_assignments",
            "assignment_academic_count_format",
            "warning_inactive_tooltip",
            "warning_inactive_accessible_name",
            "assignment_listing_error",
        ):
            texts["messages"].pop(key)

        settings = build_settings(visual, texts)
        view = AssignmentsListView(settings, StyleManager(settings.visual))
        self.addCleanup(view.deleteLater)

        self.assertEqual(settings.visual.screens[ASSIGNMENTS_SCREEN].width, 1200)
        self.assertEqual(len(settings.texts.assignment_table_headers), 5)


class AssignmentsNavigationTestCase(QtTestCase):
    def _window(self, responses=()):
        controller = _FakeController(responses)
        return MainWindow(controller, self.settings), controller

    def test_new_route_exists(self) -> None:
        self.assertEqual(FrontendRoute.ASSIGNMENTS.value, ASSIGNMENTS_SCREEN)

    def test_main_window_registers_assignments_view(self) -> None:
        window, _controller = self._window()
        self.addCleanup(window.close)
        self.assertIs(window._views[ASSIGNMENTS_SCREEN], window.assignments_list_view)

    def test_navigates_from_menu_to_assignments(self) -> None:
        window, _controller = self._window()
        self.addCleanup(window.close)
        window.show_main_menu()
        window.main_menu_view.assignments_button.click()
        self.assertEqual(window.current_screen, ASSIGNMENTS_SCREEN)

    def test_returns_from_assignments_to_menu(self) -> None:
        window, _controller = self._window()
        self.addCleanup(window.close)
        window.show_assignments()
        window.assignments_list_view.back_button.click()
        self.assertEqual(window.current_screen, MENU_SCREEN)

    def test_logout_from_assignments_clears_session(self) -> None:
        window, controller = self._window()
        self.addCleanup(window.close)
        window._handle_authenticated("ada")
        window.show_assignments()
        window.assignments_list_view.header.logout_button.click()
        self.assertEqual(controller.logout_calls, 1)
        self.assertEqual(window.authenticated_username, "")
        self.assertEqual(window.current_screen, "login")

    def test_reloads_assignments_each_time_route_is_entered(self) -> None:
        first = (_summary(),)
        second = (_summary((_assignment(),), total="4.50"),)
        window, controller = self._window((first, second))
        self.addCleanup(window.close)
        window.show_assignments()
        window.show_main_menu()
        window.show_assignments()
        self.assertEqual(controller.assignment_calls, 2)
        self.assertIn("PSI101", window.assignments_list_view.table.item(0, 2).text())

    def test_listing_error_is_non_fatal_and_clears_table(self) -> None:
        error = AssignmentListingError("ruta interna sensible")
        window, _controller = self._window(((_summary(),), error))
        self.addCleanup(window.close)
        window.show_assignments()
        window.show_assignments()
        view = window.assignments_list_view
        self.assertEqual(window.current_screen, ASSIGNMENTS_SCREEN)
        self.assertEqual(view.table.rowCount(), 0)
        self.assertFalse(view.result_banner.isHidden())
        self.assertNotIn("ruta interna", view.result_banner.text())


if __name__ == "__main__":
    unittest.main()
