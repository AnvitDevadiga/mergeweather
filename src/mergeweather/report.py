"""Report model and exporters (JSON, Markdown, static HTML)."""
from __future__ import annotations

import html
import json
import math
import shlex
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from . import __version__
from .engine import Engine, combo_id

SCHEMA = "mergeweather.report/v1"

MINIMALITY_NOTE = (
    "'proven_1_minimal' means: the set fails stably and removing any single member was tested "
    "and did not reproduce the same failure fingerprint. 'smallest_found' means that proof is "
    "incomplete (budget, conflicts, flakiness or errors). Neither implies global minimality: "
    "another smaller or disjoint set could produce the same failure.")

ORDER_NOTE = (
    "Each combination is built from the pinned base commit by merging member branch commits one "
    "at a time with `git merge --no-ff`, in ascending lexicographic order of branch labels, with a "
    "fixed committer identity and timestamp (2000-01-01T00:00:00Z), so merge commits and trees "
    "are reproducible.")


def reproduction(engine: Engine, branches) -> str:
    lines = [
        "export GIT_AUTHOR_NAME=MergeWeather GIT_AUTHOR_EMAIL=mergeweather@localhost "
        "GIT_COMMITTER_NAME=MergeWeather GIT_COMMITTER_EMAIL=mergeweather@localhost "
        "GIT_AUTHOR_DATE='2000-01-01T00:00:00 +0000' GIT_COMMITTER_DATE='2000-01-01T00:00:00 +0000'",
        f"git worktree add --detach ../mw-repro {engine.base.sha}",
        "cd ../mw-repro",
    ]
    for label in engine.canonical(branches):
        lines.append(f"git merge --no-ff --no-edit -m {shlex.quote('mergeweather: merge ' + label)} "
                     f"{engine.branches[label].sha}")
    lines.append(engine.command)
    return "\n".join(lines)


def build(engine: Engine, argv: List[str]) -> Dict:
    combos = []
    for rec in sorted(engine.combos.values(), key=lambda r: (len(r.branches), r.branches)):
        d = asdict(rec)
        d["branches"] = list(rec.branches)
        d["evidence_id"] = f"combo:{rec.id}"
        if rec.status != "conflict":
            d["reproduction"] = reproduction(engine, rec.branches)
        combos.append(d)
    findings = []
    for f in engine.findings:
        f = dict(f)
        f["reproduction"] = reproduction(engine, f["branches"])
        f["evidence"] = [f"combo:{f['combination']}"] + [f"combo:{c['combination']}"
                                                         for c in f["removal_checks"]]
        findings.append(f)
    conflicts = [{"combination": r.id, "branches": list(r.branches), "files": r.conflict_files,
                  "conflict_while_merging": r.conflict_at}
                 for r in engine.combos.values() if r.status == "conflict"]
    flaky = [r.id for r in engine.combos.values() if r.status == "flaky"]
    unexplored = engine.unexplored()
    if not engine.base_ok:
        verdict = "base-failing"
    elif findings:
        verdict = "interactions-found"
    elif engine.budget.exhausted or unexplored:
        verdict = "inconclusive-budget"
    else:
        verdict = "no-failures-found"
    return {
        "schema": SCHEMA,
        "tool": {"name": "mergeweather", "version": __version__},
        "verdict": verdict,
        "inputs": {
            "repository": str(engine.repo),
            "base": {"ref": engine.base.ref, "commit": engine.base.sha},
            "branches": [{"label": b.label, "ref": b.ref, "commit": b.sha,
                          "changed_files": b.changed_files, "diff": b.diff,
                          "evidence_id": f"diff:{b.label}"}
                         for b in (engine.branches[l] for l in engine.order)],
            "test_command": engine.command,
            "repeats": engine.repeats,
            "fingerprint_regex": engine.fp_regex,
            "argv": argv,
        },
        "canonical_order": {"labels": engine.order, "description": ORDER_NOTE},
        "isolation": engine.runner.isolation(),
        "budget": {"max_runs": engine.budget.max_runs, "max_seconds": engine.budget.max_seconds,
                   "max_size": engine.budget.max_size, "used_runs": engine.budget.used_runs,
                   "exhausted": engine.budget.exhausted, "reason": engine.budget.reason,
                   "unexplored": unexplored},
        "minimality_note": MINIMALITY_NOTE,
        "findings": findings,
        "conflicts": conflicts,
        "flaky_combinations": flaky,
        "pruned": engine.pruned,
        "combinations": combos,
    }


