"""Canonical project paths, resolved independently of the working directory."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_project_root() -> Path:
    source_root = Path(__file__).resolve().parents[1]
    if (source_root / "config" / "frontend_texts.json").is_file():
        return source_root
    installed_root = Path(sys.prefix).resolve()
    if (installed_root / "config" / "frontend_texts.json").is_file():
        return installed_root
    return source_root


PROJECT_ROOT = _default_project_root()

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
    def config_dir(self) -> Path:
        return self.root / "config"

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
    def local_data_dir(self) -> Path:
        return self.root / "data" / "local"

    @property
    def local_users_path(self) -> Path:
        return self.local_data_dir / "users.json"

    @property
    def write_lock_path(self) -> Path:
        return self.local_data_dir / "academic-data.write.lock"

    @property
    def staging_dir(self) -> Path:
        return self.local_data_dir / "staging"

    @property
    def backups_dir(self) -> Path:
        return self.local_data_dir / "backups"

    @property
    def public_tables_dir(self) -> Path:
        return self.public_data_dir / "tables"

    @property
    def academic_path(self) -> Path:
        """Return the sole authoritative academic register path."""
        return self.public_tables_dir / "Academic.csv"

    @property
    def academic_catalogs_dir(self) -> Path:
        return self.public_data_dir / "catalogs"

    @property
    def academic_staff_catalog_path(self) -> Path:
        return self.academic_catalogs_dir / "academic_staff.csv"

    @property
    def academic_profiles_catalog_path(self) -> Path:
        return self.academic_catalogs_dir / "academic_profiles.csv"

    def table_path(self, filename: str) -> Path:
        return self.public_tables_dir / filename

    def catalog_path(self, filename: str) -> Path:
        return self.academic_catalogs_dir / filename


DEFAULT_PATHS = ProjectPaths(PROJECT_ROOT)
