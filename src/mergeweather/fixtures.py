#!/usr/bin/env python3
"""Build the two sample repositories used by the demo and the test suite.

latency-budget  A checkout pipeline whose stages are discovered from
                checkout/stages/. The integration test asserts the summed
                stage latency stays within a 250 ms SLA. Base = 100 ms and each
                feature branch adds a 60 ms stage in its own file, so:
                base 100, any single 160, any pair 220 -> pass; all three 280 -> fail.
                No branch touches the same file, so there are no textual conflicts.

harmless        Same base; three branches add a 20 ms stage, a doc file and a
                log-message tweak. Every combination passes.
"""
import os
import subprocess
import sys
from pathlib import Path

ENV = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.com",
       "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.com",
       "GIT_AUTHOR_DATE": "2024-01-01T00:00:00 +0000", "GIT_COMMITTER_DATE": "2024-01-01T00:00:00 +0000",
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, env=ENV, check=True, capture_output=True)


def write(repo: Path, files):
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


BASE_FILES = {
    "checkout/__init__.py": "",
    "checkout/stages/__init__.py": "",
    "checkout/stages/core.py": '"""Core payment authorization."""\nLATENCY_MS = 100\n'
                               'LOG = "authorizing payment"\n',
    "checkout/pipeline.py": '''"""Checkout pipeline: every module in checkout/stages runs once per request."""
import importlib
import pkgutil

from checkout import stages

SLA_MS = 250


def load_stages():
    found = []
    for info in sorted(pkgutil.iter_modules(stages.__path__), key=lambda m: m.name):
        mod = importlib.import_module(f"checkout.stages.{info.name}")
        found.append((info.name, mod.LATENCY_MS))
    return found


def total_latency_ms():
    return sum(ms for _, ms in load_stages())
''',
    "integration_test.py": '''"""Integration test: the full checkout pipeline must fit the latency SLA."""
import sys

from checkout.pipeline import SLA_MS, load_stages, total_latency_ms


def main():
    stages = load_stages()
    total = total_latency_ms()
    print("stages:", ", ".join(f"{n}={ms}ms" for n, ms in stages))
    if total > SLA_MS:
        print(f"FAIL: AssertionError: checkout latency {total}ms exceeds SLA {SLA_MS}ms")
        return 1
    print(f"PASS: checkout latency {total}ms within SLA {SLA_MS}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
    "README.md": "# checkout service (MergeWeather fixture)\n",
}


def stage(name, ms, doc):
    return {f"checkout/stages/{name}.py": f'"""{doc}"""\nLATENCY_MS = {ms}\n'}


def build(dest: Path, name: str, branches):
    repo = dest / name
    if repo.exists():
        import shutil
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    write(repo, BASE_FILES)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base: checkout pipeline with latency SLA")
    for branch, (files, msg) in branches.items():
        git(repo, "checkout", "-q", "-b", branch, "main")
        write(repo, files)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", msg)
    git(repo, "checkout", "-q", "main")
    return repo


def build_all(dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    three_way = build(dest, "latency-budget", {
        "feature/fraud-check": (stage("fraud", 60, "Fraud scoring call."), "add fraud check stage"),
        "feature/tax-service": (stage("tax", 60, "Remote tax computation."), "add tax service stage"),
        "feature/loyalty": (stage("loyalty", 60, "Loyalty points lookup."), "add loyalty stage"),
    })
    harmless = build(dest, "harmless", {
        "feature/cache-warm": (stage("cache", 20, "Cache warm-up."), "add cache warm stage"),
        "feature/docs": ({"docs/checkout.md": "# Checkout\nStages run in name order.\n"}, "add docs"),
        "feature/log-wording": ({"checkout/stages/core.py": '"""Core payment authorization."""\n'
                                 'LATENCY_MS = 100\nLOG = "authorizing card payment"\n'},
                                "clarify log message"),
    })
    return three_way, harmless


