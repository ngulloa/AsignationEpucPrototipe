"""Structural checks for the final application surface and persisted data."""

from __future__ import annotations

from pathlib import Path

from frontend.navigation import ACTIVE_ROUTES, RESERVED_ROUTES, FrontendRoute
from persistence.paths import DEFAULT_PATHS, PROJECT_ROOT, ProjectPaths


def _python_names(directory: Path) -> set[str]:
    return {path.name for path in directory.glob("*.py")}


def test_project_paths_expose_only_active_storage_locations(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)

    assert paths.local_users_path == tmp_path / "data" / "local" / "users.json"
    assert paths.academic_path == (
        tmp_path / "data" / "public" / "tables" / "Academic.csv"
    )
    assert paths.public_tables_dir == tmp_path / "data" / "public" / "tables"
    assert paths.academic_staff_catalog_path == (
        tmp_path / "data" / "public" / "catalogs" / "academic_staff.csv"
    )
    assert paths.academic_profiles_catalog_path == (
        tmp_path / "data" / "public" / "catalogs" / "academic_profiles.csv"
    )


def test_source_packages_contain_only_product_modules() -> None:
    assert _python_names(PROJECT_ROOT / "backend") == {
        "__init__.py",
        "academic_catalog.py",
        "academic_repository.py",
        "academic_service.py",
        "application_service.py",
        "authentication.py",
        "composition.py",
        "contracts.py",
        "frontend_controller.py",
        "git_sync.py",
        "rut_validator.py",
        "session.py",
    }
    assert _python_names(PROJECT_ROOT / "persistence") == {
        "__init__.py",
        "atomic_json_repository.py",
        "csv_academic_repository.py",
        "paths.py",
        "settings_repository.py",
        "user_repository.py",
    }
    assert _python_names(PROJECT_ROOT / "frontend" / "views") == {
        "__init__.py",
        "academic_form_view.py",
        "academics_list_view.py",
        "login_view.py",
        "main_menu_view.py",
        "register_view.py",
    }
    assert not (PROJECT_ROOT / "scripts").exists()
    assert not (PROJECT_ROOT / "users").exists()
    assert not (PROJECT_ROOT / "docs").exists()
    assert not (PROJECT_ROOT / "design.prototipe").exists()


def test_public_data_contains_only_catalogs_and_academic_csv() -> None:
    files = {
        path.relative_to(DEFAULT_PATHS.public_data_dir).as_posix()
        for path in DEFAULT_PATHS.public_data_dir.rglob("*")
        if path.is_file()
    }
    assert files == {
        "catalogs/academic_profiles.csv",
        "catalogs/academic_staff.csv",
        "tables/Academic.csv",
    }
    assert DEFAULT_PATHS.academic_path.read_bytes() == (
        b"academic_id,rut,name,plant,profile,weekly_hours,status\n"
    )


def test_navigation_contains_only_the_five_active_routes() -> None:
    assert PROJECT_ROOT == Path(__file__).resolve().parents[1]
    assert ACTIVE_ROUTES.isdisjoint(RESERVED_ROUTES)
    assert ACTIVE_ROUTES == frozenset(FrontendRoute)
    assert RESERVED_ROUTES == frozenset()
