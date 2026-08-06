"""Locked, staged, validated multi-file transactions for public CSV data."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from persistence.data_model import validate_dataset
from persistence.paths import ProjectPaths


class DataConcurrencyError(RuntimeError):
    pass


class DataTransactionError(RuntimeError):
    pass


def _fingerprint(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.csv")):
        digest.update(path.relative_to(folder).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class CsvUnitOfWork:
    """Copy the logical dataset, validate it, then replace it with rollback."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths
        self.stage_root: Path | None = None
        self.public_dir: Path | None = None
        self._baseline = ""
        self._lock_fd: int | None = None

    def __enter__(self) -> CsvUnitOfWork:
        self.paths.local_data_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._lock_fd = os.open(
                self.paths.write_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            os.write(self._lock_fd, str(os.getpid()).encode("ascii"))
        except FileExistsError as error:
            raise DataConcurrencyError(
                "Otra instancia está modificando los datos académicos."
            ) from error
        self._baseline = _fingerprint(self.paths.public_data_dir)
        self.paths.staging_dir.mkdir(parents=True, exist_ok=True)
        self.stage_root = Path(
            tempfile.mkdtemp(prefix="transaction-", dir=self.paths.staging_dir)
        )
        self.public_dir = self.stage_root / "public"
        shutil.copytree(self.paths.public_data_dir, self.public_dir)
        return self

    def commit(self) -> Path:
        if self.public_dir is None:
            raise DataTransactionError("La transacción no está activa.")
        validate_dataset(self.public_dir)
        if _fingerprint(self.paths.public_data_dir) != self._baseline:
            raise DataConcurrencyError(
                "Los archivos fueron modificados externamente; recargue e intente nuevamente."
            )
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f%z")
        backup = self.paths.backups_dir / f"transaction-{stamp}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.paths.public_data_dir, backup / "public")
        live = self.paths.public_data_dir
        displaced = self.stage_root / "previous-public"
        try:
            os.replace(live, displaced)
            os.replace(self.public_dir, live)
            validate_dataset(live)
        except Exception as error:
            if live.exists():
                shutil.rmtree(live)
            if displaced.exists():
                os.replace(displaced, live)
            raise DataTransactionError(
                "La operación fue revertida; no se modificó el conjunto operacional."
            ) from error
        shutil.rmtree(displaced)
        self._baseline = _fingerprint(live)
        return backup

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.stage_root is not None:
            shutil.rmtree(self.stage_root, ignore_errors=True)
        if self._lock_fd is not None:
            os.close(self._lock_fd)
        self.paths.write_lock_path.unlink(missing_ok=True)
