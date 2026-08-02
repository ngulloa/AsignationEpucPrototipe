"""Characterize the local authentication and process-session contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.authentication import (
    InvalidPasswordError,
    LocalAuthenticationService,
    validate_password,
)
from backend.session import InMemorySession
from persistence.paths import ProjectPaths, normalize_username
from persistence.user_repository import JsonUserRepository


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("A", "a"),
        (" Usuario.Demo_1 ", "usuario.demo_1"),
        ("a" * 32, "a" * 32),
    ],
)
def test_current_username_validation_accepts_only_canonical_safe_components(
    raw: str,
    canonical: str,
) -> None:
    assert normalize_username(raw) == canonical


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "a" * 33,
        ".usuario",
        "usuario-",
        "dos usuarios",
        "usuário",
        "ruta/usuario",
        "ruta\\usuario",
        "con",
        "nul.txt",
    ],
)
def test_current_username_validation_rejects_unsafe_or_reserved_components(
    invalid: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_username(invalid)


@pytest.mark.parametrize("password", ["1234", "12345678", "    "])
def test_current_password_validation_accepts_four_to_eight_characters_verbatim(
    password: str,
) -> None:
    assert validate_password(password) is None


@pytest.mark.parametrize("password", ["123", "123456789", "", None])
def test_current_password_validation_rejects_values_outside_the_length_contract(
    password: object,
) -> None:
    with pytest.raises(
        InvalidPasswordError,
        match="La contraseña debe tener entre 4 y 8 caracteres.",
    ):
        validate_password(password)  # type: ignore[arg-type]


def test_registration_survives_process_restart_and_logout_clears_each_session(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    first_process_session = InMemorySession()
    first_process = LocalAuthenticationService(
        JsonUserRepository(paths),
        first_process_session,
    )

    registered = first_process.register_user(" Usuario.Demo ", "1234")

    assert registered.username == "usuario.demo"
    assert first_process_session.current_session == registered
    first_process.logout()
    assert first_process_session.current_session is None

    restarted_session = InMemorySession()
    restarted_process = LocalAuthenticationService(
        JsonUserRepository(paths),
        restarted_session,
    )
    assert restarted_session.current_session is None

    authenticated = restarted_process.authenticate("USUARIO.DEMO", "1234")

    assert authenticated.username == registered.username
    assert restarted_session.current_session == authenticated
    restarted_process.logout()
    assert restarted_session.current_session is None
