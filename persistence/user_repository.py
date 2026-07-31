"""Local user profiles containing only derived password-verification material."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime

from persistence.atomic_json_repository import (
    AtomicJsonRepository,
    JsonDocument,
    JsonDocumentCorruptError,
)
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username

USER_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StoredUser:
    """Password verifier data kept in a user's private local profile."""

    username: str
    algorithm: str
    salt: bytes
    password_hash: bytes
    n: int
    r: int
    p: int
    length: int
    created_at: str


class UserAlreadyExistsError(RuntimeError):
    """The canonical username already owns a local directory."""


class UserNotFoundError(RuntimeError):
    """No usable local profile exists for the canonical username."""


def _validate_user_document(document: JsonDocument) -> None:
    if document.get("schema_version") != USER_SCHEMA_VERSION:
        raise ValueError("Versión de perfil no soportada.")
    username = document.get("username")
    if not isinstance(username, str) or normalize_username(username) != username:
        raise ValueError("Nombre de usuario inválido.")
    created_at = document.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise ValueError("Fecha de creación inválida.")
    verifier = document.get("password_verifier")
    if not isinstance(verifier, dict):
        raise ValueError("Verificador de contraseña ausente.")
    if verifier.get("algorithm") != "scrypt":
        raise ValueError("Algoritmo de contraseña no soportado.")
    for key in ("salt", "hash"):
        value = verifier.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError("Verificador de contraseña inválido.")
        try:
            base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("Verificador de contraseña inválido.") from error
    for key in ("n", "r", "p", "length"):
        value = verifier.get(key)
        if type(value) is not int or value <= 0:
            raise ValueError("Parámetros de contraseña inválidos.")


class JsonUserRepository:
    """Create and load fail-closed local user profiles."""

    def __init__(self, paths: ProjectPaths = DEFAULT_PATHS) -> None:
        self.paths = paths

    def exists(self, username: str) -> bool:
        canonical = normalize_username(username)
        return self.paths.user_profile_path(canonical).is_file()

    def create(
        self,
        username: str,
        *,
        algorithm: str,
        salt: bytes,
        password_hash: bytes,
        n: int,
        r: int,
        p: int,
        length: int,
    ) -> StoredUser:
        canonical = normalize_username(username)
        user_directory = self.paths.user_dir(canonical)
        try:
            user_directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise UserAlreadyExistsError(
                "El nombre de usuario ya está registrado."
            ) from error

        created_at = datetime.now(UTC).isoformat()
        document: JsonDocument = {
            "schema_version": USER_SCHEMA_VERSION,
            "username": canonical,
            "created_at": created_at,
            "password_verifier": {
                "algorithm": algorithm,
                "salt": base64.b64encode(salt).decode("ascii"),
                "hash": base64.b64encode(password_hash).decode("ascii"),
                "n": n,
                "r": r,
                "p": p,
                "length": length,
            },
        }
        self._store(canonical).write(document)
        CsvAcademicRepository(
            self.paths.personal_academics_path(canonical)
        ).replace_all([])
        return self._to_user(document)

    def get(self, username: str) -> StoredUser:
        canonical = normalize_username(username)
        path = self.paths.user_profile_path(canonical)
        if not path.exists():
            raise UserNotFoundError("Las credenciales no son válidas.")
        try:
            document = self._store(canonical).read()
        except JsonDocumentCorruptError as error:
            raise UserNotFoundError(
                "El perfil local está dañado y fue aislado para recuperación."
            ) from error
        user = self._to_user(document)
        if user.username != canonical:
            raise UserNotFoundError("El perfil local no corresponde al usuario.")
        return user

    def list_usernames(self) -> list[str]:
        if not self.paths.users_dir.is_dir():
            return []
        usernames: list[str] = []
        for child in self.paths.users_dir.iterdir():
            if not child.is_dir() or not (child / "user.json").is_file():
                continue
            try:
                canonical = normalize_username(child.name)
                self.get(canonical)
            except ValueError, UserNotFoundError:
                continue
            usernames.append(canonical)
        return sorted(usernames)

    def _store(self, username: str) -> AtomicJsonRepository:
        # Invalid credentials must never be replaced with an empty profile.
        empty = {
            "schema_version": USER_SCHEMA_VERSION,
            "username": username,
            "created_at": datetime.now(UTC).isoformat(),
            "password_verifier": {
                "algorithm": "scrypt",
                "salt": "AA==",
                "hash": "AA==",
                "n": 1,
                "r": 1,
                "p": 1,
                "length": 1,
            },
        }
        return AtomicJsonRepository(
            self.paths.user_profile_path(username),
            empty_document=empty,
            validator=_validate_user_document,
            recover_corrupt=False,
            file_mode=0o600,
        )

    @staticmethod
    def _to_user(document: JsonDocument) -> StoredUser:
        verifier = document["password_verifier"]
        assert isinstance(verifier, dict)
        return StoredUser(
            username=str(document["username"]),
            algorithm=str(verifier["algorithm"]),
            salt=base64.b64decode(str(verifier["salt"]), validate=True),
            password_hash=base64.b64decode(str(verifier["hash"]), validate=True),
            n=int(verifier["n"]),
            r=int(verifier["r"]),
            p=int(verifier["p"]),
            length=int(verifier["length"]),
            created_at=str(document["created_at"]),
        )
