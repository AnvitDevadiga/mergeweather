# Contributing to MergeWeather

Thanks for stopping by! Bug reports, fixture ideas, docs fixes and features are all
welcome. This guide gets you from clone to merged PR.

## Quick start

```sh
git clone https://github.com/AnvitDevadiga/merge-weather
cd merge-weather
make install   # creates .venv with uv and installs mergeweather in editable mode + dev extras
make test      # runs the full pytest suite
make demo      # builds the 3-way-bug fixture, analyzes it, opens the HTML report
```

You need **Python ≥ 3.9**, **git**, and [uv](https://docs.astral.sh/uv/) for the `make`
targets. Without uv:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

Docker is optional for development. The tests use the local backend, so they run
anywhere. Install Docker if you're changing `DockerRunner` or want to try the real
sandbox.

## Make targets

| Target | What it does |
|---|---|
| `make install` | `uv venv` + editable install with `[dev]` extras |
| `make test` | `pytest -q` (about 30 s) |
| `make demo` | `mergeweather demo` against the bundled fixture |
| `make css` | Recompile the report's Tailwind CSS (needs Node; see below) |
| `make build` | Build the sdist and wheel into `dist/` |
| `make clean` | Remove `.venv`, build output and demo reports |

## Project layout

```
src/mergeweather/
  engine.py        deterministic exploration, repetition and reduction  ← the core
  gitutil.py       git wrappers, ref pinning, fixed merge identity
  workspace.py     disposable workspaces, signal handling, cleanup
  runner.py        Docker and local execution backends
  fingerprint.py   failure fingerprints
  report.py        report model, JSON + Markdown export
  html_report.py   self-contained HTML dashboard
  assets/          compiled report CSS and the dashboard JS
  console.py       rich terminal dashboard and weather summary
  explain.py       optional evidence-cited LLM explanation
  fixtures.py      sample repos used by `demo` and the tests
  cli.py           argparse CLI
tests/             pytest suite
tools/             Tailwind config and input CSS
```

## Ground rules for changes

These properties are what make MergeWeather trustworthy. Please keep them intact:

- **Never modify the user's repository.** All git writes happen in the disposable workspace.
- **Determinism.** The same inputs must give the same merge commits and tree IDs.
  `test_deterministic_trees` guards this.
- **Honest claims.** Only label a result `proven_1_minimal` when every single removal was
  actually tested and was definitive. Never claim global minimality.
- **Clean up on interrupt.** Any new child process or container must be tracked in
  `workspace.py` so SIGINT/SIGTERM cleans it up.
- **Stdlib-first.** The only runtime dependency is `rich`. Please open an issue before
  adding another.
- **The report stays self-contained.** No CDN or network requests in `report.html`.

## Working on the HTML report

Styling uses Tailwind utility classes in `html_report.py` and `assets/report.js`.
After adding or changing classes, run:

```sh
make css   # npx tailwindcss@3.4.17 … → src/mergeweather/assets/report.css
```

Commit the regenerated `report.css`, so users never need Node. To preview, run
`make demo` (or `mergeweather render path/to/report.json`) and open the HTML file.

## Tests

Every behavior change needs a test. Useful helpers live in `tests/conftest.py`:
`make_repo()` builds a throwaway git repo from dicts of files, and the `make_engine`
fixture runs the engine with the local backend. Existing suites:

- `test_fixtures.py`: the 3-way bug, the harmless fixture, determinism, reduction
- `test_edge_cases.py`: invalid refs, conflicts, flaky outcomes, budget exhaustion,
  timeouts, credential scrubbing, SIGINT/SIGTERM cleanup
- `test_cli_ux.py`: `demo`, the terminal dashboard and the weather summary
- `test_html_report.py`: self-containment, escaping, copy buttons, graph data
- `test_units.py`: fingerprints, Docker flags, explanation citation checks

Run one file or test with `pytest tests/test_edge_cases.py -k flaky -q`.

## Submitting a pull request

1. Fork the repo and create a branch: `git checkout -b fix/short-description`.
2. Make your change and add or update tests.
3. Run `make test` and make sure it passes. If you touched the report, check it in a browser.
4. Update `README.md` if you changed user-facing behavior or flags.
5. Open a PR describing **what** changed and **why**. Screenshots help for UI changes.

CI runs the suite on macOS (Python 3.9, 3.13) and Linux (Python 3.10, 3.13), plus a demo smoke test.
Keep PRs focused: several small PRs are easier to review than one large one.

## Reporting bugs

Please include `mergeweather --version`, your OS, Python and git versions, the command
you ran, and, if you can, the `report.json` (remove anything sensitive first: it
contains branch diffs and test output).

## Code of conduct

Be kind, assume good intent, and keep feedback about the code. Harassment of any kind
isn't tolerated.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
