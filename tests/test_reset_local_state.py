"""Safety and schema tests for the administrative local-state reset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from persistence.paths import ProjectPaths
from scripts import reset_local_state as reset_module
from scripts.reset_local_state import reset_local_state


def _seed_runtime(paths: ProjectPaths) -> None:
    paths.user_profile_path("sample-user").parent.mkdir(parents=True)
    paths.user_profile_path("sample-user").write_text(
        '{"synthetic": true}\n', encoding="utf-8"
    )
    paths.config_dir.mkdir(parents=True)
    paths.owner_local_path.write_text(
        '{"schema_version": 1, "username": "sample-user"}\n', encoding="utf-8"
    )
    paths.public_tables_dir.mkdir(parents=True)
    paths.shared_table_path("table-000001-sample-user.csv").write_text(
        "synthetic\n", encoding="utf-8"
    )
    paths.approved_users_path.write_text(
        '{"schema_version": 2, "approved_users": [{"synthetic": true}]}\n',
        encoding="utf-8",
    )
    paths.tables_index_path.write_text(
        '{"schema_version": 2, "tables": [{"synthetic": true}]}\n',
        encoding="utf-8",
    )
    paths.error_notifications_path.write_text(
        '{"schema_version": 3, "notifications": [{"synthetic": true}]}\n',
        encoding="utf-8",
    )


def _seed_catalogs(paths: ProjectPaths) -> tuple[bytes, bytes]:
    paths.academic_catalogs_dir.mkdir(parents=True, exist_ok=True)
    paths.academic_staff_catalog_path.write_text(
        "id,label\nA,Alpha\n", encoding="utf-8"
    )
    paths.academic_profiles_catalog_path.write_text(
        "id,label\nP,Profile\n", encoding="utf-8"
    )
    return (
        paths.academic_staff_catalog_path.read_bytes(),
        paths.academic_profiles_catalog_path.read_bytes(),
    )


def test_dry_run_does_not_change_state(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _seed_runtime(paths)
    before = paths.owner_local_path.read_bytes()

    report = reset_local_state(paths)

    assert not report.apply
    assert report.changed == 0
    assert report.backup_directory is None
    assert paths.owner_local_path.read_bytes() == before
    assert len(report.planned) == 6


def test_apply_requires_and_verifies_backup_before_reset(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _seed_runtime(paths)
    backup = tmp_path / "backup"

    report = reset_local_state(paths, apply=True, backup_directory=backup)

    assert report.changed == 6
    assert report.backup_directory == backup.resolve()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]
    assert not paths.owner_local_path.exists()
    assert not any(paths.users_dir.iterdir())
    assert not any(paths.public_tables_dir.iterdir())


def test_apply_rejects_missing_backup_when_state_exists(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _seed_runtime(paths)

    with pytest.raises(ValueError, match="backup-dir"):
        reset_local_state(paths, apply=True)

    assert paths.owner_local_path.exists()


def test_failed_backup_leaves_all_state_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _seed_runtime(paths)
    before = paths.owner_local_path.read_bytes()

    def fail_copy(source: Path, destination: Path) -> None:
        raise OSError("synthetic backup failure")

    monkeypatch.setattr(reset_module, "_copy_backup_file", fail_copy)
    with pytest.raises(OSError):
        reset_local_state(paths, apply=True, backup_directory=tmp_path / "backup")

    assert paths.owner_local_path.read_bytes() == before
    assert paths.user_profile_path("sample-user").exists()


def test_external_allowlisted_path_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside-owner.json"
    outside.write_text("{}\n", encoding="utf-8")

    class ExternalOwnerPaths(ProjectPaths):
        @property
        def owner_local_path(self) -> Path:
            return outside

    paths = ExternalOwnerPaths(tmp_path / "project")

    with pytest.raises(ValueError, match="externa"):
        reset_local_state(paths)

    assert outside.exists()


def test_symlink_in_allowlisted_tree_is_rejected(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    paths.users_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (paths.users_dir / "unsafe").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="simbólico"):
        reset_local_state(paths)


def test_apply_is_idempotent(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _seed_runtime(paths)
    first = reset_local_state(
        paths, apply=True, backup_directory=tmp_path / "first-backup"
    )
    second = reset_local_state(paths, apply=True)

    assert first.changed == 6
    assert second.changed == 0
    assert second.planned == ()


def test_reset_writes_current_valid_empty_documents(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _seed_runtime(paths)

    reset_local_state(paths, apply=True, backup_directory=tmp_path / "backup")

    assert json.loads(paths.approved_users_path.read_text(encoding="utf-8")) == {
        "schema_version": 2,
        "approved_users": [],
    }
    assert json.loads(paths.tables_index_path.read_text(encoding="utf-8")) == {
        "schema_version": 2,
        "tables": [],
    }
    assert json.loads(paths.error_notifications_path.read_text(encoding="utf-8")) == {
        "schema_version": 3,
        "notifications": [],
    }


def test_catalogs_are_not_in_whitelist_and_are_preserved(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    _seed_runtime(paths)
    before = _seed_catalogs(paths)

    reset_local_state(paths, apply=True, backup_directory=tmp_path / "backup")

    assert paths.academic_staff_catalog_path.read_bytes() == before[0]
    assert paths.academic_profiles_catalog_path.read_bytes() == before[1]
