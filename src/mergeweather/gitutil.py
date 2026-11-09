"""Thin, deterministic wrappers around the git CLI."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

# Fixed identity and timestamps make every synthesized merge commit reproducible:
# the same base + the same branch commits in the same order -> the same commit ID.
DETERMINISTIC_ENV: dict[str, str] = {
    "GIT_AUTHOR_NAME": "MergeWeather",
    "GIT_AUTHOR_EMAIL": "mergeweather@localhost",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00 +0000",
    "GIT_COMMITTER_NAME": "MergeWeather",
    "GIT_COMMITTER_EMAIL": "mergeweather@localhost",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00 +0000",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "LC_ALL": "C",
}


class GitError(RuntimeError):
    pass


class InvalidRef(GitError):
    pass


def git(
    args: Sequence[str], cwd: Path, check: bool = True, isolated: bool = True, stdout_path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if isolated:
        env.update(DETERMINISTIC_ENV)
    cmd = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", *args]
    if stdout_path is not None:
        with open(stdout_path, "wb") as fh:
            raw = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=fh, stderr=subprocess.PIPE)
        proc: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            cmd, raw.returncode, "", raw.stderr.decode(errors="replace")
        )
    else:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, errors="replace")
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc


def ensure_repo(path: Path) -> Path:
    proc = git(["rev-parse", "--show-toplevel"], cwd=path, check=False)
    if proc.returncode != 0:
        raise GitError(f"{path} is not a git repository")
    return Path(proc.stdout.strip())


def resolve_commit(repo: Path, ref: str) -> str:
    """Pin a reference to a full commit ID. Raises InvalidRef."""
    if not ref or ref.startswith("-"):
        raise InvalidRef(f"invalid reference {ref!r}")
    proc = git(["rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"], cwd=repo, check=False)
    sha = proc.stdout.strip()
    if proc.returncode != 0 or len(sha) < 40:
        raise InvalidRef(f"reference {ref!r} does not resolve to a commit in {repo}")
    return sha


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return git(["merge-base", "--is-ancestor", ancestor, descendant], cwd=repo, check=False).returncode == 0


def diff_text(repo: Path, base: str, head: str, limit: int = 6000) -> str:
    out = git(["diff", "--no-color", "--no-ext-diff", base, head], cwd=repo).stdout
    if len(out) > limit:
        out = out[:limit] + f"\n... [truncated {len(out) - limit} chars]\n"
    return out


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    out = git(["diff", "--name-only", base, head], cwd=repo).stdout
    return [l for l in out.splitlines() if l]
