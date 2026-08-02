"""Stage-two authentication, persistence, session and route boundaries."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from backend.authentication import AuthenticationError, LocalAuthenticationService
from backend.session import InMemorySession
from frontend.frontend_main import LOGIN_SCREEN, MENU_SCREEN
from frontend.navigation import ACTIVE_ROUTES, RESERVED_ROUTES, FrontendRoute
from main import build_production_application_window
from persistence.atomic_json_repository import JsonDocumentIOError
from persistence.paths import PROJECT_ROOT, ProjectPaths
from persistence.user_repository import JsonUserRepository


def _authentication(paths: ProjectPaths) -> LocalAuthenticationService:
    return LocalAuthenticationService(JsonUserRepository(paths), InMemorySession())


def test_first_registration_creates_only_strict_consolidated_account_store(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    authentication = _authentication(paths)

    session = authentication.register_user(" Persona.Sintetica ", "1234")

    assert session.username == "persona.sintetica"
    assert paths.local_users_path.is_file()
    assert not (tmp_path / "users").exists()
    assert not paths.public_data_dir.exists()
    document = json.loads(paths.local_users_path.read_text(encoding="utf-8"))
    assert set(document) == {"schema_version", "users"}
    assert document["schema_version"] == 1
    assert len(document["users"]) == 1
    account = document["users"][0]
    assert set(account) == {"username", "password_verifier"}
    assert account["username"] == "persona.sintetica"
    assert set(account["password_verifier"]) == {
        "algorithm",
        "salt",
        "hash",
        "n",
        "r",
        "p",
        "length",
    }
    assert account["password_verifier"]["algorithm"] == "scrypt"
    assert "1234" not in paths.local_users_path.read_text(encoding="utf-8")
    assert os.stat(paths.local_users_path).st_mode & 0o777 == 0o600


def test_failed_authentication_does_not_create_a_store_and_is_generic(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    authentication = _authentication(paths)

    for username, password in (("missing", "1234"), ("ruta/usuario", "1234")):
        with pytest.raises(
            AuthenticationError,
            match=r"^Las credenciales no son válidas\.$",
        ):
            authentication.authenticate(username, password)

    assert not paths.local_users_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_existing_account_uses_constant_time_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = ProjectPaths(tmp_path)
    authentication = _authentication(paths)
    authentication.register_user("persona.sintetica", "1234")
    authentication.logout()
    calls: list[tuple[bytes, bytes]] = []

    def controlled_compare(candidate: bytes, expected: bytes) -> bool:
        calls.append((candidate, expected))
        return False

    monkeypatch.setattr(
        "backend.authentication.hmac.compare_digest", controlled_compare
    )

    with pytest.raises(
        AuthenticationError,
        match=r"^Las credenciales no son válidas\.$",
    ):
        authentication.authenticate("persona.sintetica", "5678")

    assert len(calls) == 1
    assert all(isinstance(value, bytes) for value in calls[0])


def test_atomic_replacement_failure_preserves_previous_accounts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = ProjectPaths(tmp_path)
    authentication = _authentication(paths)
    authentication.register_user("primera.cuenta", "1234")
    before = paths.local_users_path.read_bytes()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("controlled replacement failure")

    monkeypatch.setattr("persistence.atomic_json_repository.os.replace", fail_replace)
    with pytest.raises(JsonDocumentIOError):
        authentication.register_user("segunda.cuenta", "5678")

    assert paths.local_users_path.read_bytes() == before
    assert not list(paths.local_data_dir.glob("*.tmp"))


def test_removed_profile_layout_is_never_used_as_account_fallback(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    seed = _authentication(paths)
    seed.register_user("perfil.local", "1234")
    consolidated = json.loads(paths.local_users_path.read_text(encoding="utf-8"))
    account = consolidated["users"][0]
    removed_profile = tmp_path / "users" / "perfil.local" / "user.json"
    removed_profile.parent.mkdir(parents=True)
    removed_profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "username": "perfil.local",
                "created_at": "2026-08-01T00:00:00+00:00",
                "password_verifier": account["password_verifier"],
            }
        ),
        encoding="utf-8",
    )
    paths.local_users_path.unlink()

    restarted = _authentication(paths)
    with pytest.raises(AuthenticationError):
        restarted.authenticate("perfil.local", "1234")

    assert removed_profile.is_file()
    assert not paths.local_users_path.exists()


def test_registration_restart_logout_and_login_use_only_consolidated_store(
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    first_window = build_production_application_window(paths=paths)
    qtbot.addWidget(first_window)
    first_window.show()
    qtbot.mouseClick(
        first_window.login_view.register_button,
        Qt.MouseButton.LeftButton,
    )
    registration = first_window.register_view
    registration.username_input.setText("cuenta.reinicio")
    registration.password_input.setText("1234")
    registration.confirmation_input.setText("1234")
    qtbot.mouseClick(registration.register_button, Qt.MouseButton.LeftButton)

    assert first_window.current_screen == MENU_SCREEN
    assert first_window.authenticated_username == "cuenta.reinicio"
    assert paths.local_users_path.is_file()
    assert not (tmp_path / "users").exists()
    qtbot.mouseClick(
        first_window.main_menu_view.header.logout_button,
        Qt.MouseButton.LeftButton,
    )
    assert first_window.current_screen == LOGIN_SCREEN
    assert first_window.authenticated_username == ""

    restarted_window = build_production_application_window(paths=paths)
    qtbot.addWidget(restarted_window)
    restarted_window.login_view.username_input.setText("CUENTA.REINICIO")
    restarted_window.login_view.password_input.setText("1234")
    qtbot.mouseClick(
        restarted_window.login_view.login_button,
        Qt.MouseButton.LeftButton,
    )

    assert restarted_window.current_screen == MENU_SCREEN
    assert restarted_window.authenticated_username == "cuenta.reinicio"
    assert not (tmp_path / "users").exists()


def test_only_five_routes_are_active() -> None:
    assert ACTIVE_ROUTES == frozenset(FrontendRoute)
    assert {route.value for route in ACTIVE_ROUTES} == {
        "login",
        "register",
        "menu",
        "academic_list",
        "academic_form",
    }
    assert RESERVED_ROUTES == frozenset()
    assert ACTIVE_ROUTES.isdisjoint(RESERVED_ROUTES)


def test_consolidated_account_store_is_git_ignored() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "data/local/users.json"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "data/local/users.json"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
    )

    assert ignored.returncode == 0
    assert tracked.returncode != 0
