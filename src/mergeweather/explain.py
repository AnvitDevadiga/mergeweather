"""Optional LLM explanation that must cite recorded evidence.

The model receives only data already in the report (branch diffs, combination
outcomes, failure signatures) and must answer with JSON claims, each citing
evidence IDs. Claims are validated after the fact:

* citations to IDs not present in the evidence bundle are dropped;
* a claim with no valid citation, or one the model marked as a hypothesis,
  is labeled ``hypothesis``.

This step never changes findings; it only annotates the report.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Callable, Dict, List, Optional

DEFAULT_MODEL = "claude-sonnet-5-5"
API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = (
    "You explain why a set of Git branches fails an integration test only when combined. "
    "Use ONLY the evidence provided. Every claim must cite evidence IDs exactly as given "
    "(e.g. 'diff:feature-x', 'combo:a+b'). If a claim is inference beyond what the evidence "
    "directly shows, set kind to 'hypothesis'. Reply with a single JSON object: "
    '{"summary": str, "claims": [{"text": str, "kind": "observation"|"hypothesis", '
    '"evidence": [str]}]}. No prose outside the JSON.')


def evidence_bundle(report: Dict, max_diff: int = 3000) -> Dict[str, Dict]:
    ev: Dict[str, Dict] = {}
    for b in report["inputs"]["branches"]:
        ev[f"diff:{b['label']}"] = {"branch": b["label"], "changed_files": b["changed_files"],
                                    "diff": b["diff"][:max_diff]}
    for c in report["combinations"]:
        ev[f"combo:{c['id']}"] = {
            "branches": c["branches"], "status": c["status"], "tree": c["tree"],
            "conflict_files": c["conflict_files"],
            "runs": [{"id": r["id"], "outcome": r["outcome"], "exit_code": r["exit_code"],
                      "signature": r["signature"], "output_tail": (r["stdout_tail"] + r["stderr_tail"])[-800:]}
                     for r in c["runs"][:2]],
        }
    for f in report["findings"]:
        ev[f"finding:{f['id']}"] = {k: f[k] for k in ("branches", "kind", "fingerprint", "minimality",
                                                    "minimality_caveats", "stability", "signature")}
    return ev


def build_prompt(report: Dict) -> str:
    ev = evidence_bundle(report)
    return ("Test command: " + report["inputs"]["test_command"] + "\n\nEvidence (JSON, keyed by ID):\n"
            + json.dumps(ev, indent=1) + "\n\nExplain the findings "
            + ", ".join(f["id"] for f in report["findings"]) + ".")


def anthropic_transport(prompt: str, model: str, api_key: Optional[str] = None) -> str:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    body = json.dumps({"model": model, "max_tokens": 2000, "system": SYSTEM,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")


def _parse(text: str) -> Dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("model reply did not contain JSON")
    return json.loads(m.group(0))


def validate(raw: Dict, evidence_ids) -> Dict:
    warnings: List[str] = []
    claims = []
    for c in raw.get("claims", []):
        text = str(c.get("text", "")).strip()
        if not text:
            continue
        cited = [str(x) for x in c.get("evidence", []) if isinstance(x, (str, int))]
        valid = [x for x in cited if x in evidence_ids]
        bad = [x for x in cited if x not in evidence_ids]
        if bad:
            warnings.append(f"dropped unknown citations {bad} from claim: {text[:60]}")
        label = "observation" if c.get("kind") == "observation" and valid else "hypothesis"
        claims.append({"text": text, "label": label, "evidence": valid})
    return {"summary": str(raw.get("summary", "")), "claims": claims, "warnings": warnings}


def explain(report: Dict, model: str = DEFAULT_MODEL,
            transport: Optional[Callable[[str, str], str]] = None) -> Dict:
    if not report["findings"]:
        return {"model": None, "summary": "No findings to explain.", "claims": [], "warnings": []}
    prompt = build_prompt(report)
    reply = (transport or anthropic_transport)(prompt, model)
    result = validate(_parse(reply), set(evidence_bundle(report)))
    result["model"] = model
    return result
