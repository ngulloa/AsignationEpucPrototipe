"""Privacy and migration checks for structured shared notifications."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.composition import build_application_service
from backend.system_contracts import ErrorNotification
from persistence.atomic_json_repository import JsonPersistenceError
from persistence.error_notification_repository import (
    NOTIFICATION_FIELDS,
    JsonErrorNotificationRepository,
    NotificationMigrationRequiredError,
    migrate_legacy_notifications,
)
from persistence.paths import ProjectPaths


def _configure_owner(paths: ProjectPaths) -> None:
    paths.config_dir.mkdir(parents=True)
    paths.owner_local_path.write_text(
        json.dumps({"schema_version": 1, "username": "owner"}),
        encoding="utf-8",
    )


def test_shared_json_contains_only_allowlisted_nonpersonal_fields(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    application = build_application_service(paths=paths)
    application.register_user("owner", "1234")

    application.notify_error(
        ErrorNotification(
            source_screen="academic_form",
            category="validation",
            error_code="INVALID_RUT",
            description="El formulario rechazó un dato ficticio.",
        )
    )

    document = json.loads(paths.error_notifications_path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 3
    assert len(document["notifications"]) == 1
    record = document["notifications"][0]
    assert set(record) == NOTIFICATION_FIELDS
    serialized = json.dumps(document, ensure_ascii=False).lower()
    for forbidden in (
        "owner",
        "username",
        "detail",
        "email",
        "traceback",
        str(tmp_path).lower(),
    ):
        assert forbidden not in serialized
    assert "rut" not in record


@pytest.mark.parametrize(
    ("notification", "message"),
    (
        (
            ErrorNotification(
                "local/path", "unexpected", "OTHER_ERROR", "Falla ficticia."
            ),
            "Pantalla",
        ),
        (
            ErrorNotification("menu", "texto libre", "OTHER_ERROR", "Falla ficticia."),
            "Categoría",
        ),
        (
            ErrorNotification("menu", "unexpected", "FREE_TEXT", "Falla ficticia."),
            "Código",
        ),
        (
            ErrorNotification("menu", "validation", "OTHER_ERROR", "Falla ficticia."),
            "corresponde",
        ),
    ),
)
def test_backend_rejects_every_nonallowlisted_value(
    tmp_path: Path,
    notification: ErrorNotification,
    message: str,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    application = build_application_service(paths=paths)
    application.register_user("owner", "1234")

    with pytest.raises(ValueError, match=message):
        application.notify_error(notification)

    assert not paths.error_notifications_path.exists()


def test_repository_rejects_extra_shared_fields(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    repository = JsonErrorNotificationRepository(paths)
    invalid = {
        "schema_version": 3,
        "notifications": [
            {
                "notification_id": str(uuid4()),
                "created_at": "2026-07-31T12:00:00+00:00",
                "source_screen": "menu",
                "category": "unexpected",
                "error_code": "OTHER_ERROR",
                "status": "new",
                "description": "Descripción segura.",
                "extra": "campo no autorizado",
            }
        ],
    }

    with pytest.raises(JsonPersistenceError):
        repository._shared.write(invalid)

    assert not paths.error_notifications_path.exists()


def test_nonempty_legacy_file_requires_explicit_migration_without_changes(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    paths.public_data_dir.mkdir(parents=True)
    legacy = {
        "schema_version": 1,
        "notifications": [
            {
                "notification_id": str(uuid4()),
                "created_at": "2026-07-31T12:00:00+00:00",
                "username": "persona.real",
                "screen": "Formulario académico",
                "code": "SAVE_ERROR",
                "message": "texto libre",
                "description": "RUT 12.345.678-5",
            }
        ],
    }
    paths.error_notifications_path.write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
    )
    before = paths.error_notifications_path.read_bytes()

    with pytest.raises(NotificationMigrationRequiredError):
        JsonErrorNotificationRepository(paths).list_all()

    assert paths.error_notifications_path.read_bytes() == before


def test_legacy_migration_drops_personal_and_free_text_on_temporary_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "notifications_error.json"
    legacy_id = str(uuid4())
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "notifications": [
                    {
                        "notification_id": legacy_id,
                        "created_at": "2026-07-31T12:00:00+00:00",
                        "username": "persona.real",
                        "screen": "Formulario académico",
                        "code": "SAVE_ERROR",
                        "message": "texto libre",
                        "description": "correo@example.invalid",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert migrate_legacy_notifications(path) == 1

    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated == {
        "schema_version": 3,
        "notifications": [
            {
                "notification_id": legacy_id,
                "created_at": "2026-07-31T12:00:00+00:00",
                "source_screen": "academic_form",
                "category": "persistence",
                "error_code": "SAVE_ERROR",
                "status": "new",
                "description": (
                    "Descripción histórica omitida durante la migración por privacidad."
                ),
            }
        ],
    }
