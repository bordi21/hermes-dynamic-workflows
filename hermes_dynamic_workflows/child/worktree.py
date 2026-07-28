"""Per-child workspace leases and transactional git worktree mechanics."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_REPO_LOCKS: dict[str, threading.RLock] = {}
_REPO_LOCKS_GUARD = threading.Lock()


@dataclass
class WorkspaceReviewContext:
    mode: str
    workspace: str
    repo_root: str | None
    branch: str | None
    base_commit: str | None
    head_commit: str | None
    status: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    diff_stat: str = ""
    commits: tuple[str, ...] = ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "workspace": self.workspace,
            "repo_root": self.repo_root,
            "branch": self.branch,
            "base_commit": self.base_commit,
            "head_commit": self.head_commit,
            "status": list(self.status),
            "changed_paths": list(self.changed_paths),
            "diff_stat": self.diff_stat,
            "commits": list(self.commits),
        }


@dataclass
class WorkspaceIntegrationOutcome:
    status: str
    summary: str
    source_branch: str | None
    source_base_commit: str | None
    source_commit: str | None
    integrated_commit: str | None
    base_head_before: str | None
    base_head_after: str | None
    base_status_before: tuple[str, ...] = ()
    base_status_after: tuple[str, ...] = ()
    source_status: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    commits: tuple[str, ...] = ()
    error: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "source_branch": self.source_branch,
            "source_base_commit": self.source_base_commit,
            "source_commit": self.source_commit,
            "integrated_commit": self.integrated_commit,
            "base_head_before": self.base_head_before,
            "base_head_after": self.base_head_after,
            "base_status_before": list(self.base_status_before),
            "base_status_after": list(self.base_status_after),
            "source_status": list(self.source_status),
            "changed_paths": list(self.changed_paths),
            "commits": list(self.commits),
            "error": self.error,
        }


@dataclass
class WorkspaceLease:
    task_id: str
    cwd: str
    isolation: str | None = None
    path: str | None = None
    branch: str | None = None
    repo_root: str | None = None
    base_commit: str | None = None
    source_commit: str | None = None
    integrated_commit: str | None = None
    keep: bool = False

    def review_context(self) -> WorkspaceReviewContext:
        return inspect_workspace(self)

    def integrate(self, *, commit_message: str) -> WorkspaceIntegrationOutcome:
        return integrate_workspace(self, commit_message=commit_message)

    def cleanup(self) -> None:
        if self.isolation != "worktree" or not self.path or not self.repo_root:
            return
        if self.keep:
            return
        wt_path = Path(self.path)
        if not wt_path.exists():
            return
        if self.integrated_commit:
            if _git_lines(str(wt_path), ["status", "--porcelain"]) is None:
                return
            if _git_lines(str(wt_path), ["status", "--porcelain"]):
                return
        elif _worktree_has_changes(wt_path, self.base_commit):
            return
        removed = subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_path)],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if removed.returncode != 0:
            return
        if self.branch:
            subprocess.run(
                ["git", "branch", "-D", self.branch],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        try:
            wt_path.parent.rmdir()
        except OSError:
            pass


def create_workspace_lease(
    *,
    cwd: str,
    isolation: str | None,
    label: str,
    task_id: str | None = None,
    keep_worktree: bool = False,
) -> WorkspaceLease:
    task_id = task_id or f"workflow-{uuid.uuid4().hex[:12]}"
    base_cwd = str(Path(cwd or os.getcwd()).expanduser().resolve())
    if isolation in (None, "", "shared"):
        return WorkspaceLease(task_id=task_id, cwd=base_cwd)
    if isolation != "worktree":
        raise ValueError(f"unsupported isolation mode: {isolation!r}")

    repo_root = _git_repo_root(base_cwd)
    if not repo_root:
        raise ValueError("isolation='worktree' requires running inside a git repository")
    base_commit = _git_head(repo_root)
    if not base_commit:
        raise ValueError("isolation='worktree' requires a git repository with at least one commit")

    short_id = uuid.uuid4().hex[:8]
    safe_label = _safe_label(label)
    wt_name = f"hermes-wf-{safe_label}-{short_id}"[:80].rstrip("-")
    branch = f"hermes/{wt_name}"
    worktrees_dir = Path(repo_root) / ".worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    _ensure_worktree_excluded(repo_root)
    wt_path = worktrees_dir / wt_name

    result = subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch, base_commit],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise ValueError(f"failed to create worktree: {(result.stderr or result.stdout).strip()}")

    _copy_worktree_includes(Path(repo_root), wt_path)
    return WorkspaceLease(
        task_id=task_id,
        cwd=str(wt_path),
        isolation="worktree",
        path=str(wt_path),
        branch=branch,
        repo_root=repo_root,
        base_commit=base_commit,
        keep=keep_worktree,
    )


def inspect_workspace(lease: WorkspaceLease) -> WorkspaceReviewContext:
    workspace = str(Path(lease.cwd).expanduser().resolve())
    repo_root = lease.repo_root or _git_repo_root(workspace)
    if not repo_root:
        return WorkspaceReviewContext(
            mode="worktree" if lease.isolation == "worktree" else "shared",
            workspace=workspace,
            repo_root=None,
            branch=lease.branch,
            base_commit=lease.base_commit,
            head_commit=None,
        )

    base_commit = lease.base_commit if lease.isolation == "worktree" else _git_head(repo_root)
    head_commit = _git_head(workspace)
    status = _git_lines(workspace, ["status", "--porcelain"]) or []
    branch = lease.branch or _git_text(workspace, ["branch", "--show-current"]) or None
    changed_paths: list[str] = []
    diff_stat = ""
    commits: list[str] = []
    if lease.isolation == "worktree" and base_commit:
        changed_paths = _git_lines(workspace, ["diff", "--name-only", base_commit]) or []
        diff_stat = _git_text(workspace, ["diff", "--stat", base_commit]) or ""
        commits = _git_lines(workspace, ["rev-list", "--reverse", f"{base_commit}..HEAD"]) or []
    else:
        changed_paths = _git_lines(workspace, ["diff", "--name-only", "HEAD"]) or []
        diff_stat = _git_text(workspace, ["diff", "--stat", "HEAD"]) or ""

    return WorkspaceReviewContext(
        mode="worktree" if lease.isolation == "worktree" else "shared",
        workspace=workspace,
        repo_root=repo_root,
        branch=branch,
        base_commit=base_commit,
        head_commit=head_commit,
        status=tuple(status),
        changed_paths=tuple(changed_paths),
        diff_stat=diff_stat,
        commits=tuple(commits),
    )


def integrate_workspace(
    lease: WorkspaceLease,
    *,
    commit_message: str,
) -> WorkspaceIntegrationOutcome:
    """Commit one worktree and cherry-pick it transactionally into its base repo.

    Policy is intentionally absent here: callers must invoke this only for a
    reviewed PASS. The operation records before/after HEAD and status, aborts a
    conflicting cherry-pick, and never resets unrelated base-repository work.
    """

    if lease.isolation != "worktree":
        head = _git_head(lease.cwd)
        status = tuple(_git_lines(lease.cwd, ["status", "--porcelain"]) or [])
        lease.integrated_commit = head
        return WorkspaceIntegrationOutcome(
            status="INTEGRATED",
            summary="Shared read-only workspace requires no git integration.",
            source_branch=None,
            source_base_commit=head,
            source_commit=head,
            integrated_commit=head,
            base_head_before=head,
            base_head_after=head,
            base_status_before=status,
            base_status_after=status,
        )

    if lease.integrated_commit:
        status = tuple(_git_lines(str(lease.repo_root), ["status", "--porcelain"]) or [])
        return WorkspaceIntegrationOutcome(
            status="SKIPPED",
            summary="Workspace was already integrated.",
            source_branch=lease.branch,
            source_base_commit=lease.base_commit,
            source_commit=lease.source_commit,
            integrated_commit=lease.integrated_commit,
            base_head_before=lease.integrated_commit,
            base_head_after=lease.integrated_commit,
            base_status_before=status,
            base_status_after=status,
        )

    if not lease.path or not lease.repo_root or not lease.base_commit:
        return WorkspaceIntegrationOutcome(
            status="FAILED",
            summary="Worktree lease is missing repository lineage.",
            source_branch=lease.branch,
            source_base_commit=lease.base_commit,
            source_commit=None,
            integrated_commit=None,
            base_head_before=None,
            base_head_after=None,
            error="missing path, repo_root, or base_commit",
        )

    workspace = str(Path(lease.path).expanduser().resolve())
    repo_root = str(Path(lease.repo_root).expanduser().resolve())
    lock = _repo_lock(repo_root)
    with lock:
        base_head_before = _git_head(repo_root)
        base_status_before = tuple(_git_lines(repo_root, ["status", "--porcelain"]) or [])
        source_context = inspect_workspace(lease)
        if base_status_before:
            return WorkspaceIntegrationOutcome(
                status="FAILED",
                summary="Base repository is dirty; integration was not attempted.",
                source_branch=lease.branch,
                source_base_commit=lease.base_commit,
                source_commit=source_context.head_commit,
                integrated_commit=None,
                base_head_before=base_head_before,
                base_head_after=base_head_before,
                base_status_before=base_status_before,
                base_status_after=base_status_before,
                source_status=source_context.status,
                changed_paths=source_context.changed_paths,
                commits=source_context.commits,
                error="base repository has uncommitted changes",
            )

        if source_context.status:
            added = _run_git(workspace, ["add", "-A"])
            if added.returncode != 0:
                return _integration_failure(
                    lease,
                    source_context,
                    base_head_before,
                    base_status_before,
                    "FAILED",
                    "Failed to stage worktree changes.",
                    added,
                )
            committed = _run_git(
                workspace,
                [
                    "-c",
                    "user.name=Hermes Workflow",
                    "-c",
                    "user.email=workflow@hermes.local",
                    "commit",
                    "-m",
                    commit_message,
                ],
            )
            if committed.returncode != 0:
                return _integration_failure(
                    lease,
                    inspect_workspace(lease),
                    base_head_before,
                    base_status_before,
                    "FAILED",
                    "Failed to commit worktree changes.",
                    committed,
                )

        source_context = inspect_workspace(lease)
        source_commit = source_context.head_commit
        commits = tuple(
            _git_lines(workspace, ["rev-list", "--reverse", f"{lease.base_commit}..HEAD"])
            or []
        )
        lease.source_commit = source_commit
        if not commits:
            lease.integrated_commit = base_head_before
            return WorkspaceIntegrationOutcome(
                status="INTEGRATED",
                summary="Reviewed workspace had no changes to integrate.",
                source_branch=lease.branch,
                source_base_commit=lease.base_commit,
                source_commit=source_commit,
                integrated_commit=base_head_before,
                base_head_before=base_head_before,
                base_head_after=base_head_before,
                base_status_before=base_status_before,
                base_status_after=base_status_before,
                source_status=source_context.status,
                changed_paths=source_context.changed_paths,
                commits=commits,
            )

        cherry_pick = _run_git(repo_root, ["cherry-pick", *commits], timeout=120)
        if cherry_pick.returncode != 0:
            abort = _run_git(repo_root, ["cherry-pick", "--abort"], timeout=30)
            base_head_after = _git_head(repo_root)
            base_status_after = tuple(_git_lines(repo_root, ["status", "--porcelain"]) or [])
            error = (cherry_pick.stderr or cherry_pick.stdout).strip()
            if abort.returncode != 0:
                abort_error = (abort.stderr or abort.stdout).strip()
                error = f"{error}; cherry-pick abort failed: {abort_error}"
            return WorkspaceIntegrationOutcome(
                status="CONFLICT",
                summary="Reviewed workspace conflicted with the current base; integration was aborted.",
                source_branch=lease.branch,
                source_base_commit=lease.base_commit,
                source_commit=source_commit,
                integrated_commit=None,
                base_head_before=base_head_before,
                base_head_after=base_head_after,
                base_status_before=base_status_before,
                base_status_after=base_status_after,
                source_status=source_context.status,
                changed_paths=source_context.changed_paths,
                commits=commits,
                error=error,
            )

        base_head_after = _git_head(repo_root)
        base_status_after = tuple(_git_lines(repo_root, ["status", "--porcelain"]) or [])
        lease.integrated_commit = base_head_after
        return WorkspaceIntegrationOutcome(
            status="INTEGRATED",
            summary="Reviewed workspace integrated successfully.",
            source_branch=lease.branch,
            source_base_commit=lease.base_commit,
            source_commit=source_commit,
            integrated_commit=base_head_after,
            base_head_before=base_head_before,
            base_head_after=base_head_after,
            base_status_before=base_status_before,
            base_status_after=base_status_after,
            source_status=source_context.status,
            changed_paths=source_context.changed_paths,
            commits=commits,
        )


def _integration_failure(
    lease: WorkspaceLease,
    source_context: WorkspaceReviewContext,
    base_head: str | None,
    base_status: tuple[str, ...],
    status: str,
    summary: str,
    process: subprocess.CompletedProcess[str],
) -> WorkspaceIntegrationOutcome:
    return WorkspaceIntegrationOutcome(
        status=status,
        summary=summary,
        source_branch=lease.branch,
        source_base_commit=lease.base_commit,
        source_commit=source_context.head_commit,
        integrated_commit=None,
        base_head_before=base_head,
        base_head_after=base_head,
        base_status_before=base_status,
        base_status_after=base_status,
        source_status=source_context.status,
        changed_paths=source_context.changed_paths,
        commits=source_context.commits,
        error=(process.stderr or process.stdout).strip(),
    )


def _repo_lock(repo_root: str) -> threading.RLock:
    clean = str(Path(repo_root).expanduser().resolve())
    with _REPO_LOCKS_GUARD:
        return _REPO_LOCKS.setdefault(clean, threading.RLock())


def _run_git(
    cwd: str,
    args: list[str],
    *,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return subprocess.CompletedProcess(
            args=["git", *args],
            returncode=1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
        )


def _git_text(cwd: str, args: list[str]) -> str | None:
    result = _run_git(cwd, args)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_lines(cwd: str, args: list[str]) -> list[str] | None:
    text = _git_text(cwd, args)
    if text is None:
        return None
    return [line for line in text.splitlines() if line]


def _git_repo_root(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return str(Path(result.stdout.strip()).expanduser().resolve())


def _git_head(repo_root: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _ensure_worktree_excluded(repo_root: str) -> None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return
    if result.returncode != 0 or not result.stdout.strip():
        return
    exclude = Path(result.stdout.strip())
    if not exclude.is_absolute():
        exclude = Path(repo_root) / exclude
    entry = ".worktrees/"
    try:
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if entry in existing.splitlines():
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(entry + "\n")
    except Exception:
        pass


def _copy_worktree_includes(repo_root: Path, wt_path: Path) -> None:
    include_file = repo_root / ".worktreeinclude"
    if not include_file.exists():
        return
    repo_root_resolved = repo_root.resolve()
    wt_path_resolved = wt_path.resolve()
    try:
        lines = include_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        src = repo_root / entry
        dst = wt_path / entry
        try:
            src_resolved = src.resolve(strict=False)
            dst_resolved = dst.resolve(strict=False)
        except (OSError, ValueError):
            continue
        if not _is_within(src_resolved, repo_root_resolved):
            continue
        if not _is_within(dst_resolved, wt_path_resolved):
            continue
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        elif src.is_dir() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(str(src_resolved), str(dst))
            except (OSError, NotImplementedError):
                if sys.platform == "win32":
                    shutil.copytree(str(src_resolved), str(dst), symlinks=True)
                else:
                    raise


def _worktree_has_changes(wt_path: Path, base_commit: str | None) -> bool:
    checks = [["git", "status", "--porcelain"]]
    if base_commit:
        checks.append(["git", "rev-list", "--count", f"{base_commit}..HEAD"])
    for command in checks:
        try:
            result = subprocess.run(
                command,
                cwd=str(wt_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return True
        if result.returncode != 0:
            return True
        output = result.stdout.strip()
        if command[1] == "rev-list":
            if output != "0":
                return True
        elif output:
            return True
    return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_label(label: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(label or "agent"))
    clean = "-".join(part for part in raw.split("-") if part)
    return clean[:32] or "agent"
