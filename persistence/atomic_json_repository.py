"""Validated JSON documents with durable, atomic replacement and recovery."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any
from uuid import uuid4

JsonDocument = dict[str, Any]
DocumentValidator = Callable[[JsonDocument], None]


class JsonPersistenceError(RuntimeError):
    """Base class for controlled JSON persistence failures."""


class JsonDocumentCorruptError(JsonPersistenceError):
    """A JSON document was unreadable or failed its schema validation."""

    def __init__(self, path: Path, recovery_path: Path | None = None) -> None:
        self.path = path
        self.recovery_path = recovery_path
        super().__init__("El archivo de datos local está dañado y no puede usarse.")


class JsonDocumentIOError(JsonPersistenceError):
    """An operating-system error prevented a JSON operation."""


def _recovery_path(path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return path.with_name(f"{path.name}.corrupt.{timestamp}.{uuid4().hex}")


def atomic_write_json(
    path: str | os.PathLike[str],
    document: JsonDocument,
    *,
    file_mode: int | None = None,
) -> None:
    """Write one UTF-8 JSON object through a same-directory temporary file."""
    destination = Path(path).expanduser().resolve(strict=False)
    temporary_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(
                document,
                temporary_file,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        if file_mode is not None:
            os.chmod(temporary_path, file_mode)
        os.replace(temporary_path, destination)
        temporary_path = None
        if file_mode is not None:
            os.chmod(destination, file_mode)
        _fsync_directory(destination.parent)
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise JsonDocumentIOError(
            "No fue posible guardar los datos JSON de forma atómica."
        ) from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def create_migration_backup(
    source: Path,
    backup_directory: Path,
    *,
    filename: str,
) -> Path:
    """Create one exact, durable backup without overwriting an earlier copy."""
    source = source.expanduser().resolve(strict=True)
    directory = backup_directory.expanduser().resolve(strict=False)
    backup = directory / filename
    if backup.exists():
        try:
            if backup.read_bytes() == source.read_bytes():
                return backup
        except OSError as error:
            raise JsonDocumentIOError(
                "No fue posible comprobar el respaldo de migración."
            ) from error
        raise JsonDocumentIOError("Existe un respaldo distinto para esta migración.")
    temporary: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        payload = source.read_bytes()
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=directory,
            prefix=f".{backup.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, backup)
        temporary = None
        _fsync_directory(directory)
    except OSError as error:
        raise JsonDocumentIOError(
            "No fue posible crear el respaldo de migración."
        ) from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return backup


def restore_migration_backup(backup: Path, destination: Path) -> None:
    """Atomically restore an exact backup while retaining the backup itself."""
    resolved_backup = backup.expanduser().resolve(strict=True)
    target = destination.expanduser().resolve(strict=False)
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.rollback.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(resolved_backup.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
        _fsync_directory(target.parent)
    except OSError as error:
        raise JsonDocumentIOError("No fue posible restaurar el respaldo.") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory sync; unsupported platforms safely skip it."""
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def quarantine_corrupt_json(path: str | os.PathLike[str]) -> Path:
    """Move an invalid document aside without exposing its contents."""
    source = Path(path).expanduser().resolve(strict=False)
    recovery = _recovery_path(source)
    try:
        os.replace(source, recovery)
        _fsync_directory(source.parent)
    except OSError as error:
        raise JsonDocumentIOError(
            "No fue posible aislar el archivo de datos dañado."
        ) from error
    return recovery


class AtomicJsonRepository:
    """Manage one JSON object with explicit schema and recovery policy."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        empty_document: JsonDocument,
        validator: DocumentValidator,
        recover_corrupt: bool = True,
        file_mode: int | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self._empty_document = copy.deepcopy(empty_document)
        self._validator = validator
        self._recover_corrupt = recover_corrupt
        self._file_mode = file_mode
        self.last_recovery_path: Path | None = None
        self._validator(copy.deepcopy(self._empty_document))

    def read(self) -> JsonDocument:
        """Read a validated object, creating or recovering it as configured."""
        if not self.path.exists():
            document = copy.deepcopy(self._empty_document)
            self.write(document)
            return document
        try:
            content = self.path.read_text(encoding="utf-8")
            parsed: object = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("Se esperaba un objeto JSON.")
            self._validator(parsed)
            return parsed
        except (
            JSONDecodeError,
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
        ) as error:
            recovery = quarantine_corrupt_json(self.path)
            self.last_recovery_path = recovery
            if self._recover_corrupt:
                document = copy.deepcopy(self._empty_document)
                self.write(document)
                return document
            raise JsonDocumentCorruptError(self.path, recovery) from error
        except OSError as error:
            raise JsonDocumentIOError("No fue posible leer los datos JSON.") from error

    def write(self, document: JsonDocument) -> None:
        """Validate before atomically replacing the stored document."""
        try:
            self._validator(document)
        except (ValueError, TypeError, KeyError) as error:
            raise JsonPersistenceError(
                "El documento JSON no cumple el esquema requerido."
            ) from error
        atomic_write_json(self.path, document, file_mode=self._file_mode)
