"""Single-file local account storage for derived password verifiers only."""

from __future__ import annotations

import base64
from dataclasses import dataclass

from persistence.atomic_json_repository import (
    AtomicJsonRepository,
    JsonDocument,
    JsonDocumentCorruptError,
)
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username

USER_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StoredUser:
    """Password verifier data kept in the consolidated local account file."""

    username: str
    algorithm: str
    salt: bytes
    password_hash: bytes
    n: int
    r: int
    p: int
    length: int


class UserAlreadyExistsError(RuntimeError):
    """The canonical username already exists in the local account file."""


class UserNotFoundError(RuntimeError):
    """No usable local profile exists for the canonical username."""


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("Verificador de contraseña inválido.")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("Verificador de contraseña inválido.") from error
    if not decoded or base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("Verificador de contraseña inválido.")
    return decoded


def _validate_verifier(verifier: object) -> None:
    if not isinstance(verifier, dict) or set(verifier) != {
        "algorithm",
        "salt",
        "hash",
        "n",
        "r",
        "p",
        "length",
    }:
        raise ValueError("Verificador de contraseña inválido.")
    if verifier["algorithm"] != "scrypt":
        raise ValueError("Algoritmo de contraseña no soportado.")
    salt = _decode_base64(verifier["salt"])
    password_hash = _decode_base64(verifier["hash"])
    if len(salt) < 16:
        raise ValueError("Salt de contraseña inválido.")
    for key in ("n", "r", "p", "length"):
        value = verifier[key]
        if type(value) is not int or value <= 0:
            raise ValueError("Parámetros de contraseña inválidos.")
    n = verifier["n"]
    if n <= 1 or n & (n - 1):
        raise ValueError("Parámetro scrypt inválido.")
    if len(password_hash) != verifier["length"]:
        raise ValueError("Longitud del verificador inválida.")


def _validate_user_document(document: JsonDocument) -> None:
    if set(document) != {"schema_version", "users"}:
        raise ValueError("Estructura de cuentas inválida.")
    if document.get("schema_version") != USER_SCHEMA_VERSION:
        raise ValueError("Versión de cuentas no soportada.")
    users = document.get("users")
    if not isinstance(users, list):
        raise ValueError("Lista de cuentas inválida.")
    usernames: set[str] = set()
    for user in users:
        if not isinstance(user, dict) or set(user) != {
            "username",
            "password_verifier",
        }:
            raise ValueError("Cuenta local inválida.")
        username = user["username"]
        if not isinstance(username, str):
            raise ValueError("Nombre de usuario inválido.")
        try:
            canonical = normalize_username(username)
        except ValueError as error:
            raise ValueError("Nombre de usuario inválido.") from error
        if canonical != username or canonical in usernames:
            raise ValueError("Nombre de usuario duplicado o no normalizado.")
        _validate_verifier(user["password_verifier"])
        usernames.add(canonical)


class JsonUserRepository:
    """Create and load accounts from one fail-closed atomic JSON document."""

    def __init__(self, paths: ProjectPaths = DEFAULT_PATHS) -> None:
        self.paths = paths

    def exists(self, username: str) -> bool:
        canonical = normalize_username(username)
        return any(item.username == canonical for item in self._read_users_if_present())

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
        document = self._read_document_if_present()
        users = document["users"]
        assert isinstance(users, list)
        if any(
            isinstance(item, dict) and item.get("username") == canonical
            for item in users
        ):
            raise UserAlreadyExistsError("El nombre de usuario ya está registrado.")
        user_document: JsonDocument = {
            "username": canonical,
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
        users.append(user_document)
        users.sort(
            key=lambda item: (
                str(item.get("username", "")) if isinstance(item, dict) else ""
            )
        )
        self._store().write(document)
        return self._to_user(user_document)

    def get(self, username: str) -> StoredUser:
        canonical = normalize_username(username)
        for user in self._read_users_if_present():
            if user.username == canonical:
                return user
        raise UserNotFoundError("Las credenciales no son válidas.")

    def list_usernames(self) -> list[str]:
        return [user.username for user in self._read_users_if_present()]

    def _read_document_if_present(self) -> JsonDocument:
        if not self.paths.local_users_path.exists():
            return {
                "schema_version": USER_SCHEMA_VERSION,
                "users": [],
            }
        try:
            return self._store().read()
        except JsonDocumentCorruptError as error:
            raise UserNotFoundError(
                "El archivo local de cuentas está dañado y fue aislado."
            ) from error

    def _read_users_if_present(self) -> list[StoredUser]:
        document = self._read_document_if_present()
        users = document["users"]
        assert isinstance(users, list)
        return [self._to_user(item) for item in users if isinstance(item, dict)]

    def _store(self) -> AtomicJsonRepository:
        empty: JsonDocument = {
            "schema_version": USER_SCHEMA_VERSION,
            "users": [],
        }
        return AtomicJsonRepository(
            self.paths.local_users_path,
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
        )
