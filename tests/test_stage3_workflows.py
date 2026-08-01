"""Stage-three privacy, lifecycle, naming and workflow boundaries."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from backend.approval import ApprovalError, AuthorizationError
from backend.composition import build_application_service
from backend.contracts import AcademicFormData
from backend.system_contracts import (
    DESCRIPTION_PRIVACY_WARNING,
    ErrorNotification,
    TablePublication,
    normalize_notification_description,
    normalize_table_name,
    table_name_key,
    validate_notification_description,
)
from frontend.contracts import ApprovalItem
from frontend.controller import FakeFrontendController
from frontend.frontend_main import build_frontend_window
from persistence.approval_repository import migrate_approvals
from persistence.error_notification_repository import (
    HISTORICAL_DESCRIPTION,
    migrate_notifications,
)
from persistence.paths import ProjectPaths
from persistence.private_table_metadata_repository import (
    PrivateTableMetadataRepository,
)
from persistence.settings_repository import load_application_settings
from persistence.shared_table_repository import migrate_tables_index


class RecordingGit:
    def __init__(self) -> None:
        self.update_calls = 0
        self.publications: list[tuple[str, str, tuple[Path, ...]]] = []

    def run_update(self):
        from backend.system_contracts import UpdateResult

        self.update_calls += 1
        return UpdateResult(False, "Sin cambios remotos ficticios.")

    def pending_summary(self) -> str:
        return "Resumen ficticio."

    def publish_changes(self, *, name: str, username: str, paths: tuple[Path, ...]):
        from backend.system_contracts import UpdateResult

        self.publications.append((name, username, paths))
        return UpdateResult(True, "Publicación ficticia.")


def _configure_owner(paths: ProjectPaths, username: str = "owner") -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.owner_local_path.write_text(
        json.dumps({"schema_version": 1, "username": username}),
        encoding="utf-8",
    )


def _academic(name: str, rut: str = "12.345.678-5") -> AcademicFormData:
    return AcademicFormData(
        name=name,
        rut=rut,
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )


def test_description_normalization_paragraphs_and_exact_limit() -> None:
    raw = "\r\n  Primer\t párrafo  \r\n\r\n\r\n  Segundo   párrafo\t \r\n"
    assert normalize_notification_description(raw) == (
        "Primer párrafo\n\nSegundo párrafo"
    )
    assert validate_notification_description("x" * 1000) == "x" * 1000
    with pytest.raises(ValueError, match="1000"):
        validate_notification_description("x" * 1001)
    with pytest.raises(ValueError, match="descripción"):
        validate_notification_description(" \r\n\t ")
    assert "credenciales" in DESCRIPTION_PRIVACY_WARNING


@pytest.mark.parametrize(
    "sensitive",
    (
        "password=secreto-ficticio",
        "token: abcdef123456",
        "api_key = clave-ficticia",
        "Authorization: Bearer abcdef",
        "-----BEGIN PRIVATE KEY-----",
        "https://usuario:clave@example.invalid/ruta",
        "/home/persona/Documentos/proyecto/archivo.txt",
        "C:\\Users\\persona\\proyecto\\archivo.txt",
        "Traceback (most recent call last):\n  File x\nValueError: falla",
    ),
)
def test_sensitive_description_is_rejected_generically_without_log_echo(
    sensitive: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValueError) as captured:
        validate_notification_description(sensitive)
    assert str(captured.value) == (
        "La descripción contiene información que no puede enviarse."
    )
    assert sensitive not in caplog.text
    assert sensitive not in str(captured.value)


@pytest.mark.parametrize("version", (1, 2))
def test_notification_migration_is_backed_and_idempotent(
    tmp_path: Path,
    version: int,
) -> None:
    path = tmp_path / "notifications.json"
    identifier = str(uuid4())
    item = {
        "notification_id": identifier,
        "created_at": "2026-07-31T12:00:00+00:00",
    }
    if version == 1:
        item |= {
            "screen": "Académicos",
            "code": "SAVE_ERROR",
            "username": "persona-ficticia",
            "description": "texto histórico que no se conserva",
        }
    else:
        item |= {
            "source_screen": "academic_list",
            "category": "persistence",
            "error_code": "SAVE_ERROR",
            "status": "seen",
        }
    path.write_text(
        json.dumps({"schema_version": version, "notifications": [item]}),
        encoding="utf-8",
    )
    before = path.read_bytes()

    count, backup = migrate_notifications(
        path,
        backup_directory=tmp_path / "backups",
    )

    assert count == 1
    assert backup is not None and backup.read_bytes() == before
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 3
    assert migrated["notifications"][0]["notification_id"] == identifier
    assert migrated["notifications"][0]["description"] == HISTORICAL_DESCRIPTION
    if version == 2:
        assert migrated["notifications"][0]["status"] == "seen"
    assert migrate_notifications(
        path,
        backup_directory=tmp_path / "backups",
    ) == (0, None)


def test_notification_queue_and_public_file_keep_normalized_description(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    app = build_application_service(paths=paths, git_service=RecordingGit())
    app.register_user("owner", "1234")

    stored = app.notify_error(
        ErrorNotification(
            "menu",
            "unexpected",
            "OTHER_ERROR",
            "  Falla\t ficticia.\r\n\r\n  Segundo párrafo. ",
        )
    )

    assert stored.description == "Falla ficticia.\n\nSegundo párrafo."
    public = json.loads(paths.error_notifications_path.read_text(encoding="utf-8"))
    queue = json.loads(
        paths.personal_error_queue_path("owner").read_text(encoding="utf-8")
    )
    assert public["schema_version"] == queue["schema_version"] == 3
    assert public["notifications"][0]["description"] == stored.description
    assert queue["queue"][0]["description"] == stored.description


def test_private_v2_queue_migrates_delivery_state_to_v3(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "queue": [
                    {
                        "notification_id": str(uuid4()),
                        "created_at": "2026-07-31T12:00:00+00:00",
                        "source_screen": "menu",
                        "category": "unexpected",
                        "error_code": "OTHER_ERROR",
                        "status": "new",
                        "delivered": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    migrate_notifications(path, backup_directory=tmp_path / "backups")
    migrated = json.loads(path.read_text(encoding="utf-8"))["queue"][0]
    assert migrated["delivered"] is True
    assert migrated["description"] == HISTORICAL_DESCRIPTION


def test_notification_migration_rolls_back_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "notifications.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "notifications": [
                    {
                        "notification_id": str(uuid4()),
                        "created_at": "2026-07-31T12:00:00+00:00",
                        "source_screen": "menu",
                        "category": "unexpected",
                        "error_code": "OTHER_ERROR",
                        "status": "new",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fallo ficticio")

    monkeypatch.setattr(
        "persistence.error_notification_repository.atomic_write_json",
        fail_write,
    )
    with pytest.raises(RuntimeError, match="ficticio"):
        migrate_notifications(path, backup_directory=tmp_path / "backups")
    assert path.read_bytes() == before
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_mark_seen_is_owner_only_and_persists(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    app = build_application_service(paths=paths, git_service=RecordingGit())
    app.register_user("owner", "1234")
    alert = app.notify_error(
        ErrorNotification("menu", "unexpected", "OTHER_ERROR", "Falla ficticia.")
    )
    app.mark_error_seen(alert.notification_id)
    assert app.list_received_errors()[0].status == "seen"
    app.logout()
    app.register_user("otra", "5678")
    with pytest.raises(AuthorizationError):
        app.mark_error_seen(alert.notification_id)


def test_withdrawal_owner_only_pending_and_zero_write_failures(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    app = build_application_service(paths=paths, git_service=RecordingGit())
    app.register_user("solicitante", "1234")
    request = app.list_approval_requests()[0]
    app.logout()
    app.register_user("otra", "5678")
    before = paths.approved_users_path.read_bytes()
    with pytest.raises(AuthorizationError):
        app.withdraw_approval_request(request.request_id)
    assert paths.approved_users_path.read_bytes() == before
    app.logout()
    app.authenticate("solicitante", "1234")
    withdrawn = app.withdraw_approval_request(request.request_id)
    assert withdrawn.status == "withdrawn"
    assert withdrawn.withdrawn_by == "solicitante"
    assert withdrawn.withdrawn_at
    after = paths.approved_users_path.read_bytes()
    assert app.list_approval_requests() == []
    with pytest.raises(ApprovalError, match="retirada"):
        app.withdraw_approval_request(request.request_id)
    assert paths.approved_users_path.read_bytes() == after


def test_approved_request_cannot_be_withdrawn(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    app = build_application_service(paths=paths, git_service=RecordingGit())
    app.register_user("owner", "1234")
    app.logout()
    app.register_user("solicitante", "5678")
    request = app.list_approval_requests()[0]
    app.logout()
    app.authenticate("owner", "1234")
    app.grant_request(request.request_id)
    app.logout()
    app.authenticate("solicitante", "5678")
    before = paths.approved_users_path.read_bytes()
    with pytest.raises(ApprovalError, match="aprobada"):
        app.withdraw_approval_request(request.request_id)
    assert paths.approved_users_path.read_bytes() == before


def test_approval_v1_migration_adds_no_historical_withdrawal(tmp_path: Path) -> None:
    path = tmp_path / "approved.json"
    document = {
        "schema_version": 1,
        "approved_users": [
            {
                "request_id": str(uuid4()),
                "username": "persona",
                "status": "pending",
                "requested_at": "2026-07-31T12:00:00+00:00",
                "approved_at": None,
                "approved_by": None,
            }
        ],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    before = path.read_bytes()
    count, backup = migrate_approvals(path, backup_directory=tmp_path / "backups")
    assert count == 1
    assert backup is not None and backup.read_bytes() == before
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 2
    assert migrated["approved_users"][0]["withdrawn_at"] is None
    assert migrated["approved_users"][0]["withdrawn_by"] is None
    assert migrate_approvals(
        path,
        backup_directory=tmp_path / "backups",
    ) == (0, None)


def test_table_name_normalization_and_unicode_comparison() -> None:
    assert normalize_table_name("  Ｔabla   Única  ") == "Tabla Única"
    assert table_name_key("Tabla Única") == table_name_key("TABLA ÚNICA")
    with pytest.raises(ValueError, match="saltos"):
        normalize_table_name("Tabla\nOtra")
    with pytest.raises(ValueError, match="80"):
        normalize_table_name("x" * 81)


def test_table_index_migration_stops_on_unicode_collision_without_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tables.json"
    tables = []
    for number, username, name in (
        (1, "persona-a", "Tabla Única"),
        (2, "persona-b", "TABLA ÚNICA"),
    ):
        tables.append(
            {
                "number": number,
                "username": username,
                "name": name,
                "filename": f"table-{number:06d}-{username}.csv",
                "updated_at": "2026-07-31T12:00:00+00:00",
            }
        )
    path.write_text(
        json.dumps({"schema_version": 1, "tables": tables}, ensure_ascii=False),
        encoding="utf-8",
    )
    before = path.read_bytes()
    with pytest.raises(ValueError, match="duplicada"):
        migrate_tables_index(path, backup_directory=tmp_path / "backups")
    assert path.read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_empty_table_index_migration_is_backed_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "tables.json"
    path.write_text(
        json.dumps({"schema_version": 1, "tables": []}),
        encoding="utf-8",
    )
    before = path.read_bytes()
    count, backup = migrate_tables_index(
        path,
        backup_directory=tmp_path / "backups",
    )
    assert count == 0
    assert backup is not None and backup.read_bytes() == before
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
    assert migrate_tables_index(
        path,
        backup_directory=tmp_path / "backups",
    ) == (0, None)


def test_backend_and_repository_reject_casefolded_table_name_collision(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    app = build_application_service(paths=paths, git_service=RecordingGit())
    app.register_user("owner", "1234")
    app.save_academic(_academic("Persona uno"))
    app.share_table(
        TablePublication("Tabla Única", paths.personal_academics_path("owner"))
    )
    with pytest.raises(ValueError, match="existe"):
        app.shared_tables.ensure_name_available("ＴＡＢＬＡ ÚNICA")

    app.logout()
    app.register_user("otra", "5678")
    app.save_academic(_academic("Persona dos", "40.000.000-K"))
    app.logout()
    app.authenticate("owner", "1234")
    request = next(
        item for item in app.list_approval_requests() if item.username == "otra"
    )
    app.grant_request(request.request_id)
    app.logout()
    app.authenticate("otra", "5678")
    with pytest.raises(ValueError, match="existe"):
        app.share_table(
            TablePublication(
                "ＴＡＢＬＡ ÚNICA",
                paths.personal_academics_path("otra"),
            )
        )
    assert len(app.shared_tables.list_shared_tables()) == 1


def test_save_and_share_are_git_free_and_prepare_two_file_dataset(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    git = RecordingGit()
    app = build_application_service(paths=paths, git_service=git)
    app.register_user("owner", "1234")

    assert app.save_academic(_academic("Persona ficticia")).success
    assert git.update_calls == 0 and git.publications == []
    table = app.share_table(
        TablePublication("  Tabla   Personal  ", paths.personal_academics_path("owner"))
    )

    assert git.update_calls == 0 and git.publications == []
    assert table.name == "Tabla Personal"
    assert table.path.is_file()
    assert paths.academic_appointments_path(table.path).is_file()
    metadata = PrivateTableMetadataRepository("owner", paths=paths)
    assert metadata.name() == "Tabla Personal"
    pending = metadata.pending_intent()
    assert pending is not None and pending.table_number == table.table_number


def test_public_rename_is_owner_only_and_keeps_identity_and_paths(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    app = build_application_service(paths=paths, git_service=RecordingGit())
    app.register_user("owner", "1234")
    app.save_academic(_academic("Persona ficticia"))
    table = app.share_table(
        TablePublication("Nombre inicial", paths.personal_academics_path("owner"))
    )
    renamed = app.rename_public_table(table.table_number or 1, "Nombre final")
    assert (renamed.table_id, renamed.path) == (table.table_id, table.path)
    app.logout()
    app.register_user("otra", "5678")
    app.logout()
    app.authenticate("owner", "1234")
    request = next(
        item for item in app.list_approval_requests() if item.username == "otra"
    )
    app.grant_request(request.request_id)
    app.logout()
    app.authenticate("otra", "5678")
    with pytest.raises(AuthorizationError):
        app.rename_public_table(table.table_number or 1, "Intento ajeno")


def test_login_and_registration_hide_session_required_error_action(
    qtbot: QtBot,
) -> None:
    window = build_frontend_window(
        FakeFrontendController(),
        load_application_settings(),
    )
    qtbot.addWidget(window)
    window.show()
    assert window.login_view.error_footer.isHidden()
    window.show_registration()
    assert window.register_view.error_footer.isHidden()


def test_alert_view_marks_seen_and_refreshes_visible_status(qtbot: QtBot) -> None:
    controller = FakeFrontendController()
    window = build_frontend_window(controller, load_application_settings())
    qtbot.addWidget(window)
    window.show()
    window.login_view.username_input.setText("owner")
    window.login_view.password_input.setText("1234")
    qtbot.mouseClick(window.login_view.login_button, Qt.MouseButton.LeftButton)
    window.show_alerts()
    window.alerts_view.table.selectRow(0)
    assert window.alerts_view.mark_seen_button.isEnabled()
    qtbot.mouseClick(
        window.alerts_view.mark_seen_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.alerts_view.table.item(0, 4).text() == "Vista"
    assert not window.alerts_view.mark_seen_button.isEnabled()


def test_withdraw_view_confirms_before_backend_call(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = ApprovalItem(
        request_id="request-ficticia",
        username="persona",
        requested_at="31-07-2026 12:00",
        status="Pendiente",
        can_withdraw=True,
        can_approve=False,
    )
    controller = FakeFrontendController(approvals=(item,))
    window = build_frontend_window(controller, load_application_settings())
    qtbot.addWidget(window)
    window.show()
    window.login_view.username_input.setText("persona")
    window.login_view.password_input.setText("1234")
    qtbot.mouseClick(window.login_view.login_button, Qt.MouseButton.LeftButton)
    window.show_approvals()
    window.approval_view.table.selectRow(0)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    qtbot.mouseClick(window.approval_view.withdraw_button, Qt.MouseButton.LeftButton)
    assert len(controller.list_approvals()) == 1

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    qtbot.mouseClick(window.approval_view.withdraw_button, Qt.MouseButton.LeftButton)
    assert controller.list_approvals() == ()
