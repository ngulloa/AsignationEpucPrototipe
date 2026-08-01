"""Explicit v1-to-v2 migration for canonical private and indexed public tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.academic_catalog import get_academic_catalogs
from backend.academic_repository import AcademicRepositoryError
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username
from persistence.shared_table_repository import _validate_tables_document


@dataclass(frozen=True, slots=True)
class MigrationReport:
    discovered: int
    migratable: int
    already_v2: int
    incompatible: int
    migrated: int
    backup_directory: Path | None = None


@dataclass(frozen=True, slots=True)
class _DatasetPlan:
    code: str
    academic_path: Path
    appointments_path: Path
    version: int
    compatible: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _private_paths(paths: ProjectPaths) -> list[Path]:
    if not paths.users_dir.is_dir():
        return []
    result: list[Path] = []
    for directory in sorted(paths.users_dir.iterdir(), key=lambda item: item.name):
        if not directory.is_dir():
            continue
        try:
            username = normalize_username(directory.name)
        except ValueError:
            continue
        candidate = paths.personal_academics_path(username)
        if candidate.is_file():
            result.append(candidate)
    return result


def _public_paths(paths: ProjectPaths) -> list[Path]:
    if not paths.tables_index_path.is_file():
        return []
    try:
        document = json.loads(paths.tables_index_path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("schema_version") == 1:
            compatible_document = dict(document)
            compatible_document["schema_version"] = 2
            _validate_tables_document(compatible_document)
        else:
            _validate_tables_document(document)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("El índice público no pudo prevalidarse.") from error
    tables = document["tables"]
    assert isinstance(tables, list)
    return [
        paths.shared_table_path(str(item["filename"]))
        for item in tables
        if isinstance(item, dict)
        and paths.shared_table_path(str(item["filename"])).is_file()
    ]


def _discover(paths: ProjectPaths) -> list[_DatasetPlan]:
    catalogs = get_academic_catalogs(paths)
    candidates = [("private", item) for item in _private_paths(paths)] + [
        ("public", item) for item in _public_paths(paths)
    ]
    counters = {"private": 0, "public": 0}
    plans: list[_DatasetPlan] = []
    for kind, academic_path in candidates:
        counters[kind] += 1
        code = f"{kind}-{counters[kind]:04d}"
        appointments_path = paths.academic_appointments_path(academic_path)
        repository = CsvAcademicRepository(
            academic_path,
            appointments_path=appointments_path,
            catalogs=catalogs,
        )
        version: int | None = None
        try:
            version = repository.dataset_version()
            if version is None:
                continue
            if version == 1 and appointments_path.exists():
                compatible = False
            else:
                repository.list_aggregates()
                compatible = True
        except AcademicRepositoryError:
            version = version or 1
            compatible = False
        plans.append(
            _DatasetPlan(
                code,
                academic_path,
                appointments_path,
                version,
                compatible,
            )
        )
    return plans


def _write_json_atomically(path: Path, value: object) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(value, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _prepare_backups(plans: list[_DatasetPlan], backup_dir: Path) -> dict[str, str]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, object]] = []
    expected: dict[str, str] = {}
    for plan in plans:
        destination = backup_dir / f"{plan.code}.academics.csv"
        digest = _sha256(plan.academic_path)
        if destination.exists():
            if _sha256(destination) != digest:
                raise RuntimeError("Un respaldo existente no coincide con su origen.")
        else:
            shutil.copyfile(plan.academic_path, destination)
        if _sha256(destination) != digest:
            raise RuntimeError("No fue posible verificar un respaldo académico.")
        expected[plan.code] = digest
        manifest_entries.append(
            {
                "code": plan.code,
                "source": str(plan.academic_path),
                "backup": destination.name,
                "sha256": digest,
                "appointments_existed": plan.appointments_path.exists(),
            }
        )
    _write_json_atomically(
        backup_dir / "manifest.json",
        {"schema_version": 1, "datasets": manifest_entries},
    )
    return expected


def _restore_v1(plan: _DatasetPlan, backup_dir: Path, expected_hash: str) -> None:
    source = backup_dir / f"{plan.code}.academics.csv"
    if _sha256(source) != expected_hash:
        raise RuntimeError(
            "El respaldo requerido para recuperación dejó de ser válido."
        )
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=plan.academic_path.parent,
        prefix=f".{plan.academic_path.name}.",
        suffix=".restore",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(source.read_bytes())
        temporary.flush()
        os.fsync(temporary.fileno())
    os.replace(temporary_path, plan.academic_path)
    plan.appointments_path.unlink(missing_ok=True)
    if _sha256(plan.academic_path) != expected_hash:
        raise RuntimeError("La recuperación no pudo verificarse.")


def migrate_academic_datasets(
    paths: ProjectPaths = DEFAULT_PATHS,
    *,
    apply: bool = False,
    backup_dir: Path | None = None,
) -> MigrationReport:
    """Prevalidate every canonical dataset and optionally migrate compatible v1."""
    if apply and backup_dir is None:
        raise ValueError("--apply requiere un directorio de respaldo.")
    plans = _discover(paths)
    migratable = [plan for plan in plans if plan.version == 1 and plan.compatible]
    incompatible = [plan for plan in plans if not plan.compatible]
    already_v2 = [plan for plan in plans if plan.version == 2 and plan.compatible]
    if not apply:
        return MigrationReport(
            len(plans),
            len(migratable),
            len(already_v2),
            len(incompatible),
            0,
        )

    assert backup_dir is not None
    resolved_backup = backup_dir.expanduser().resolve(strict=False)
    sources = {plan.academic_path.parent for plan in plans}
    if resolved_backup in sources:
        raise ValueError("El respaldo no puede compartir la raíz de un dataset.")
    expected_hashes = (
        _prepare_backups(migratable, resolved_backup) if migratable else {}
    )
    catalogs = get_academic_catalogs(paths)
    migrated: list[_DatasetPlan] = []
    try:
        for plan in migratable:
            repository = CsvAcademicRepository(
                plan.academic_path,
                appointments_path=plan.appointments_path,
                catalogs=catalogs,
            )
            if repository.migrate_to_v2():
                migrated.append(plan)
    except (AcademicRepositoryError, OSError, RuntimeError) as error:
        for plan in reversed(migrated):
            _restore_v1(plan, resolved_backup, expected_hashes[plan.code])
        raise RuntimeError(
            "La migración falló y los datasets ya modificados fueron recuperados."
        ) from error
    return MigrationReport(
        len(plans),
        len(migratable),
        len(already_v2),
        len(incompatible),
        len(migrated),
        resolved_backup,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prevalida y migra tablas académicas canónicas de v1 a v2."
    )
    parser.add_argument("--apply", action="store_true", help="aplica la migración")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="directorio obligatorio y verificable para respaldos con --apply",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=DEFAULT_PATHS.root,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = migrate_academic_datasets(
            ProjectPaths(arguments.project_root),
            apply=arguments.apply,
            backup_dir=arguments.backup_dir,
        )
    except (RuntimeError, ValueError) as error:
        print(f"Migración detenida: {error}")
        return 1
    mode = "apply" if arguments.apply else "dry-run"
    print(
        f"Modo {mode}: descubiertos={report.discovered}, "
        f"migrables={report.migratable}, v2={report.already_v2}, "
        f"incompatibles={report.incompatible}, migrados={report.migrated}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
