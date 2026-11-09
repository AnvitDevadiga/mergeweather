import json
import subprocess
import sys

from rich.console import Console

from conftest import ROOT
from mergeweather.cli import main
from mergeweather.console import Dashboard, print_summary, weather_key
from mergeweather.engine import ComboRecord
from mergeweather.fixtures import build_all


def test_fixture_test_script_actually_runs(tmp_path):
    """Guard: the fixture's integration test must execute and print a verdict."""
    three_way, harmless = build_all(tmp_path)
    out = subprocess.run([sys.executable, "integration_test.py"], cwd=three_way, capture_output=True, text=True)
    assert out.returncode == 0 and "PASS: checkout latency 100ms" in out.stdout
    subprocess.run(["git", "merge", "-q", "--no-edit", "feature/fraud-check", "feature/tax-service",
                    "feature/loyalty"], cwd=three_way, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})
    out = subprocess.run([sys.executable, "integration_test.py"], cwd=three_way, capture_output=True, text=True)
    assert out.returncode == 1 and "280ms exceeds SLA 250ms" in out.stdout


def _demo(tmp_path, *extra):
    out = tmp_path / "demo"
    code = main(["demo", "--no-open", "--sandbox", "local", "--out", str(out),
                 "--workroot", str(tmp_path / "w"), *extra])
    return code, json.loads((out / "report.json").read_text()), out


def test_demo_command_finds_three_way_bug(tmp_path, capsys):
    code, rep, out = _demo(tmp_path)
    assert code == 0
    assert rep["verdict"] == "interactions-found"
    (f,) = rep["findings"]
    assert sorted(f["branches"]) == ["fraud", "loyalty", "tax"]
    assert f["minimality"] == "proven_1_minimal" and f["stability"] == "stable"
    assert (out / "report.html").exists() and (out / "report.md").exists()
    text = capsys.readouterr().out
    assert "Storm warning" in text and "Thunderstorm" in text
    assert list((tmp_path / "w").iterdir()) == []


def test_demo_harmless(tmp_path, capsys):
    code, rep, _ = _demo(tmp_path, "--harmless")
    assert code == 0 and rep["verdict"] == "no-failures-found" and rep["findings"] == []
    assert "Clear skies" in capsys.readouterr().out


def test_demo_via_module_entrypoint(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "mergeweather", "demo", "--no-open", "--sandbox", "local",
                           "--out", str(tmp_path / "o"), "-q"], capture_output=True, text=True,
                          env={"PYTHONPATH": str(ROOT / "src"), "PATH": __import__("os").environ["PATH"]})
    assert proc.returncode == 0, proc.stderr
    assert "verdict: interactions-found" in proc.stdout


def test_weather_mapping():
    assert weather_key("pass", 2) == "pass"
    assert weather_key("fail", 1) == "fail"          # Rain: single branch broken
    assert weather_key("fail", 3) == "interaction"   # Thunderstorm
    assert weather_key("flaky", 2) == "flaky"        # Showers
    assert weather_key("conflict", 2) == "conflict"  # Fog
    assert weather_key("not_run", 2) == "not_run"


def test_summary_renders_every_weather():
    rep = {
        "verdict": "interactions-found",
        "inputs": {"branches": [{"label": l, "commit": "c" * 40} for l in "abcd"]},
        "combinations": [
            {"id": "a", "branches": ["a"], "status": "pass", "runs": [1], "fingerprints": ["pass"], "conflict_files": []},
            {"id": "b", "branches": ["b"], "status": "flaky", "runs": [1, 2, 3], "fingerprints": ["fail:x", "pass"], "conflict_files": []},
            {"id": "c+d", "branches": ["c", "d"], "status": "conflict", "runs": [], "fingerprints": [], "conflict_files": ["x.py"]},
            {"id": "a+c", "branches": ["a", "c"], "status": "fail", "runs": [1, 2, 3], "fingerprints": ["fail:y"], "conflict_files": []},
            {"id": "a+d", "branches": ["a", "d"], "status": "not_run", "runs": [], "fingerprints": [], "conflict_files": []},
        ],
        "findings": [{"id": "F1", "branches": ["a", "c"], "kind": "pairwise interaction", "minimality": "proven_1_minimal",
                      "stability": "stable", "fingerprint": "fail:y", "minimality_caveats": [], "signature": ["FAIL: #ms"]}],
        "conflicts": [{"combination": "c+d", "branches": ["c", "d"], "files": ["x.py"]}],
        "budget": {"used_runs": 7, "max_runs": 7, "exhausted": True, "reason": "max_runs=7 reached"},
        "isolation": {"backend": "docker", "network_isolated": True},
    }
    con = Console(record=True, width=140, force_terminal=False)
    print_summary(rep, con)
    text = con.export_text()
    for word in ["Storm warning", "Sunny", "Showers", "Fog", "Thunderstorm", "Uncharted", "conflict in x.py",
                 "exhausted (max_runs=7 reached)", "conflict:c+d"]:
        assert word in text, word


def test_dashboard_consumes_engine_events():
    con = Console(record=True, width=120, force_terminal=False)
    dash = Dashboard(con)
    rec = ComboRecord("a+b", ("a", "b"), status="fail", tree="t" * 40)
    dash("phase", name="size 2")
    dash("run_start", combo=rec, attempt=1)
    dash("combo", combo=rec)
    con.print(dash.render())
    text = con.export_text()
    assert "size 2" in text and "a+b" in text and "Thunderstorm" in text
