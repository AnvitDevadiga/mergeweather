"""Deterministic execution and reduction engine.

Canonical combination order
---------------------------
Branches are identified by a label (``label=ref`` on the CLI, or the ref itself).
A combination is a *set* of labels; it is always built by checking out the pinned
base commit and merging the member branches' pinned commits one at a time with
``git merge --no-ff`` in ascending lexicographic order of their labels, using a
fixed author/committer identity and timestamp. The same set therefore always
yields the same merge commits and the same resulting tree, regardless of the
order branches were given on the command line.

Exploration order
-----------------
1. base (repeated, must pass stably)
2. optional: the full set (``--full-first``)
3. each branch alone, then every pair, then sizes 3..max_size, each size in
   lexicographic order. A combination is pruned (not run) if any proper subset
   already failed, was flaky, or textually conflicted; such supersets cannot
   reveal a *new* minimal interaction.
4. every failing combination is reduced by one-at-a-time removal while the
   failure fingerprint is preserved.

Minimality
----------
A reduced set is reported as ``proven_1_minimal`` only if removing any single
member was actually tested and definitively did not reproduce the fingerprint
(stable pass, or a different failure), and the set itself failed stably.
Otherwise it is ``smallest_found``. Neither claim implies global minimality:
a smaller, disjoint set with the same fingerprint may exist.
"""
from __future__ import annotations

import itertools
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import gitutil
from .fingerprint import fingerprint as make_fingerprint
from .runner import Runner
from .workspace import Workspace

Combo = Tuple[str, ...]

DEFINITIVE_NO_REPRO = "definitive"
INCONCLUSIVE = "inconclusive"


@dataclass
class Branch:
    label: str
    ref: str
    sha: str = ""
    changed_files: List[str] = field(default_factory=list)
    diff: str = ""


@dataclass
class Budget:
    max_runs: int = 60
    max_seconds: Optional[float] = None
    max_size: int = 4
    used_runs: int = 0
    started: float = field(default_factory=time.monotonic)
    exhausted: bool = False
    reason: Optional[str] = None

    def try_charge(self) -> bool:
        if self.exhausted:
            return False
        if self.used_runs >= self.max_runs:
            self.exhausted, self.reason = True, f"max_runs={self.max_runs} reached"
            return False
        if self.max_seconds is not None and time.monotonic() - self.started > self.max_seconds:
            self.exhausted, self.reason = True, f"max_seconds={self.max_seconds} reached"
            return False
        self.used_runs += 1
        return True


@dataclass
class Run:
    id: str
    outcome: str  # pass | fail | timeout | error
    exit_code: Optional[int]
    duration: float
    fingerprint: str
    signature: List[str]
    stdout_tail: str
    stderr_tail: str


@dataclass
class ComboRecord:
    id: str
    branches: Combo
    status: str = "pending"  # pass|fail|flaky|conflict|error|not_run
    merge_commit: Optional[str] = None
    tree: Optional[str] = None
    merge_steps: List[Dict[str, str]] = field(default_factory=list)
    conflict_files: List[str] = field(default_factory=list)
    conflict_at: Optional[str] = None
    runs: List[Run] = field(default_factory=list)
    fingerprints: List[str] = field(default_factory=list)
    reused_runs_from: Optional[str] = None
    incomplete: bool = False

    @property
    def primary_fingerprint(self) -> Optional[str]:
        fails = [r.fingerprint for r in self.runs if r.outcome != "pass"]
        if not fails:
            return None
        return Counter(fails).most_common(1)[0][0]


class ConfigError(RuntimeError):
    pass


def combo_id(c: Combo) -> str:
    return "+".join(c) if c else "base"


