"""Structural tests for the reserved users, sharing and synchronization system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frontend.navigation import ACTIVE_ROUTES, RESERVED_ROUTES, FrontendRoute
from frontend.views import approval_view, error_notification_view, update_view
from persistence.error_notification_repository import (
    JsonErrorNotificationRepository,
    NotificationMigrationRequiredError,
)
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
    assert paths.error_notifications_path == (
        tmp_path / "data" / "public" / "notifications_error.json"
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

    for path, collection_name in expected_collections.items():
        document = json.loads(path.read_text(encoding="utf-8"))
        assert set(document) == {"schema_version", collection_name}
        assert document["schema_version"] == 1
        assert isinstance(document[collection_name], list)

    owner_example = json.loads(DEFAULT_PATHS.owner_example_path.read_text("utf-8"))
    assert owner_example == {"schema_version": 1, "username": None}


def test_nonempty_real_legacy_notifications_are_preserved_for_migration() -> None:
    path = DEFAULT_PATHS.error_notifications_path
    before = path.read_bytes()
    document = json.loads(before)
    assert document.get("schema_version") == 1
    assert document.get("notifications")

    with pytest.raises(NotificationMigrationRequiredError):
        JsonErrorNotificationRepository(DEFAULT_PATHS).list_all()

    assert path.read_bytes() == before


def test_all_required_view_routes_are_active() -> None:
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert ACTIVE_ROUTES.isdisjoint(RESERVED_ROUTES)
    assert ACTIVE_ROUTES == frozenset(FrontendRoute)
    assert RESERVED_ROUTES == frozenset()
    assert approval_view.ROUTE is FrontendRoute.APPROVAL
    assert error_notification_view.ROUTE is FrontendRoute.ERROR_NOTIFICATION
    assert update_view.ROUTE is FrontendRoute.UPDATE
