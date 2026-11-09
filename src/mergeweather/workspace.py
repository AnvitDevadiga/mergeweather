"""Disposable workspaces that never touch the user's working tree.

Every workspace is a fresh directory under a temp root containing a marker file.
Child processes and containers started from it are tracked so an interrupt
(SIGINT / SIGTERM) can terminate them before the directory is removed.
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional, Set

from . import gitutil

MARKER = ".mergeweather-workspace"
PREFIX = "mergeweather-"

_lock = threading.Lock()
_active_pgids: Set[int] = set()
_active_containers: Set[str] = set()
_active_workspaces: Set["Workspace"] = set()


def track_pgid(pgid: int) -> None:
    with _lock:
        _active_pgids.add(pgid)


def untrack_pgid(pgid: int) -> None:
    with _lock:
        _active_pgids.discard(pgid)


def track_container(name: str) -> None:
    with _lock:
        _active_containers.add(name)


def untrack_container(name: str) -> None:
    with _lock:
        _active_containers.discard(name)


def kill_children() -> None:
    with _lock:
        pgids, containers = list(_active_pgids), list(_active_containers)
        _active_pgids.clear()
        _active_containers.clear()
    for pgid in pgids:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    for name in containers:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _rm_onerror(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        func(path)
    except OSError:
        pass


def remove_tree(path: Path) -> None:
    if path.exists():
        # make read-only test artifacts deletable
        for root, dirs, _files in os.walk(path):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o700)
                except OSError:
                    pass
        shutil.rmtree(path, onerror=_rm_onerror)


class Workspace:
    def __init__(self, root: Optional[Path] = None):
        if root is not None:
            Path(root).mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix=PREFIX, dir=str(root) if root else None))
        (self.path / MARKER).write_text(str(os.getpid()))
        self.repo = self.path / "repo"
        self.trees = self.path / "trees"
        self.trees.mkdir()
        self._closed = False
        with _lock:
            _active_workspaces.add(self)

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        kill_children()
        remove_tree(self.path)
        with _lock:
            _active_workspaces.discard(self)

    # -- git operations inside the disposable copy -------------------------
    def import_commits(self, source: Path, shas) -> None:
        """Copy objects from the user's repo by fetching into a fresh repo.

        Fetching only reads from the source; its refs, index and working tree
        are never modified.
        """
        self.repo.mkdir()
        gitutil.git(["init", "-q"], cwd=self.repo)
        gitutil.git(["fetch", "-q", "--no-tags", "--no-write-fetch-head", str(source),
                     "+refs/*:refs/mw-src/*"], cwd=self.repo)
        for sha in shas:
            if gitutil.git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd=self.repo,
                           check=False).returncode != 0:
                # commit not reachable from any ref (e.g. detached); fetch it directly
                gitutil.git(["fetch", "-q", "--no-tags", "--no-write-fetch-head", str(source), sha],
                            cwd=self.repo)

    def export_tree(self, tree: str) -> Path:
        """Materialize a tree as a plain directory (no .git, no credentials)."""
        dest = self.trees / tree
        if dest.exists():
            remove_tree(dest)
        dest.mkdir()
        tar = self.path / f"{tree}.tar"
        gitutil.git(["archive", "--format=tar", tree], cwd=self.repo, stdout_path=tar)
        import tarfile
        with tarfile.open(tar) as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(dest, filter="data")
            else:  # pragma: no cover
                tf.extractall(dest)
        tar.unlink()
        return dest


def _cleanup_all() -> None:
    with _lock:
        spaces = list(_active_workspaces)
    for ws in spaces:
        ws.close()


atexit.register(_cleanup_all)


def install_signal_handlers() -> None:
    """Turn SIGTERM/SIGHUP into KeyboardInterrupt so `with Workspace()` unwinds."""
    def handler(signum, _frame):
        kill_children()
        raise KeyboardInterrupt(f"signal {signum}")
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is not None:
            signal.signal(sig, handler)


def clean_stale(root: Optional[Path] = None) -> int:
    """Remove leftover workspaces (e.g. after SIGKILL). Only touches marked dirs."""
    base = Path(root) if root else Path(tempfile.gettempdir())
    removed = 0
    if not base.exists():
        return 0
    for entry in base.iterdir():
        if entry.name.startswith(PREFIX) and (entry / MARKER).exists():
            try:
                pid = int((entry / MARKER).read_text().strip())
                os.kill(pid, 0)
                if pid != os.getpid():
                    continue  # owner still alive
            except (ValueError, ProcessLookupError):
                pass
            except PermissionError:
                continue
            remove_tree(entry)
            removed += 1
    return removed