class Engine:
    def __init__(self, repo: Path, base_ref: str, branches: Sequence[Tuple[str, str]],
                 test_command: str, runner: Runner, budget: Budget, repeats: int = 3,
                 fingerprint_regex: Optional[str] = None, workroot: Optional[Path] = None,
                 full_first: bool = False, log=None):
        if not branches:
            raise ConfigError("at least one branch is required")
        labels = [b[0] for b in branches]
        if len(set(labels)) != len(labels):
            raise ConfigError("branch labels must be unique")
        if any("+" in l or not l for l in labels):
            raise ConfigError("branch labels must be non-empty and must not contain '+'")
        if repeats < 1:
            raise ConfigError("repeats must be >= 1")
        self.repo = gitutil.ensure_repo(Path(repo))
        self.base = Branch("base", base_ref)
        self.branches = {l: Branch(l, r) for l, r in branches}
        self.order: List[str] = sorted(labels)  # canonical order
        self.command = test_command
        self.runner = runner
        self.budget = budget
        self.repeats = repeats
        self.fp_regex = fingerprint_regex
        self.workroot = workroot
        self.full_first = full_first
        self.log = log or (lambda msg: None)
        self.combos: Dict[Combo, ComboRecord] = {}
        self.tree_runs: Dict[str, ComboRecord] = {}
        self.pruned: List[Dict[str, object]] = []
        self.findings: List[Dict[str, object]] = []
        self.base_ok = False
        self.ws: Optional[Workspace] = None

    # ------------------------------------------------------------------ setup
    def resolve(self) -> None:
        """Pin every reference to a commit ID (read-only on the user repo)."""
        self.base.sha = gitutil.resolve_commit(self.repo, self.base.ref)
        for b in self.branches.values():
            b.sha = gitutil.resolve_commit(self.repo, b.ref)
            if not gitutil.is_ancestor(self.repo, self.base.sha, b.sha):
                raise ConfigError(
                    f"base {self.base.ref} ({self.base.sha[:12]}) is not an ancestor of "
                    f"branch {b.label} ({b.ref}); pass the true common base with --base")
            b.changed_files = gitutil.changed_files(self.repo, self.base.sha, b.sha)
            b.diff = gitutil.diff_text(self.repo, self.base.sha, b.sha)

    def canonical(self, labels) -> Combo:
        s = set(labels)
        return tuple(l for l in self.order if l in s)

    # ------------------------------------------------------------- execution
    def _build(self, rec: ComboRecord) -> None:
        repo = self.ws.repo
        gitutil.git(["checkout", "-q", "-f", "--detach", self.base.sha], cwd=repo)
        gitutil.git(["clean", "-qfdx"], cwd=repo)
        for label in rec.branches:
            sha = self.branches[label].sha
            proc = gitutil.git(["merge", "--no-ff", "--no-edit", "-q", "-m",
                                f"mergeweather: merge {label}", sha], cwd=repo, check=False)
            if proc.returncode != 0:
                files = gitutil.git(["diff", "--name-only", "--diff-filter=U"], cwd=repo,
                                    check=False).stdout.split()
                gitutil.git(["merge", "--abort"], cwd=repo, check=False)
                if not files:
                    raise gitutil.GitError(f"merge of {label} failed: {proc.stderr.strip()}")
                rec.status, rec.conflict_files, rec.conflict_at = "conflict", sorted(files), label
                return
            head = gitutil.git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
            rec.merge_steps.append({"branch": label, "commit": sha, "result": head})
        rec.merge_commit = gitutil.git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
        rec.tree = gitutil.git(["rev-parse", "HEAD^{tree}"], cwd=repo).stdout.strip()

    def _run_once(self, rec: ComboRecord) -> None:
        workdir = self.ws.export_tree(rec.tree)
        raw = self.runner.run(workdir, self.command)
        if raw.infra_error:
            outcome = "error"
        elif raw.timed_out:
            outcome = "timeout"
        else:
            outcome = "pass" if raw.exit_code == 0 else "fail"
        fp, sig = make_fingerprint(outcome, raw.exit_code, raw.stdout, raw.stderr, self.fp_regex)
        rec.runs.append(Run(f"{rec.id}#{len(rec.runs) + 1}", outcome, raw.exit_code, raw.duration,
                            fp, sig, raw.stdout, raw.stderr + (raw.infra_error or "")))
        self.log(f"  run {rec.id}#{len(rec.runs)}: {outcome} {'' if fp == 'pass' else fp}")

    def _classify(self, rec: ComboRecord) -> None:
        if not rec.runs:
            rec.status = "not_run"
            return
        outcomes = {r.outcome for r in rec.runs}
        rec.fingerprints = sorted({r.fingerprint for r in rec.runs})
        if "error" in outcomes:
            rec.status = "error"
        elif outcomes == {"pass"}:
            rec.status = "pass"
        elif len(rec.fingerprints) == 1:
            rec.status = "fail"
        else:
            rec.status = "flaky"

    def evaluate(self, labels, confirm: bool = False) -> ComboRecord:
        """Build and test a combination. Never raises on budget exhaustion.

        Failing results are always repeated ``repeats`` times; passing results are
        repeated too when ``confirm`` is set (used for base and reduction proofs).
        """
        key = self.canonical(labels)
        rec = self.combos.get(key)
        if rec is None:
            rec = ComboRecord(combo_id(key), key)
            self.combos[key] = rec
            self._build(rec)
            if rec.status == "conflict":
                self.log(f"  {rec.id}: textual merge conflict in {', '.join(rec.conflict_files)}")
                return rec
            twin = self.tree_runs.get(rec.tree)
            if twin is not None and twin is not rec:
                rec.reused_runs_from = twin.id
                rec.runs = twin.runs  # identical tree -> identical evidence (shared list)
            else:
                self.tree_runs[rec.tree] = rec
        if rec.status == "conflict":
            return rec
        while True:
            have_nonpass = any(r.outcome != "pass" for r in rec.runs)
            target = self.repeats if (have_nonpass or confirm) else 1
            if len(rec.runs) >= target:
                break
            if not self.budget.try_charge():
                rec.incomplete = True
                break
            self._run_once(rec)
            if rec.runs[-1].outcome == "error":
                break
        if len(rec.runs) < (self.repeats if (confirm or any(r.outcome != "pass" for r in rec.runs)) else 1):
            rec.incomplete = True
        else:
            rec.incomplete = False
        self._classify(rec)
        return rec

    # ------------------------------------------------------------ reduction
    def _reproduces(self, rec: ComboRecord, target: str) -> bool:
        return rec.status in ("fail", "flaky") and any(r.fingerprint == target for r in rec.runs)

    def _removal_verdict(self, rec: ComboRecord, target: str) -> str:
        if rec.status == "pass" and not rec.incomplete:
            return DEFINITIVE_NO_REPRO
        if rec.status == "fail" and not rec.incomplete and target not in rec.fingerprints:
            return DEFINITIVE_NO_REPRO
        return INCONCLUSIVE

    def reduce(self, start: ComboRecord) -> Dict[str, object]:
        target = start.primary_fingerprint
        current = start.branches
        steps = []
        changed = True
        while changed and len(current) > 1:
            changed = False
            for label in current:
                sub = tuple(l for l in current if l != label)
                rec = self.evaluate(sub, confirm=True)
                steps.append({"removed": label, "tested": rec.id, "status": rec.status})
                if self._reproduces(rec, target):
                    current, changed = sub, True
                    break
        final = self.evaluate(current)
        # verify every single-removal of the final set
        checks, reasons = [], []
        for label in current:
            sub = tuple(l for l in current if l != label)
            rec = self.evaluate(sub, confirm=True)
            verdict = self._removal_verdict(rec, target)
            checks.append({"removed": label, "combination": rec.id, "status": rec.status,
                           "incomplete": rec.incomplete, "verdict": verdict})
            if verdict != DEFINITIVE_NO_REPRO:
                reasons.append(f"removing {label} -> {rec.id} is {rec.status}"
                               f"{' (budget-limited)' if rec.incomplete else ''}")
        stable = final.status == "fail" and not final.incomplete
        if not stable:
            reasons.append(f"{final.id} itself is {final.status}"
                           f"{' (budget-limited)' if final.incomplete else ''}")
        minimality = "proven_1_minimal" if not reasons else "smallest_found"
        k = len(current)
        kind = ("single-branch failure" if k == 1 else
                "pairwise interaction" if k == 2 else f"{k}-way interaction")
        return {
            "branches": list(current), "combination": final.id, "fingerprint": target,
            "kind": kind, "minimality": minimality, "minimality_caveats": reasons,
            "stability": "stable" if final.status == "fail" else "unstable",
            "reduced_from": start.id, "reduction_steps": steps, "removal_checks": checks,
            "signature": next((r.signature for r in final.runs if r.fingerprint == target), []),
        }

    # -------------------------------------------------------------- explore
    def _pruned_by(self, combo: Combo) -> Optional[str]:
        for k in range(1, len(combo)):
            for sub in itertools.combinations(combo, k):
                rec = self.combos.get(sub)
                if rec and rec.status in ("fail", "flaky", "conflict"):
                    return f"subset {rec.id} is {rec.status}"
        return None

    def explore(self) -> None:
        self.log(f"base {self.base.sha[:12]}")
        base = self.evaluate((), confirm=True)
        self.base_ok = base.status == "pass" and not base.incomplete
        if not self.base_ok:
            self.log(f"base is {base.status}; refusing to attribute failures to branches")
            return
        n = len(self.order)
        if self.full_first and n > 2:
            self.log("full set first")
            self.evaluate(tuple(self.order))
        for k in range(1, min(n, self.budget.max_size) + 1):
            self.log(f"size {k}")
            for combo in itertools.combinations(self.order, k):
                if combo in self.combos:
                    continue
                why = self._pruned_by(combo)
                if why:
                    self.pruned.append({"combination": combo_id(combo), "reason": why})
                    continue
                if self.budget.exhausted:
                    return
                self.evaluate(combo)

    def run(self) -> None:
        self.resolve()
        with Workspace(self.workroot) as ws:
            self.ws = ws
            ws.import_commits(self.repo, [self.base.sha] + [b.sha for b in self.branches.values()])
            self.explore()
            if self.base_ok:
                seen = set()
                failing = sorted((r for r in self.combos.values() if r.status in ("fail", "flaky")
                                  and r.branches), key=lambda r: (len(r.branches), r.branches))
                for rec in failing:
                    if any(set(f["branches"]) <= set(rec.branches) and
                           f["fingerprint"] == rec.primary_fingerprint for f in self.findings):
                        continue  # already explained by a smaller finding
                    self.log(f"reducing {rec.id}")
                    finding = self.reduce(rec)
                    key = (tuple(finding["branches"]), finding["fingerprint"])
                    if key not in seen:
                        seen.add(key)
                        finding["id"] = f"F{len(self.findings) + 1}"
                        self.findings.append(finding)
            self.ws = None

    def unexplored(self) -> List[str]:
        out = []
        n = len(self.order)
        pruned = {p["combination"] for p in self.pruned}
        for k in range(1, min(n, self.budget.max_size) + 1):
            for combo in itertools.combinations(self.order, k):
                rec = self.combos.get(combo)
                if combo_id(combo) in pruned:
                    continue
                if rec is None or rec.status == "not_run":
                    out.append(combo_id(combo))
        return out
