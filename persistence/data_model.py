"""Strict validation and canonical metadata for the normalized CSV dataset."""

from __future__ import annotations

import csv
import shutil
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

TABLE_FIELDS = {
    "Academic.csv": (
        "academic_id",
        "rut",
        "name",
        "created_at",
        "updated_at",
        "row_version",
    ),
    "Course.csv": ("course_id", "course_code", "name", "level_id", "active"),
    "academic_employment_history.csv": (
        "employment_id",
        "academic_id",
        "profile_id",
        "status_id",
        "weekly_hours",
        "valid_from",
        "valid_to",
        "recorded_at",
        "recorded_by_actor_id",
    ),
    "academic_periods.csv": (
        "period_id",
        "year",
        "term_code",
        "start_date",
        "end_date",
        "status_code",
    ),
    "course_offerings.csv": (
        "offering_id",
        "course_id",
        "period_id",
        "section_code",
        "nrc",
        "enrollment_count",
        "status_code",
        "created_at",
        "updated_at",
    ),
    "academic_assignments.csv": (
        "assignment_id",
        "employment_id",
        "period_id",
        "assignment_type_id",
        "classification_id",
        "status_id",
        "policy_id",
        "calculated_points",
        "calculated_at",
        "created_by_actor_id",
        "created_at",
        "updated_at",
        "row_version",
    ),
    "course_assignments.csv": (
        "assignment_id",
        "offering_id",
        "participation_percentage",
        "enrollment_at_calculation",
        "demand_category_id",
        "demand_basis_code",
    ),
    "assignment_authorizations.csv": (
        "authorization_id",
        "assignment_id",
        "decision_sequence",
        "decision_code",
        "approved_points",
        "justification",
        "decided_by_actor_id",
        "decided_by_role_code",
        "decided_at",
    ),
    "assignment_point_adjustments.csv": (
        "adjustment_id",
        "assignment_id",
        "authorization_id",
        "requested_delta_points",
        "approved_delta_points",
        "reason",
        "status_code",
        "requested_by_actor_id",
        "requested_at",
        "decided_by_actor_id",
        "decided_at",
    ),
}

CATALOG_FIELDS = {
    "academic_staff.csv": ("staff_id", "key", "name", "active"),
    "academic_profiles.csv": (
        "profile_id",
        "staff_id",
        "key",
        "name",
        "teaching_percentage",
        "management_percentage",
        "research_percentage",
        "allows_extra_courses",
        "active",
    ),
    "academic_statuses.csv": ("status_id", "status_code", "name", "active"),
    "assignment_classifications.csv": (
        "classification_id",
        "classification_code",
        "name",
        "active",
    ),
    "assignment_statuses.csv": ("status_id", "status_code", "name", "active"),
    "assignment_types.csv": (
        "assignment_type_id",
        "type_code",
        "name",
        "implemented",
        "active",
    ),
    "course_levels.csv": ("level_id", "level_code", "name", "active"),
    "demand_categories.csv": (
        "demand_category_id",
        "policy_id",
        "category_code",
        "name",
        "min_students",
        "max_students",
        "annual_points",
        "active",
    ),
    "profile_workload_rules.csv": (
        "workload_rule_id",
        "policy_id",
        "profile_id",
        "weekly_hours",
        "teaching_points",
        "management_points",
        "research_points",
        "dom_course_equivalents",
        "aac_points",
        "validation_status",
        "source_page",
    ),
    "workload_policies.csv": (
        "policy_id",
        "policy_code",
        "version_label",
        "approval_status",
        "dom_course_points",
        "min_compensable_participation_percentage",
        "effective_from",
        "effective_to",
        "source_name",
        "source_pages",
    ),
}

SHARED_TABLE_ALLOWLIST = tuple(f"data/public/tables/{name}" for name in TABLE_FIELDS)


class DataModelError(ValueError):
    """A complete normalized dataset is missing or internally inconsistent."""


