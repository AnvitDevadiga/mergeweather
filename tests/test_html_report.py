import json
import re

import pytest

from mergeweather.cli import main
from mergeweather.html_report import graph_data, render


@pytest.fixture(scope="module")
def demo_report(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    assert main(["demo", "--no-open", "-q", "--sandbox", "local", "--out", str(out)]) == 0
    return json.loads((out / "report.json").read_text()), (out / "report.html").read_text()


def test_self_contained_no_network(demo_report):
    _, html = demo_report
    assert not re.search(r'<(script|link|img)[^>]+(src|href)="(https?:)?//', html)
    assert "@import" not in html and "fonts.googleapis" not in html
    assert "--tw-" in html  # compiled Tailwind inlined
    assert 'class="dark"' in html  # dark-mode first


def test_dashboard_sections(demo_report):
    _, html = demo_report
    for text in [
        "Storm warning",
        "Interaction graph",
        'id="mw-graph"',
        "Combination lattice",
        "Branch network",
        "Evidence &amp; LLM Explanation",
        "Copy reproduction command",
        "Removal checks",
        "proven 1-minimal",
        "mergeweather explain report.json",
    ]:
        assert text in html, text


def test_copy_buttons_target_existing_blocks(demo_report):
    _, html = demo_report
    targets = re.findall(r'data-copy="([^"]+)"', html)
    assert targets
    for t in targets:
        assert f'id="{t}"' in html
    m = re.search(r'<pre id="repro-F1"[^>]*>(.*?)</pre>', html, re.S)
    assert "git merge --no-ff" in m.group(1) and "python3 integration_test.py" in m.group(1)


def test_embedded_graph_data(demo_report):
    rep, html = demo_report
    raw = re.search(r'<script type="application/json" id="mw-data">(.*?)</script>', html, re.S).group(1)
    data = json.loads(raw)
    assert data == json.loads(json.dumps(graph_data(rep)))
    f = data["findings"][0]
    assert sorted(f["b"]) == ["fraud", "loyalty", "tax"]
    assert {n["id"] for n in data["nodes"]} >= set(f["checks"]) | {f["combo"]}


def test_hostile_content_is_escaped(demo_report):
    rep, _ = demo_report
    rep = json.loads(json.dumps(rep))
    evil = "</script><script>alert(1)</script>"
    rep["inputs"]["test_command"] = evil
    rep["combinations"][0]["runs"][0]["stdout_tail"] = evil
    rep["findings"][0]["signature"] = [evil]
    html = render(rep)
    assert evil not in html
    assert html.count("<script") == 3  # theme bootstrap, data, app


def test_explanation_in_drawer_with_labels(demo_report):
    rep, _ = demo_report
    rep = json.loads(json.dumps(rep))
    rep["explanation"] = {
        "model": "test-model",
        "summary": "Three stages exceed the SLA together.",
        "warnings": [],
        "claims": [
            {"text": "Each branch adds 60 ms.", "label": "observation", "evidence": ["diff:tax"]},
            {"text": "A budget check per stage would catch this.", "label": "hypothesis", "evidence": []},
        ],
    }
    html = render(rep)
    assert "Three stages exceed the SLA together." in html
    assert "OBSERVATION" in html and "HYPOTHESIS" in html and "diff:tax" in html
    assert "test-model" in html


def test_report_html_written_for_harmless(tmp_path):
    out = tmp_path / "h"
    assert main(["demo", "--harmless", "--no-open", "-q", "--sandbox", "local", "--out", str(out)]) == 0
    html = (out / "report.html").read_text()
    assert "Clear skies" in html and "No failing combinations" in html
