"""Course assignment use cases and centralized V3 point rules."""

from __future__ import annotations

import csv
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from backend.contracts import (
    AcademicAssignmentsSummary,
    AcademicPeriod,
    AssignmentListingError,
    AssignmentResult,
    AssignmentSummary,
    Course,
    CourseAssignmentDraft,
    CourseOffering,
)
from persistence.data_model import CATALOG_FIELDS, TABLE_FIELDS, read_csv
from persistence.normalized_academic_repository import NormalizedAcademicRepository
from persistence.paths import ProjectPaths
from persistence.unit_of_work import CsvUnitOfWork


class AssignmentValidationError(ValueError):
    pass


def _indexed(
    rows: list[dict[str, str]], key: str, label: str
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        identifier = row[key]
        if not identifier:
            raise AssignmentListingError(f"Identificador vacío en {label}.{key}.")
        if identifier in result:
            raise AssignmentListingError(
                f"Identificador duplicado {identifier!r} en {label}.{key}."
            )
        result[identifier] = row
    return result


def _required_reference(
    index: dict[str, dict[str, str]], identifier: str, relationship: str
) -> dict[str, str]:
    try:
        return index[identifier]
    except KeyError as error:
        raise AssignmentListingError(
            f"Referencia inexistente en {relationship}: {identifier!r}."
        ) from error


def _persisted_decimal(value: str, relationship: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise AssignmentListingError(
            f"Decimal inválido en {relationship}: {value!r}."
        ) from error
    if not result.is_finite():
        raise AssignmentListingError(f"Decimal no finito en {relationship}.")
    return result


def _normalized_name(value: str) -> str:
    collapsed = " ".join(value.split()).casefold()
    decomposed = unicodedata.normalize("NFKD", collapsed)
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )


def _write(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class WorkloadRules:
    """Read versioned point values from catalogs; never duplicate them in UI."""

    def __init__(self, public_dir: Path) -> None:
        catalog = public_dir / "catalogs"
        self.policy = read_csv(
            catalog / "workload_policies.csv", CATALOG_FIELDS["workload_policies.csv"]
        )[0]
        self.demands = {
            row["category_code"]: row
            for row in read_csv(
                catalog / "demand_categories.csv",
                CATALOG_FIELDS["demand_categories.csv"],
            )
        }

    def calculate(
        self, classification: str, participation: Decimal, demand: str | None
    ) -> Decimal:
        if participation <= 0 or participation > 100:
            raise AssignmentValidationError(
                "La participación debe estar entre 0 y 100%."
            )
        if classification in {"DOM", "AAC"}:
            if demand:
                raise AssignmentValidationError("La demanda solo modifica cursos AAA.")
            base = Decimal(self.policy["dom_course_points"])
        elif classification == "AAA":
            if participation < Decimal(
                self.policy["min_compensable_participation_percentage"]
            ):
                raise AssignmentValidationError(
                    "AAA requiere al menos 20% de participación."
                )
            if demand not in self.demands:
                raise AssignmentValidationError(
                    "Seleccione una categoría de demanda A, B, C o D."
                )
            base = Decimal(self.demands[demand]["annual_points"])
        else:
            raise AssignmentValidationError("Clasificación de asignación inválida.")
        return (base * participation / Decimal(100)).quantize(Decimal("0.01"))


class AssignmentService:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def list_active_academics(self):
        return NormalizedAcademicRepository(self.paths).list_active()

    def list_assignments_by_academic(
        self, period_id: str | None = None
    ) -> tuple[AcademicAssignmentsSummary, ...]:
        """Return a complete, read-only assignment projection grouped by academic."""
        tables = self.paths.public_tables_dir
        catalogs = self.paths.academic_catalogs_dir
        try:
            academic_rows = read_csv(
                tables / "Academic.csv", TABLE_FIELDS["Academic.csv"]
            )
            employment_rows = read_csv(
                tables / "academic_employment_history.csv",
                TABLE_FIELDS["academic_employment_history.csv"],
            )
            period_rows = read_csv(
                tables / "academic_periods.csv",
                TABLE_FIELDS["academic_periods.csv"],
            )
            assignment_rows = read_csv(
                tables / "academic_assignments.csv",
                TABLE_FIELDS["academic_assignments.csv"],
            )
            detail_rows = read_csv(
                tables / "course_assignments.csv",
                TABLE_FIELDS["course_assignments.csv"],
            )
            offering_rows = read_csv(
                tables / "course_offerings.csv",
                TABLE_FIELDS["course_offerings.csv"],
            )
            course_rows = read_csv(tables / "Course.csv", TABLE_FIELDS["Course.csv"])
            authorization_rows = read_csv(
                tables / "assignment_authorizations.csv",
                TABLE_FIELDS["assignment_authorizations.csv"],
            )
            type_rows = read_csv(
                catalogs / "assignment_types.csv",
                CATALOG_FIELDS["assignment_types.csv"],
            )
            classification_rows = read_csv(
                catalogs / "assignment_classifications.csv",
                CATALOG_FIELDS["assignment_classifications.csv"],
            )
            status_rows = read_csv(
                catalogs / "assignment_statuses.csv",
                CATALOG_FIELDS["assignment_statuses.csv"],
            )
        except ValueError as error:
            raise AssignmentListingError(
                f"No fue posible leer la consulta de asignaciones: {error}"
            ) from error

        academics = _indexed(academic_rows, "academic_id", "Academic")
        employments = _indexed(
            employment_rows, "employment_id", "academic_employment_history"
        )
        periods = _indexed(period_rows, "period_id", "academic_periods")
        assignments = _indexed(assignment_rows, "assignment_id", "academic_assignments")
        details = _indexed(detail_rows, "assignment_id", "course_assignments")
        offerings = _indexed(offering_rows, "offering_id", "course_offerings")
        courses = _indexed(course_rows, "course_id", "Course")
        types = _indexed(type_rows, "assignment_type_id", "assignment_types")
        classifications = _indexed(
            classification_rows,
            "classification_id",
            "assignment_classifications",
        )
        statuses = _indexed(status_rows, "status_id", "assignment_statuses")

        for employment in employment_rows:
            _required_reference(
                academics,
                employment["academic_id"],
                "academic_employment_history.academic_id → Academic.academic_id",
            )
        for offering in offering_rows:
            _required_reference(
                courses,
                offering["course_id"],
                "course_offerings.course_id → Course.course_id",
            )
            _required_reference(
                periods,
                offering["period_id"],
                "course_offerings.period_id → academic_periods.period_id",
            )
        for detail in detail_rows:
            _required_reference(
                assignments,
                detail["assignment_id"],
                "course_assignments.assignment_id → academic_assignments.assignment_id",
            )
            _required_reference(
                offerings,
                detail["offering_id"],
                "course_assignments.offering_id → course_offerings.offering_id",
            )

        current_academic_ids = {
            row["academic_id"] for row in employment_rows if not row["valid_to"]
        }

        authorizations_by_assignment: dict[str, list[tuple[int, dict[str, str]]]] = {}
        sequences: set[tuple[str, int]] = set()
        for authorization in authorization_rows:
            assignment_id = authorization["assignment_id"]
            _required_reference(
                assignments,
                assignment_id,
                "assignment_authorizations.assignment_id "
                "→ academic_assignments.assignment_id",
            )
            try:
                sequence = int(authorization["decision_sequence"])
            except ValueError as error:
                raise AssignmentListingError(
                    "Secuencia inválida en "
                    f"assignment_authorizations: {authorization['decision_sequence']!r}."
                ) from error
            if sequence < 1 or (assignment_id, sequence) in sequences:
                raise AssignmentListingError(
                    "Secuencia duplicada o menor que uno para la asignación "
                    f"{assignment_id!r}."
                )
            sequences.add((assignment_id, sequence))
            decision = authorization["decision_code"]
            if decision not in {"AUTHORIZED", "REJECTED", "REVOKED"}:
                raise AssignmentListingError(
                    f"Decisión desconocida {decision!r} para {assignment_id!r}."
                )
            authorizations_by_assignment.setdefault(assignment_id, []).append(
                (sequence, authorization)
            )

        grouped: dict[str, list[AssignmentSummary]] = {
            academic_id: [] for academic_id in current_academic_ids
        }
        for assignment in assignment_rows:
            assignment_id = assignment["assignment_id"]
            included = period_id is None or assignment["period_id"] == period_id
            employment = _required_reference(
                employments,
                assignment["employment_id"],
                "academic_assignments.employment_id "
                "→ academic_employment_history.employment_id",
            )
            academic = _required_reference(
                academics,
                employment["academic_id"],
                "academic_employment_history.academic_id → Academic.academic_id",
            )
            period = _required_reference(
                periods,
                assignment["period_id"],
                "academic_assignments.period_id → academic_periods.period_id",
            )
            assignment_type = _required_reference(
                types,
                assignment["assignment_type_id"],
                "academic_assignments.assignment_type_id "
                "→ assignment_types.assignment_type_id",
            )
            classification = _required_reference(
                classifications,
                assignment["classification_id"],
                "academic_assignments.classification_id "
                "→ assignment_classifications.classification_id",
            )
            status = _required_reference(
                statuses,
                assignment["status_id"],
                "academic_assignments.status_id → assignment_statuses.status_id",
            )

            course_code = course_name = section_code = nrc = None
            if assignment_type["type_code"] == "COURSE":
                detail = _required_reference(
                    details,
                    assignment_id,
                    "academic_assignments.assignment_id "
                    "→ course_assignments.assignment_id",
                )
                offering = _required_reference(
                    offerings,
                    detail["offering_id"],
                    "course_assignments.offering_id → course_offerings.offering_id",
                )
                if offering["period_id"] != assignment["period_id"]:
                    raise AssignmentListingError(
                        "Períodos inconsistentes entre la asignación "
                        f"{assignment_id!r} y su oferta {offering['offering_id']!r}."
                    )
                course = _required_reference(
                    courses,
                    offering["course_id"],
                    "course_offerings.course_id → Course.course_id",
                )
                course_code = course["course_code"]
                course_name = course["name"]
                section_code = offering["section_code"] or None
                nrc = offering["nrc"] or None

            calculated_points = _persisted_decimal(
                assignment["calculated_points"],
                f"academic_assignments.calculated_points ({assignment_id})",
            )
            decisions = sorted(
                authorizations_by_assignment.get(assignment_id, ()),
                key=lambda item: item[0],
            )
            latest_decision = decisions[-1][1]["decision_code"] if decisions else None
            authorized = [
                item for item in decisions if item[1]["decision_code"] == "AUTHORIZED"
            ]
            latest_authorized_points = None
            if authorized:
                authorization = authorized[-1][1]
                latest_authorized_points = _persisted_decimal(
                    authorization["approved_points"],
                    "assignment_authorizations.approved_points "
                    f"({authorization['authorization_id']})",
                )
            displayed_points = (
                latest_authorized_points
                if latest_authorized_points is not None
                else calculated_points
            )
            contributes = status["status_code"] in {
                "PENDING_AUTHORIZATION",
                "AUTHORIZED",
            } and latest_decision not in {"REJECTED", "REVOKED"}
            summary = AssignmentSummary(
                assignment_id=assignment_id,
                period_id=period["period_id"],
                period_label=f"{period['year']} · {period['term_code']}",
                type_code=assignment_type["type_code"],
                type_name=assignment_type["name"],
                classification_code=classification["classification_code"],
                classification_name=classification["name"],
                status_code=status["status_code"],
                status_name=status["name"],
                course_code=course_code,
                course_name=course_name,
                section_code=section_code,
                nrc=nrc,
                calculated_points=calculated_points,
                latest_authorized_points=latest_authorized_points,
                displayed_points=displayed_points,
                contributes_to_total=contributes,
            )
            if included and academic["academic_id"] in grouped:
                grouped[academic["academic_id"]].append(summary)

        result = []
        for academic_id in current_academic_ids:
            academic = academics[academic_id]
            academic_assignments = tuple(
                sorted(
                    grouped[academic_id],
                    key=lambda item: (
                        item.period_label,
                        item.course_code or "",
                        item.assignment_id,
                    ),
                )
            )
            total = sum(
                (
                    item.displayed_points
                    for item in academic_assignments
                    if item.contributes_to_total
                ),
                Decimal(0),
            )
            result.append(
                AcademicAssignmentsSummary(
                    academic_id=academic_id,
                    name=academic["name"],
                    rut=academic["rut"],
                    assignments=academic_assignments,
                    total_points=total,
                )
            )
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    _normalized_name(item.name),
                    item.rut,
                    item.academic_id,
                ),
            )
        )

    def list_periods(self) -> list[AcademicPeriod]:
        rows = read_csv(
            self.paths.table_path("academic_periods.csv"),
            TABLE_FIELDS["academic_periods.csv"],
        )
        return [
            AcademicPeriod(
                row["period_id"],
                int(row["year"]),
                row["term_code"],
                row["start_date"],
                row["end_date"],
                row["status_code"],
            )
            for row in rows
            if row["status_code"] in {"DRAFT", "OPEN"}
        ]

    def create_period(
        self, year: int, term_code: str, start_date: str, end_date: str
    ) -> AcademicPeriod:
        if not 2000 <= year <= 2100 or term_code not in {
            "ANNUAL",
            "SEMESTER_1",
            "SEMESTER_2",
        }:
            raise AssignmentValidationError("Los datos del período son inválidos.")
        if not start_date or not end_date or start_date > end_date:
            raise AssignmentValidationError("Las fechas del período son inválidas.")
        with CsvUnitOfWork(self.paths) as uow:
            assert uow.public_dir is not None
            path = uow.public_dir / "tables" / "academic_periods.csv"
            rows = read_csv(path, TABLE_FIELDS[path.name])
            if any(
                int(row["year"]) == year and row["term_code"] == term_code
                for row in rows
            ):
                raise AssignmentValidationError("El período ya existe.")
            period = AcademicPeriod(
                f"period-{year}-{term_code.lower()}",
                year,
                term_code,
                start_date,
                end_date,
                "OPEN",
            )
            rows.append(
                {
                    "period_id": period.period_id,
                    "year": year,
                    "term_code": term_code,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status_code": "OPEN",
                }
            )
            _write(path, TABLE_FIELDS[path.name], rows)
            uow.commit()
        return period

    def list_courses(self) -> list[Course]:
        rows = read_csv(self.paths.table_path("Course.csv"), TABLE_FIELDS["Course.csv"])
        return [
            Course(row["course_id"], row["course_code"], row["name"], row["level_id"])
            for row in rows
            if row["active"] == "true"
        ]

    def list_offerings(self, period_id: str, course_id: str) -> list[CourseOffering]:
        rows = read_csv(
            self.paths.table_path("course_offerings.csv"),
            TABLE_FIELDS["course_offerings.csv"],
        )
        return [
            CourseOffering(
                row["offering_id"],
                row["course_id"],
                row["period_id"],
                row["section_code"],
                row["nrc"],
                int(row["enrollment_count"]) if row["enrollment_count"] else None,
            )
            for row in rows
            if row["period_id"] == period_id
            and row["course_id"] == course_id
            and row["status_code"] != "CANCELLED"
        ]

    def calculate(self, draft: CourseAssignmentDraft) -> AssignmentResult:
        self._ensure_calculation_inputs(draft)
        rules = WorkloadRules(self.paths.public_data_dir)
        points = rules.calculate(
            draft.classification_code,
            Decimal(draft.participation_percentage),
            draft.demand_category_code,
        )
        return AssignmentResult(
            "", points, rules.policy["policy_id"], rules.policy["approval_status"]
        )

    def create_assignment(
        self, draft: CourseAssignmentDraft, actor_id: str
    ) -> AssignmentResult:
        preview = self.calculate(draft)
        if not actor_id:
            raise AssignmentValidationError("Se requiere una sesión para guardar.")
        with CsvUnitOfWork(self.paths) as uow:
            assert uow.public_dir is not None
            tables = uow.public_dir / "tables"
            periods = read_csv(
                tables / "academic_periods.csv", TABLE_FIELDS["academic_periods.csv"]
            )
            if draft.period_id not in {
                row["period_id"]
                for row in periods
                if row["status_code"] in {"DRAFT", "OPEN"}
            }:
                raise AssignmentValidationError(
                    "El período seleccionado no está disponible."
                )
            courses = read_csv(tables / "Course.csv", TABLE_FIELDS["Course.csv"])
            if draft.course_id not in {
                row["course_id"] for row in courses if row["active"] == "true"
            }:
                raise AssignmentValidationError(
                    "El curso seleccionado no está disponible."
                )
            employment = self._active_employment(tables, draft.academic_id)
            period_row = next(
                row for row in periods if row["period_id"] == draft.period_id
            )
            if date.fromisoformat(employment["valid_from"]) > date.fromisoformat(
                period_row["start_date"]
            ) or (
                employment["valid_to"]
                and date.fromisoformat(employment["valid_to"])
                < date.fromisoformat(period_row["end_date"])
            ):
                raise AssignmentValidationError(
                    "El vínculo académico no cubre completamente el período."
                )
            offerings_path = tables / "course_offerings.csv"
            offerings = read_csv(offerings_path, TABLE_FIELDS[offerings_path.name])
            offering_id = draft.offering_id
            if offering_id:
                offering = next(
                    (
                        row
                        for row in offerings
                        if row["offering_id"] == offering_id
                        and row["period_id"] == draft.period_id
                        and row["course_id"] == draft.course_id
                    ),
                    None,
                )
                if offering is None:
                    raise AssignmentValidationError(
                        "La oferta seleccionada no corresponde al período y curso."
                    )
            else:
                if not draft.section_code.strip():
                    raise AssignmentValidationError(
                        "Ingrese una sección para crear la oferta."
                    )
                if any(
                    row["course_id"] == draft.course_id
                    and row["period_id"] == draft.period_id
                    and row["section_code"] == draft.section_code.strip()
                    for row in offerings
                ):
                    raise AssignmentValidationError(
                        "La oferta ya existe; selecciónela."
                    )
                offering_id = f"offering-{uuid4()}"
                now = datetime.now().astimezone().isoformat(timespec="seconds")
                offerings.append(
                    {
                        "offering_id": offering_id,
                        "course_id": draft.course_id,
                        "period_id": draft.period_id,
                        "section_code": draft.section_code.strip(),
                        "nrc": draft.nrc.strip(),
                        "enrollment_count": ""
                        if draft.enrollment_count is None
                        else draft.enrollment_count,
                        "status_code": "OPEN",
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                _write(offerings_path, TABLE_FIELDS[offerings_path.name], offerings)
            details_path = tables / "course_assignments.csv"
            details = read_csv(details_path, TABLE_FIELDS[details_path.name])
            total = sum(
                (
                    Decimal(row["participation_percentage"])
                    for row in details
                    if row["offering_id"] == offering_id
                ),
                Decimal(0),
            ) + Decimal(draft.participation_percentage)
            if total > 100:
                raise AssignmentValidationError(
                    "La suma de participaciones de co-docencia supera 100%."
                )
            catalog = uow.public_dir / "catalogs"
            classification_id = next(
                row["classification_id"]
                for row in read_csv(
                    catalog / "assignment_classifications.csv",
                    CATALOG_FIELDS["assignment_classifications.csv"],
                )
                if row["classification_code"] == draft.classification_code
            )
            demand_id = ""
            if draft.demand_category_code:
                demand_id = next(
                    row["demand_category_id"]
                    for row in read_csv(
                        catalog / "demand_categories.csv",
                        CATALOG_FIELDS["demand_categories.csv"],
                    )
                    if row["category_code"] == draft.demand_category_code
                )
            assignment_id = f"assignment-{uuid4()}"
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            assignments_path = tables / "academic_assignments.csv"
            assignments = read_csv(
                assignments_path, TABLE_FIELDS[assignments_path.name]
            )
            assignments.append(
                {
                    "assignment_id": assignment_id,
                    "employment_id": employment["employment_id"],
                    "period_id": draft.period_id,
                    "assignment_type_id": "assignment-type-course-v1",
                    "classification_id": classification_id,
                    "status_id": "assignment-status-pending-authorization-v1",
                    "policy_id": preview.policy_id,
                    "calculated_points": str(preview.calculated_points),
                    "calculated_at": now,
                    "created_by_actor_id": actor_id,
                    "created_at": now,
                    "updated_at": now,
                    "row_version": 1,
                }
            )
            details.append(
                {
                    "assignment_id": assignment_id,
                    "offering_id": offering_id,
                    "participation_percentage": str(
                        Decimal(draft.participation_percentage)
                    ),
                    "enrollment_at_calculation": ""
                    if draft.enrollment_count is None
                    else draft.enrollment_count,
                    "demand_category_id": demand_id,
                    "demand_basis_code": "ENROLLMENT" if demand_id else "",
                }
            )
            _write(assignments_path, TABLE_FIELDS[assignments_path.name], assignments)
            _write(details_path, TABLE_FIELDS[details_path.name], details)
            uow.commit()
        return AssignmentResult(
            assignment_id,
            preview.calculated_points,
            preview.policy_id,
            preview.policy_status,
        )

    def authorize_assignment(
        self,
        assignment_id: str,
        approved_points: Decimal,
        actor_id: str,
        role_code: str = "DIRECTOR",
        justification: str = "Aprobación interna",
    ) -> None:
        if approved_points < 0 or role_code not in {
            "DIRECTOR",
            "UNDERGRADUATE_DEPUTY",
            "POSTGRADUATE_DEPUTY",
        }:
            raise AssignmentValidationError("La autorización es inválida.")
        with CsvUnitOfWork(self.paths) as uow:
            assert uow.public_dir is not None
            tables = uow.public_dir / "tables"
            assignments_path = tables / "academic_assignments.csv"
            assignments = read_csv(
                assignments_path, TABLE_FIELDS[assignments_path.name]
            )
            assignment = next(
                (row for row in assignments if row["assignment_id"] == assignment_id),
                None,
            )
            if assignment is None:
                raise AssignmentValidationError("La asignación no existe.")
            authorizations_path = tables / "assignment_authorizations.csv"
            authorizations = read_csv(
                authorizations_path, TABLE_FIELDS[authorizations_path.name]
            )
            sequence = (
                max(
                    (
                        int(row["decision_sequence"])
                        for row in authorizations
                        if row["assignment_id"] == assignment_id
                    ),
                    default=0,
                )
                + 1
            )
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            authorizations.append(
                {
                    "authorization_id": f"authorization-{uuid4()}",
                    "assignment_id": assignment_id,
                    "decision_sequence": sequence,
                    "decision_code": "AUTHORIZED",
                    "approved_points": str(approved_points),
                    "justification": justification,
                    "decided_by_actor_id": actor_id,
                    "decided_by_role_code": role_code,
                    "decided_at": now,
                }
            )
            assignment.update(
                status_id="assignment-status-authorized-v1",
                updated_at=now,
                row_version=str(int(assignment["row_version"]) + 1),
            )
            _write(assignments_path, TABLE_FIELDS[assignments_path.name], assignments)
            _write(
                authorizations_path,
                TABLE_FIELDS[authorizations_path.name],
                authorizations,
            )
            uow.commit()

    def adjust_points(
        self,
        assignment_id: str,
        new_points: Decimal,
        reason: str,
        actor_id: str,
    ) -> None:
        if not reason.strip() or new_points < 0:
            raise AssignmentValidationError(
                "El ajuste requiere motivo y puntos válidos."
            )
        with CsvUnitOfWork(self.paths) as uow:
            assert uow.public_dir is not None
            tables = uow.public_dir / "tables"
            assignments = read_csv(
                tables / "academic_assignments.csv",
                TABLE_FIELDS["academic_assignments.csv"],
            )
            assignment = next(
                (row for row in assignments if row["assignment_id"] == assignment_id),
                None,
            )
            if assignment is None:
                raise AssignmentValidationError("La asignación no existe.")
            authorizations_path = tables / "assignment_authorizations.csv"
            authorizations = read_csv(
                authorizations_path, TABLE_FIELDS[authorizations_path.name]
            )
            previous = next(
                (
                    Decimal(row["approved_points"])
                    for row in reversed(authorizations)
                    if row["assignment_id"] == assignment_id
                    and row["decision_code"] == "AUTHORIZED"
                ),
                Decimal(assignment["calculated_points"]),
            )
            sequence = 1 + max(
                (
                    int(row["decision_sequence"])
                    for row in authorizations
                    if row["assignment_id"] == assignment_id
                ),
                default=0,
            )
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            authorization_id = f"authorization-{uuid4()}"
            authorizations.append(
                {
                    "authorization_id": authorization_id,
                    "assignment_id": assignment_id,
                    "decision_sequence": sequence,
                    "decision_code": "AUTHORIZED",
                    "approved_points": str(new_points),
                    "justification": reason.strip(),
                    "decided_by_actor_id": actor_id,
                    "decided_by_role_code": "DIRECTOR",
                    "decided_at": now,
                }
            )
            adjustments_path = tables / "assignment_point_adjustments.csv"
            adjustments = read_csv(
                adjustments_path, TABLE_FIELDS[adjustments_path.name]
            )
            delta = new_points - previous
            adjustments.append(
                {
                    "adjustment_id": f"adjustment-{uuid4()}",
                    "assignment_id": assignment_id,
                    "authorization_id": authorization_id,
                    "requested_delta_points": str(delta),
                    "approved_delta_points": str(delta),
                    "reason": reason.strip(),
                    "status_code": "APPROVED",
                    "requested_by_actor_id": actor_id,
                    "requested_at": now,
                    "decided_by_actor_id": actor_id,
                    "decided_at": now,
                }
            )
            assignment.update(
                status_id="assignment-status-authorized-v1",
                updated_at=now,
                row_version=str(int(assignment["row_version"]) + 1),
            )
            _write(
                tables / "academic_assignments.csv",
                TABLE_FIELDS["academic_assignments.csv"],
                assignments,
            )
            _write(
                authorizations_path,
                TABLE_FIELDS[authorizations_path.name],
                authorizations,
            )
            _write(
                adjustments_path,
                TABLE_FIELDS[adjustments_path.name],
                adjustments,
            )
            uow.commit()

    @staticmethod
    def _active_employment(tables: Path, academic_id: str) -> dict[str, str]:
        rows = read_csv(
            tables / "academic_employment_history.csv",
            TABLE_FIELDS["academic_employment_history.csv"],
        )
        found = [
            row
            for row in rows
            if row["academic_id"] == academic_id
            and not row["valid_to"]
            and row["status_id"] == "academic-status-active-v1"
        ]
        if len(found) != 1:
            raise AssignmentValidationError(
                "El académico no posee un vínculo activo único."
            )
        return found[0]

    def _ensure_calculation_inputs(self, draft: CourseAssignmentDraft) -> None:
        tables = self.paths.public_tables_dir
        if not draft.academic_id:
            raise AssignmentValidationError(
                "Seleccione un académico activo antes de calcular."
            )
        self._active_employment(tables, draft.academic_id)
        periods = read_csv(
            tables / "academic_periods.csv", TABLE_FIELDS["academic_periods.csv"]
        )
        if draft.period_id not in {
            row["period_id"]
            for row in periods
            if row["status_code"] in {"DRAFT", "OPEN"}
        }:
            raise AssignmentValidationError(
                "Seleccione un período académico abierto antes de calcular."
            )
        courses = read_csv(tables / "Course.csv", TABLE_FIELDS["Course.csv"])
        if draft.course_id not in {
            row["course_id"] for row in courses if row["active"] == "true"
        }:
            raise AssignmentValidationError(
                "Seleccione un curso activo antes de calcular."
            )
