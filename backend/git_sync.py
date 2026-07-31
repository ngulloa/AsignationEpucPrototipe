"""Cross-platform Git synchronization restricted to shared application data."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

from backend.system_contracts import UpdateResult
from persistence.paths import normalize_username

RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class GitServiceError(RuntimeError):
    """A safe, user-facing Git workflow error."""


class GitUnavailableError(GitServiceError):
    """Git or the configured repository is unavailable."""


class GitRepositoryStateError(GitServiceError):
    """The repository, remote, branch or index is unsafe for this operation."""


class RemoteUpdateDetectedError(GitServiceError):
    """The remote branch changed before this publication could be pushed."""


class GitSyncService:
    """Run argument-list Git commands without managing credentials or branches."""

    def __init__(
        self,
        repository_root: str | os.PathLike[str],
        *,
        remote: str = "origin",
        runner: RunCommand = subprocess.run,
        git_executable: str | None = None,
    ) -> None:
        self.root = Path(repository_root).expanduser().resolve(strict=False)
        self.remote = remote
        self._runner = runner
        self._configured_git = git_executable

    def run_update(self) -> UpdateResult:
        """Fast-forward the current branch using only allowlisted public data."""
        executable, branch = self._check_environment()
        self._ensure_only_public_worktree_changes(executable)
        before = self._git(executable, "rev-parse", "HEAD").stdout.strip()
        self._git(executable, "fetch", "--prune", self.remote)
        remote_revision = self._remote_revision(executable, branch)
        if before == remote_revision:
            return UpdateResult(False, "La aplicación ya estaba actualizada.")

        ancestry = self._git(
            executable,
            "merge-base",
            "--is-ancestor",
            before,
            remote_revision,
            allowed_returncodes=(0, 1),
        )
        if ancestry.returncode != 0:
            raise GitRepositoryStateError(
                "La rama local no puede actualizarse mediante avance rápido."
            )
        changed_paths = self._paths_between(
            executable,
            before,
            remote_revision,
        )
        if any(not self._is_allowed_shared_path(path) for path in changed_paths):
            raise GitRepositoryStateError(
                "La actualización remota contiene cambios inesperados en código o "
                "configuración."
            )

        self._git(executable, "merge", "--ff-only", remote_revision)
        after = self._git(executable, "rev-parse", "HEAD").stdout.strip()
        if after != remote_revision:
            raise GitRepositoryStateError(
                "No fue posible confirmar el avance rápido de la rama actual."
            )
        return UpdateResult(
            changed=True,
            message="Actualización recibida mediante avance rápido.",
        )

    def pending_summary(self) -> str:
        """Describe shared changes without returning file contents."""
        executable, _branch = self._check_environment()
        result = self._git(
            executable,
            "status",
            "--short",
            "--",
            "data/public",
        )
        count = len([line for line in result.stdout.splitlines() if line.strip()])
        if count == 0:
            return "No hay archivos compartidos pendientes de publicación Git."
        return f"Archivos compartidos pendientes: {count}."

    def publish_changes(
        self,
        *,
        name: str,
        username: str,
        paths: Iterable[str | os.PathLike[str]],
    ) -> UpdateResult:
        """Commit only allowlisted shared paths and push the existing branch."""
        executable, branch = self._check_environment()
        canonical_username = normalize_username(username)
        clean_name = self._clean_commit_component(name, label="nombre")
        relative_paths = self._validated_shared_paths(paths)
        if not relative_paths:
            raise GitRepositoryStateError(
                "No hay archivos compartidos permitidos para publicar."
            )

        self._ensure_worktree_contains_only(executable, set(relative_paths))
        self._ensure_index_contains_only(executable, set(relative_paths))
        self._git(executable, "fetch", "--prune", self.remote)
        baseline = self._remote_revision(executable, branch)
        local_revision = self._git(executable, "rev-parse", "HEAD").stdout.strip()
        if baseline != local_revision:
            raise RemoteUpdateDetectedError(
                "Existe una actualización remota. Actualice antes de publicar."
            )

        self._git(executable, "add", "--", *relative_paths)
        self._ensure_index_contains_only(executable, set(relative_paths))
        difference = self._git(
            executable,
            "diff",
            "--cached",
            "--quiet",
            "--",
            *relative_paths,
            allowed_returncodes=(0, 1),
        )
        if difference.returncode == 0:
            return UpdateResult(False, "No hay cambios compartidos para publicar.")

        # Fetch once more immediately before committing. A later race is rejected
        # by the normal non-force push; it is never resolved by overwriting data.
        self._git(executable, "fetch", "--prune", self.remote)
        if self._remote_revision(executable, branch) != baseline:
            raise RemoteUpdateDetectedError(
                "Otro usuario publicó primero. Actualice antes de reintentar."
            )

        message = f"Actualización: {clean_name} | usuario: {canonical_username}"
        self._git(executable, "commit", "-m", message)
        pushed = self._git(
            executable,
            "push",
            self.remote,
            branch,
            raise_on_error=False,
        )
        if pushed.returncode != 0:
            raise RemoteUpdateDetectedError(
                "La publicación fue detenida porque el remoto cambió o rechazó el envío."
            )
        return UpdateResult(True, "Cambios compartidos publicados correctamente.")

    def _check_environment(self) -> tuple[str, str]:
        executable = self._configured_git or shutil.which("git")
        if not executable:
            raise GitUnavailableError("Git no está instalado o no está disponible.")
        if not self.root.is_dir():
            raise GitUnavailableError("El directorio del repositorio no existe.")
        inside = self._git(
            executable,
            "rev-parse",
            "--is-inside-work-tree",
            raise_on_error=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise GitUnavailableError(
                "El directorio configurado no es un repositorio Git."
            )
        branch_result = self._git(
            executable,
            "symbolic-ref",
            "--quiet",
            "--short",
            "HEAD",
            raise_on_error=False,
        )
        branch = branch_result.stdout.strip()
        if branch_result.returncode != 0 or not branch:
            raise GitRepositoryStateError(
                "El repositorio no tiene una rama actual utilizable."
            )
        remotes = self._git(executable, "remote").stdout.splitlines()
        if self.remote not in {value.strip() for value in remotes}:
            raise GitRepositoryStateError("El remoto Git configurado no existe.")
        # Verify the URL exists, but deliberately never expose or retain its value.
        remote_url = self._git(
            executable,
            "remote",
            "get-url",
            "--push",
            self.remote,
            raise_on_error=False,
        )
        if remote_url.returncode != 0 or not remote_url.stdout.strip():
            raise GitRepositoryStateError("El remoto Git no tiene una URL de envío.")
        return executable, branch

    def _remote_revision(self, executable: str, branch: str) -> str:
        reference = f"refs/remotes/{self.remote}/{branch}"
        result = self._git(
            executable,
            "rev-parse",
            "--verify",
            reference,
            raise_on_error=False,
        )
        revision = result.stdout.strip()
        if result.returncode != 0 or not revision:
            raise GitRepositoryStateError(
                "No fue posible comprobar la rama remota actual."
            )
        return revision

    def _validated_shared_paths(
        self, paths: Iterable[str | os.PathLike[str]]
    ) -> list[str]:
        valid: set[str] = set()
        for supplied in paths:
            candidate = Path(supplied)
            absolute = (
                candidate.resolve(strict=False)
                if candidate.is_absolute()
                else (self.root / candidate).resolve(strict=False)
            )
            try:
                relative = absolute.relative_to(self.root)
            except ValueError as error:
                raise GitRepositoryStateError(
                    "Se intentó publicar una ruta fuera del repositorio."
                ) from error
            portable = PurePosixPath(*relative.parts).as_posix()
            if not self._is_allowed_shared_path(portable):
                raise GitRepositoryStateError(
                    "La ruta solicitada no pertenece a los datos compartidos permitidos."
                )
            valid.add(portable)
        return sorted(valid)

    @staticmethod
    def _is_allowed_shared_path(path: str) -> bool:
        fixed = {
            "data/public/approved_users.json",
            "data/public/tables_index.json",
            "data/public/notifications_error.json",
        }
        if path in fixed:
            return True
        pure = PurePosixPath(path)
        return (
            pure.parent == PurePosixPath("data/public/tables")
            and pure.suffix.lower() == ".csv"
            and pure.name not in {".", ".."}
        )

    def _ensure_index_contains_only(
        self, executable: str, requested_paths: set[str]
    ) -> None:
        result = self._git(
            executable,
            "diff",
            "--cached",
            "--name-only",
            "-z",
        )
        staged = {value for value in result.stdout.split("\0") if value}
        unexpected = staged - requested_paths
        if unexpected:
            raise GitRepositoryStateError(
                "El índice Git contiene archivos ajenos a esta publicación."
            )

    def _ensure_only_public_worktree_changes(self, executable: str) -> None:
        unexpected = {
            path
            for path in self._worktree_changes(executable)
            if not self._is_allowed_shared_path(path)
        }
        if unexpected:
            raise GitRepositoryStateError(
                "El repositorio contiene cambios inesperados en código o configuración."
            )

    def _ensure_worktree_contains_only(
        self, executable: str, requested_paths: set[str]
    ) -> None:
        unexpected = self._worktree_changes(executable) - requested_paths
        if unexpected:
            raise GitRepositoryStateError(
                "El repositorio contiene cambios ajenos a esta publicación."
            )

    def _worktree_changes(self, executable: str) -> set[str]:
        commands = (
            ("diff", "--no-renames", "--name-only", "-z"),
            ("diff", "--cached", "--no-renames", "--name-only", "-z"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        )
        changed: set[str] = set()
        for arguments in commands:
            result = self._git(executable, *arguments)
            changed.update(value for value in result.stdout.split("\0") if value)
        return changed

    def _paths_between(
        self,
        executable: str,
        older_revision: str,
        newer_revision: str,
    ) -> set[str]:
        result = self._git(
            executable,
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            older_revision,
            newer_revision,
        )
        return {value for value in result.stdout.split("\0") if value}

    @staticmethod
    def _clean_commit_component(value: str, *, label: str) -> str:
        clean = " ".join(value.replace("\r", " ").replace("\n", " ").split())
        if not clean or len(clean) > 80:
            raise GitRepositoryStateError(
                f"El {label} de la actualización debe tener entre 1 y 80 caracteres."
            )
        return clean

    def _git(
        self,
        executable: str,
        *arguments: str,
        allowed_returncodes: tuple[int, ...] = (0,),
        raise_on_error: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [executable, *arguments]
        try:
            completed = self._runner(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise GitServiceError(
                "No fue posible ejecutar Git de forma segura."
            ) from error
        if raise_on_error and completed.returncode not in allowed_returncodes:
            operation = arguments[0] if arguments else "comando"
            raise GitServiceError(
                f"La operación Git '{operation}' no pudo completarse."
            )
        return completed
