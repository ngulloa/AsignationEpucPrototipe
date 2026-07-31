"""End-to-end checks for the persistent application composition."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from backend.approval import AuthorizationError
from backend.authentication import AuthenticationError
from backend.composition import build_application_service
from backend.contracts import AcademicFormData, AcademicRecord
from backend.frontend_controller import PersistentFrontendController
from backend.git_sync import GitRepositoryStateError, GitSyncService
from backend.system_contracts import ErrorNotification, TablePublication, UpdateResult
from frontend.contracts import UpdateRequest
from frontend.frontend_main import LOGIN_SCREEN, MENU_SCREEN
from main import build_production_application_window
from persistence.paths import ProjectPaths


class RecordingGitService:
    def __init__(self) -> None:
        self.update_calls = 0
        self.publications: list[tuple[str, str, tuple[Path, ...]]] = []

    def run_update(self) -> UpdateResult:
        self.update_calls += 1
        return UpdateResult(False, "Repositorio temporal actualizado.")

    def pending_summary(self) -> str:
        return "No hay archivos compartidos pendientes de publicación Git."

    def publish_changes(
        self,
        *,
        name: str,
        username: str,
        paths: tuple[Path, ...],
    ) -> UpdateResult:
        self.publications.append((name, username, tuple(paths)))
        return UpdateResult(True, "Cambios temporales publicados.")


def _git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _configure_owner(paths: ProjectPaths, username: str = "owner") -> None:
    paths.config_dir.mkdir(parents=True)
    paths.owner_local_path.write_text(
        json.dumps({"schema_version": 1, "username": username}),
        encoding="utf-8",
    )


def _academic(name: str) -> AcademicFormData:
    return AcademicFormData(
        name=name,
        rut="12.345.678-5",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )


def test_productive_services_enforce_permissions_and_data_boundaries(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    git = RecordingGitService()
    application = build_application_service(paths=paths, git_service=git)

    application.register_user("owner", "1234")
    assert application.get_permissions().owner is True
    assert application.save_academic(_academic("Registro del propietario")).success
    application.logout()

    application.register_user("alice", "5678")
    assert application.get_permissions().approved is False
    assert application.save_academic(_academic("Registro privado de Alice")).success
    with pytest.raises(AuthorizationError):
        application.list_shared_table_contents()
    with pytest.raises(AuthorizationError):
        application.list_received_errors()
    application.logout()

    application.authenticate("owner", "1234")
    request = next(
        item
        for item in application.list_approval_requests()
        if item.username == "alice"
    )
    application.grant_request(request.request_id)
    published = application.publish_table(
        TablePublication(
            "Tabla del propietario",
            paths.personal_academics_path("owner"),
        )
    )
    assert published.owner_username == "owner"
    application.logout()

    application.authenticate("alice", "5678")
    assert application.get_permissions().approved is True
    shared = application.list_shared_table_contents()
    assert [item.metadata.owner_username for item in shared] == ["owner"]
    assert shared[0].academics[0].name == "Registro del propietario"
    application.notify_error(
        ErrorNotification(
            source_screen="academic_form",
            category="persistence",
            error_code="SAVE_ERROR",
        )
    )
    with pytest.raises(AuthorizationError):
        application.list_received_errors()
    application.logout()

    application.authenticate("owner", "1234")
    alerts = application.list_received_errors()
    assert len(alerts) == 1
    assert alerts[0].source_screen == "academic_form"
    assert alerts[0].error_code == "SAVE_ERROR"
    assert not hasattr(alerts[0], "username")
    assert not hasattr(alerts[0], "description")
    with pytest.raises(AuthenticationError):
        application.authenticate("owner", "incorrecta")
    with pytest.raises(AuthorizationError):
        application.list_academics()

    owner_csv = paths.personal_academics_path("owner").read_text(encoding="utf-8")
    alice_csv = paths.personal_academics_path("alice").read_text(encoding="utf-8")
    assert "Registro del propietario" in owner_csv
    assert "Registro privado de Alice" not in owner_csv
    assert "Registro privado de Alice" in alice_csv
    assert "Registro del propietario" not in alice_csv


def test_update_flushes_pending_notifications_and_publishes_shared_files(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    git = RecordingGitService()
    application = build_application_service(paths=paths, git_service=git)
    application.register_user("owner", "1234")
    assert application.save_academic(_academic("Registro publicable")).success
    stored = application.notify_error(
        ErrorNotification(
            source_screen="update",
            category="synchronization",
            error_code="UPDATE_ERROR",
        )
    )

    queue_path = paths.personal_error_queue_path("owner")
    queue_document = json.loads(queue_path.read_text(encoding="utf-8"))
    queue_document["queue"][0]["delivered"] = False
    queue_path.write_text(json.dumps(queue_document), encoding="utf-8")
    paths.error_notifications_path.write_text(
        json.dumps({"schema_version": 2, "notifications": []}),
        encoding="utf-8",
    )

    controller = PersistentFrontendController(application)
    result = controller.run_update(UpdateRequest("owner", "Carga inicial"))

    assert result.success is True
    assert git.update_calls == 1
    assert len(git.publications) == 1
    name, username, published_paths = git.publications[0]
    assert (name, username) == ("Carga inicial", "owner")
    assert paths.error_notifications_path in published_paths
    assert paths.approved_users_path in published_paths
    assert paths.tables_index_path in published_paths
    assert any(path.suffix == ".csv" for path in published_paths)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))["queue"]
    assert queue[0]["delivered"] is True
    notifications = json.loads(
        paths.error_notifications_path.read_text(encoding="utf-8")
    )["notifications"]
    assert [item["notification_id"] for item in notifications] == [
        stored.notification_id
    ]


def test_shared_table_update_rechecks_backend_permission(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    application = build_application_service(
        paths=paths,
        git_service=RecordingGitService(),
    )
    application.register_user("owner", "1234")
    assert application.save_academic(_academic("Registro compartido")).success
    table = application.publish_table(
        TablePublication(
            "Tabla editable",
            paths.personal_academics_path("owner"),
        )
    )
    shared_academic_id = (
        application.list_shared_table_contents()[0].academics[0].academic_id
    )
    application.logout()
    application.register_user("unapproved", "5678")
    edited = AcademicRecord(
        academic_id="shared-edit",
        name="Edición autorizada",
        rut="12.345.678-5",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )

    frontend_denied = PersistentFrontendController(application).update_shared_academic(
        table.table_number or 1,
        shared_academic_id,
        _academic("Intento desde interfaz"),
    )
    assert frontend_denied.success is False
    assert "aprobad" in frontend_denied.message.lower()

    with pytest.raises(AuthorizationError):
        application.update_shared_table(
            table.table_number or 1,
            [edited],
            update_name="Intento no autorizado",
        )

    application.logout()
    application.authenticate("owner", "1234")
    request = next(
        item
        for item in application.list_approval_requests()
        if item.username == "unapproved"
    )
    application.grant_request(request.request_id)
    application.logout()
    application.authenticate("unapproved", "5678")
    updated = application.update_shared_table(
        table.table_number or 1,
        [edited],
        update_name="Edición autorizada",
    )

    assert updated.table_number == table.table_number
    assert application.list_shared_table_contents()[0].academics[0].name == (
        "Edición autorizada"
    )


def test_real_window_authenticates_and_logout_clears_backend_session(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    _configure_owner(paths)
    setup = build_application_service(paths=paths, git_service=RecordingGitService())
    setup.register_user("owner", "1234")
    setup.logout()

    window = build_production_application_window(paths=paths)
    qtbot.addWidget(window)
    window.show()
    window.login_view.username_input.setText("owner")
    window.login_view.password_input.setText("1234")
    qtbot.mouseClick(window.login_view.login_button, Qt.MouseButton.LeftButton)

    assert isinstance(window.controller, PersistentFrontendController)
    assert window.current_screen == MENU_SCREEN
    assert window.main_menu_view.alerts_button.isVisibleTo(window.main_menu_view)
    qtbot.mouseClick(
        window.main_menu_view.header.logout_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.current_screen == LOGIN_SCREEN
    with pytest.raises(AuthorizationError):
        window.controller.application.list_academics()


def test_backend_errors_reach_existing_frontend_messages(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    window = build_production_application_window(paths=ProjectPaths(tmp_path))
    qtbot.addWidget(window)

    window.show_approvals()
    assert "sesión" in window.approval_view.result_label.text().lower()
    window.show_alerts()
    assert "sesión" in window.alerts_view.detail_text.toPlainText().lower()


def test_git_update_and_publication_use_only_a_temporary_remote(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    work = tmp_path / "work"
    peer = tmp_path / "peer"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "-b", "main", str(seed))
    _git(seed, "config", "user.name", "Prueba EPUC")
    _git(seed, "config", "user.email", "epuc@example.invalid")
    shared = seed / "data" / "public"
    shared.mkdir(parents=True)
    notifications = shared / "notifications_error.json"
    notifications.write_text(
        json.dumps({"schema_version": 1, "notifications": []}),
        encoding="utf-8",
    )
    (seed / "main.py").write_text("SAFE = True\n", encoding="utf-8")
    (seed / ".gitignore").write_text(
        "users/\nconfig/owner.local.json\n",
        encoding="utf-8",
    )
    _git(
        seed,
        "add",
        ".gitignore",
        "main.py",
        "data/public/notifications_error.json",
    )
    _git(seed, "commit", "-m", "Estado inicial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    _git(tmp_path, "clone", "-b", "main", str(remote), str(work))
    _git(work, "config", "user.name", "Prueba EPUC")
    _git(work, "config", "user.email", "epuc@example.invalid")
    work_notifications = work / "data" / "public" / "notifications_error.json"
    work_notifications.write_text(
        json.dumps({"schema_version": 1, "notifications": [{"id": "local"}]}),
        encoding="utf-8",
    )
    private = work / "users" / "owner" / "user.json"
    private.parent.mkdir(parents=True)
    private.write_text("{}", encoding="utf-8")
    service = GitSyncService(work)

    with pytest.raises(GitRepositoryStateError):
        service.publish_changes(
            name="Intento privado",
            username="owner",
            paths=(private,),
        )

    unexpected = work / "frontend" / "config.json"
    unexpected.parent.mkdir()
    unexpected.write_text("{}", encoding="utf-8")
    with pytest.raises(GitRepositoryStateError, match="cambios ajenos"):
        service.publish_changes(
            name="Intento con configuración inesperada",
            username="owner",
            paths=(work_notifications,),
        )
    unexpected.unlink()
    unexpected.parent.rmdir()

    publication = service.publish_changes(
        name="Notificaciones",
        username="owner",
        paths=(work_notifications,),
    )
    assert publication.changed is True
    assert "Notificaciones" in _git(
        tmp_path, "--git-dir", str(remote), "log", "-1", "--pretty=%s", "main"
    )

    _git(tmp_path, "clone", "-b", "main", str(remote), str(peer))
    _git(peer, "config", "user.name", "Prueba EPUC")
    _git(peer, "config", "user.email", "epuc@example.invalid")
    peer_notifications = peer / "data" / "public" / "notifications_error.json"
    peer_notifications.write_text(
        json.dumps({"schema_version": 1, "notifications": [{"id": "remote"}]}),
        encoding="utf-8",
    )
    _git(peer, "add", "data/public/notifications_error.json")
    _git(peer, "commit", "-m", "Cambio remoto temporal")
    _git(peer, "push", "origin", "main")

    unexpected = work / "application.py"
    unexpected.write_text("unexpected = True\n", encoding="utf-8")
    with pytest.raises(GitRepositoryStateError, match="código o configuración"):
        service.run_update()
    unexpected.unlink()

    update = service.run_update()
    assert update.changed is True
    assert "remote" in work_notifications.read_text(encoding="utf-8")

    (peer / "main.py").write_text("SAFE = False\n", encoding="utf-8")
    _git(peer, "add", "main.py")
    _git(peer, "commit", "-m", "Cambio de código remoto inesperado")
    _git(peer, "push", "origin", "main")

    with pytest.raises(GitRepositoryStateError, match="código o configuración"):
        service.run_update()
    assert (work / "main.py").read_text(encoding="utf-8") == "SAFE = True\n"
