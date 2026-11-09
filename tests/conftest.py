import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "examples"))

from mergeweather.engine import Budget, Engine  # noqa: E402
from mergeweather.runner import Limits, LocalRunner  # noqa: E402

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=GIT_ENV, check=True, capture_output=True, text=True).stdout


def make_repo(path: Path, base_files: dict, branches: dict) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for rel, c in base_files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(c)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    for name, files in branches.items():
        git(path, "checkout", "-q", "-b", name, "main")
        for rel, c in files.items():
            (path / rel).parent.mkdir(parents=True, exist_ok=True)
            (path / rel).write_text(c)
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", name)
    git(path, "checkout", "-q", "main")
    return path


@pytest.fixture
def fixtures(tmp_path):
    from make_fixtures import build_all

    return build_all(tmp_path / "fx")


@pytest.fixture
def make_engine(tmp_path):
    def _make(repo, branches, cmd, max_runs=100, max_size=4, repeats=3, **kw):
        return Engine(
            repo,
            kw.pop("base", "main"),
            [(b, b) for b in branches] if isinstance(branches[0], str) else branches,
            cmd,
            LocalRunner(Limits(timeout=kw.pop("timeout", 30))),
            Budget(max_runs=max_runs, max_size=max_size),
            repeats=repeats,
            workroot=tmp_path / "work",
            **kw,
        )

    return _make
