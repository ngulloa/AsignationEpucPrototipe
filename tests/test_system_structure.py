"""Structural tests for the reserved users, sharing and synchronization system."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from frontend.navigation import ACTIVE_ROUTES, RESERVED_ROUTES, FrontendRoute
from frontend.views import approval_view, error_notification_view, update_view
from persistence.error_notification_repository import JsonErrorNotificationRepository
from persistence.paths import DEFAULT_PATHS, PROJECT_ROOT, ProjectPaths
from persistence.personal_academic_repository import (
    build_personal_academic_repository,
)


def test_project_paths_reserve_local_and_shared_layout(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    assert paths.user_profile_path("test-user") == (
        tmp_path / "users" / "test-user" / "user.json"
    )
    assert paths.personal_academics_path("test-user") == (
        tmp_path / "users" / "test-user" / "tables" / "academics.csv"
    )
    assert paths.personal_outbox_dir("test-user") == (
        tmp_path / "users" / "test-user" / "outbox"
    )
    assert paths.owner_local_path == tmp_path / "config" / "owner.local.json"
    assert paths.approved_users_path == (
        tmp_path / "data" / "public" / "approved_users.json"
    )
    assert paths.tables_index_path == (
        tmp_path / "data" / "public" / "tables_index.json"
    )
    assert paths.public_tables_dir == tmp_path / "data" / "public" / "tables"
    assert paths.academic_staff_catalog_path == (
        tmp_path / "data" / "public" / "catalogs" / "academic_staff.csv"
    )
    assert paths.academic_profiles_catalog_path == (
        tmp_path / "data" / "public" / "catalogs" / "academic_profiles.csv"
    )
    assert paths.personal_academic_appointments_path("test-user") == (
        tmp_path / "users" / "test-user" / "tables" / "academic_appointments.csv"
    )
    assert paths.error_notifications_path == (
        tmp_path / "data" / "public" / "notifications_error.json"
    )
    assert paths.personal_table_metadata_path("test-user") == (
        tmp_path / "users" / "test-user" / "tables" / "table_metadata.json"
    )
    assert paths.personal_share_intent_path("test-user") == (
        tmp_path / "users" / "test-user" / "outbox" / "table_share.json"
    )
    assert paths.publication_operations_dir("test-user") == (
        tmp_path / "users" / "test-user" / "outbox" / "publications"
    )
    assert paths.publication_operation_dir("test-user", "operation-id") == (
        tmp_path / "users" / "test-user" / "outbox" / "publications" / "operation-id"
    )
    shared = paths.shared_table_path("table-000001-test-user.csv")
    assert paths.academic_appointments_path(shared) == (
        paths.public_tables_dir / "table-000001-test-user.appointments.csv"
    )


@pytest.mark.parametrize("username", ["", ".", "..", "a/b", "a\\b"])
def test_user_paths_reject_non_component_usernames(username: str) -> None:
    with pytest.raises(ValueError):
        DEFAULT_PATHS.user_dir(username)


def test_personal_repository_reuses_csv_adapter_without_creating_files(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)

    repository = build_personal_academic_repository("test-user", paths=paths)

    assert repository.path == paths.personal_academics_path("test-user")
    assert not paths.users_dir.exists()


def test_existing_shared_registry_files_keep_valid_top_level_shapes() -> None:
    expected_collections = {
        DEFAULT_PATHS.approved_users_path: "approved_users",
        DEFAULT_PATHS.tables_index_path: "tables",
    }

    expected_versions = {
        DEFAULT_PATHS.approved_users_path: 2,
        DEFAULT_PATHS.tables_index_path: 2,
    }
    for path, collection_name in expected_collections.items():
        document = json.loads(path.read_text(encoding="utf-8"))
        assert set(document) == {"schema_version", collection_name}
        assert document["schema_version"] == expected_versions[path]
        assert isinstance(document[collection_name], list)

    owner_text = DEFAULT_PATHS.owner_example_path.read_text(encoding="utf-8")
    assert owner_text == '{\n  "schema_version": 1,\n  "username": null\n}\n'
    owner_example = json.loads(owner_text)
    assert owner_example == {"schema_version": 1, "username": None}


def test_owner_local_configuration_is_ignored_and_untracked() -> None:
    ignore_rules = (
        (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    )
    assert "config/owner.local.json" in ignore_rules
    if not (PROJECT_ROOT / ".git").is_dir():
        return

    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "config/owner.local.json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "config/owner.local.json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )

    assert ignored.returncode == 0
    assert tracked.returncode != 0


def test_distributed_notifications_are_empty_valid_v3() -> None:
    path = DEFAULT_PATHS.error_notifications_path
    before = path.read_bytes()
    document = json.loads(before)
    assert document.get("schema_version") == 3
    assert document.get("notifications") == []
    notifications = JsonErrorNotificationRepository(DEFAULT_PATHS).list_all()
    assert notifications == []
    assert path.read_bytes() == before


def test_all_required_view_routes_are_active() -> None:
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert ACTIVE_ROUTES.isdisjoint(RESERVED_ROUTES)
    assert ACTIVE_ROUTES == frozenset(FrontendRoute)
    assert RESERVED_ROUTES == frozenset()
    assert approval_view.ROUTE is FrontendRoute.APPROVAL
    assert error_notification_view.ROUTE is FrontendRoute.ERROR_NOTIFICATION
    assert update_view.ROUTE is FrontendRoute.UPDATE
