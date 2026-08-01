"""Private display-name and pending-share state kept apart from credentials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.system_contracts import normalize_table_name
from persistence.atomic_json_repository import AtomicJsonRepository, JsonDocument
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username


@dataclass(frozen=True, slots=True)
class PendingShareIntent:
    table_number: int
    name: str
    prepared_at: str


def _validate_metadata(document: JsonDocument) -> None:
    if (
        set(document) != {"schema_version", "name"}
        or document.get("schema_version") != 1
    ):
        raise ValueError("Metadatos privados de tabla inválidos.")
    name = document.get("name")
    if name is not None and (
        not isinstance(name, str) or normalize_table_name(name) != name
    ):
        raise ValueError("Nombre privado de tabla inválido.")


def _validate_intent(document: JsonDocument) -> None:
    if (
        set(document) != {"schema_version", "pending"}
        or document.get("schema_version") != 1
    ):
        raise ValueError("Intención de compartir inválida.")
    pending = document.get("pending")
    if pending is None:
        return
    if not isinstance(pending, dict) or set(pending) != {
        "table_number",
        "name",
        "prepared_at",
    }:
        raise ValueError("Intención de compartir inválida.")
    if type(pending["table_number"]) is not int or pending["table_number"] <= 0:
        raise ValueError("Identificador de tabla pendiente inválido.")
    if (
        not isinstance(pending["name"], str)
        or normalize_table_name(pending["name"]) != pending["name"]
    ):
        raise ValueError("Nombre pendiente inválido.")
    if not isinstance(pending["prepared_at"], str) or not pending["prepared_at"]:
        raise ValueError("Fecha de preparación inválida.")


class PrivateTableMetadataRepository:
    """Persist a nullable local name plus one replaceable publication intent."""

    def __init__(
        self,
        username: str,
        *,
        paths: ProjectPaths = DEFAULT_PATHS,
    ) -> None:
        self.username = normalize_username(username)
        self.paths = paths
        self._metadata = AtomicJsonRepository(
            paths.personal_table_metadata_path(self.username),
            empty_document={"schema_version": 1, "name": None},
            validator=_validate_metadata,
            file_mode=0o600,
        )
        self._intent = AtomicJsonRepository(
            paths.personal_share_intent_path(self.username),
            empty_document={"schema_version": 1, "pending": None},
            validator=_validate_intent,
            file_mode=0o600,
        )

    def name(self) -> str | None:
        value = self._metadata.read()["name"]
        return str(value) if value is not None else None

    def save_name(self, name: str) -> str:
        clean = normalize_table_name(name)
        self._metadata.write({"schema_version": 1, "name": clean})
        return clean

    def prepare_intent(self, table_number: int, name: str) -> PendingShareIntent:
        intent = PendingShareIntent(
            table_number=table_number,
            name=normalize_table_name(name),
            prepared_at=datetime.now(UTC).isoformat(),
        )
        self._intent.write(
            {
                "schema_version": 1,
                "pending": {
                    "table_number": intent.table_number,
                    "name": intent.name,
                    "prepared_at": intent.prepared_at,
                },
            }
        )
        return intent

    def pending_intent(self) -> PendingShareIntent | None:
        value = self._intent.read()["pending"]
        if value is None:
            return None
        assert isinstance(value, dict)
        return PendingShareIntent(
            table_number=int(value["table_number"]),
            name=str(value["name"]),
            prepared_at=str(value["prepared_at"]),
        )

    def clear_intent(self) -> None:
        self._intent.write({"schema_version": 1, "pending": None})
