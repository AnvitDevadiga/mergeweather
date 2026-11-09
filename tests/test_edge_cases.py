import os
import signal
import subprocess
import sys
import time

import pytest

from conftest import ROOT, make_repo
from mergeweather import report
from mergeweather.cli import main
from mergeweather.engine import ConfigError
from mergeweather.gitutil import InvalidRef


def simple_repo(tmp_path, branches=None):
    return make_repo(tmp_path / "r", {"t.py": "print('ok')\n", "v.txt": "1\n"},
                     branches or {"a": {"a.txt": "a"}, "b": {"b.txt": "b"}})


# --- invalid refs ---------------------------------------------------------
def test_invalid_branch_ref(tmp_path, make_engine):
    repo = simple_repo(tmp_path)
    with pytest.raises(InvalidRef):
        make_engine(repo, ["a", "does-not-exist"], "true").run()


def test_invalid_base_ref(tmp_path, make_engine):
    repo = simple_repo(tmp_path)
    with pytest.raises(InvalidRef):
        make_engine(repo, ["a"], "true", base="nope").run()


def test_option_like_ref_rejected(tmp_path, make_engine):
    repo = simple_repo(tmp_path)
    with pytest.raises(InvalidRef):
        make_engine(repo, ["--output=/tmp/x"], "true").run()


def test_base_not_ancestor(tmp_path, make_engine):
    repo = simple_repo(tmp_path)
    with pytest.raises(ConfigError):
        make_engine(repo, ["b"], "true", base="a").run()


def test_cli_invalid_ref_exit_code(tmp_path, capsys):
    repo = simple_repo(tmp_path)
    code = main(["run", "--repo", str(repo), "--base", "main", "-b", "missing", "--test-cmd", "true",
                 "--sandbox", "local", "--allow-unsandboxed", "--out", str(tmp_path / "o"),
                 "--workroot", str(tmp_path / "w")])
    assert code == 2
    assert "does not resolve" in capsys.readouterr().err


def test_local_requires_opt_in(tmp_path):
    repo = simple_repo(tmp_path)
    assert main(["run", "--repo", str(repo), "--base", "main", "-b", "a", "--test-cmd", "true",
                 "--sandbox", "local"]) == 2


# --- merge conflicts ------------------------------------------------------
def test_merge_conflict_reported_separately(tmp_path, make_engine):
    repo = simple_repo(tmp_path, {"a": {"v.txt": "A\n"}, "b": {"v.txt": "B\n"}, "c": {"c.txt": "c"}})
    eng = make_engine(repo, ["a", "b", "c"], "python3 t.py")
    eng.run()
    rec = eng.combos[("a", "b")]
    assert rec.status == "conflict"
    assert rec.conflict_files == ["v.txt"] and rec.conflict_at == "b"
    assert rec.runs == []
    assert eng.findings == []
    assert {"combination": "a+b+c", "reason": "subset a+b is conflict"} in eng.pruned
    rep = report.build(eng, [])
    assert rep["conflicts"][0]["files"] == ["v.txt"]
    assert rep["verdict"] == "no-failures-found"


# --- flaky outcomes -------------------------------------------------------
def test_flaky_outcome_detected(tmp_path, make_engine):
    counter = tmp_path / "counter"
    counter.write_text("0")
    # fails on 1st, 3rd, ... invocation whenever b.txt is present
    script = (f"import os,sys\np={str(counter)!r}\nn=int(open(p).read())\n"
              "if not os.path.exists('b.txt'): sys.exit(0)\n"
              "open(p,'w').write(str(n+1))\n"
              "print('FAIL: AssertionError flaky') if n%2==0 else None\nsys.exit(1 if n%2==0 else 0)\n")
    repo = make_repo(tmp_path / "r", {"t.py": script}, {"a": {"a.txt": "a"}, "b": {"b.txt": "b"}})
    eng = make_engine(repo, ["a", "b"], "python3 t.py")
    eng.run()
    assert eng.combos[("b",)].status == "flaky"
    f = [f for f in eng.findings if f["branches"] == ["b"]][0]
    assert f["stability"] == "unstable"
    assert f["minimality"] == "smallest_found"
    assert "b" in report.build(eng, [])["flaky_combinations"]


