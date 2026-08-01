"""Strictly allowlisted shared notifications and personal delivery outboxes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from uuid import UUID

from backend.system_contracts import validate_notification_description
from persistence.atomic_json_repository import (
    AtomicJsonRepository,
    JsonDocument,
    atomic_write_json,
    create_migration_backup,
    restore_migration_backup,
)
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username

NOTIFICATION_SCHEMA_VERSION = 3
SEEN_SCHEMA_VERSION = 1
HISTORICAL_DESCRIPTION = (
    "Descripción histórica omitida durante la migración por privacidad."
)
NOTIFICATION_FIELDS = frozenset(
    {
        "notification_id",
        "created_at",
        "source_screen",
        "category",
        "error_code",
        "status",
        "description",
    }
)
QUEUE_FIELDS = NOTIFICATION_FIELDS | {"delivered"}
ALLOWED_SOURCE_SCREENS = frozenset(
    {
        "login",
        "register",
        "menu",
        "academic_list",
        "academic_form",
        "approval",
        "error_notification",
        "update",
        "alerts",
    }
)
ERROR_CATEGORY_BY_CODE = {
    "SAVE_ERROR": "persistence",
    "DUPLICATE_RUT": "validation",
    "INVALID_RUT": "validation",
    "AUTH_ERROR": "authentication",
    "UPDATE_ERROR": "synchronization",
    "ACCESS_DENIED": "authorization",
    "OTHER_ERROR": "unexpected",
}
ALLOWED_ERROR_CODES = frozenset(ERROR_CATEGORY_BY_CODE)
ALLOWED_CATEGORIES = frozenset(ERROR_CATEGORY_BY_CODE.values())
ALLOWED_STATUSES = frozenset({"new", "seen"})


class NotificationMigrationRequiredError(RuntimeError):
    """A non-empty legacy register must be migrated explicitly."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            "El registro de notificaciones contiene datos legados y requiere "
            "migración explícita antes de continuar."
        )


@dataclass(frozen=True, slots=True)
class StoredErrorNotification:
    notification_id: str
    created_at: str
    source_screen: str
    category: str
    error_code: str
    status: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "description",
            validate_notification_description(self.description),
        )


