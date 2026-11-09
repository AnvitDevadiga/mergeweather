"""Report model and exporters (JSON, Markdown, static HTML)."""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .engine import Engine

SCHEMA = "mergeweather.report/v1"

MINIMALITY_NOTE = (
    "'proven_1_minimal' means: the set fails stably and removing any single member was tested "
    "and did not reproduce the same failure fingerprint. 'smallest_found' means that proof is "
    "incomplete (budget, conflicts, flakiness or errors). Neither implies global minimality: "
    "another smaller or disjoint set could produce the same failure."
)

ORDER_NOTE = (
    "Each combination is built from the pinned base commit by merging member branch commits one "
    "at a time with `git merge --no-ff`, in ascending lexicographic order of branch labels, with a "
    "fixed committer identity and timestamp (2000-01-01T00:00:00Z), so merge commits and trees "
    "are reproducible."
)


def reproduction(engine: Engine, branches) -> str:
    lines = [
        "export GIT_AUTHOR_NAME=MergeWeather GIT_AUTHOR_EMAIL=mergeweather@localhost "
        "GIT_COMMITTER_NAME=MergeWeather GIT_COMMITTER_EMAIL=mergeweather@localhost "
        "GIT_AUTHOR_DATE='2000-01-01T00:00:00 +0000' GIT_COMMITTER_DATE='2000-01-01T00:00:00 +0000'",
        f"git worktree add --detach ../mw-repro {engine.base.sha}",
        "cd ../mw-repro",
    ]
    for label in engine.canonical(branches):
        lines.append(
            f"git merge --no-ff --no-edit -m {shlex.quote('mergeweather: merge ' + label)} {engine.branches[label].sha}"
        )
    lines.append(engine.command)
    return "\n".join(lines)


def build(engine: Engine, argv: list[str]) -> dict:
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
        f["evidence"] = [f"combo:{f['combination']}"] + [f"combo:{c['combination']}" for c in f["removal_checks"]]
        findings.append(f)
    conflicts = [
        {
            "combination": r.id,
            "branches": list(r.branches),
            "files": r.conflict_files,
            "conflict_while_merging": r.conflict_at,
        }
        for r in engine.combos.values()
        if r.status == "conflict"
    ]
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
            "branches": [
                {
                    "label": b.label,
                    "ref": b.ref,
                    "commit": b.sha,
                    "changed_files": b.changed_files,
                    "diff": b.diff,
                    "evidence_id": f"diff:{b.label}",
                }
                for b in (engine.branches[l] for l in engine.order)
            ],
            "test_command": engine.command,
            "repeats": engine.repeats,
            "fingerprint_regex": engine.fp_regex,
            "argv": argv,
        },
        "canonical_order": {"labels": engine.order, "description": ORDER_NOTE},
        "isolation": engine.runner.isolation(),
        "budget": {
            "max_runs": engine.budget.max_runs,
            "max_seconds": engine.budget.max_seconds,
            "max_size": engine.budget.max_size,
            "used_runs": engine.budget.used_runs,
            "exhausted": engine.budget.exhausted,
            "reason": engine.budget.reason,
            "unexplored": unexplored,
        },
        "minimality_note": MINIMALITY_NOTE,
        "findings": findings,
        "conflicts": conflicts,
        "flaky_combinations": flaky,
        "pruned": engine.pruned,
        "combinations": combos,
    }


# ------------------------------------------------------------------ markdown
def _mermaid(report: dict) -> str:
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


def to_markdown(report: dict) -> str:
    inp = report["inputs"]
    out = [
        "# MergeWeather report",
        "",
        f"**Verdict:** `{report['verdict']}`  ",
        f"**Repository:** `{inp['repository']}`  ",
        f"**Base:** `{inp['base']['ref']}` @ `{inp['base']['commit']}`  ",
        f"**Test command:** `{inp['test_command']}`  ",
        f"**Sandbox:** {report['isolation']['backend']} (network isolated: {report['isolation']['network_isolated']})",
        "",
    ]
    if report["isolation"].get("warning"):
        out += [f"> **Warning:** {report['isolation']['warning']}", ""]
    out += ["## Branches", "", "| Label | Ref | Commit | Changed files |", "|---|---|---|---|"]
    for b in inp["branches"]:
        out.append(f"| {b['label']} | `{b['ref']}` | `{b['commit'][:12]}` | {', '.join(b['changed_files']) or '-'} |")
    out += ["", "## Findings", ""]
    if not report["findings"]:
        out += ["No failing combinations were found within the explored space.", ""]
    for f in report["findings"]:
        out += [
            f"### {f['id']}: {f['kind']} — {' + '.join(f['branches'])}",
            "",
            f"- Fingerprint: `{f['fingerprint']}`",
            f"- Minimality: **{f['minimality']}**"
            + (f" ({'; '.join(f['minimality_caveats'])})" if f["minimality_caveats"] else ""),
            f"- Stability: {f['stability']}",
            f"- Reduced from: `{f['reduced_from']}`",
            f"- Evidence: {', '.join('`' + e + '`' for e in f['evidence'])}",
            "",
        ]
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
            out.append(
                f"- `{c['combination']}`: conflict while merging `{c['conflict_while_merging']}` "
                f"in {', '.join('`' + x + '`' for x in c['files'])}"
            )
    else:
        out.append("None.")
    out += [
        "",
        "## All combinations",
        "",
        "| Combination | Status | Runs | Fingerprints | Tree |",
        "|---|---|---|---|---|",
    ]
    for c in report["combinations"]:
        out.append(
            f"| `{c['id']}` | {c['status']}{' (incomplete)' if c['incomplete'] else ''} | "
            f"{len(c['runs'])} | {', '.join(c['fingerprints']) or '-'} | "
            f"`{(c['tree'] or '-')[:12]}` |"
        )
    b = report["budget"]
    out += [
        "",
        "## Budget",
        "",
        f"Used {b['used_runs']} / {b['max_runs']} test runs; max size {b['max_size']}; "
        f"exhausted: {b['exhausted']}{' (' + b['reason'] + ')' if b['reason'] else ''}.",
        "",
    ]
    if b["unexplored"]:
        out.append(
            f"Unexplored combinations ({len(b['unexplored'])}): " + ", ".join(f"`{u}`" for u in b["unexplored"][:50])
        )
    if report["pruned"]:
        out += [
            "",
            f"Pruned combinations ({len(report['pruned'])}): supersets of failing, flaky or "
            "conflicting sets are not run.",
        ]
    out += ["", "## Canonical order", "", report["canonical_order"]["description"], ""]
    if report.get("explanation"):
        out += [explanation_markdown(report["explanation"])]
    return "\n".join(out) + "\n"


def explanation_markdown(exp: dict) -> str:
    out = [
        "## Explanation (generated, evidence-cited)",
        "",
        f"_Model: {exp.get('model')}. Claims marked HYPOTHESIS are not established by the recorded evidence._",
        "",
        exp.get("summary", ""),
        "",
    ]
    for c in exp.get("claims", []):
        tag = "OBSERVATION" if c["label"] == "observation" else "HYPOTHESIS"
        cites = ", ".join(f"`{e}`" for e in c["evidence"]) or "no valid citation"
        out.append(f"- **[{tag}]** {c['text']} — {cites}")
    for w in exp.get("warnings", []):
        out.append(f"- _note: {w}_")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- html
def to_html(report: dict) -> str:
    from .html_report import render

    return render(report)


def write(report: dict, out_dir: Path, formats=("json", "md", "html")) -> list[Path]:
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