def test_stable_failure_repeated(tmp_path, make_engine):
    repo = make_repo(tmp_path / "r", {"t.py": "import os,sys\nsys.exit(1 if os.path.exists('b.txt') else 0)\n"},
                     {"b": {"b.txt": "b"}})
    eng = make_engine(repo, ["b"], "python3 t.py", repeats=4)
    eng.run()
    assert len(eng.combos[("b",)].runs) == 4
    assert eng.findings[0]["minimality"] == "proven_1_minimal"
    assert eng.findings[0]["kind"] == "single-branch failure"


# --- budget exhaustion ----------------------------------------------------
def test_budget_exhaustion(tmp_path, fixtures, make_engine):
    repo, _ = fixtures
    eng = make_engine(repo, ["feature/fraud-check", "feature/tax-service", "feature/loyalty"],
                      "python3 integration_test.py", max_runs=5)
    eng.run()
    assert eng.budget.exhausted and eng.budget.used_runs == 5
    rep = report.build(eng, [])
    assert rep["verdict"] == "inconclusive-budget"
    assert rep["budget"]["unexplored"]
    assert rep["findings"] == []
    report.write(rep, tmp_path / "out")


def test_budget_exhaustion_during_reduction(tmp_path, fixtures, make_engine):
    """Triple found but too little budget to prove minimality -> smallest_found, not proven."""
    repo, _ = fixtures
    eng = make_engine(repo, ["feature/fraud-check", "feature/tax-service", "feature/loyalty"],
                      "python3 integration_test.py", max_runs=13, full_first=True)
    eng.run()
    assert eng.budget.exhausted
    assert eng.findings and all(f["minimality"] == "smallest_found" for f in eng.findings)


def test_timeout_is_a_distinct_failure(tmp_path, make_engine):
    repo = make_repo(tmp_path / "r", {"t.py": "import os,time\nos.path.exists('s.txt') and time.sleep(30)\n"},
                     {"s": {"s.txt": "s"}})
    eng = make_engine(repo, ["s"], "python3 t.py", repeats=1, timeout=1)
    eng.run()
    assert eng.combos[("s",)].runs[0].outcome == "timeout"
    assert eng.findings[0]["fingerprint"] == "timeout"


def test_base_failing_stops(tmp_path, make_engine):
    repo = simple_repo(tmp_path)
    eng = make_engine(repo, ["a", "b"], "false")
    eng.run()
    assert not eng.base_ok and eng.findings == []
    assert report.build(eng, [])["verdict"] == "base-failing"


def test_credentials_not_passed(tmp_path, make_engine, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cr3t")
    repo = make_repo(tmp_path / "r", {"t.py": "import os,sys\nsys.exit(1 if 'AWS_SECRET_ACCESS_KEY' in os.environ else 0)\n"},
                     {"a": {"a.txt": "a"}})
    eng = make_engine(repo, ["a"], "python3 t.py")
    eng.run()
    assert eng.base_ok and eng.findings == []


# --- cleanup after interruption ------------------------------------------
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_cleanup_after_interrupt(tmp_path, sig):
    repo = simple_repo(tmp_path)
    work = tmp_path / "work"
    marker = tmp_path / "started"
    cmd = f"touch {marker}; sleep 60"
    proc = subprocess.Popen(
        [sys.executable, "-m", "mergeweather", "run", "--repo", str(repo), "--base", "main", "-b", "a",
         "--test-cmd", cmd, "--sandbox", "local", "--allow-unsandboxed", "--workroot", str(work),
         "--out", str(tmp_path / "o"), "-q"],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    while not marker.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert marker.exists(), proc.stderr.read() if proc.poll() is not None else "never started"
    assert any(work.iterdir())
    proc.send_signal(sig)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 130, err
    assert list(work.iterdir()) == []
    # the sleeping test process was killed too
    ps = subprocess.run(["pgrep", "-f", "sleep 60"], capture_output=True, text=True).stdout.split()
    for pid in ps:
        cmdline = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
        assert str(marker) not in cmdline


def test_clean_stale(tmp_path):
    from mergeweather.workspace import MARKER, clean_stale
    d = tmp_path / "mergeweather-stale"
    d.mkdir()
    (d / MARKER).write_text("999999")
    (tmp_path / "unrelated").mkdir()
    assert clean_stale(tmp_path) == 1
    assert not d.exists() and (tmp_path / "unrelated").exists()
