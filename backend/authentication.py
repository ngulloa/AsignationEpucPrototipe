"""Backend boundary for future local authentication."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from backend.session import SessionMemory
from backend.system_contracts import AuthenticatedSession
from persistence.paths import normalize_username
from persistence.user_repository import (
    JsonUserRepository,
    UserAlreadyExistsError,
    UserNotFoundError,
)

MIN_PASSWORD_LENGTH = 4
MAX_PASSWORD_LENGTH = 8
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LENGTH = 32
SALT_LENGTH = 16


class AuthenticationError(RuntimeError):
    """A presentation-safe authentication or registration failure."""


class InvalidUsernameError(AuthenticationError):
    """A username cannot be represented as one safe route component."""


class InvalidPasswordError(AuthenticationError):
    """A password does not meet the local length contract."""


def validate_password(password: str) -> None:
    """Enforce the deliberately short MVP password contract without trimming."""
    if not isinstance(password, str) or not (
        MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH
    ):
        raise InvalidPasswordError("La contraseña debe tener entre 4 y 8 caracteres.")


class LocalAuthenticationService:
    """Register and authenticate local users with stdlib scrypt verifiers."""

    __slots__ = ("_sessions", "_users")

    def __init__(
        self,
        users: JsonUserRepository,
        sessions: SessionMemory,
    ) -> None:
        self._users = users
        self._sessions = sessions

    def register_user(self, username: str, password: str) -> AuthenticatedSession:
        self._sessions.clear_session()
        try:
            canonical = normalize_username(username)
        except ValueError as error:
            raise InvalidUsernameError(str(error)) from error
        validate_password(password)
        salt = secrets.token_bytes(SALT_LENGTH)
        password_hash = self._derive(
            password,
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            length=SCRYPT_LENGTH,
        )
        try:
            self._users.create(
                canonical,
                algorithm="scrypt",
                salt=salt,
                password_hash=password_hash,
                n=SCRYPT_N,
                r=SCRYPT_R,
                p=SCRYPT_P,
                length=SCRYPT_LENGTH,
            )
        except UserAlreadyExistsError as error:
            raise AuthenticationError(
                "El nombre de usuario ya está registrado."
            ) from error
        session = AuthenticatedSession(canonical)
        self._sessions.establish_session(session)
        return session

    def authenticate(self, username: str, password: str) -> AuthenticatedSession:
        self._sessions.clear_session()
        try:
            canonical = normalize_username(username)
            validate_password(password)
            user = self._users.get(canonical)
            candidate = self._derive(
                password,
                salt=user.salt,
                n=user.n,
                r=user.r,
                p=user.p,
                length=user.length,
            )
        except (ValueError, AuthenticationError, UserNotFoundError) as error:
            raise AuthenticationError("Las credenciales no son válidas.") from error

        if user.algorithm != "scrypt" or not hmac.compare_digest(
            candidate, user.password_hash
        ):
            raise AuthenticationError("Las credenciales no son válidas.")
        session = AuthenticatedSession(user.username)
        self._sessions.establish_session(session)
        return session

    def logout(self) -> None:
        self._sessions.clear_session()

    @staticmethod
    def _derive(
        password: str,
        *,
        salt: bytes,
        n: int,
        r: int,
        p: int,
        length: int,
    ) -> bytes:
        try:
            return hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=n,
                r=r,
                p=p,
                dklen=length,
                maxmem=64 * 1024 * 1024,
            )
        except (ValueError, OSError) as error:
            raise AuthenticationError(
                "No fue posible verificar las credenciales localmente."
            ) from error