# ------------------------------------------------------------------ markdown
def _mermaid(report: Dict) -> str:
    lines = ["```mermaid", "graph LR"]
    for b in report["inputs"]["branches"]:
        lines.append(f'  {_nid(b["label"])}["{b["label"]}"]')
    for f in report["findings"]:
        if len(f["branches"]) == 1:
            lines.append(f'  {_nid(f["branches"][0])} -. "{f["id"]} fails alone" .- {_nid(f["branches"][0])}')
        elif len(f["branches"]) == 2:
            a, b = f["branches"]
            lines.append(f'  {_nid(a)} == "{f["id"]}" === {_nid(b)}')
        else:
            hub = f["id"]
            lines.append(f'  {hub}(("{hub}: {f["kind"]}"))')
            for m in f["branches"]:
                lines.append(f"  {_nid(m)} === {hub}")
    for c in report["conflicts"]:
        if len(c["branches"]) == 2:
            a, b = c["branches"]
            lines.append(f'  {_nid(a)} -. "conflict" .- {_nid(b)}')
    lines.append("```")
    return "\n".join(lines)


def _nid(label: str) -> str:
    return "b_" + "".join(ch if ch.isalnum() else "_" for ch in label)


def to_markdown(report: Dict) -> str:
    inp = report["inputs"]
    out = [f"# MergeWeather report", "",
           f"**Verdict:** `{report['verdict']}`  ",
           f"**Repository:** `{inp['repository']}`  ",
           f"**Base:** `{inp['base']['ref']}` @ `{inp['base']['commit']}`  ",
           f"**Test command:** `{inp['test_command']}`  ",
           f"**Sandbox:** {report['isolation']['backend']} "
           f"(network isolated: {report['isolation']['network_isolated']})", ""]
    if report["isolation"].get("warning"):
        out += [f"> **Warning:** {report['isolation']['warning']}", ""]
    out += ["## Branches", "", "| Label | Ref | Commit | Changed files |", "|---|---|---|---|"]
    for b in inp["branches"]:
        out.append(f"| {b['label']} | `{b['ref']}` | `{b['commit'][:12]}` | "
                   f"{', '.join(b['changed_files']) or '-'} |")
    out += ["", "## Findings", ""]
    if not report["findings"]:
        out += ["No failing combinations were found within the explored space.", ""]
    for f in report["findings"]:
        out += [f"### {f['id']}: {f['kind']} — {' + '.join(f['branches'])}", "",
                f"- Fingerprint: `{f['fingerprint']}`",
                f"- Minimality: **{f['minimality']}**" +
                (f" ({'; '.join(f['minimality_caveats'])})" if f["minimality_caveats"] else ""),
                f"- Stability: {f['stability']}",
                f"- Reduced from: `{f['reduced_from']}`",
                f"- Evidence: {', '.join('`' + e + '`' for e in f['evidence'])}", ""]
        if f["signature"]:
            out += ["Failure signature (normalized):", "", "```", *f["signature"], "```", ""]
        out += ["Removal checks:", "", "| Removed | Combination | Status | Verdict |", "|---|---|---|---|"]
        for c in f["removal_checks"]:
            out.append(f"| {c['removed']} | `{c['combination']}` | {c['status']} | {c['verdict']} |")
        out += ["", "Reproduce:", "", "```sh", f["reproduction"], "```", ""]
    out += ["> " + report["minimality_note"], "", "## Interaction graph", "", _mermaid(report), ""]
    out += ["## Textual merge conflicts", ""]
    if report["conflicts"]:
        for c in report["conflicts"]:
            out.append(f"- `{c['combination']}`: conflict while merging `{c['conflict_while_merging']}` "
                       f"in {', '.join('`' + x + '`' for x in c['files'])}")
    else:
        out.append("None.")
    out += ["", "## All combinations", "", "| Combination | Status | Runs | Fingerprints | Tree |",
            "|---|---|---|---|---|"]
    for c in report["combinations"]:
        out.append(f"| `{c['id']}` | {c['status']}{' (incomplete)' if c['incomplete'] else ''} | "
                   f"{len(c['runs'])} | {', '.join(c['fingerprints']) or '-'} | "
                   f"`{(c['tree'] or '-')[:12]}` |")
    b = report["budget"]
    out += ["", "## Budget", "",
            f"Used {b['used_runs']} / {b['max_runs']} test runs; max size {b['max_size']}; "
            f"exhausted: {b['exhausted']}{' (' + b['reason'] + ')' if b['reason'] else ''}.", ""]
    if b["unexplored"]:
        out.append(f"Unexplored combinations ({len(b['unexplored'])}): " +
                   ", ".join(f"`{u}`" for u in b["unexplored"][:50]))
    if report["pruned"]:
        out += ["", f"Pruned combinations ({len(report['pruned'])}): supersets of failing, flaky or "
                    "conflicting sets are not run."]
    out += ["", "## Canonical order", "", report["canonical_order"]["description"], ""]
    if report.get("explanation"):
        out += [explanation_markdown(report["explanation"])]
    return "\n".join(out) + "\n"


