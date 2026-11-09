import json
from pathlib import Path

from mergeweather import explain, report
from mergeweather.fingerprint import fingerprint
from mergeweather.runner import DockerRunner, Limits


def test_fingerprint_normalizes_numbers_and_paths():
    a, _ = fingerprint("fail", 1, "FAIL: latency 280ms > 250 at /tmp/x/y.py", "")
    b, _ = fingerprint("fail", 1, "FAIL: latency 310ms > 250 at /tmp/z/q.py", "")
    c, _ = fingerprint("fail", 1, "FAIL: KeyError missing", "")
    assert a == b != c
    assert fingerprint("timeout", None, "", "")[0] == "timeout"


def test_docker_command_boundaries(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    r = DockerRunner(Limits(timeout=10, memory_mb=256, cpus=0.5, pids=64), image="img:1")
    args = r.build_command(Path("/w"), "make test", "n1")
    s = " ".join(args)
    for frag in [
        "--network none",
        "--memory 256m",
        "--memory-swap 256m",
        "--pids-limit 64",
        "--cap-drop ALL",
        "no-new-privileges",
        "--cpus 0.5",
        "-v /w:/work:rw",
        "img:1 sh -c make test",
    ]:
        assert frag in s
    assert "ghp_x" not in s and "--rm" in args


def _report_with_finding():
    return {
        "inputs": {"test_command": "t", "branches": [{"label": "a", "changed_files": ["a"], "diff": "+x"}]},
        "combinations": [
            {"id": "a", "branches": ["a"], "status": "fail", "tree": "t", "conflict_files": [], "runs": []}
        ],
        "findings": [
            {
                "id": "F1",
                "branches": ["a"],
                "kind": "k",
                "fingerprint": "f",
                "minimality": "m",
                "minimality_caveats": [],
                "stability": "stable",
                "signature": [],
            }
        ],
    }


def test_explain_labels_and_validates_citations():
    reply = json.dumps(
        {
            "summary": "s",
            "claims": [
                {"text": "a fails", "kind": "observation", "evidence": ["combo:a"]},
                {"text": "invented", "kind": "observation", "evidence": ["combo:zzz"]},
                {"text": "maybe x", "kind": "hypothesis", "evidence": ["diff:a"]},
            ],
        }
    )
    seen = {}

    def fake(prompt, model):
        seen["prompt"] = prompt
        return "Here:\n" + reply

    out = explain.explain(_report_with_finding(), transport=fake)
    labels = [(c["text"], c["label"], c["evidence"]) for c in out["claims"]]
    assert labels == [
        ("a fails", "observation", ["combo:a"]),
        ("invented", "hypothesis", []),
        ("maybe x", "hypothesis", ["diff:a"]),
    ]
    assert out["warnings"] and "combo:a" in seen["prompt"]


def test_explanation_rendered_and_escaped():
    exp = {
        "model": "m",
        "summary": "<b>x</b>",
        "warnings": [],
        "claims": [{"text": "<script>", "label": "hypothesis", "evidence": []}],
    }
    md = report.explanation_markdown(exp)
    assert "[HYPOTHESIS]" in md
