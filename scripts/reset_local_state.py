"""Safely reset allowlisted local and public runtime state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from persistence.approval_repository import (
    APPROVAL_SCHEMA_VERSION,
    _validate_approval_document,
)
from persistence.atomic_json_repository import atomic_write_json
from persistence.error_notification_repository import (
    NOTIFICATION_SCHEMA_VERSION,
    _validate_shared_document,
)
from persistence.paths import DEFAULT_PATHS, ProjectPaths
from persistence.shared_table_repository import (
    TABLES_SCHEMA_VERSION,
    _validate_tables_document,
)

_EMPTY_DOCUMENTS = (
    (
        "aprobaciones públicas",
        "approved_users_path",
        {"schema_version": APPROVAL_SCHEMA_VERSION, "approved_users": []},
        _validate_approval_document,
    ),
    (
        "índice de tablas públicas",
        "tables_index_path",
        {"schema_version": TABLES_SCHEMA_VERSION, "tables": []},
        _validate_tables_document,
    ),
    (
        "notificaciones públicas",
        "error_notifications_path",
        {"schema_version": NOTIFICATION_SCHEMA_VERSION, "notifications": []},
        _validate_shared_document,
    ),
)


@dataclass(frozen=True, slots=True)
class ResetItem:
    """One allowlisted state mutation, without exposing file contents."""

    category: str
    path: Path
    action: str
    empty_document: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ResetReport:
    """Summary suitable for CLI reporting and automated verification."""

    apply: bool
    planned: tuple[ResetItem, ...]
    changed: int
    backup_directory: Path | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_safe_repo_path(paths: ProjectPaths, candidate: Path) -> Path:
    root = paths.root
    lexical = Path(os.path.abspath(candidate))
    try:
        relative = lexical.relative_to(root)
    except ValueError as error:
        raise ValueError(
            "La lista blanca contiene una ruta externa al proyecto."
        ) from error

    current = root
    for component in relative.parts:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("La lista blanca contiene un enlace simbólico inseguro.")

    try:
        lexical.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise ValueError("La lista blanca resuelve fuera del proyecto.") from error
    return lexical


def _safe_files_in_tree(paths: ProjectPaths, directory: Path) -> list[Path]:
    directory = _assert_safe_repo_path(paths, directory)
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ValueError("Una ruta de datos esperada no es un directorio.")
    files: list[Path] = []
    pending = [directory]
    while pending:
        current = pending.pop()
        for entry in os.scandir(current):
            entry_path = Path(entry.path)
            if entry.is_symlink():
                raise ValueError("Los datos contienen un enlace simbólico inseguro.")
            if entry.is_dir(follow_symlinks=False):
                pending.append(entry_path)
            elif entry.is_file(follow_symlinks=False):
                files.append(_assert_safe_repo_path(paths, entry_path))
            else:
                raise ValueError("Los datos contienen un tipo de archivo no soportado.")
    return sorted(files)


def _json_requires_reset(path: Path, empty_document: dict[str, object]) -> bool:
    if not path.exists():
        return True
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return True
    return parsed != empty_document


def build_reset_plan(paths: ProjectPaths = DEFAULT_PATHS) -> tuple[ResetItem, ...]:
    """Build the fixed whitelist and include only state that needs a mutation."""
    candidates: list[ResetItem] = []

    users_dir = _assert_safe_repo_path(paths, paths.users_dir)
    if users_dir.exists():
        _safe_files_in_tree(paths, users_dir)
        if next(users_dir.iterdir(), None) is not None:
            candidates.append(
                ResetItem("estado privado de usuarios", users_dir, "clear")
            )

    owner_local = _assert_safe_repo_path(paths, paths.owner_local_path)
    if owner_local.exists():
        if not owner_local.is_file():
            raise ValueError("La configuración local no es un archivo regular.")
        candidates.append(
            ResetItem("configuración local del propietario", owner_local, "remove")
        )

    public_tables = _assert_safe_repo_path(paths, paths.public_tables_dir)
    if public_tables.exists():
        _safe_files_in_tree(paths, public_tables)
        if next(public_tables.iterdir(), None) is not None:
            candidates.append(ResetItem("tablas públicas", public_tables, "clear"))

    for category, attribute, empty_document, validator in _EMPTY_DOCUMENTS:
        validator(dict(empty_document))
        path = _assert_safe_repo_path(paths, getattr(paths, attribute))
        if _json_requires_reset(path, empty_document):
            candidates.append(ResetItem(category, path, "reset_json", empty_document))

    return tuple(candidates)


def _backup_sources(
    paths: ProjectPaths, plan: tuple[ResetItem, ...]
) -> list[tuple[ResetItem, Path]]:
    sources: list[tuple[ResetItem, Path]] = []
    for item in plan:
        if item.action == "clear":
            sources.extend(
                (item, path) for path in _safe_files_in_tree(paths, item.path)
            )
        elif item.path.exists():
            sources.append((item, _assert_safe_repo_path(paths, item.path)))
    return sources


def _copy_backup_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with (
            source.open("rb") as input_stream,
            tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as output_stream,
        ):
            temporary = Path(output_stream.name)
            for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _prepare_backup(
    paths: ProjectPaths,
    plan: tuple[ResetItem, ...],
    backup_directory: Path,
) -> Path:
    resolved = backup_directory.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(paths.root)
    except ValueError:
        pass
    else:
        raise ValueError("El respaldo debe estar fuera del repositorio.")
    if resolved.exists() and resolved.is_symlink():
        raise ValueError("El directorio de respaldo no puede ser un enlace simbólico.")
    manifest_path = resolved / "manifest.json"
    if manifest_path.exists():
        raise ValueError("El directorio de respaldo ya contiene un manifiesto.")

    sources = _backup_sources(paths, plan)
    entries: list[dict[str, object]] = []
    resolved.mkdir(parents=True, exist_ok=True)
    for item, source in sources:
        relative = source.relative_to(paths.root)
        destination = resolved / "payload" / relative
        _copy_backup_file(source, destination)
        source_hash = _sha256(source)
        if _sha256(destination) != source_hash:
            raise RuntimeError("La copia de respaldo no coincide con su origen.")
        entries.append(
            {
                "category": item.category,
                "path": relative.as_posix(),
                "size": source.stat().st_size,
                "sha256": source_hash,
            }
        )

    manifest: dict[str, object] = {"schema_version": 1, "files": entries}
    atomic_write_json(manifest_path, manifest, file_mode=0o600)
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    if loaded != manifest:
        raise RuntimeError("El manifiesto del respaldo no pudo validarse.")
    for entry in entries:
        relative = Path(str(entry["path"]))
        if _sha256(resolved / "payload" / relative) != entry["sha256"]:
            raise RuntimeError("El respaldo dejó de ser válido antes de limpiar.")
    return resolved


def _clear_tree(paths: ProjectPaths, directory: Path) -> None:
    directory = _assert_safe_repo_path(paths, directory)
    files: list[Path] = []
    directories: list[Path] = []
    pending = [directory]
    while pending:
        current = pending.pop()
        for entry in os.scandir(current):
            path = Path(entry.path)
            if entry.is_symlink():
                raise ValueError("Los datos contienen un enlace simbólico inseguro.")
            if entry.is_dir(follow_symlinks=False):
                safe_directory = _assert_safe_repo_path(paths, path)
                directories.append(safe_directory)
                pending.append(safe_directory)
            elif entry.is_file(follow_symlinks=False):
                files.append(_assert_safe_repo_path(paths, path))
            else:
                raise ValueError("Los datos contienen un tipo de archivo no soportado.")
    for path in files:
        path.unlink()
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        path.rmdir()


def reset_local_state(
    paths: ProjectPaths = DEFAULT_PATHS,
    *,
    apply: bool = False,
    backup_directory: Path | None = None,
) -> ResetReport:
    """Plan or apply the allowlisted reset after a verified external backup."""
    plan = build_reset_plan(paths)
    if not apply:
        return ResetReport(False, plan, 0, None)
    if not plan:
        return ResetReport(True, plan, 0, None)
    if backup_directory is None:
        raise ValueError("--apply requiere --backup-dir cuando hay datos o estado.")

    backup = _prepare_backup(paths, plan, backup_directory)
    for item in plan:
        if item.action == "clear":
            _clear_tree(paths, item.path)
        elif item.action == "remove":
            _assert_safe_repo_path(paths, item.path).unlink()
        elif item.action == "reset_json":
            assert item.empty_document is not None
            atomic_write_json(item.path, item.empty_document)
        else:  # pragma: no cover - ResetItem is private and fixed above.
            raise RuntimeError("Acción de reinicio desconocida.")
    return ResetReport(True, plan, len(plan), backup)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Previsualiza o reinicia únicamente el estado local autorizado."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="previsualiza el reinicio (modo predeterminado)",
    )
    mode.add_argument("--apply", action="store_true", help="aplica el reinicio")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        help="respaldo externo obligatorio cuando --apply tiene cambios",
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
    paths = ProjectPaths(arguments.project_root)
    try:
        report = reset_local_state(
            paths,
            apply=arguments.apply,
            backup_directory=arguments.backup_dir,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Reinicio detenido: {error}")
        return 1

    mode = "apply" if report.apply else "dry-run"
    print(f"Modo {mode}: cambios planificados={len(report.planned)}.")
    for item in report.planned:
        print(f"- {item.category}: {item.path}")
    if report.backup_directory is not None:
        print(f"Respaldo verificado: {report.backup_directory}")
    print(f"Cambios aplicados={report.changed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
