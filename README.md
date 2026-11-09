# MergeWeather

**Find behavioral integration failures between Git branches that each pass on their own.**

Branch A is green. Branch B is green. Branch C is green. Merging all three breaks
production. Textual merge tools can't see this kind of failure, because the code merges
cleanly and the bug only shows up when the branches run together. MergeWeather builds
the combinations deterministically, runs your integration test against each one in an
isolated container, and reduces every failure to a small set of branches that still
reproduces it. Each finding comes with evidence and the commands to reproduce it.

```
$ make demo
=== latency-budget ===
verdict: interactions-found
  F1 3-way interaction: fraud + loyalty + tax [proven_1_minimal, stable]
=== harmless ===
verdict: no-failures-found
```

## Install

```sh
pip install -e .            # Python ≥ 3.9, no runtime dependencies
pip install -e '.[dev]'     # + pytest
```

You need `git`. Docker is the default sandbox.

## Usage

```sh
mergeweather run \
  --repo path/to/repo \
  --base 3f2a9c1 \                       # explicit common base
  -b fraud=feature/fraud-check \         # [LABEL=]REF, repeatable
  -b tax=feature/tax-service \
  -b loyalty=feature/loyalty \
  --test-cmd "python -m pytest tests/integration" \
  --max-runs 60 --max-size 4 --repeats 3 \
  --image python:3.12-slim --timeout 120 --memory 1024 \
  --out report/
```

| Exit code | Meaning |
|---|---|
| 0 | no failing combinations found (explored space fully covered) |
| 1 | interactions found |
| 2 | usage error, invalid ref, base not an ancestor, sandbox unavailable |
| 3 | the base itself fails, so failures are not attributed to branches |
| 4 | inconclusive: the budget ran out before the space was covered |
| 130 | interrupted (workspaces and child processes are cleaned up) |

Other commands:

- `mergeweather render report/report.json`: regenerate the Markdown and HTML reports from the JSON.
- `mergeweather explain report/report.json [--dry-run]`: optional LLM explanation (see below).
- `mergeweather clean`: remove workspaces left behind by a run killed with `SIGKILL`.

## How it works

1. **Pinning.** The base and every branch are resolved to full commit IDs up front, and
   only those IDs are used afterwards. Every branch must descend from the base.
2. **Disposable copies.** Commits are fetched into a fresh repository under a temp
   directory. Your repo is only read: refs, index, working tree and stash are never
   touched. Each combination's tree is exported with `git archive` into a plain
   directory with no `.git` and no credentials, and that directory is what gets tested.
3. **Canonical order.** A combination is a set of labels. MergeWeather builds it by
   checking out the base and running `git merge --no-ff` on each member, in ascending
   lexicographic label order, with a fixed committer identity and a fixed timestamp.
   The same set always produces the same merge commits and tree IDs, and the report
   records both. Combinations with identical trees share their test evidence.
4. **Exploration.** The order is: base (repeated, and it must pass stably), then each
   branch alone, then every pair, then sizes 3 through `--max-size`, all within the
   budget. A superset of a set that already failed, was flaky, or conflicted is pruned,
   because it cannot reveal a new minimal interaction. `--full-first` tests the full set
   right after the base.
5. **Textual conflicts** are recorded separately (files, plus the branch whose merge
   conflicted). They are never counted as behavioral failures.
6. **Fingerprints.** A failure's identity is its outcome class plus a normalized
   signature taken from the test output. Numbers, addresses and temp paths are
   normalized away. You can override which output lines count with
   `--fingerprint-regex`. Timeouts get their own fingerprint.
7. **Repetition.** Every non-passing result is rerun `--repeats` times. Mixed outcomes
   are classified as `flaky`, and findings built on them are labeled `unstable`.
8. **Reduction.** Each failing combination is reduced by removing one member at a time,
   as long as the same fingerprint still reproduces.

### What "minimal" means here

- `proven_1_minimal`: the set fails stably, and removing any single member was tested
  (with repeats) and definitively did not reproduce the fingerprint.
- `smallest_found`: the proof is incomplete. The report lists why: budget, conflicts,
  flakiness or infrastructure errors.

Neither label claims **global** minimality. A different, smaller or disjoint set could
produce the same failure.

## Isolation

The `docker` backend (the default) runs each test with `--network none`, memory and swap
caps, a CPU cap, `--pids-limit`, `--cap-drop ALL`, `no-new-privileges`, a non-root
user, a tmpfs `/tmp`, and a wall-clock timeout. No host environment variables are passed
unless you name them with `--pass-env`.

The `local` backend is meant for trusted code only, and you have to opt in with
`--allow-unsandboxed`. It enforces the timeout, scrubs the environment, gives the test a
throwaway `HOME` and applies rlimits where the OS supports them. It **cannot** block
network access. Every report states which guarantees actually held.

## Reports

`report.json` (schema `mergeweather.report/v1`), `report.md` and a self-contained
`report.html` contain:

- pinned inputs and branch diffs
- every combination with its merge commit, tree, runs, output tails and fingerprints
- findings with removal checks, minimality caveats and copy-paste reproduction commands
- conflicts, pruned and unexplored combinations, and budget usage
- an interaction graph: SVG in the HTML report, Mermaid in the Markdown report

## Optional explanation step

```sh
export ANTHROPIC_API_KEY=...
mergeweather explain report/report.json            # adds an "explanation" section
mergeweather explain report/report.json --dry-run  # print the exact prompt only
```

The model only sees evidence that is already in the report: branch diffs, combination
outcomes and failure signatures. Every claim has to cite evidence IDs such as
`diff:tax` or `combo:fraud+loyalty+tax`. Citations to IDs that don't exist are dropped.
Any claim without a valid citation, or one the model marked as inference, is shown as
**HYPOTHESIS**. This step never changes the findings.

## Fixtures and demo

`examples/make_fixtures.py` builds two repositories:

- **latency-budget**: the integration test asserts that the summed checkout-stage
  latency is ≤ 250 ms. The base is 100 ms, and each of three branches adds a 60 ms
  stage in its own file. Base, singles and pairs pass (160 and 220 ms); the triple
  fails (280 ms).
- **harmless**: three branches (a 20 ms stage, docs, a log wording change) whose
  combinations all pass.

`make demo` builds both and analyzes them. It uses Docker if it is running and
otherwise falls back to the local backend. Open `demo-output/latency-budget/report.html`
to see the result.

## Tests

```sh
make test
```

The suite covers both fixtures, deterministic trees, reduction from the full set,
invalid and option-like refs, merge conflicts, flaky outcomes, budget exhaustion
(during exploration and during reduction), timeouts, credential scrubbing, the Docker
isolation flags, explanation citation checks, and cleanup after SIGINT/SIGTERM.

## License

MIT