def read_csv(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if tuple(reader.fieldnames or ()) != fields:
                raise DataModelError(f"Esquema incompatible en {path.name}.")
            rows = list(reader)
            if any(None in row for row in rows):
                raise DataModelError(f"Columnas inesperadas en {path.name}.")
            return rows
    except FileNotFoundError as error:
        raise DataModelError(f"Falta el archivo requerido {path.name}.") from error
    except (OSError, UnicodeError, csv.Error) as error:
        raise DataModelError(f"No fue posible leer {path.name}.") from error


def _unique(rows: list[dict[str, str]], field: str, label: str) -> set[str]:
    values = [row[field] for row in rows]
    if any(not value for value in values) or len(values) != len(set(values)):
        raise DataModelError(f"Clave vacía o duplicada en {label}.{field}.")
    return set(values)


def _decimal(value: str, label: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise DataModelError(f"Decimal inválido en {label}.") from error
    if not result.is_finite():
        raise DataModelError(f"Decimal no finito en {label}.")
    return result


def validate_dataset(public_dir: Path) -> dict[str, int]:
    """Validate exact files, keys, references, types, dates and course rules."""
    tables_dir = public_dir / "tables"
    catalogs_dir = public_dir / "catalogs"
    table_names = {p.name for p in tables_dir.glob("*.csv")}
    catalog_names = {p.name for p in catalogs_dir.glob("*.csv")}
    if table_names != set(TABLE_FIELDS) or catalog_names != set(CATALOG_FIELDS):
        raise DataModelError("El conjunto v1 está incompleto o mezcla esquemas.")
    tables = {
        name: read_csv(tables_dir / name, fields)
        for name, fields in TABLE_FIELDS.items()
    }
    catalogs = {
        name: read_csv(catalogs_dir / name, fields)
        for name, fields in CATALOG_FIELDS.items()
    }

    ids = {
        "academic": _unique(tables["Academic.csv"], "academic_id", "Academic"),
        "course": _unique(tables["Course.csv"], "course_id", "Course"),
        "employment": _unique(
            tables["academic_employment_history.csv"], "employment_id", "employment"
        ),
        "period": _unique(tables["academic_periods.csv"], "period_id", "period"),
        "offering": _unique(tables["course_offerings.csv"], "offering_id", "offering"),
        "assignment": _unique(
            tables["academic_assignments.csv"], "assignment_id", "assignment"
        ),
        "profile": _unique(catalogs["academic_profiles.csv"], "profile_id", "profile"),
        "academic_status": _unique(
            catalogs["academic_statuses.csv"], "status_id", "academic_status"
        ),
        "assignment_status": _unique(
            catalogs["assignment_statuses.csv"], "status_id", "assignment_status"
        ),
        "assignment_type": _unique(
            catalogs["assignment_types.csv"], "assignment_type_id", "assignment_type"
        ),
        "classification": _unique(
            catalogs["assignment_classifications.csv"],
            "classification_id",
            "classification",
        ),
        "policy": _unique(catalogs["workload_policies.csv"], "policy_id", "policy"),
        "level": _unique(catalogs["course_levels.csv"], "level_id", "level"),
        "demand": _unique(
            catalogs["demand_categories.csv"], "demand_category_id", "demand"
        ),
    }
    _unique(tables["Academic.csv"], "rut", "Academic")
    _unique(tables["Course.csv"], "course_code", "Course")

    def fk(
        rows: list[dict[str, str]],
        field: str,
        target: set[str],
        label: str,
        nullable: bool = False,
    ) -> None:
        if any(row[field] not in target for row in rows if row[field] or not nullable):
            raise DataModelError(f"Clave foránea inválida en {label}.{field}.")

    fk(
        tables["academic_employment_history.csv"],
        "academic_id",
        ids["academic"],
        "employment",
    )
    fk(
        tables["academic_employment_history.csv"],
        "profile_id",
        ids["profile"],
        "employment",
    )
    fk(
        tables["academic_employment_history.csv"],
        "status_id",
        ids["academic_status"],
        "employment",
    )
    fk(tables["Course.csv"], "level_id", ids["level"], "Course")
    fk(tables["course_offerings.csv"], "course_id", ids["course"], "offering")
    fk(tables["course_offerings.csv"], "period_id", ids["period"], "offering")
    assignments = tables["academic_assignments.csv"]
    for field, target in (
        ("employment_id", "employment"),
        ("period_id", "period"),
        ("assignment_type_id", "assignment_type"),
        ("classification_id", "classification"),
        ("status_id", "assignment_status"),
        ("policy_id", "policy"),
    ):
        fk(assignments, field, ids[target], "assignment")
    details = tables["course_assignments.csv"]
    fk(details, "assignment_id", ids["assignment"], "course_assignment")
    fk(details, "offering_id", ids["offering"], "course_assignment")
    fk(details, "demand_category_id", ids["demand"], "course_assignment", nullable=True)
    if len(details) != len({row["assignment_id"] for row in details}):
        raise DataModelError("Una asignación tiene más de un detalle de curso.")
    course_type_id = next(
        row["assignment_type_id"]
        for row in catalogs["assignment_types.csv"]
        if row["type_code"] == "COURSE"
    )
    detail_ids = {row["assignment_id"] for row in details}
    if any(
        row["assignment_type_id"] == course_type_id
        and row["assignment_id"] not in detail_ids
        for row in assignments
    ):
        raise DataModelError("Una asignación COURSE quedó sin detalle obligatorio.")

    for row in tables["Academic.csv"]:
        created = datetime.fromisoformat(row["created_at"])
        updated = datetime.fromisoformat(row["updated_at"])
        if (
            created.tzinfo is None
            or updated.tzinfo is None
            or updated < created
            or int(row["row_version"]) < 1
        ):
            raise DataModelError("Trazabilidad académica inválida.")
    for row in tables["academic_employment_history.csv"]:
        if not 1 <= int(row["weekly_hours"]) <= 40 or (
            row["valid_to"]
            and date.fromisoformat(row["valid_to"])
            < date.fromisoformat(row["valid_from"])
        ):
            raise DataModelError("Vigencia contractual inválida.")

    assignment_by_id = {row["assignment_id"]: row for row in assignments}
    offering_by_id = {row["offering_id"]: row for row in tables["course_offerings.csv"]}
    classification_by_id = {
        row["classification_id"]: row["classification_code"]
        for row in catalogs["assignment_classifications.csv"]
    }
    participation = Counter()
    for row in details:
        value = _decimal(row["participation_percentage"], "participación")
        if value <= 0 or value > 100:
            raise DataModelError("Participación fuera de rango.")
        participation[row["offering_id"]] += value
        assignment = assignment_by_id[row["assignment_id"]]
        if assignment["period_id"] != offering_by_id[row["offering_id"]]["period_id"]:
            raise DataModelError("Oferta y asignación pertenecen a períodos distintos.")
        code = classification_by_id[assignment["classification_id"]]
        if code == "AAA" and (
            not row["demand_category_id"] or not row["demand_basis_code"]
        ):
            raise DataModelError("AAA requiere categoría y fundamento de demanda.")
        if code != "AAA" and (row["demand_category_id"] or row["demand_basis_code"]):
            raise DataModelError("La demanda solo se aplica a AAA.")
    if any(value > 100 for value in participation.values()):
        raise DataModelError("La co-docencia supera el 100%.")

    authorization_rows = tables["assignment_authorizations.csv"]
    authorization_ids = _unique(authorization_rows, "authorization_id", "authorization")
    fk(authorization_rows, "assignment_id", ids["assignment"], "authorization")
    sequences: set[tuple[str, str]] = set()
    authorized_assignment_ids: set[str] = set()
    for row in authorization_rows:
        key = (row["assignment_id"], row["decision_sequence"])
        if key in sequences or int(row["decision_sequence"]) < 1:
            raise DataModelError("Secuencia de autorización inválida.")
        sequences.add(key)
        if row["decision_code"] not in {"AUTHORIZED", "REJECTED", "REVOKED"}:
            raise DataModelError("Código de autorización inválido.")
        if row["decision_code"] == "AUTHORIZED":
            if (
                not row["approved_points"]
                or _decimal(row["approved_points"], "approved_points") < 0
            ):
                raise DataModelError("Puntos aprobados inválidos.")
            authorized_assignment_ids.add(row["assignment_id"])
        elif row["approved_points"]:
            raise DataModelError("Una decisión no autorizada no puede aprobar puntos.")
        if not row["decided_by_actor_id"] or not row["decided_at"]:
            raise DataModelError("La autorización carece de trazabilidad.")
    status_codes = {
        row["status_id"]: row["status_code"]
        for row in catalogs["assignment_statuses.csv"]
    }
    if any(
        status_codes[row["status_id"]] == "AUTHORIZED"
        and row["assignment_id"] not in authorized_assignment_ids
        for row in assignments
    ):
        raise DataModelError("Asignación autorizada sin decisión trazable.")

    adjustments = tables["assignment_point_adjustments.csv"]
    _unique(adjustments, "adjustment_id", "adjustment")
    fk(adjustments, "assignment_id", ids["assignment"], "adjustment")
    fk(
        adjustments,
        "authorization_id",
        authorization_ids,
        "adjustment",
        nullable=True,
    )
    for row in adjustments:
        if (
            not row["reason"]
            or not row["requested_by_actor_id"]
            or not row["requested_at"]
        ):
            raise DataModelError("El ajuste carece de motivo o trazabilidad.")
        if row["status_code"] == "APPROVED" and (
            not row["authorization_id"]
            or not row["approved_delta_points"]
            or not row["decided_by_actor_id"]
            or not row["decided_at"]
        ):
            raise DataModelError("Ajuste aprobado incompleto.")
    return {
        "academics": len(tables["Academic.csv"]),
        "employments": len(tables["academic_employment_history.csv"]),
        "courses": len(tables["Course.csv"]),
        "assignments": len(assignments),
    }


def initialize_empty_dataset(target_public: Path, template_public: Path) -> None:
    """Create a complete v1 dataset for a new or isolated installation root."""
    if target_public.exists():
        validate_dataset(target_public)
        return
    shutil.copytree(template_public / "catalogs", target_public / "catalogs")
    (target_public / "tables").mkdir(parents=True)
    for name, fields in TABLE_FIELDS.items():
        _write_empty(target_public / "tables" / name, fields)
    validate_dataset(target_public)


def _write_empty(path: Path, fields: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerow(fields)
