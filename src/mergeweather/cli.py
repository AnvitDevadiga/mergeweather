"""Command-line interface."""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__, report as report_mod, workspace
from .engine import Budget, ConfigError, Engine
from .gitutil import GitError, InvalidRef
from .runner import DockerRunner, Limits, LocalRunner

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE, EXIT_BASE, EXIT_INCONCLUSIVE, EXIT_INTERRUPTED = 0, 1, 2, 3, 4, 130


def _branch_arg(s: str):
    if "=" in s:
        label, ref = s.split("=", 1)
        return label.strip(), ref.strip()
    return s, s


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mergeweather", description="Detect behavioral integration "
                                "failures across independently passing Git branches.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="analyze branch combinations")
    r.add_argument("--repo", default=".", help="repository path (never modified)")
    r.add_argument("--base", required=True, help="explicit common base commit/ref")
    r.add_argument("--branch", "-b", action="append", required=True, type=_branch_arg,
                   metavar="[LABEL=]REF", help="branch reference (repeatable)")
    r.add_argument("--test-cmd", required=True, help="integration test command (run via sh -c)")
    r.add_argument("--max-runs", type=int, default=60, help="budget: max test executions")
    r.add_argument("--max-seconds", type=float, default=None, help="budget: wall-clock seconds")
    r.add_argument("--max-size", type=int, default=4, help="largest combination size to explore")
    r.add_argument("--repeats", type=int, default=3, help="repetitions for suspected failures")
    r.add_argument("--full-first", action="store_true", help="test the full branch set right after base")
    r.add_argument("--fingerprint-regex", default=None, help="regex selecting signature lines")
    r.add_argument("--sandbox", choices=["docker", "local", "auto"], default="docker")
    r.add_argument("--allow-unsandboxed", action="store_true",
                   help="permit the local backend (no network isolation)")
    r.add_argument("--image", default="python:3.12-slim", help="container image")
    r.add_argument("--timeout", type=float, default=120.0, help="per-run timeout seconds")
    r.add_argument("--memory", type=int, default=1024, help="memory limit MB")
    r.add_argument("--cpus", type=float, default=1.0)
    r.add_argument("--pass-env", action="append", default=[], help="env var to pass through")
    r.add_argument("--out", default="mergeweather-report", help="output directory")
    r.add_argument("--formats", default="json,md,html")
    r.add_argument("--workroot", default=None, help="parent dir for disposable workspaces")
    r.add_argument("--quiet", "-q", action="store_true")

    e = sub.add_parser("explain", help="add an evidence-cited LLM explanation to a report")
    e.add_argument("report")
    e.add_argument("--model", default=None)
    e.add_argument("--dry-run", action="store_true", help="print the prompt; make no API call")
    e.add_argument("--out", default=None, help="output dir (default: alongside report)")

    rd = sub.add_parser("render", help="re-render Markdown/HTML from report.json")
    rd.add_argument("report")
    rd.add_argument("--out", default=None)

    c = sub.add_parser("clean", help="remove leftover workspaces from killed runs")
    c.add_argument("--workroot", default=None)
    return p


def _make_runner(a) -> Optional[object]:
    limits = Limits(timeout=a.timeout, memory_mb=a.memory, cpus=a.cpus)
    mode = a.sandbox
    if mode == "auto":
        mode = "docker" if DockerRunner.available() else "local"
    if mode == "docker":
        if not DockerRunner.available():
            print("error: Docker is not available. Start Docker, or use --sandbox local "
                  "--allow-unsandboxed for trusted code.", file=sys.stderr)
            return None
        return DockerRunner(limits, image=a.image, pass_env=a.pass_env)
    if not a.allow_unsandboxed:
        print("error: the local backend does not isolate network/filesystem; "
              "pass --allow-unsandboxed to use it for trusted code.", file=sys.stderr)
        return None
    print("warning: running repository code WITHOUT container isolation", file=sys.stderr)
    return LocalRunner(limits, pass_env=a.pass_env)


def cmd_run(a, argv) -> int:
    runner = _make_runner(a)
    if runner is None:
        return EXIT_USAGE
    log = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr, flush=True))
    try:
        engine = Engine(Path(a.repo), a.base, a.branch, a.test_cmd, runner,
                        Budget(max_runs=a.max_runs, max_seconds=a.max_seconds, max_size=a.max_size),
                        repeats=a.repeats, fingerprint_regex=a.fingerprint_regex,
                        workroot=Path(a.workroot) if a.workroot else None,
                        full_first=a.full_first, log=log)
        engine.run()
    except InvalidRef as ex:
        print(f"error: {ex}", file=sys.stderr)
        return EXIT_USAGE
    except (ConfigError, GitError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return EXIT_USAGE
    rep = report_mod.build(engine, ["mergeweather"] + argv)
    paths = report_mod.write(rep, Path(a.out), tuple(x.strip() for x in a.formats.split(",")))
    print(f"verdict: {rep['verdict']}")
    for f in rep["findings"]:
        print(f"  {f['id']} {f['kind']}: {' + '.join(f['branches'])} [{f['minimality']}, {f['stability']}]")
    for c in rep["conflicts"]:
        print(f"  conflict {c['combination']}: {', '.join(c['files'])}")
    for p in paths:
        print(f"wrote {p}")
    return {"base-failing": EXIT_BASE, "interactions-found": EXIT_FINDINGS,
            "inconclusive-budget": EXIT_INCONCLUSIVE}.get(rep["verdict"], EXIT_OK)


def cmd_explain(a) -> int:
    from . import explain
    path = Path(a.report)
    rep = json.loads(path.read_text())
    if a.dry_run:
        print(explain.build_prompt(rep))
        return EXIT_OK
    try:
        rep["explanation"] = explain.explain(rep, model=a.model or explain.DEFAULT_MODEL)
    except Exception as ex:  # network/API/parse errors must not corrupt the report
        print(f"error: explanation failed: {ex}", file=sys.stderr)
        return EXIT_USAGE
    out = Path(a.out) if a.out else path.parent
    for p in report_mod.write(rep, out):
        print(f"wrote {p}")
    return EXIT_OK


def cmd_render(a) -> int:
    path = Path(a.report)
    rep = json.loads(path.read_text())
    for p in report_mod.write(rep, Path(a.out) if a.out else path.parent, ("md", "html")):
        print(f"wrote {p}")
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    workspace.install_signal_handlers()
    try:
        if a.cmd == "run":
            return cmd_run(a, argv)
        if a.cmd == "explain":
            return cmd_explain(a)
        if a.cmd == "render":
            return cmd_render(a)
        if a.cmd == "clean":
            n = workspace.clean_stale(Path(a.workroot) if a.workroot else None)
            print(f"removed {n} stale workspace(s)")
            return EXIT_OK
    except KeyboardInterrupt:
        workspace.kill_children()
        print("interrupted; workspaces cleaned up", file=sys.stderr)
        return EXIT_INTERRUPTED
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
