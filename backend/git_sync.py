"""Git synchronization restricted to the one authoritative academic CSV."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path, PurePosixPath

from backend.academic_catalog import get_academic_catalogs
from backend.academic_repository import AcademicRepositoryError
from backend.contracts import UpdateResult
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import ProjectPaths

PRODUCTIVE_REMOTE_URL = "https://github.com/ngulloa/AsignationEpucPrototipe.git"
REMOTE_NAME = "origin"
BRANCH_NAME = "main"
ACADEMIC_PATH = "data/public/tables/Academic.csv"
COMMIT_MESSAGE = "Actualizar Academic.csv"

RunCommand = Callable[..., subprocess.CompletedProcess[str]]
CsvValidator = Callable[[Path], object]


class GitServiceError(RuntimeError):
    """A sanitized, user-facing synchronization failure."""


class GitUnavailableError(GitServiceError):
    """Git is not installed or cannot be executed."""


class GitConfigurationError(GitServiceError):
    """The repository, remote URL, or fixed branch is not configured safely."""


class GitRepositoryStateError(GitServiceError):
    """The repository contains a state unsafe for this operation."""


class GitLocalChangesError(GitRepositoryStateError):
    """Local tracked, staged, or untracked files make synchronization unsafe."""


class GitCodeUpdateRequiredError(GitRepositoryStateError):
    """The remote range includes something other than Academic.csv."""


class GitDivergenceError(GitRepositoryStateError):
    """Local and remote main have diverged."""


class GitRemoteAdvanceError(GitRepositoryStateError):
    """Remote main has data that must be downloaded before an upload."""


class GitLocalAdvanceError(GitRepositoryStateError):
    """Local main contains an unrecognized unpublished commit."""


class GitCsvValidationError(GitServiceError):
    """Academic.csv is missing, unsafe, or invalid."""


class GitNetworkError(GitServiceError):
    """A fetch could not complete because of network or authentication."""


class GitPushPendingError(GitServiceError):
    """One valid local commit must be retained for a later non-force retry."""

    def __init__(self, commit: str) -> None:
        super().__init__(
            "El envío falló por red, autenticación o rechazo remoto. "
            "Hay un commit local pendiente; se conservará para reintentar."
        )
        self.commit = commit


class _Relation(StrEnum):
    EQUAL = "equal"
    REMOTE_AHEAD = "remote_ahead"
    LOCAL_AHEAD = "local_ahead"
    DIVERGED = "diverged"


class GitSyncService:
    """Fetch, fast-forward, commit, and push only ``Academic.csv``.

    Production constants are deliberately fixed. Tests inject only a disposable
    repository root and its expected local remote URL.
    """

    def __init__(
        self,
        repository_root: str | os.PathLike[str],
        *,
        expected_remote_url: str | os.PathLike[str] = PRODUCTIVE_REMOTE_URL,
        runner: RunCommand = subprocess.run,
        git_executable: str | None = None,
        csv_validator: CsvValidator | None = None,
    ) -> None:
        self.root = Path(repository_root).expanduser().resolve(strict=False)
        self.expected_remote_url = os.fspath(expected_remote_url)
        self._runner = runner
        self._configured_git = git_executable
        self._csv_validator = csv_validator or self._default_csv_validator
        self._pending_commit: str | None = None

    @property
    def pending_commit(self) -> str | None:
        """Return the in-process pending commit without exposing it in UI text."""
        return self._pending_commit

    def download_information(self) -> UpdateResult:
        """Fetch and fast-forward only when the remote range is exactly the CSV."""
        executable = self._check_environment()
        self._ensure_download_target_is_clean(executable)
        unrelated_before = self._worktree_changes(executable) - {ACADEMIC_PATH}
        local_revision = self._revision(executable, "HEAD")
        self._fetch(executable)
        remote_revision = self._remote_revision(executable)
        relation = self._classify(executable, local_revision, remote_revision)

        if relation is _Relation.EQUAL:
            return UpdateResult(False, "No hay información nueva para bajar.")
        if relation is _Relation.LOCAL_AHEAD:
            if self._pending_commit is None and self._is_recoverable_pending(
                executable,
                local_revision=local_revision,
                remote_revision=remote_revision,
            ):
                self._pending_commit = local_revision
            if self._pending_commit == local_revision:
                raise GitPushPendingError(local_revision)
            raise GitLocalAdvanceError(
                "La rama local contiene commits no publicados. "
                "La descarga se detuvo sin modificar archivos."
            )
        if relation is _Relation.DIVERGED:
            raise GitDivergenceError(
                "La rama main local y origin/main están divergentes. "
                "Se requiere revisión manual."
            )

        changed_paths = self._paths_between(
            executable,
            local_revision,
            remote_revision,
        )
        if changed_paths != {ACADEMIC_PATH}:
            raise GitCodeUpdateRequiredError(
                "La actualización remota incluye código, configuración, catálogos "
                "u otra ruta. La aplicación necesita una actualización manual de código."
            )
        self._validate_revision_csv(executable, remote_revision)
        merged = self._git(
            executable,
            "merge",
            "--ff-only",
            f"{REMOTE_NAME}/{BRANCH_NAME}",
            raise_on_error=False,
        )
        if merged.returncode != 0:
            raise GitRepositoryStateError(
                "No fue posible aplicar el avance rápido seguro. "
                "No se intentó mezclar ramas."
            )
        if self._revision(executable, "HEAD") != remote_revision:
            raise GitRepositoryStateError(
                "No fue posible confirmar el avance rápido seguro."
            )
        self._validate_local_csv()
        if self._worktree_changes(executable) - {ACADEMIC_PATH} != unrelated_before:
            raise GitRepositoryStateError(
                "La verificación posterior detectó cambios ajenos a Academic.csv."
            )
        if self._paths_between(executable, local_revision, remote_revision) != {
            ACADEMIC_PATH
        }:
            raise GitRepositoryStateError(
                "La verificación posterior no confirmó la allowlist exacta."
            )
        return UpdateResult(True, "Academic.csv se actualizó correctamente.")

    def upload_information(self) -> UpdateResult:
        """Commit and non-force push exactly ``Academic.csv``."""
        executable = self._check_environment()
        self._validate_local_csv()
        changes = self._worktree_changes(executable)
        unexpected = changes - {ACADEMIC_PATH}
        if unexpected:
            raise GitLocalChangesError(
                "Hay cambios locales, staged o archivos no versionados fuera de "
                "Academic.csv. La subida se detuvo."
            )
        if self._pending_commit is not None and changes:
            raise GitPushPendingError(self._pending_commit)

        try:
            self._fetch(executable)
        except GitNetworkError as error:
            if self._pending_commit is not None:
                raise GitPushPendingError(self._pending_commit) from error
            raise

        local_revision = self._revision(executable, "HEAD")
        remote_revision = self._remote_revision(executable)
        if self._pending_commit is not None:
            return self._retry_pending(
                executable,
                local_revision=local_revision,
                remote_revision=remote_revision,
            )

        relation = self._classify(executable, local_revision, remote_revision)
        if relation is _Relation.REMOTE_AHEAD:
            raise GitRemoteAdvanceError(
                "Origin/main contiene información nueva. Baje la información antes "
                "de subir cambios."
            )
        if relation is _Relation.LOCAL_AHEAD:
            if self._is_recoverable_pending(
                executable,
                local_revision=local_revision,
                remote_revision=remote_revision,
            ):
                self._pending_commit = local_revision
                return self._retry_pending(
                    executable,
                    local_revision=local_revision,
                    remote_revision=remote_revision,
                )
            raise GitLocalAdvanceError(
                "La rama local contiene un commit no reconocido. La subida se detuvo."
            )
        if relation is _Relation.DIVERGED:
            raise GitDivergenceError(
                "La rama main local y origin/main están divergentes. "
                "Se requiere revisión manual."
            )

        added = self._git(
            executable,
            "add",
            "--",
            ACADEMIC_PATH,
            raise_on_error=False,
        )
        if added.returncode != 0:
            raise GitRepositoryStateError(
                "No fue posible preparar Academic.csv de forma segura."
            )
        staged = self._staged_paths(executable)
        if not staged:
            return UpdateResult(False, "No hay cambios en Academic.csv para subir.")
        if staged != {ACADEMIC_PATH}:
            raise GitLocalChangesError(
                "El área staged contiene rutas no autorizadas. La subida se detuvo."
            )
        self._validate_local_csv()

        committed = self._git(
            executable,
            "commit",
            "-m",
            COMMIT_MESSAGE,
            "--only",
            "--",
            ACADEMIC_PATH,
            raise_on_error=False,
        )
        if committed.returncode != 0:
            raise GitRepositoryStateError(
                "No fue posible crear el commit local de Academic.csv. "
                "Revise la identidad Git configurada."
            )
        commit = self._revision(executable, "HEAD")
        if self._commit_paths(executable, commit) != {ACADEMIC_PATH}:
            raise GitRepositoryStateError(
                "El commit local no superó la verificación de allowlist y no se envió."
            )
        self._pending_commit = commit
        self._push_pending(executable, commit)
        self._pending_commit = None
        return UpdateResult(True, "Academic.csv se subió correctamente.")

    def _retry_pending(
        self,
        executable: str,
        *,
        local_revision: str,
        remote_revision: str,
    ) -> UpdateResult:
        commit = self._pending_commit
        if commit is None:
            raise GitRepositoryStateError("No existe un commit local pendiente.")
        exists = self._git(
            executable,
            "cat-file",
            "-e",
            f"{commit}^{{commit}}",
            raise_on_error=False,
        )
        if exists.returncode != 0 or local_revision != commit:
            raise GitPushPendingError(commit)
        if remote_revision == commit:
            self._pending_commit = None
            return UpdateResult(True, "El commit pendiente ya estaba publicado.")
        if self._is_ancestor(executable, commit, remote_revision):
            self._pending_commit = None
            return UpdateResult(
                True,
                "El commit pendiente ya estaba publicado; "
                "origin/main contiene información posterior para bajar.",
            )
        if not self._is_ancestor(executable, remote_revision, commit):
            raise GitDivergenceError(
                "Origin/main ya no es ancestro del commit local pendiente. "
                "El reintento se detuvo sin crear otro commit."
            )
        if self._paths_between(executable, remote_revision, commit) != {ACADEMIC_PATH}:
            raise GitPushPendingError(commit)
        self._validate_revision_csv(executable, commit)
        self._push_pending(executable, commit)
        self._pending_commit = None
        return UpdateResult(
            True, "El mismo commit local pendiente se subió correctamente."
        )

    def _is_recoverable_pending(
        self,
        executable: str,
        *,
        local_revision: str,
        remote_revision: str,
    ) -> bool:
        """Recognize one exact service commit after an application restart."""
        if not self._is_ancestor(executable, remote_revision, local_revision):
            return False
        count = self._git(
            executable,
            "rev-list",
            "--count",
            f"{remote_revision}..{local_revision}",
            raise_on_error=False,
        )
        subject = self._git(
            executable,
            "show",
            "-s",
            "--format=%s",
            local_revision,
            raise_on_error=False,
        )
        return (
            count.returncode == 0
            and count.stdout.strip() == "1"
            and subject.returncode == 0
            and subject.stdout.strip() == COMMIT_MESSAGE
            and self._commit_paths(executable, local_revision) == {ACADEMIC_PATH}
        )

    def _push_pending(self, executable: str, commit: str) -> None:
        pushed = self._git(
            executable,
            "push",
            REMOTE_NAME,
            f"{commit}:refs/heads/{BRANCH_NAME}",
            raise_on_error=False,
        )
        if pushed.returncode != 0:
            raise GitPushPendingError(commit)

    def _check_environment(self) -> str:
        executable = self._git_executable()
        if executable is None:
            raise GitUnavailableError("Git no está disponible en este equipo.")
        if not self.root.is_dir():
            raise GitConfigurationError(
                "El repositorio Git de la aplicación no está configurado."
            )
        inside = self._git(
            executable,
            "rev-parse",
            "--is-inside-work-tree",
            raise_on_error=False,
        )
        top = self._git(
            executable,
            "rev-parse",
            "--show-toplevel",
            raise_on_error=False,
        )
        if (
            inside.returncode != 0
            or inside.stdout.strip() != "true"
            or top.returncode != 0
        ):
            raise GitConfigurationError(
                "El repositorio Git de la aplicación no está configurado."
            )
        try:
            top_level = Path(top.stdout.strip()).resolve(strict=True)
        except OSError, RuntimeError:
            raise GitConfigurationError(
                "La raíz del repositorio Git no coincide con la configuración."
            ) from None
        if top_level != self.root:
            raise GitConfigurationError(
                "La raíz del repositorio Git no coincide con la configuración."
            )

        branch = self._git(
            executable,
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            raise_on_error=False,
        )
        if branch.returncode != 0 or branch.stdout.strip() != BRANCH_NAME:
            raise GitConfigurationError(
                "La aplicación solo puede sincronizar desde la rama main."
            )
        remotes = self._git(executable, "remote", raise_on_error=False)
        if remotes.returncode != 0 or REMOTE_NAME not in {
            line.strip() for line in remotes.stdout.splitlines()
        }:
            raise GitConfigurationError("El remoto origin no está configurado.")
        fetch_urls = self._remote_urls(executable, push=False)
        push_urls = self._remote_urls(executable, push=True)
        expected = (self.expected_remote_url,)
        if fetch_urls != expected or push_urls != expected:
            raise GitConfigurationError(
                "La URL de origin no coincide con el repositorio configurado."
            )
        return executable

    def _git_executable(self) -> str | None:
        if self._configured_git is None:
            return shutil.which("git")
        configured = self._configured_git
        if os.sep in configured or (os.altsep is not None and os.altsep in configured):
            return configured if Path(configured).is_file() else None
        return shutil.which(configured)

    def _remote_urls(self, executable: str, *, push: bool) -> tuple[str, ...]:
        arguments = ["remote", "get-url", "--all"]
        if push:
            arguments.append("--push")
        arguments.append(REMOTE_NAME)
        result = self._git(executable, *arguments, raise_on_error=False)
        if result.returncode != 0:
            return ()
        return tuple(
            line.strip() for line in result.stdout.splitlines() if line.strip()
        )

    def _fetch(self, executable: str) -> None:
        fetched = self._git(
            executable,
            "fetch",
            REMOTE_NAME,
            BRANCH_NAME,
            raise_on_error=False,
        )
        if fetched.returncode != 0:
            raise GitNetworkError(
                "No fue posible consultar origin/main. "
                "Revise la red y la autenticación Git."
            )

    def _remote_revision(self, executable: str) -> str:
        result = self._git(
            executable,
            "rev-parse",
            "--verify",
            f"refs/remotes/{REMOTE_NAME}/{BRANCH_NAME}",
            raise_on_error=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise GitConfigurationError("La rama origin/main no está configurada.")
        return result.stdout.strip()

    def _revision(self, executable: str, revision: str) -> str:
        result = self._git(
            executable,
            "rev-parse",
            "--verify",
            revision,
            raise_on_error=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise GitRepositoryStateError(
                "No fue posible identificar la revisión Git requerida."
            )
        return result.stdout.strip()

    def _classify(self, executable: str, local: str, remote: str) -> _Relation:
        if local == remote:
            return _Relation.EQUAL
        if self._is_ancestor(executable, local, remote):
            return _Relation.REMOTE_AHEAD
        if self._is_ancestor(executable, remote, local):
            return _Relation.LOCAL_AHEAD
        return _Relation.DIVERGED

    def _is_ancestor(self, executable: str, older: str, newer: str) -> bool:
        result = self._git(
            executable,
            "merge-base",
            "--is-ancestor",
            older,
            newer,
            allowed_returncodes=(0, 1),
        )
        return result.returncode == 0

    def _paths_between(self, executable: str, older: str, newer: str) -> set[str]:
        result = self._git(
            executable,
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            older,
            newer,
        )
        return self._nul_paths(result.stdout)

    def _commit_paths(self, executable: str, commit: str) -> set[str]:
        result = self._git(
            executable,
            "diff-tree",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-r",
            "-z",
            commit,
        )
        return self._nul_paths(result.stdout)

    def _worktree_changes(self, executable: str) -> set[str]:
        commands = (
            ("diff", "--no-renames", "--name-only", "-z"),
            ("diff", "--cached", "--no-renames", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        )
        changed: set[str] = set()
        for arguments in commands:
            changed.update(self._nul_paths(self._git(executable, *arguments).stdout))
        return changed

    def _staged_paths(self, executable: str) -> set[str]:
        result = self._git(
            executable,
            "diff",
            "--cached",
            "--no-renames",
            "--name-only",
            "-z",
        )
        return self._nul_paths(result.stdout)

    @staticmethod
    def _nul_paths(output: str) -> set[str]:
        return {value for value in output.split("\0") if value}

    def _ensure_download_target_is_clean(self, executable: str) -> None:
        if ACADEMIC_PATH in self._worktree_changes(executable):
            raise GitLocalChangesError(
                "Academic.csv tiene cambios locales que podrían sobrescribirse. "
                "La descarga se detuvo."
            )
        target = self.root / ACADEMIC_PATH
        if target.exists() or target.is_symlink():
            self._assert_safe_regular_file(target)

    def _validate_local_csv(self) -> None:
        target = self.root / ACADEMIC_PATH
        self._assert_safe_regular_file(target)
        self._validate_csv(target)

    def _validate_revision_csv(self, executable: str, revision: str) -> None:
        tree = self._git(
            executable,
            "ls-tree",
            "-z",
            revision,
            "--",
            ACADEMIC_PATH,
            raise_on_error=False,
        )
        entries = [entry for entry in tree.stdout.split("\0") if entry]
        if tree.returncode != 0 or len(entries) != 1:
            raise GitCsvValidationError("El Academic.csv remoto es inválido.")
        descriptor, separator, path = entries[0].partition("\t")
        mode_and_type = descriptor.split()
        if (
            not separator
            or path != ACADEMIC_PATH
            or len(mode_and_type) < 2
            or mode_and_type[0] != "100644"
            or mode_and_type[1] != "blob"
        ):
            raise GitCsvValidationError(
                "El Academic.csv remoto no es un archivo regular autorizado."
            )
        try:
            blob = self._git(
                executable,
                "show",
                f"{revision}:{ACADEMIC_PATH}",
                raise_on_error=False,
            )
        except GitServiceError as error:
            raise GitCsvValidationError(
                "El Academic.csv remoto no tiene una codificación válida."
            ) from error
        if blob.returncode != 0:
            raise GitCsvValidationError("El Academic.csv remoto es inválido.")
        try:
            with tempfile.TemporaryDirectory(
                prefix="epuc-academic-validate-"
            ) as folder:
                candidate = Path(folder) / "Academic.csv"
                candidate.write_text(blob.stdout, encoding="utf-8", newline="")
                self._validate_csv(candidate)
        except GitCsvValidationError:
            raise
        except (OSError, UnicodeError) as error:
            raise GitCsvValidationError(
                "No fue posible validar el Academic.csv remoto."
            ) from error

    def _validate_csv(self, path: Path) -> None:
        try:
            self._csv_validator(path)
        except (AcademicRepositoryError, OSError, UnicodeError, ValueError) as error:
            raise GitCsvValidationError(
                "Academic.csv es inválido y no se sincronizó."
            ) from error

    def _default_csv_validator(self, path: Path) -> object:
        catalogs_path = ProjectPaths(self.root)
        return CsvAcademicRepository(
            path,
            catalogs=get_academic_catalogs(catalogs_path),
        ).list_all()

    def _assert_safe_regular_file(self, target: Path) -> None:
        current = self.root
        for component in PurePosixPath(ACADEMIC_PATH).parts:
            current = current / component
            if current.is_symlink():
                raise GitCsvValidationError(
                    "Academic.csv no puede ser un enlace simbólico."
                )
        try:
            mode = os.lstat(target).st_mode
        except OSError as error:
            raise GitCsvValidationError(
                "Academic.csv no existe o no puede leerse."
            ) from error
        if not stat.S_ISREG(mode):
            raise GitCsvValidationError("Academic.csv debe ser un archivo regular.")

    def _git(
        self,
        executable: str,
        *arguments: str,
        allowed_returncodes: tuple[int, ...] = (0,),
        raise_on_error: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = self._runner(
                [executable, *arguments],
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                check=False,
                shell=False,
            )
        except (OSError, UnicodeError, subprocess.SubprocessError) as error:
            raise GitServiceError(
                "No fue posible ejecutar Git de forma segura."
            ) from error
        if raise_on_error and completed.returncode not in allowed_returncodes:
            raise GitServiceError("Una comprobación Git segura no pudo completarse.")
        return completed
