"""Recoverable public-table publication against disposable Git repositories."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from backend.composition import build_application_service
from backend.contracts import AcademicFormData, AcademicRecord
from backend.git_sync import (
    GitPushPendingError,
    GitRepositoryStateError,
    GitServiceError,
    GitSyncService,
)
from backend.publication import (
    ConcurrentDatasetChangeError,
    PublicationBusyError,
)
from backend.system_contracts import PublicationState, TablePublication
from persistence.paths import ProjectPaths
from persistence.publication_operation_repository import (
    PublicationOperationRepository,
)

STAFF = (
    "staff_id,key,name,active\n"
    "academic-staff-ordinary-v1,Ordinaria,Planta Ordinaria,true\n"
    "academic-staff-special-v1,Especial,Planta Especial,true\n"
)
PROFILES = (
    "profile_id,staff_id,key,name,teaching_percentage,management_percentage,"
    "research_percentage,allows_extra_courses,active\n"
    "academic-profile-ordinary-mixed-v1,academic-staff-ordinary-v1,Mixto,Mixto,"
    "50,10,40,true,true\n"
    "academic-profile-special-standard-v1,academic-staff-special-v1,Standard,"
    "Standard,75,10,15,true,true\n"
)


def _git(directory: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


class ControlledRunner:
    def __init__(self) -> None:
        self.fail: str | None = None
        self.calls: list[str] = []

    def __call__(self, command: list[str], **kwargs: object):
        operation = command[1] if len(command) > 1 else ""
        self.calls.append(operation)
        if operation == self.fail:
            return subprocess.CompletedProcess(command, 1, "", "falla sintética")
        return subprocess.run(command, **kwargs)


def _repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "-b", "main", str(seed))
    _git(seed, "config", "user.name", "Identidad Ficticia")
    _git(seed, "config", "user.email", "tests@example.invalid")
    public = seed / "data" / "public"
    catalogs = public / "catalogs"
    catalogs.mkdir(parents=True)
    (catalogs / "academic_staff.csv").write_text(STAFF, encoding="utf-8")
    (catalogs / "academic_profiles.csv").write_text(PROFILES, encoding="utf-8")
    (public / "tables_index.json").write_text(
        json.dumps({"schema_version": 2, "tables": []}) + "\n",
        encoding="utf-8",
    )
    (public / "approved_users.json").write_text(
        json.dumps({"schema_version": 2, "approved_users": []}) + "\n",
        encoding="utf-8",
    )
    (public / "notifications_error.json").write_text(
        json.dumps({"schema_version": 3, "notifications": []}) + "\n",
        encoding="utf-8",
    )
    (seed / ".gitignore").write_text(
        "users/\nconfig/owner.local.json\n",
        encoding="utf-8",
    )
    _git(seed, "add", ".gitignore", "data/public")
    _git(seed, "commit", "-m", "Base ficticia")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", "-b", "main", str(remote), str(work))
    _git(work, "config", "user.name", "Identidad Ficticia")
    _git(work, "config", "user.email", "tests@example.invalid")
    config = work / "config"
    config.mkdir()
    (config / "owner.local.json").write_text(
        json.dumps({"schema_version": 1, "username": "owner"}),
        encoding="utf-8",
    )
    return remote, work


def _academic(name: str = "Persona Ficticia") -> AcademicFormData:
    return AcademicFormData(
        name=name,
        rut="12.345.678-5",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )


def _prepared_app(
    tmp_path: Path,
    *,
    runner: ControlledRunner | None = None,
):
    remote, work = _repository(tmp_path)
    paths = ProjectPaths(work)
    git = GitSyncService(work, runner=runner or subprocess.run)
    app = build_application_service(paths=paths, git_service=git)
    app.register_user("owner", "1234")
    assert app.save_academic(_academic()).success
    table = app.share_table(
        TablePublication("Tabla Ficticia", paths.personal_academics_path("owner"))
    )
    operations = PublicationOperationRepository(
        "owner",
        paths=paths,
        catalogs=app.academic_catalogs(),
    )
    operation = operations.pending_personal()
    assert operation is not None
    return remote, work, paths, app, table, operations, operation


def test_personal_update_publishes_exact_two_csv_dataset_and_index(
    tmp_path: Path,
) -> None:
    remote, work, paths, app, table, operations, operation = _prepared_app(tmp_path)
    head_before = _git(work, "rev-parse", "HEAD")
    assert operation.state is PublicationState.PREPARED
    assert set(operation.authorized_paths) == {
        "data/public/tables_index.json",
        "data/public/tables/table-000001-owner.csv",
        "data/public/tables/table-000001-owner.appointments.csv",
    }

    result = app.run_update("Publicación ficticia")

    stored = operations.get(operation.operation_id)
    assert result.changed is True
    assert stored.state is PublicationState.PUBLISHED
    assert stored.commit == _git(work, "rev-parse", "HEAD")
    assert stored.commit != head_before
    assert _git(work, "status", "--porcelain=v1") == ""
    assert (
        _git(tmp_path, "--git-dir", str(remote), "rev-parse", "main") == stored.commit
    )
    assert table.path.is_file()
    assert paths.academic_appointments_path(table.path).is_file()
    assert not operations.draft_repository(operation.operation_id).path.exists()


def test_public_edit_cancel_and_later_publish_keep_two_csv_unit(
    tmp_path: Path,
) -> None:
    _remote, _work, _paths, app, table, _operations, _operation = _prepared_app(
        tmp_path
    )
    app.run_update("Base pública")
    before_academic = table.path.read_bytes()
    appointments = app.paths.academic_appointments_path(table.path)
    before_appointments = appointments.read_bytes()
    record = app.list_shared_table_contents()[0].academics[0]
    edited = AcademicRecord(
        academic_id=record.academic_id,
        name="Edición solo en borrador",
        rut=record.rut,
        plant=record.plant,
        profile=record.profile,
        weekly_hours=record.weekly_hours,
        status=record.status,
    )

    app.update_shared_table(table.table_number or 1, [edited])

    assert table.path.read_bytes() == before_academic
    assert appointments.read_bytes() == before_appointments
    assert app.list_shared_table_contents()[0].academics[0].name == edited.name
    app.cancel_shared_table_draft(table.table_number or 1)
    assert table.path.read_bytes() == before_academic
    assert appointments.read_bytes() == before_appointments

    app.update_shared_table(table.table_number or 1, [edited])
    result = app.publish_shared_table(table.table_number or 1)

    assert result.changed is True
    assert b"Edici\xc3\xb3n solo en borrador" in table.path.read_bytes()
    assert appointments.read_bytes() == before_appointments


def test_push_failure_is_retry_pending_and_retry_uses_same_commit(
    tmp_path: Path,
) -> None:
    runner = ControlledRunner()
    remote, work, _paths, app, _table, operations, operation = _prepared_app(
        tmp_path,
        runner=runner,
    )
    runner.fail = "push"

    with pytest.raises(GitPushPendingError):
        app.run_update("Push rechazado")

    pending = operations.get(operation.operation_id)
    assert pending.state is PublicationState.RETRY_PENDING
    assert pending.commit == _git(work, "rev-parse", "HEAD")
    commit_count = _git(work, "rev-list", "--count", "HEAD")
    runner.fail = None
    app.run_update("Reintento")
    published = operations.get(operation.operation_id)
    assert published.state is PublicationState.PUBLISHED
    assert published.commit == pending.commit
    assert _git(work, "rev-list", "--count", "HEAD") == commit_count
    assert (
        _git(tmp_path, "--git-dir", str(remote), "rev-parse", "main") == pending.commit
    )


def test_fetch_failure_restores_only_operation_files_and_keeps_draft(
    tmp_path: Path,
) -> None:
    runner = ControlledRunner()
    _remote, work, _paths, app, table, operations, operation = _prepared_app(
        tmp_path,
        runner=runner,
    )
    unrelated = work / "local-note.txt"
    unrelated.write_text("ajeno", encoding="utf-8")
    runner.fail = "fetch"

    with pytest.raises(GitRepositoryStateError, match="ajenos"):
        app.run_update("Fetch fallido con ruta ajena")

    assert unrelated.read_text(encoding="utf-8") == "ajeno"
    unrelated.unlink()
    with pytest.raises(GitServiceError, match="fetch"):
        app.run_update("Fetch fallido")
    failed = operations.get(operation.operation_id)
    assert failed.state is PublicationState.FAILED_BEFORE_COMMIT
    assert operations.draft_repository(operation.operation_id).path.is_file()
    assert not table.path.exists()
    assert _git(work, "status", "--porcelain=v1") == ""


def test_staging_failure_rolls_back_materialization_and_preserves_draft(
    tmp_path: Path,
) -> None:
    runner = ControlledRunner()
    _remote, work, _paths, app, table, operations, operation = _prepared_app(
        tmp_path,
        runner=runner,
    )
    runner.fail = "add"

    with pytest.raises(GitServiceError, match="add"):
        app.run_update("Staging fallido")

    failed = operations.get(operation.operation_id)
    assert failed.state is PublicationState.FAILED_BEFORE_COMMIT
    assert failed.commit is None
    assert operations.draft_repository(operation.operation_id).path.is_file()
    assert not table.path.exists()
    assert _git(work, "status", "--porcelain=v1") == ""


def test_unknown_local_head_stops_retry_without_duplicate_commit(
    tmp_path: Path,
) -> None:
    runner = ControlledRunner()
    _remote, work, _paths, app, _table, _operations, _operation = _prepared_app(
        tmp_path,
        runner=runner,
    )
    runner.fail = "push"
    with pytest.raises(GitPushPendingError):
        app.run_update("Commit pendiente")
    notifications = work / "data" / "public" / "notifications_error.json"
    notifications.write_text(
        json.dumps({"schema_version": 3, "notifications": [{"synthetic": True}]})
        + "\n",
        encoding="utf-8",
    )
    _git(work, "add", "data/public/notifications_error.json")
    _git(work, "commit", "-m", "Commit adelantado desconocido")
    count = _git(work, "rev-list", "--count", "HEAD")
    runner.fail = None

    with pytest.raises(GitRepositoryStateError, match="desconocidos"):
        app.run_update("Reintento inseguro")

    assert _git(work, "rev-list", "--count", "HEAD") == count


def test_compatible_remote_fast_forward_is_integrated_before_publication(
    tmp_path: Path,
) -> None:
    remote, work, _paths, app, _table, _operations, _operation = _prepared_app(tmp_path)
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", "-b", "main", str(remote), str(peer))
    _git(peer, "config", "user.name", "Par Ficticio")
    _git(peer, "config", "user.email", "peer@example.invalid")
    notifications = peer / "data" / "public" / "notifications_error.json"
    notifications.write_text(
        json.dumps({"schema_version": 3, "notifications": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    _git(peer, "add", "data/public/notifications_error.json")
    _git(peer, "commit", "-m", "Cambio remoto compatible")
    _git(peer, "push", "origin", "main")

    app.run_update("Integra avance rápido")

    assert _git(work, "rev-list", "--count", "HEAD") == "3"
    assert _git(work, "status", "--porcelain=v1") == ""


def test_remote_change_of_same_dataset_rejects_stale_draft(
    tmp_path: Path,
) -> None:
    remote, work, paths, app, table, operations, operation = _prepared_app(tmp_path)
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", "-b", "main", str(remote), str(peer))
    _git(peer, "config", "user.name", "Par Ficticio")
    _git(peer, "config", "user.email", "peer@example.invalid")
    peer_paths = ProjectPaths(peer)
    peer_table = peer_paths.shared_table_path(table.path.name)
    peer_table.parent.mkdir(parents=True)
    peer_table.write_text(
        "academic_id,rut,name,email,status\nremote-id,40000000-K,Remoto,,Activo\n",
        encoding="utf-8",
    )
    peer_paths.academic_appointments_path(peer_table).write_text(
        "appointment_id,academic_id,profile_id,weekly_hours,start_date,end_date\n"
        "remote-appointment,remote-id,academic-profile-ordinary-mixed-v1,20,,\n",
        encoding="utf-8",
    )
    peer_paths.tables_index_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "tables": [
                    {
                        "number": 1,
                        "username": "remote-owner",
                        "name": "Tabla Remota",
                        "filename": table.path.name,
                        "updated_at": "2026-07-31T12:00:00+00:00",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _git(peer, "add", "data/public/tables", "data/public/tables_index.json")
    _git(peer, "commit", "-m", "Cambio remoto del mismo dataset")
    _git(peer, "push", "origin", "main")

    with pytest.raises(ConcurrentDatasetChangeError, match="cambiaron"):
        app.run_update("Borrador obsoleto")

    failed = operations.get(operation.operation_id)
    assert failed.state is PublicationState.FAILED_BEFORE_COMMIT
    assert operations.draft_repository(operation.operation_id).path.is_file()
    assert b"Remoto" in table.path.read_bytes()
    assert _git(work, "status", "--porcelain=v1") == ""


def test_remote_path_outside_allowlist_stops_before_fast_forward(
    tmp_path: Path,
) -> None:
    remote, work, _paths, app, table, operations, operation = _prepared_app(tmp_path)
    initial_head = _git(work, "rev-parse", "HEAD")
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", "-b", "main", str(remote), str(peer))
    _git(peer, "config", "user.name", "Par Ficticio")
    _git(peer, "config", "user.email", "peer@example.invalid")
    (peer / "application.py").write_text("UNEXPECTED = True\n", encoding="utf-8")
    _git(peer, "add", "application.py")
    _git(peer, "commit", "-m", "Ruta remota no autorizada")
    _git(peer, "push", "origin", "main")

    with pytest.raises(GitRepositoryStateError, match="allowlist"):
        app.run_update("Remoto incompatible")

    assert _git(work, "rev-parse", "HEAD") == initial_head
    assert not (work / "application.py").exists()
    assert not table.path.exists()
    failed = operations.get(operation.operation_id)
    assert failed.state is PublicationState.FAILED_BEFORE_COMMIT
    assert failed.error is not None and str(work) not in failed.error


@pytest.mark.parametrize("failed_operation", ("commit",))
def test_failure_before_commit_restores_files_and_index(
    tmp_path: Path,
    failed_operation: str,
) -> None:
    runner = ControlledRunner()
    _remote, work, paths, app, table, operations, operation = _prepared_app(
        tmp_path,
        runner=runner,
    )
    index_before = json.loads(paths.tables_index_path.read_text(encoding="utf-8"))
    assert index_before["tables"]
    runner.fail = failed_operation

    with pytest.raises(GitServiceError, match=failed_operation):
        app.run_update("Falla antes del commit")

    assert (
        json.loads(paths.tables_index_path.read_text(encoding="utf-8"))["tables"] == []
    )
    assert not table.path.exists()
    assert _git(work, "status", "--porcelain=v1") == ""
    assert (
        operations.get(operation.operation_id).state
        is PublicationState.FAILED_BEFORE_COMMIT
    )


def test_partial_materialization_is_rolled_back_as_one_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _remote, work, _paths, app, table, operations, operation = _prepared_app(tmp_path)

    def partial_failure(*_args: object, **_kwargs: object) -> None:
        table.path.parent.mkdir(parents=True, exist_ok=True)
        table.path.write_text("parcial\n", encoding="utf-8")
        raise OSError("falla sintética entre CSV")

    monkeypatch.setattr(app.shared_tables, "materialize_exact", partial_failure)

    with pytest.raises(OSError, match="entre CSV"):
        app.run_update("Materialización parcial")

    assert not table.path.exists()
    assert not app.paths.academic_appointments_path(table.path).exists()
    assert _git(work, "status", "--porcelain=v1") == ""
    assert operations.draft_repository(operation.operation_id).path.is_file()


def test_publication_lock_rejects_concurrent_execution(tmp_path: Path) -> None:
    _remote, _work, _paths, app, _table, operations, operation = _prepared_app(tmp_path)
    lock = app.publications._lock()
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(PublicationBusyError, match="curso"):
            app.run_update("Doble ejecución")
    finally:
        lock.release()
    assert operations.get(operation.operation_id).state is PublicationState.PREPARED