def explanation_markdown(exp: Dict) -> str:
    out = ["## Explanation (generated, evidence-cited)", "",
           f"_Model: {exp.get('model')}. Claims marked HYPOTHESIS are not established by the "
           f"recorded evidence._", "", exp.get("summary", ""), ""]
    for c in exp.get("claims", []):
        tag = "OBSERVATION" if c["label"] == "observation" else "HYPOTHESIS"
        cites = ", ".join(f"`{e}`" for e in c["evidence"]) or "no valid citation"
        out.append(f"- **[{tag}]** {c['text']} — {cites}")
    for w in exp.get("warnings", []):
        out.append(f"- _note: {w}_")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- html
def _svg_graph(report: Dict) -> str:
    labels = [b["label"] for b in report["inputs"]["branches"]]
    n = len(labels)
    W, H, R = 520, 380, 140
    cx, cy = W / 2, H / 2
    pos = {}
    for i, l in enumerate(labels):
        a = -math.pi / 2 + 2 * math.pi * i / max(n, 1)
        pos[l] = (cx + R * math.cos(a), cy + R * math.sin(a))
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Branch interaction graph" '
             f'class="graph">']
    for c in report["conflicts"]:
        if len(c["branches"]) == 2:
            (x1, y1), (x2, y2) = pos[c["branches"][0]], pos[c["branches"][1]]
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                         f'class="e-conflict"><title>textual conflict</title></line>')
    for f in report["findings"]:
        members = f["branches"]
        cls = "e-fail" if f["stability"] == "stable" else "e-flaky"
        tip = html.escape(f"{f['id']}: {f['kind']} ({f['minimality']})")
        if len(members) == 2:
            (x1, y1), (x2, y2) = pos[members[0]], pos[members[1]]
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                         f'class="{cls}"><title>{tip}</title></line>')
        elif len(members) >= 3:
            hx = sum(pos[m][0] for m in members) / len(members)
            hy = sum(pos[m][1] for m in members) / len(members)
            for m in members:
                parts.append(f'<line x1="{pos[m][0]:.1f}" y1="{pos[m][1]:.1f}" x2="{hx:.1f}" '
                             f'y2="{hy:.1f}" class="{cls}"><title>{tip}</title></line>')
            parts.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="16" class="hub"><title>{tip}</title>'
                         f'</circle><text x="{hx:.1f}" y="{hy + 4:.1f}" class="hubt">'
                         f'{html.escape(f["id"])}</text>')
    failing_alone = {f["branches"][0] for f in report["findings"] if len(f["branches"]) == 1}
    for l, (x, y) in pos.items():
        cls = "node bad" if l in failing_alone else "node"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" class="{cls}"></circle>'
                     f'<text x="{x:.1f}" y="{y - 16:.1f}" class="nlabel">{html.escape(l)}</text>')
    parts.append("</svg>")
    return "".join(parts)


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--card:#fff;--line:#e4e1d8;--bad:#c2410c;
--ok:#15803d;--warn:#b45309;--accent:#1e40af;--code:#f3f1ea}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--muted:#a3a29b;--card:#1f1f1d;
--line:#34332f;--bad:#f97316;--ok:#4ade80;--warn:#fbbf24;--accent:#93c5fd;--code:#262623}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 10px;border-bottom:1px solid var(--line);
padding-bottom:6px}h3{font-size:16px;margin:0 0 8px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px;margin:12px 0}
code,pre{font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--code);border-radius:6px}
code{padding:1px 5px}pre{padding:10px 12px;overflow-x:auto;white-space:pre}
table{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;
border:1px solid currentColor}
.s-pass{color:var(--ok)}.s-fail{color:var(--bad)}.s-flaky,.s-conflict,.s-not_run,.s-error{color:var(--warn)}
.warn{border-left:4px solid var(--warn)}
.graph{width:100%;max-width:560px;height:auto;display:block;margin:auto}
.node{fill:var(--accent)}.node.bad{fill:var(--bad)}.nlabel{fill:var(--fg);font-size:13px;text-anchor:middle}
.e-fail{stroke:var(--bad);stroke-width:3}.e-flaky{stroke:var(--warn);stroke-width:3;stroke-dasharray:2 4}
.e-conflict{stroke:var(--warn);stroke-width:2;stroke-dasharray:6 5}
.hub{fill:var(--card);stroke:var(--bad);stroke-width:2}.hubt{fill:var(--fg);font-size:11px;text-anchor:middle;font-weight:700}
details summary{cursor:pointer;color:var(--accent)}
"""


def _pill(status: str) -> str:
    return f'<span class="pill s-{html.escape(status)}">{html.escape(status)}</span>'


def to_html(report: Dict) -> str:
    e = html.escape
    inp = report["inputs"]
    iso = report["isolation"]
    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>MergeWeather Report</title><style>{CSS}</style></head><body><main>",
         f"<h1>MergeWeather report</h1><p class='muted'>Verdict {_pill(report['verdict'])} · "
         f"base <code>{e(inp['base']['ref'])}</code> @ <code>{e(inp['base']['commit'][:12])}</code> · "
         f"command <code>{e(inp['test_command'])}</code></p>"]
    h.append(f"<div class='card{' warn' if iso.get('warning') else ''}'><b>Sandbox:</b> "
             f"{e(str(iso['backend']))} · network isolated: {e(str(iso['network_isolated']))} · "
             f"memory limit: {e(str(iso.get('memory_limit_mb')))} MB · timeout: "
             f"{e(str(iso['timeout_s']))} s · credentials scrubbed: {e(str(iso['credentials_scrubbed']))}"
             + (f"<br><b>Warning:</b> {e(iso['warning'])}" if iso.get("warning") else "") + "</div>")
    h.append("<h2>Interaction graph</h2><div class='card'>" + _svg_graph(report) +
             "<p class='muted'>Solid red: stable failing interaction (hub = 3+ branches). "
             "Dotted amber: unstable. Dashed amber: textual conflict.</p></div>")
    h.append("<h2>Findings</h2>")
    if not report["findings"]:
        h.append("<div class='card'>No failing combinations were found within the explored space.</div>")
    for f in report["findings"]:
        rows = "".join(f"<tr><td>{e(c['removed'])}</td><td><code>{e(c['combination'])}</code></td>"
                       f"<td>{_pill(c['status'])}</td><td>{e(c['verdict'])}</td></tr>"
                       for c in f["removal_checks"])
        h.append(
            f"<div class='card'><h3>{e(f['id'])}: {e(f['kind'])} — {e(' + '.join(f['branches']))}</h3>"
            f"<p>Fingerprint <code>{e(f['fingerprint'] or '')}</code> · minimality "
            f"<b>{e(f['minimality'])}</b> · stability {e(f['stability'])} · reduced from "
            f"<code>{e(f['reduced_from'])}</code></p>"
            + (f"<p class='muted'>Caveats: {e('; '.join(f['minimality_caveats']))}</p>"
               if f["minimality_caveats"] else "")
            + (f"<pre>{e(chr(10).join(f['signature']))}</pre>" if f["signature"] else "")
            + f"<table><tr><th>Removed</th><th>Combination</th><th>Status</th><th>Verdict</th></tr>{rows}</table>"
            f"<details><summary>Reproduction commands</summary><pre>{e(f['reproduction'])}</pre></details>"
            "</div>")
    h.append(f"<p class='muted'>{e(report['minimality_note'])}</p>")
    if report.get("explanation"):
        exp = report["explanation"]
        items = "".join(
            f"<li><span class='pill {'s-pass' if c['label'] == 'observation' else 's-flaky'}'>"
            f"{'OBSERVATION' if c['label'] == 'observation' else 'HYPOTHESIS'}</span> {e(c['text'])} "
            f"<span class='muted'>[{e(', '.join(c['evidence']) or 'no valid citation')}]</span></li>"
            for c in exp.get("claims", []))
        h.append(f"<h2>Explanation</h2><div class='card'><p class='muted'>Generated by "
                 f"{e(str(exp.get('model')))}; hypotheses are not established by evidence.</p>"
                 f"<p>{e(exp.get('summary', ''))}</p><ul>{items}</ul></div>")
    h.append("<h2>Textual merge conflicts</h2><div class='card'>")
    if report["conflicts"]:
        h.append("<ul>" + "".join(
            f"<li><code>{e(c['combination'])}</code>: while merging <code>{e(c['conflict_while_merging'])}"
            f"</code> — {e(', '.join(c['files']))}</li>" for c in report["conflicts"]) + "</ul>")
    else:
        h.append("None.")
    h.append("</div><h2>Branches</h2><table><tr><th>Label</th><th>Ref</th><th>Commit</th>"
             "<th>Changed files</th></tr>")
    for b in inp["branches"]:
        h.append(f"<tr><td>{e(b['label'])}</td><td><code>{e(b['ref'])}</code></td>"
                 f"<td><code>{e(b['commit'][:12])}</code></td><td>{e(', '.join(b['changed_files']))}</td></tr>")
    h.append("</table><h2>All combinations</h2><table><tr><th>Combination</th><th>Status</th>"
             "<th>Runs</th><th>Tree</th><th>Evidence</th></tr>")
    for c in report["combinations"]:
        runs = "".join(
            f"<p><b>{e(r['id'])}</b> {e(r['outcome'])} exit={e(str(r['exit_code']))} "
            f"{e(str(r['duration']))}s <code>{e(r['fingerprint'])}</code></p>"
            f"<pre>{e(r['stdout_tail'][-1500:])}\n{e(r['stderr_tail'][-1500:])}</pre>" for r in c["runs"])
        extra = (f"<p>Conflict files: {e(', '.join(c['conflict_files']))}</p>" if c["conflict_files"] else
                 f"<pre>{e(c.get('reproduction', ''))}</pre>")
        h.append(f"<tr><td><code>{e(c['id'])}</code></td><td>{_pill(c['status'])}"
                 f"{' <span class=muted>incomplete</span>' if c['incomplete'] else ''}</td>"
                 f"<td>{len(c['runs'])}</td><td><code>{e((c['tree'] or '-')[:12])}</code></td>"
                 f"<td><details><summary>details</summary>{extra}{runs}</details></td></tr>")
    b = report["budget"]
    h.append(f"</table><h2>Budget</h2><div class='card'>Used {b['used_runs']} / {b['max_runs']} runs, "
             f"max size {b['max_size']}, exhausted: {e(str(b['exhausted']))}"
             f"{' — ' + e(b['reason']) if b['reason'] else ''}. Unexplored: {len(b['unexplored'])}. "
             f"Pruned: {len(report['pruned'])}.</div>")
    h.append(f"<h2>Canonical order</h2><p>{e(report['canonical_order']['description'])}</p>")
    h.append("</main></body></html>")
    return "\n".join(h)


def write(report: Dict, out_dir: Path, formats=("json", "md", "html")) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    if "json" in formats:
        p = out_dir / "report.json"
        p.write_text(json.dumps(report, indent=2, sort_keys=False))
        written.append(p)
    if "md" in formats:
        p = out_dir / "report.md"
        p.write_text(to_markdown(report))
        written.append(p)
    if "html" in formats:
        p = out_dir / "report.html"
        p.write_text(to_html(report))
        written.append(p)
    return written
