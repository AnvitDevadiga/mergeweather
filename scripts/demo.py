#!/usr/bin/env python3
"""One-command demo: `make demo` (or `python3 scripts/demo.py`).

Builds both fixture repositories and analyzes them. Uses Docker when it is
available; otherwise falls back to the local backend (trusted fixture code only)
and the report states that network isolation was not in effect.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from make_fixtures import build_all  # noqa: E402
from mergeweather.cli import main  # noqa: E402
from mergeweather.runner import DockerRunner  # noqa: E402

out = ROOT / "demo-output"
if out.exists():
    shutil.rmtree(out)
three_way, harmless = build_all(out / "fixtures")

sandbox = ["--sandbox", "docker"] if DockerRunner.available() else ["--sandbox", "local", "--allow-unsandboxed"]
cmd = "python3 integration_test.py"

for repo, branches, name in [
    (three_way, ["fraud=feature/fraud-check", "tax=feature/tax-service", "loyalty=feature/loyalty"], "latency-budget"),
    (harmless, ["cache=feature/cache-warm", "docs=feature/docs", "log=feature/log-wording"], "harmless"),
]:
    print(f"\n=== {name} ===", flush=True)
    args = ["run", "--repo", str(repo), "--base", "main", "--test-cmd", cmd, "--out", str(out / name),
            "--timeout", "60", *sandbox]
    for b in branches:
        args += ["--branch", b]
    code = main(args)
    print(f"exit code {code}")

print(f"\nOpen {out / 'latency-budget' / 'report.html'} in a browser.")
