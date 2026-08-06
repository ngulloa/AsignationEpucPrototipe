from __future__ import annotations

import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from backend.application_service import ApplicationService, AuthenticationRequiredError
from backend.assignment_service import AssignmentService
from backend.contracts import AssignmentListingError
from backend.session import InMemorySession
from persistence.data_model import CATALOG_FIELDS, TABLE_FIELDS
from persistence.paths import ProjectPaths


class AssignmentListingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.paths = ProjectPaths(self.root)
        self.paths.public_tables_dir.mkdir(parents=True)
        self.paths.academic_catalogs_dir.mkdir(parents=True)
        self.tables = self._base_tables()
        self.catalogs = self._base_catalogs()
        self._write_dataset()
        self.service = AssignmentService(self.paths)

    @staticmethod
    def _row(fields: tuple[str, ...], **values: object) -> dict[str, object]:
        return {field: values.get(field, "") for field in fields}

    def _base_tables(self) -> dict[str, list[dict[str, object]]]:
        academic = TABLE_FIELDS["Academic.csv"]
        employment = TABLE_FIELDS["academic_employment_history.csv"]
        period = TABLE_FIELDS["academic_periods.csv"]
        course = TABLE_FIELDS["Course.csv"]
        offering = TABLE_FIELDS["course_offerings.csv"]
        assignment = TABLE_FIELDS["academic_assignments.csv"]
        detail = TABLE_FIELDS["course_assignments.csv"]
        return {
            "Academic.csv": [
                self._row(
                    academic,
                    academic_id="academic-z",
                    rut="11.111.111-1",
                    name="Zoé",
                    created_at="2024-01-01T00:00:00+00:00",
                    updated_at="2024-01-01T00:00:00+00:00",
                    row_version="1",
                ),
                self._row(
                    academic,
                    academic_id="academic-b",
                    rut="22.222.222-2",
                    name="Ána",
                    created_at="2024-01-01T00:00:00+00:00",
                    updated_at="2024-01-01T00:00:00+00:00",
                    row_version="1",
                ),
                self._row(
                    academic,
                    academic_id="academic-a",
                    rut="10.000.000-0",
                    name="Ana",
                    created_at="2024-01-01T00:00:00+00:00",
                    updated_at="2024-01-01T00:00:00+00:00",
                    row_version="1",
                ),
            ],
            "academic_employment_history.csv": [
                self._row(
                    employment,
                    employment_id="employment-z-old",
                    academic_id="academic-z",
                    profile_id="profile-1",
                    status_id="academic-status-active",
                    weekly_hours="40",
                    valid_from="2024-01-01",
                    valid_to="2025-12-31",
                    recorded_at="2024-01-01T00:00:00+00:00",
                    recorded_by_actor_id="fixture",
                ),
                self._row(
                    employment,
                    employment_id="employment-z-current",
                    academic_id="academic-z",
                    profile_id="profile-1",
                    status_id="academic-status-active",
                    weekly_hours="40",
                    valid_from="2026-01-01",
                    recorded_at="2026-01-01T00:00:00+00:00",
                    recorded_by_actor_id="fixture",
                ),
                self._row(
                    employment,
                    employment_id="employment-b-current",
                    academic_id="academic-b",
                    profile_id="profile-1",
                    status_id="academic-status-sabbatical",
                    weekly_hours="20",
                    valid_from="2025-01-01",
                    recorded_at="2025-01-01T00:00:00+00:00",
                    recorded_by_actor_id="fixture",
                ),
                self._row(
                    employment,
                    employment_id="employment-a-current",
                    academic_id="academic-a",
                    profile_id="profile-1",
                    status_id="academic-status-active",
                    weekly_hours="20",
                    valid_from="2025-01-01",
                    recorded_at="2025-01-01T00:00:00+00:00",
                    recorded_by_actor_id="fixture",
                ),
            ],
            "academic_periods.csv": [
                self._row(
                    period,
                    period_id="period-2026",
                    year="2026",
                    term_code="SEMESTER_1",
                    start_date="2026-01-01",
                    end_date="2026-06-30",
                    status_code="OPEN",
                ),
                self._row(
                    period,
                    period_id="period-2025",
                    year="2025",
                    term_code="SEMESTER_2",
                    start_date="2025-07-01",
                    end_date="2025-12-31",
                    status_code="CLOSED",
                ),
            ],
            "Course.csv": [
                self._row(
                    course,
                    course_id="course-b",
                    course_code="PSI200",
                    name="Curso B",
                    level_id="level-1",
                    active="true",
                ),
                self._row(
                    course,
                    course_id="course-a",
                    course_code="PSI100",
                    name="Curso A",
                    level_id="level-1",
                    active="true",
                ),
            ],
            "course_offerings.csv": [
                self._row(
                    offering,
                    offering_id="offering-b",
                    course_id="course-b",
                    period_id="period-2026",
                    section_code="02",
                    nrc="20002",
                    enrollment_count="20",
                    status_code="OPEN",
                    created_at="2026-01-01T00:00:00+00:00",
                    updated_at="2026-01-01T00:00:00+00:00",
                ),
                self._row(
                    offering,
                    offering_id="offering-a",
                    course_id="course-a",
                    period_id="period-2025",
                    section_code="01",
                    nrc="10001",
                    enrollment_count="10",
                    status_code="CLOSED",
                    created_at="2025-01-01T00:00:00+00:00",
                    updated_at="2025-01-01T00:00:00+00:00",
                ),
            ],
            "academic_assignments.csv": [
                self._row(
                    assignment,
                    assignment_id="assignment-b",
                    employment_id="employment-z-old",
                    period_id="period-2026",
                    assignment_type_id="type-course",
                    classification_id="classification-dom",
                    status_id="status-pending",
                    policy_id="policy-1",
                    calculated_points="6.25",
                    calculated_at="2026-01-01T00:00:00+00:00",
                    created_by_actor_id="fixture",
                    created_at="2026-01-01T00:00:00+00:00",
                    updated_at="2026-01-01T00:00:00+00:00",
                    row_version="1",
                ),
                self._row(
                    assignment,
                    assignment_id="assignment-a",
                    employment_id="employment-z-old",
                    period_id="period-2025",
                    assignment_type_id="type-course",
                    classification_id="classification-aac",
                    status_id="status-pending",
                    policy_id="policy-1",
                    calculated_points="3.10",
                    calculated_at="2025-01-01T00:00:00+00:00",
                    created_by_actor_id="fixture",
                    created_at="2025-01-01T00:00:00+00:00",
                    updated_at="2025-01-01T00:00:00+00:00",
                    row_version="1",
                ),
            ],
            "course_assignments.csv": [
                self._row(
                    detail,
                    assignment_id="assignment-b",
                    offering_id="offering-b",
                    participation_percentage="100",
                    enrollment_at_calculation="20",
                ),
                self._row(
                    detail,
                    assignment_id="assignment-a",
                    offering_id="offering-a",
                    participation_percentage="50",
                    enrollment_at_calculation="10",
                ),
            ],
            "assignment_authorizations.csv": [],
        }

    def _base_catalogs(self) -> dict[str, list[dict[str, object]]]:
        assignment_type = CATALOG_FIELDS["assignment_types.csv"]
        classification = CATALOG_FIELDS["assignment_classifications.csv"]
        status = CATALOG_FIELDS["assignment_statuses.csv"]
        return {
            "assignment_types.csv": [
                self._row(
                    assignment_type,
                    assignment_type_id="type-course",
                    type_code="COURSE",
                    name="Curso",
                    implemented="true",
                    active="true",
                )
            ],
            "assignment_classifications.csv": [
                self._row(
                    classification,
                    classification_id="classification-dom",
                    classification_code="DOM",
                    name="Docencia Obligatoria Mínima",
                    active="true",
                ),
                self._row(
                    classification,
                    classification_id="classification-aac",
                    classification_code="AAC",
                    name="Actividad Académica Complementaria",
                    active="true",
                ),
            ],
            "assignment_statuses.csv": [
                self._row(
                    status,
                    status_id="status-pending",
                    status_code="PENDING_AUTHORIZATION",
                    name="Pendiente de autorización",
                    active="true",
                ),
                self._row(
                    status,
                    status_id="status-authorized",
                    status_code="AUTHORIZED",
                    name="Autorizada",
                    active="true",
                ),
                self._row(
                    status,
                    status_id="status-rejected",
                    status_code="REJECTED",
                    name="Rechazada",
                    active="true",
                ),
                self._row(
                    status,
                    status_id="status-cancelled",
                    status_code="CANCELLED",
                    name="Cancelada",
                    active="true",
                ),
            ],
        }

    def _write_dataset(self) -> None:
        for name, rows in self.tables.items():
            self._write_csv(self.paths.table_path(name), TABLE_FIELDS[name], rows)
        for name, rows in self.catalogs.items():
            self._write_csv(self.paths.catalog_path(name), CATALOG_FIELDS[name], rows)

    @staticmethod
    def _write_csv(
        path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def _assignment(self, assignment_id: str = "assignment-b"):
        academic = next(
            item
            for item in self.service.list_assignments_by_academic()
            if item.academic_id == "academic-z"
        )
        return next(
            item for item in academic.assignments if item.assignment_id == assignment_id
        )

    def _set_assignment_status(self, status_id: str) -> None:
        self.tables["academic_assignments.csv"][0]["status_id"] = status_id
        self._write_dataset()

    def _set_authorizations(self, *decisions: tuple[int, str, str]) -> None:
        fields = TABLE_FIELDS["assignment_authorizations.csv"]
        self.tables["assignment_authorizations.csv"] = [
            self._row(
                fields,
                authorization_id=f"authorization-{sequence}",
                assignment_id="assignment-b",
                decision_sequence=str(sequence),
                decision_code=decision,
                approved_points=points,
                justification="fixture",
                decided_by_actor_id="fixture",
                decided_by_role_code="DIRECTOR",
                decided_at=f"2026-01-0{sequence}T00:00:00+00:00",
            )
            for sequence, decision, points in decisions
        ]
        self._write_dataset()

    def test_includes_current_academic_without_assignments(self) -> None:
        results = self.service.list_assignments_by_academic()
        empty = next(item for item in results if item.academic_id == "academic-a")
        self.assertEqual(empty.assignments, ())
        self.assertEqual(empty.total_points, Decimal(0))

    def test_groups_multiple_assignments_for_academic(self) -> None:
        result = next(
            item
            for item in self.service.list_assignments_by_academic()
            if item.academic_id == "academic-z"
        )
        self.assertEqual(len(result.assignments), 2)

    def test_links_assignment_through_historical_employment(self) -> None:
        result = next(
            item
            for item in self.service.list_assignments_by_academic()
            if item.academic_id == "academic-z"
        )
        self.assertEqual(
            {item.assignment_id for item in result.assignments},
            {"assignment-a", "assignment-b"},
        )

    def test_resolves_course_period_and_catalogs(self) -> None:
        result = self._assignment()
        self.assertEqual(result.period_label, "2026 · SEMESTER_1")
        self.assertEqual(result.type_code, "COURSE")
        self.assertEqual(result.classification_code, "DOM")
        self.assertEqual(result.status_name, "Pendiente de autorización")
        self.assertEqual(
            (result.course_code, result.course_name, result.section_code, result.nrc),
            ("PSI200", "Curso B", "02", "20002"),
        )

    def test_total_uses_decimal(self) -> None:
        result = next(
            item
            for item in self.service.list_assignments_by_academic()
            if item.academic_id == "academic-z"
        )
        self.assertIsInstance(result.total_points, Decimal)
        self.assertEqual(result.total_points, Decimal("9.35"))

    def test_selects_authorization_with_greatest_sequence(self) -> None:
        self._set_authorizations((1, "AUTHORIZED", "7.00"), (3, "AUTHORIZED", "9.00"))
        result = self._assignment()
        self.assertEqual(result.latest_authorized_points, Decimal("9.00"))
        self.assertEqual(result.displayed_points, Decimal("9.00"))

    def test_authorization_selection_ignores_physical_csv_order(self) -> None:
        self._set_authorizations((4, "AUTHORIZED", "11.00"), (2, "AUTHORIZED", "8.00"))
        self.assertEqual(self._assignment().displayed_points, Decimal("11.00"))

    def test_pending_assignment_contributes(self) -> None:
        result = self._assignment()
        self.assertTrue(result.contributes_to_total)
        self.assertEqual(result.displayed_points, Decimal("6.25"))

    def test_authorized_assignment_contributes(self) -> None:
        self._set_assignment_status("status-authorized")
        self._set_authorizations((1, "AUTHORIZED", "8.50"))
        result = self._assignment()
        self.assertTrue(result.contributes_to_total)
        self.assertEqual(result.displayed_points, Decimal("8.50"))

    def test_rejected_assignment_does_not_contribute(self) -> None:
        self._set_assignment_status("status-rejected")
        result = self._assignment()
        self.assertFalse(result.contributes_to_total)
        self.assertEqual(result.displayed_points, Decimal("6.25"))

    def test_cancelled_assignment_does_not_contribute(self) -> None:
        self._set_assignment_status("status-cancelled")
        result = self._assignment()
        self.assertFalse(result.contributes_to_total)
        self.assertEqual(result.displayed_points, Decimal("6.25"))

    def test_latest_revoked_decision_preserves_points_but_excludes_total(self) -> None:
        self._set_assignment_status("status-authorized")
        self._set_authorizations((1, "AUTHORIZED", "8.50"), (2, "REVOKED", ""))
        result = self._assignment()
        self.assertEqual(result.displayed_points, Decimal("8.50"))
        self.assertFalse(result.contributes_to_total)

    def test_missing_employment_reference_raises_specific_error(self) -> None:
        self.tables["academic_assignments.csv"][0]["employment_id"] = "missing"
        self._write_dataset()
        with self.assertRaisesRegex(AssignmentListingError, "employment_id"):
            self.service.list_assignments_by_academic()

    def test_missing_academic_reference_raises_specific_error(self) -> None:
        self.tables["academic_employment_history.csv"][0]["academic_id"] = "missing"
        self._write_dataset()
        with self.assertRaisesRegex(AssignmentListingError, "academic_id"):
            self.service.list_assignments_by_academic()

    def test_missing_course_detail_raises_specific_error(self) -> None:
        self.tables["course_assignments.csv"] = [
            row
            for row in self.tables["course_assignments.csv"]
            if row["assignment_id"] != "assignment-b"
        ]
        self._write_dataset()
        with self.assertRaisesRegex(AssignmentListingError, "course_assignments"):
            self.service.list_assignments_by_academic()

    def test_optional_period_filter_limits_assignments_and_total(self) -> None:
        results = self.service.list_assignments_by_academic("period-2025")
        result = next(item for item in results if item.academic_id == "academic-z")
        self.assertEqual(
            [item.assignment_id for item in result.assignments], ["assignment-a"]
        )
        self.assertEqual(result.total_points, Decimal("3.10"))
        self.assertEqual(len(results), 3)

    def test_period_filter_does_not_hide_an_invalid_assignment(self) -> None:
        self.tables["academic_assignments.csv"][0]["employment_id"] = "missing"
        self._write_dataset()
        with self.assertRaises(AssignmentListingError):
            self.service.list_assignments_by_academic("period-2025")

    def test_ordering_is_deterministic(self) -> None:
        results = self.service.list_assignments_by_academic()
        self.assertEqual(
            [item.academic_id for item in results],
            ["academic-a", "academic-b", "academic-z"],
        )
        zoe = results[-1]
        self.assertEqual(
            [item.assignment_id for item in zoe.assignments],
            ["assignment-a", "assignment-b"],
        )

    def test_application_service_rejects_query_without_session(self) -> None:
        application = ApplicationService(
            authentication=Mock(),
            sessions=InMemorySession(),
            academics=Mock(),
            paths=self.paths,
            academic_catalogs=Mock(),
            git_sync=Mock(),
            assignments=self.service,
        )
        with self.assertRaises(AuthenticationRequiredError):
            application.list_assignments_by_academic()


if __name__ == "__main__":
    unittest.main()
