"""Stage-four Git and responsive Inicio boundaries using only local remotes."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from backend.composition import build_application_service
from backend.contracts import AcademicFormData
from backend.frontend_controller import PersistentFrontendController
from backend.git_sync import (
    ACADEMIC_PATH,
    BRANCH_NAME,
    COMMIT_MESSAGE,
    PRODUCTIVE_REMOTE_URL,
    REMOTE_NAME,
    GitCodeUpdateRequiredError,
    GitConfigurationError,
    GitCsvValidationError,
    GitDivergenceError,
    GitLocalChangesError,
    GitNetworkError,
    GitPushPendingError,
    GitRemoteAdvanceError,
    GitSyncService,
    GitUnavailableError,
)
from frontend.contracts import UiResult
from frontend.controller import FakeFrontendController
from frontend.frontend_main import ACADEMIC_LIST_SCREEN, build_frontend_window
from persistence.paths import ProjectPaths
from persistence.settings_repository import load_application_settings

VALID_CSV = (
    "academic_id,rut,name,plant,profile,weekly_hours,status\n"
    "academic-1,12.345.678-5,Persona Ficticia,Ordinaria,Mixto,40,Activo\n"
)
UPDATED_CSV = VALID_CSV.replace("Persona Ficticia", "Registro Remoto")


def _git(directory: Path, *arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        shell=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(f"Falló Git temporal: {arguments[0]}")
    return completed.stdout.strip()


@dataclass(frozen=True)
class LocalGitEnvironment:
    remote: Path
    seed: Path
    work: Path

    def service(self) -> GitSyncService:
        return GitSyncService(
            self.work,
            expected_remote_url=str(self.remote),
        )

    def peer(self, destination: Path) -> Path:
        _git(
            destination.parent,
            "clone",
            "-b",
            "main",
            str(self.remote),
            str(destination),
        )
        _configure_identity(destination)
        return destination


def _configure_identity(repository: Path) -> None:
    _git(repository, "config", "user.name", "Identidad de prueba")
    _git(repository, "config", "user.email", "git-tests@example.invalid")


@pytest.fixture
def git_environment(tmp_path: Path) -> LocalGitEnvironment:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "-b", "main", str(seed))
    _configure_identity(seed)
    academic = seed / ACADEMIC_PATH
    academic.parent.mkdir(parents=True)
    academic.write_text(VALID_CSV, encoding="utf-8")
    (seed / "application.py").write_text("SAFE = True\n", encoding="utf-8")
    (seed / ".gitignore").write_text("data/local/\n", encoding="utf-8")
    _git(seed, "add", ".gitignore", "application.py", ACADEMIC_PATH)
    _git(seed, "commit", "-m", "Base temporal")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", "-b", "main", str(remote), str(work))
    _configure_identity(work)
    return LocalGitEnvironment(remote, seed, work)


def test_local_academic_symlink_is_rejected_before_fetch(
    git_environment: LocalGitEnvironment,
    tmp_path: Path,
) -> None:
    external = tmp_path / "outside.csv"
    external.write_text(VALID_CSV, encoding="utf-8")
    academic = git_environment.work / ACADEMIC_PATH
    academic.unlink()
    academic.symlink_to(external)

    with pytest.raises(GitCsvValidationError, match="simbólico"):
        git_environment.service().upload_information()


def test_productive_git_configuration_is_fixed_and_wrong_url_stops_before_fetch(
    git_environment: LocalGitEnvironment,
) -> None:
    assert REMOTE_NAME == "origin"
    assert BRANCH_NAME == "main"
    assert PRODUCTIVE_REMOTE_URL == (
        "https://github.com/ngulloa/AsignationEpucPrototipe.git"
    )

    with pytest.raises(GitConfigurationError) as captured:
        GitSyncService(git_environment.work).upload_information()

    assert str(git_environment.remote) not in str(captured.value)

    with pytest.raises(GitUnavailableError, match="no está disponible"):
        GitSyncService(
            git_environment.work,
            expected_remote_url=str(git_environment.remote),
            git_executable="git-executable-that-does-not-exist",
        ).download_information()


def test_download_rejects_local_academic_change_before_fetch(
    git_environment: LocalGitEnvironment,
) -> None:
    (git_environment.work / ACADEMIC_PATH).write_text(UPDATED_CSV, encoding="utf-8")

    with pytest.raises(GitLocalChangesError, match="sobrescribirse"):
        git_environment.service().download_information()


def test_remote_symlink_is_rejected_without_fast_forward(
    git_environment: LocalGitEnvironment,
    tmp_path: Path,
) -> None:
    peer = git_environment.peer(tmp_path / "peer")
    academic = peer / ACADEMIC_PATH
    academic.unlink()
    academic.symlink_to("../../application.py")
    _git(peer, "add", ACADEMIC_PATH)
    _git(peer, "commit", "-m", "Symlink remoto temporal")
    _git(peer, "push", "origin", "main")
    before = _git(git_environment.work, "rev-parse", "HEAD")

    with pytest.raises(GitCsvValidationError, match="regular"):
        git_environment.service().download_information()

    assert _git(git_environment.work, "rev-parse", "HEAD") == before
    assert not (git_environment.work / ACADEMIC_PATH).is_symlink()


def test_remote_code_change_requires_manual_update_and_keeps_head(
    git_environment: LocalGitEnvironment,
    tmp_path: Path,
) -> None:
    peer = git_environment.peer(tmp_path / "peer")
    (peer / "application.py").write_text("SAFE = False\n", encoding="utf-8")
    (peer / ACADEMIC_PATH).write_text(UPDATED_CSV, encoding="utf-8")
    _git(peer, "add", "application.py", ACADEMIC_PATH)
    _git(peer, "commit", "-m", "Código remoto temporal")
    _git(peer, "push", "origin", "main")
    before = _git(git_environment.work, "rev-parse", "HEAD")

    with pytest.raises(GitCodeUpdateRequiredError, match="manual de código"):
        git_environment.service().download_information()

    assert _git(git_environment.work, "rev-parse", "HEAD") == before
    assert (git_environment.work / "application.py").read_text() == "SAFE = True\n"


def test_download_fast_forwards_only_valid_academic_csv(
    git_environment: LocalGitEnvironment,
    tmp_path: Path,
) -> None:
    peer = git_environment.peer(tmp_path / "peer")
    (peer / ACADEMIC_PATH).write_text(UPDATED_CSV, encoding="utf-8")
    _git(peer, "add", ACADEMIC_PATH)
    _git(peer, "commit", "-m", "Dato académico remoto")
    _git(peer, "push", "origin", "main")

    result = git_environment.service().download_information()

    assert result.changed is True
    assert _git(git_environment.work, "rev-parse", "HEAD") == _git(
        peer, "rev-parse", "HEAD"
    )
    assert (git_environment.work / ACADEMIC_PATH).read_text() == UPDATED_CSV
    assert (git_environment.work / "application.py").read_text() == "SAFE = True\n"
    assert _git(git_environment.work, "status", "--porcelain=v1") == ""


def test_download_rejects_divergence(
    git_environment: LocalGitEnvironment,
    tmp_path: Path,
) -> None:
    local_csv = git_environment.work / ACADEMIC_PATH
    local_csv.write_text(
        VALID_CSV.replace("Persona Ficticia", "Local"), encoding="utf-8"
    )
    _git(git_environment.work, "add", ACADEMIC_PATH)
    _git(git_environment.work, "commit", "-m", "Dato local temporal")
    peer = git_environment.peer(tmp_path / "peer")
    (peer / ACADEMIC_PATH).write_text(UPDATED_CSV, encoding="utf-8")
    _git(peer, "add", ACADEMIC_PATH)
    _git(peer, "commit", "-m", "Dato remoto temporal")
    _git(peer, "push", "origin", "main")

    with pytest.raises(GitDivergenceError, match="divergentes"):
        git_environment.service().download_information()


def test_invalid_remote_csv_is_rejected_before_fast_forward(
    git_environment: LocalGitEnvironment,
    tmp_path: Path,
) -> None:
    peer = git_environment.peer(tmp_path / "peer")
    (peer / ACADEMIC_PATH).write_text("wrong,header\n1,2\n", encoding="utf-8")
    _git(peer, "add", ACADEMIC_PATH)
    _git(peer, "commit", "-m", "CSV remoto inválido")
    _git(peer, "push", "origin", "main")
    before = _git(git_environment.work, "rev-parse", "HEAD")

    with pytest.raises(GitCsvValidationError, match="inválido"):
        git_environment.service().download_information()

    assert _git(git_environment.work, "rev-parse", "HEAD") == before
    assert (git_environment.work / ACADEMIC_PATH).read_text() == VALID_CSV


def test_invalid_local_csv_is_rejected_before_upload(
    git_environment: LocalGitEnvironment,
) -> None:
    (git_environment.work / ACADEMIC_PATH).write_text(
        "academic_id,rut\nincomplete,12.345.678-5\n",
        encoding="utf-8",
    )

    with pytest.raises(GitCsvValidationError, match="inválido"):
        git_environment.service().upload_information()


@pytest.mark.parametrize("staged", (False, True))
def test_upload_rejects_untracked_or_staged_unauthorized_file(
    git_environment: LocalGitEnvironment,
    staged: bool,
) -> None:
    academic = git_environment.work / ACADEMIC_PATH
    academic.write_text(UPDATED_CSV, encoding="utf-8")
    if staged:
        (git_environment.work / "application.py").write_text(
            "SAFE = False\n", encoding="utf-8"
        )
        _git(git_environment.work, "add", "application.py")
    else:
        (git_environment.work / "extra.txt").write_text("extra\n", encoding="utf-8")

    with pytest.raises(GitLocalChangesError, match="fuera de Academic.csv"):
        git_environment.service().upload_information()

    assert _git(git_environment.work, "rev-parse", "HEAD") == _git(
        git_environment.seed, "rev-parse", "HEAD"
    )


def test_upload_rejects_remote_advance_without_creating_commit(
    git_environment: LocalGitEnvironment,
    tmp_path: Path,
) -> None:
    peer = git_environment.peer(tmp_path / "peer")
    (peer / ACADEMIC_PATH).write_text(UPDATED_CSV, encoding="utf-8")
    _git(peer, "add", ACADEMIC_PATH)
    _git(peer, "commit", "-m", "Dato remoto temporal")
    _git(peer, "push", "origin", "main")
    (git_environment.work / ACADEMIC_PATH).write_text(
        VALID_CSV.replace("Persona Ficticia", "Dato local"),
        encoding="utf-8",
    )
    before = _git(git_environment.work, "rev-parse", "HEAD")

    with pytest.raises(GitRemoteAdvanceError, match="Baje"):
        git_environment.service().upload_information()

    assert _git(git_environment.work, "rev-parse", "HEAD") == before


def test_upload_allows_ignored_local_state_and_uses_generic_commit(
    git_environment: LocalGitEnvironment,
) -> None:
    ignored = git_environment.work / "data" / "local" / "users.json"
    ignored.parent.mkdir(parents=True)
    ignored.write_text('{"username": "dato-privado"}\n', encoding="utf-8")
    (git_environment.work / ACADEMIC_PATH).write_text(UPDATED_CSV, encoding="utf-8")

    result = git_environment.service().upload_information()
    commit = _git(git_environment.work, "rev-parse", "HEAD")

    assert result.changed is True
    assert _git(git_environment.work, "show", "--pretty=%s", "--no-patch", commit) == (
        COMMIT_MESSAGE
    )
    assert (
        _git(
            git_environment.work,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            commit,
        )
        == ACADEMIC_PATH
    )
    assert (
        _git(
            git_environment.remote,
            "rev-parse",
            "refs/heads/main",
        )
        == commit
    )
    assert ignored.is_file()


def test_upload_distinguishes_no_changes(git_environment: LocalGitEnvironment) -> None:
    before = _git(git_environment.work, "rev-parse", "HEAD")

    result = git_environment.service().upload_information()

    assert result.changed is False
    assert "No hay cambios" in result.message
    assert _git(git_environment.work, "rev-parse", "HEAD") == before


class _FetchFailureRunner:
    def __call__(self, command: list[str], **kwargs: object):
        if len(command) > 1 and command[1] == "fetch":
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "token=secreto /home/persona/ruta-privada",
            )
        return subprocess.run(command, **kwargs)


def test_network_error_does_not_expose_stderr_or_local_paths(
    git_environment: LocalGitEnvironment,
) -> None:
    service = GitSyncService(
        git_environment.work,
        expected_remote_url=str(git_environment.remote),
        runner=_FetchFailureRunner(),
    )

    with pytest.raises(GitNetworkError) as captured:
        service.upload_information()

    message = str(captured.value)
    assert "red" in message
    assert "secreto" not in message
    assert str(git_environment.work) not in message


def test_git_failure_does_not_break_local_academic_operations(tmp_path: Path) -> None:
    application = build_application_service(paths=ProjectPaths(tmp_path))
    application.register_user("persona.sintetica", "1234")
    form = AcademicFormData(
        name="Registro local",
        rut="12.345.678-5",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )
    assert application.save_academic(form).success
    controller = PersistentFrontendController(application)

    git_result = controller.download_information()

    assert git_result.success is False
    academics = application.list_academics()
    assert len(academics) == 1
    updated = AcademicFormData(
        name="Edición posterior al error Git",
        rut=form.rut,
        plant=form.plant,
        profile=form.profile,
        weekly_hours=form.weekly_hours,
        status=form.status,
    )
    assert application.update_academic(academics[0].academic_id, updated).success
    assert application.list_academics()[0].name == updated.name


def _rejecting_hook(remote: Path) -> Path:
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    return hook


def test_rejected_push_keeps_one_pending_commit_and_retries_same_commit(
    git_environment: LocalGitEnvironment,
) -> None:
    service = git_environment.service()
    (git_environment.work / ACADEMIC_PATH).write_text(UPDATED_CSV, encoding="utf-8")
    hook = _rejecting_hook(git_environment.remote)

    with pytest.raises(GitPushPendingError) as captured:
        service.upload_information()

    pending = captured.value.commit
    assert pending not in str(captured.value)
    commit_count = _git(git_environment.work, "rev-list", "--count", "HEAD")
    assert (
        service.pending_commit
        == pending
        == _git(git_environment.work, "rev-parse", "HEAD")
    )
    hook.unlink()
    service = git_environment.service()

    result = service.upload_information()

    assert result.changed is True
    assert "mismo commit" in result.message
    assert service.pending_commit is None
    assert _git(git_environment.work, "rev-list", "--count", "HEAD") == commit_count
    assert (
        _git(
            git_environment.remote,
            "rev-parse",
            "refs/heads/main",
        )
        == pending
    )


def test_pending_retry_stops_if_remote_is_no_longer_ancestor(
    git_environment: LocalGitEnvironment,
    tmp_path: Path,
) -> None:
    service = git_environment.service()
    (git_environment.work / ACADEMIC_PATH).write_text(UPDATED_CSV, encoding="utf-8")
    hook = _rejecting_hook(git_environment.remote)
    with pytest.raises(GitPushPendingError):
        service.upload_information()
    pending = service.pending_commit
    count = _git(git_environment.work, "rev-list", "--count", "HEAD")
    hook.unlink()
    peer = git_environment.peer(tmp_path / "peer")
    (peer / ACADEMIC_PATH).write_text(
        VALID_CSV.replace("Persona Ficticia", "Otro remoto"), encoding="utf-8"
    )
    _git(peer, "add", ACADEMIC_PATH)
    _git(peer, "commit", "-m", "Competidor temporal")
    _git(peer, "push", "origin", "main")

    with pytest.raises(GitDivergenceError, match="ancestro"):
        service.upload_information()

    assert service.pending_commit == pending
    assert _git(git_environment.work, "rev-list", "--count", "HEAD") == count


class _ControllableSyncController(FakeFrontendController):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.fail_upload = False

    def download_information(self) -> UiResult:
        self.started.set()
        self.release.wait(timeout=5)
        return UiResult(True, "Academic.csv se actualizó correctamente.")

    def upload_information(self) -> UiResult:
        if self.fail_upload:
            return UiResult(False, "No fue posible consultar origin/main.")
        return UiResult(True, "Academic.csv se subió correctamente.")


def test_inicio_is_responsive_restores_buttons_and_keeps_academic_flow(
    qtbot: QtBot,
    qapp: object,
) -> None:
    controller = _ControllableSyncController()
    window = build_frontend_window(
        controller,
        settings=load_application_settings(),
    )
    qtbot.addWidget(window)
    window.show()
    window._handle_authenticated("persona.sintetica")
    menu = window.main_menu_view
    resting_positions = tuple(button.geometry() for button in menu.action_buttons)

    qtbot.mouseClick(menu.download_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(controller.started.is_set)
    assert window._sync_operation.active
    assert all(not button.isEnabled() for button in menu.action_buttons)
    assert menu.download_button.text() == "Bajando información…"
    assert menu.download_button.cursor().shape() is Qt.CursorShape.ArrowCursor
    assert qapp.thread() == window.thread()
    controller.release.set()
    qtbot.waitUntil(lambda: not window._sync_operation.active)
    assert menu.sync_message.text() == "Academic.csv se actualizó correctamente."
    assert [button.isEnabled() for button in menu.action_buttons] == [
        False,
        True,
        False,
        True,
        True,
    ]
    assert (
        tuple(button.geometry() for button in menu.action_buttons) == resting_positions
    )
    assert menu.download_button.cursor().shape() is Qt.CursorShape.PointingHandCursor

    controller.fail_upload = True
    qtbot.mouseClick(menu.upload_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not window._sync_operation.active)
    assert "origin/main" in menu.sync_message.text()
    assert menu.sync_message.objectName() == "failureMessage"
    qtbot.mouseClick(menu.academics_button, Qt.MouseButton.LeftButton)
    assert window.current_screen == ACADEMIC_LIST_SCREEN
    qtbot.mouseClick(
        window.academics_list_view.add_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.academic_form_view.isVisibleTo(window)


def test_inicio_texts_and_geometry_are_stable_in_all_sync_states(
    qtbot: QtBot,
    qapp: object,
) -> None:
    window = build_frontend_window(
        FakeFrontendController(),
        settings=load_application_settings(),
    )
    qtbot.addWidget(window)
    window.show()
    window._handle_authenticated("visual.sintetica")
    menu = window.main_menu_view

    for width, height in ((720, 600), (768, 768), (1080, 768)):
        window.resize(width, height)
        qapp.processEvents()
        baseline = tuple(button.geometry() for button in menu.action_buttons)
        for operation, message, success in (
            ("download", "Sincronización en curso…", True),
            ("", "Academic.csv se actualizó correctamente.", True),
            ("", "No fue posible consultar origin/main.", False),
        ):
            menu.set_sync_busy(bool(operation), operation)
            if not operation:
                menu.show_sync_result(message, success=success)
            qapp.processEvents()
            assert (
                tuple(button.geometry() for button in menu.action_buttons) == baseline
            )
            for button in menu.action_buttons:
                assert (
                    button.fontMetrics().horizontalAdvance(button.text())
                    < button.width()
                )
            assert menu.sync_message.text() == message
            assert menu.sync_message.geometry().right() <= menu.width()
        menu.set_sync_busy(False)