def _validate_utc_timestamp(value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("Fecha UTC inválida.")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Fecha UTC inválida.") from error
    if timestamp.utcoffset() != UTC.utcoffset(timestamp):
        raise ValueError("La fecha debe estar expresada en UTC.")


def _validate_notification(item: object, *, allow_delivery: bool) -> None:
    if not isinstance(item, dict):
        raise ValueError("Una notificación no es un objeto.")
    expected_fields = QUEUE_FIELDS if allow_delivery else NOTIFICATION_FIELDS
    if set(item) != expected_fields:
        raise ValueError("La notificación contiene campos no autorizados.")
    try:
        UUID(str(item["notification_id"]))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Identificador de notificación inválido.") from error
    _validate_utc_timestamp(item["created_at"])
    if item["source_screen"] not in ALLOWED_SOURCE_SCREENS:
        raise ValueError("Pantalla de origen no autorizada.")
    if item["category"] not in ALLOWED_CATEGORIES:
        raise ValueError("Categoría de notificación no autorizada.")
    if item["error_code"] not in ALLOWED_ERROR_CODES:
        raise ValueError("Código de error no autorizado.")
    if ERROR_CATEGORY_BY_CODE[str(item["error_code"])] != item["category"]:
        raise ValueError("Categoría y código de error incompatibles.")
    if item["status"] not in ALLOWED_STATUSES:
        raise ValueError("Estado de notificación no autorizado.")
    validate_notification_description(item["description"])
    if allow_delivery and type(item["delivered"]) is not bool:
        raise ValueError("Estado de entrega inválido.")


def _validate_shared_document(document: JsonDocument) -> None:
    if set(document) != {"schema_version", "notifications"}:
        raise ValueError("Registro de notificaciones inválido.")
    if document.get("schema_version") != NOTIFICATION_SCHEMA_VERSION:
        raise ValueError("Versión de notificaciones no soportada.")
    notifications = document.get("notifications")
    if not isinstance(notifications, list):
        raise ValueError("Registro de notificaciones inválido.")
    identifiers: set[str] = set()
    for item in notifications:
        _validate_notification(item, allow_delivery=False)
        assert isinstance(item, dict)
        identifier = str(item["notification_id"])
        if identifier in identifiers:
            raise ValueError("Notificación duplicada.")
        identifiers.add(identifier)


def _validate_queue_document(document: JsonDocument) -> None:
    if set(document) != {"schema_version", "queue"}:
        raise ValueError("Cola de notificaciones inválida.")
    if document.get("schema_version") != NOTIFICATION_SCHEMA_VERSION:
        raise ValueError("Versión de cola no soportada.")
    queue = document.get("queue")
    if not isinstance(queue, list):
        raise ValueError("Cola de notificaciones inválida.")
    for item in queue:
        _validate_notification(item, allow_delivery=True)


def _validate_seen_document(document: JsonDocument) -> None:
    if document.get("schema_version") != SEEN_SCHEMA_VERSION:
        raise ValueError("Versión del estado visto no soportada.")
    if set(document) != {"schema_version", "seen_notification_ids"}:
        raise ValueError("Estado visto inválido.")
    seen = document.get("seen_notification_ids")
    if not isinstance(seen, list) or not all(
        isinstance(value, str) and value for value in seen
    ):
        raise ValueError("Estado visto inválido.")
    if len(seen) != len(set(seen)):
        raise ValueError("Estado visto duplicado.")


def _read_document_without_recovery(path: Path) -> JsonDocument | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _legacy_screen(value: object) -> str:
    mapping = {
        "Iniciar sesión": "login",
        "Registro de usuario": "register",
        "Sistema de asignación de carga académica": "menu",
        "Académicos": "academic_list",
        "Agregar académico": "academic_form",
        "Formulario académico": "academic_form",
        "Administración de aprobaciones": "approval",
        "Notificar error": "error_notification",
        "Actualizar aplicación": "update",
        "Alertas del propietario": "alerts",
    }
    return mapping.get(str(value), "error_notification")


def _migrated_notification(item: object, *, legacy_v1: bool) -> JsonDocument:
    if not isinstance(item, dict):
        raise ValueError("El registro legado es inválido.")
    code_key = "code" if legacy_v1 else "error_code"
    code = str(item.get(code_key, "OTHER_ERROR"))
    if code not in ALLOWED_ERROR_CODES:
        code = "OTHER_ERROR"
    source = (
        _legacy_screen(item.get("screen"))
        if legacy_v1
        else str(item.get("source_screen", "error_notification"))
    )
    if source not in ALLOWED_SOURCE_SCREENS:
        source = "error_notification"
    status = str(item.get("status", "new"))
    if status not in ALLOWED_STATUSES:
        status = "new"
    return {
        "notification_id": str(item.get("notification_id", "")),
        "created_at": str(item.get("created_at", "")),
        "source_screen": source,
        "category": ERROR_CATEGORY_BY_CODE[code],
        "error_code": code,
        "status": status,
        "description": HISTORICAL_DESCRIPTION,
    }


def migrate_notifications(
    path: Path,
    *,
    backup_directory: Path,
) -> tuple[int, Path | None]:
    """Migrate a v1/v2 shared register or private queue to validated v3."""
    document = _read_document_without_recovery(path)
    if document is None:
        raise ValueError("El archivo no contiene un registro legado válido.")
    version = document.get("schema_version")
    if version == NOTIFICATION_SCHEMA_VERSION:
        if "notifications" in document:
            _validate_shared_document(document)
        elif "queue" in document:
            _validate_queue_document(document)
        else:
            raise ValueError("El registro de notificaciones es inválido.")
        return 0, None
    if version not in {1, 2}:
        raise ValueError("El archivo no contiene un registro legado válido.")
    collection_name = "notifications" if "notifications" in document else "queue"
    legacy = document.get(collection_name)
    if not isinstance(legacy, list):
        raise ValueError("El registro legado es inválido.")
    migrated: list[JsonDocument] = []
    for item in legacy:
        migrated_item = _migrated_notification(item, legacy_v1=version == 1)
        if collection_name == "queue":
            assert isinstance(item, dict)
            migrated_item["delivered"] = bool(item.get("delivered", False))
        migrated.append(migrated_item)
    result: JsonDocument = {
        "schema_version": NOTIFICATION_SCHEMA_VERSION,
        collection_name: migrated,
    }
    validator = (
        _validate_shared_document
        if collection_name == "notifications"
        else _validate_queue_document
    )
    validator(result)
    backup = create_migration_backup(
        path,
        backup_directory,
        filename=f"{path.name}.v{version}-to-v3.backup.json",
    )
    try:
        atomic_write_json(path, result)
        validated = _read_document_without_recovery(path)
        if validated is None:
            raise ValueError("No fue posible validar el resultado de la migración.")
        validator(validated)
    except Exception:
        restore_migration_backup(backup, path)
        raise
    return len(migrated), backup


def migrate_legacy_notifications(
    path: Path,
    *,
    backup_directory: Path | None = None,
) -> int:
    """Compatibility wrapper for the backed v1/v2-to-v3 migration."""
    migrated, _backup = migrate_notifications(
        path,
        backup_directory=backup_directory or path.parent / ".migration-backups",
    )
    return migrated


class JsonErrorNotificationRepository:
    """Persist only the exact structured schema in shared and local stores."""

    def __init__(self, paths: ProjectPaths = DEFAULT_PATHS) -> None:
        self.paths = paths
        self._shared = AtomicJsonRepository(
            paths.error_notifications_path,
            empty_document={
                "schema_version": NOTIFICATION_SCHEMA_VERSION,
                "notifications": [],
            },
            validator=_validate_shared_document,
            recover_corrupt=True,
        )

    def _prepare_shared_schema(self) -> None:
        document = _read_document_without_recovery(self.paths.error_notifications_path)
        if (
            document is None
            or document.get("schema_version") == NOTIFICATION_SCHEMA_VERSION
        ):
            return
        if document.get("schema_version") in {1, 2}:
            raise NotificationMigrationRequiredError(
                self.paths.error_notifications_path
            )

    def enqueue_and_record(
        self,
        username: str,
        notification: StoredErrorNotification,
    ) -> None:
        self._prepare_shared_schema()
        canonical_username = normalize_username(username)
        document = self._to_document(notification)
        _validate_notification(document, allow_delivery=False)
        queue_store = self._queue_store(canonical_username)
        queue_document = queue_store.read()
        queue = queue_document["queue"]
        assert isinstance(queue, list)
        queued = dict(document)
        queued["delivered"] = False
        queue.append(queued)
        queue_store.write(
            {"schema_version": NOTIFICATION_SCHEMA_VERSION, "queue": queue}
        )

        shared_document = self._shared.read()
        shared = shared_document["notifications"]
        assert isinstance(shared, list)
        if not any(
            isinstance(item, dict)
            and item.get("notification_id") == notification.notification_id
            for item in shared
        ):
            shared.append(document)
            self._shared.write(
                {
                    "schema_version": NOTIFICATION_SCHEMA_VERSION,
                    "notifications": shared,
                }
            )
        queued["delivered"] = True
        queue_store.write(
            {"schema_version": NOTIFICATION_SCHEMA_VERSION, "queue": queue}
        )

    def list_all(self) -> list[StoredErrorNotification]:
        self._prepare_shared_schema()
        document = self._shared.read()
        values = document["notifications"]
        assert isinstance(values, list)
        return [self._from_document(item) for item in values]

    def list_local_queue(self, username: str) -> list[JsonDocument]:
        document = self._queue_store(normalize_username(username)).read()
        values = document["queue"]
        assert isinstance(values, list)
        return [dict(item) for item in values if isinstance(item, dict)]

    def flush_pending(self, username: str) -> int:
        self._prepare_shared_schema()
        queue_store = self._queue_store(normalize_username(username))
        queue_document = queue_store.read()
        queue = queue_document["queue"]
        assert isinstance(queue, list)
        pending = [
            item
            for item in queue
            if isinstance(item, dict) and item.get("delivered") is False
        ]
        if not pending:
            return 0
        shared_document = self._shared.read()
        shared = shared_document["notifications"]
        assert isinstance(shared, list)
        identifiers = {
            str(item["notification_id"])
            for item in shared
            if isinstance(item, dict) and "notification_id" in item
        }
        for item in pending:
            identifier = str(item["notification_id"])
            if identifier not in identifiers:
                shared.append(
                    {key: value for key, value in item.items() if key != "delivered"}
                )
                identifiers.add(identifier)
            item["delivered"] = True
        self._shared.write(
            {
                "schema_version": NOTIFICATION_SCHEMA_VERSION,
                "notifications": shared,
            }
        )
        queue_store.write(
            {"schema_version": NOTIFICATION_SCHEMA_VERSION, "queue": queue}
        )
        return len(pending)

    def mark_seen(self, owner_username: str, notification_id: str) -> None:
        self._prepare_shared_schema()
        document = self._shared.read()
        notifications = document["notifications"]
        assert isinstance(notifications, list)
        matching = next(
            (
                item
                for item in notifications
                if isinstance(item, dict)
                and item.get("notification_id") == notification_id
            ),
            None,
        )
        if matching is None:
            raise KeyError("La notificación no existe.")
        matching["status"] = "seen"
        self._shared.write(
            {
                "schema_version": NOTIFICATION_SCHEMA_VERSION,
                "notifications": notifications,
            }
        )
        store = self._seen_store(normalize_username(owner_username))
        seen_document = store.read()
        values = seen_document["seen_notification_ids"]
        assert isinstance(values, list)
        if notification_id not in values:
            values.append(notification_id)
            store.write(
                {
                    "schema_version": SEEN_SCHEMA_VERSION,
                    "seen_notification_ids": values,
                }
            )

    def seen_ids(self, owner_username: str) -> set[str]:
        document = self._seen_store(normalize_username(owner_username)).read()
        values = document["seen_notification_ids"]
        assert isinstance(values, list)
        return set(values)

    def _queue_store(self, username: str) -> AtomicJsonRepository:
        return AtomicJsonRepository(
            self.paths.personal_error_queue_path(username),
            empty_document={
                "schema_version": NOTIFICATION_SCHEMA_VERSION,
                "queue": [],
            },
            validator=_validate_queue_document,
            recover_corrupt=True,
            file_mode=0o600,
        )

    def _seen_store(self, username: str) -> AtomicJsonRepository:
        return AtomicJsonRepository(
            self.paths.notifications_seen_path(username),
            empty_document={
                "schema_version": SEEN_SCHEMA_VERSION,
                "seen_notification_ids": [],
            },
            validator=_validate_seen_document,
            recover_corrupt=True,
            file_mode=0o600,
        )

    @staticmethod
    def _to_document(notification: StoredErrorNotification) -> JsonDocument:
        return asdict(notification)

    @staticmethod
    def _from_document(value: object) -> StoredErrorNotification:
        assert isinstance(value, dict)
        return StoredErrorNotification(
            notification_id=str(value["notification_id"]),
            created_at=str(value["created_at"]),
            source_screen=str(value["source_screen"]),
            category=str(value["category"]),
            error_code=str(value["error_code"]),
            status=str(value["status"]),
            description=str(value["description"]),
        )
