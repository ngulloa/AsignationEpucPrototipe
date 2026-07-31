"""Canonical project paths, resolved independently of the working directory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_SAFE_USERNAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,30}[a-z0-9])?$", re.ASCII)
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


def _path_component(value: str, *, label: str) -> str:
    component = value.strip()
    if (
        not component
        or component in {".", ".."}
        or "/" in component
        or "\\" in component
    ):
        raise ValueError(f"{label} debe ser un único componente de ruta.")
    return component


def normalize_username(value: str) -> str:
    """Return the canonical lowercase form of a route-safe username."""
    username = value.strip().lower()
    if not _SAFE_USERNAME.fullmatch(username):
        raise ValueError(
            "El nombre de usuario debe tener entre 1 y 32 caracteres y usar "
            "solo letras ASCII minúsculas, números, punto, guion o guion bajo."
        )
    if username.split(".", maxsplit=1)[0] in _WINDOWS_RESERVED_NAMES:
        raise ValueError("El nombre de usuario está reservado por el sistema.")
    return username


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Derive every local and shared storage location from one explicit root."""

    root: Path

    def __post_init__(self) -> None:
        resolved_root = self.root.expanduser().resolve(strict=False)
        object.__setattr__(self, "root", resolved_root)

    @property
    def users_dir(self) -> Path:
        return self.root / "users"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def owner_local_path(self) -> Path:
        return self.config_dir / "owner.local.json"

    @property
    def owner_example_path(self) -> Path:
        return self.config_dir / "owner.example.json"

    @property
    def frontend_visual_settings_path(self) -> Path:
        return self.config_dir / "frontend_visual.json"

    @property
    def frontend_text_settings_path(self) -> Path:
        return self.config_dir / "frontend_texts.json"

    @property
    def public_data_dir(self) -> Path:
        return self.root / "data" / "public"

    @property
    def approved_users_path(self) -> Path:
        return self.public_data_dir / "approved_users.json"

    @property
    def tables_index_path(self) -> Path:
        return self.public_data_dir / "tables_index.json"

    @property
    def public_tables_dir(self) -> Path:
        return self.public_data_dir / "tables"

    @property
    def error_notifications_path(self) -> Path:
        return self.public_data_dir / "notifications_error.json"

    @property
    def operational_academics_path(self) -> Path:
        return self.root / "data" / "Academic.csv"

    def user_dir(self, username: str) -> Path:
        return self.users_dir / normalize_username(username)

    def user_profile_path(self, username: str) -> Path:
        return self.user_dir(username) / "user.json"

    def personal_academics_path(self, username: str) -> Path:
        return self.user_dir(username) / "tables" / "academics.csv"

    def personal_outbox_dir(self, username: str) -> Path:
        return self.user_dir(username) / "outbox"

    def personal_error_queue_path(self, username: str) -> Path:
        return self.personal_outbox_dir(username) / "error_notifications.json"

    def notifications_seen_path(self, username: str) -> Path:
        return self.user_dir(username) / "notifications_seen.json"

    def shared_table_path(self, filename: str) -> Path:
        return self.public_tables_dir / _path_component(filename, label="filename")


DEFAULT_PATHS = ProjectPaths(PROJECT_ROOT)
