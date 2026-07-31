"""Shared approval registry and local owner configuration repositories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

from persistence.atomic_json_repository import AtomicJsonRepository, JsonDocument
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username


@dataclass(frozen=True, slots=True)
class ApprovalEntry:
    request_id: str
    username: str
    status: str
    requested_at: str
    approved_at: str | None = None
    approved_by: str | None = None


class OwnerConfigurationError(RuntimeError):
    """The required local owner setting is missing or malformed."""


def _validate_approval_document(document: JsonDocument) -> None:
    if document.get("schema_version") != 1:
        raise ValueError("Versión de aprobaciones no soportada.")
    entries = document.get("approved_users")
    if not isinstance(entries, list):
        raise ValueError("La lista de aprobaciones es inválida.")
    seen_usernames: set[str] = set()
    seen_requests: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Una aprobación no es un objeto.")
        request_id = entry.get("request_id")
        username = entry.get("username")
        status = entry.get("status")
        requested_at = entry.get("requested_at")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("Identificador de aprobación inválido.")
        if not isinstance(username, str) or normalize_username(username) != username:
            raise ValueError("Usuario de aprobación inválido.")
        if status not in {"pending", "approved"}:
            raise ValueError("Estado de aprobación inválido.")
        if not isinstance(requested_at, str) or not requested_at:
            raise ValueError("Fecha de solicitud inválida.")
        approved_at = entry.get("approved_at")
        approved_by = entry.get("approved_by")
        if approved_at is not None and not isinstance(approved_at, str):
            raise ValueError("Fecha de aprobación inválida.")
        if approved_by is not None:
            if not isinstance(approved_by, str):
                raise ValueError("Aprobador inválido.")
            normalize_username(approved_by)
        if username in seen_usernames or request_id in seen_requests:
            raise ValueError("Aprobación duplicada.")
        seen_usernames.add(username)
        seen_requests.add(request_id)


class JsonApprovalRepository:
    """Atomically maintain pending and granted shared approval entries."""

    def __init__(self, paths: ProjectPaths = DEFAULT_PATHS) -> None:
        self.paths = paths
        self._store = AtomicJsonRepository(
            paths.approved_users_path,
            empty_document={"schema_version": 1, "approved_users": []},
            validator=_validate_approval_document,
            recover_corrupt=True,
        )

    @property
    def last_recovery_path(self) -> Path | None:
        return self._store.last_recovery_path

    def list_all(self) -> list[ApprovalEntry]:
        document = self._store.read()
        values = document["approved_users"]
        assert isinstance(values, list)
        return [self._entry(value) for value in values]

    def find_username(self, username: str) -> ApprovalEntry | None:
        canonical = normalize_username(username)
        return next(
            (entry for entry in self.list_all() if entry.username == canonical), None
        )

    def find_request(self, request_id: str) -> ApprovalEntry | None:
        return next(
            (entry for entry in self.list_all() if entry.request_id == request_id),
            None,
        )

    def save(self, entry: ApprovalEntry) -> None:
        entries = self.list_all()
        replaced = False
        for index, existing in enumerate(entries):
            if existing.username == entry.username:
                entries[index] = entry
                replaced = True
                break
        if not replaced:
            entries.append(entry)
        self._store.write(
            {
                "schema_version": 1,
                "approved_users": [self._document(item) for item in entries],
            }
        )

    @staticmethod
    def _entry(value: object) -> ApprovalEntry:
        assert isinstance(value, dict)
        return ApprovalEntry(
            request_id=str(value["request_id"]),
            username=str(value["username"]),
            status=str(value["status"]),
            requested_at=str(value["requested_at"]),
            approved_at=(
                str(value["approved_at"])
                if value.get("approved_at") is not None
                else None
            ),
            approved_by=(
                str(value["approved_by"])
                if value.get("approved_by") is not None
                else None
            ),
        )

    @staticmethod
    def _document(entry: ApprovalEntry) -> JsonDocument:
        return {
            "request_id": entry.request_id,
            "username": entry.username,
            "status": entry.status,
            "requested_at": entry.requested_at,
            "approved_at": entry.approved_at,
            "approved_by": entry.approved_by,
        }


def load_owner_username(paths: ProjectPaths = DEFAULT_PATHS) -> str:
    """Load the private owner setting without creating or modifying it."""
    path = paths.owner_local_path
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise OwnerConfigurationError(
            "Configure el propietario en config/owner.local.json."
        ) from error
    except (OSError, UnicodeError, JSONDecodeError) as error:
        raise OwnerConfigurationError(
            "La configuración local del propietario no es válida."
        ) from error
    if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
        raise OwnerConfigurationError(
            "La configuración local del propietario no es válida."
        )
    username = parsed.get("username")
    if not isinstance(username, str):
        raise OwnerConfigurationError(
            "La configuración local del propietario no contiene un usuario."
        )
    try:
        return normalize_username(username)
    except ValueError as error:
        raise OwnerConfigurationError(
            "El usuario propietario configurado no es seguro."
        ) from error
