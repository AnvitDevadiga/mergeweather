import json

from conftest import git
from mergeweather import report

CMD = "python3 integration_test.py"
THREE = [("fraud", "feature/fraud-check"), ("tax", "feature/tax-service"), ("loyalty", "feature/loyalty")]


def test_three_way_interaction(fixtures, make_engine, tmp_path):
    repo, _ = fixtures
    eng = make_engine(repo, THREE, CMD)
    eng.run()
    assert eng.combos[()].status == "pass"
    for k, rec in eng.combos.items():
        if 0 < len(k) < 3:
            assert rec.status == "pass", rec.id
    assert eng.combos[("fraud", "loyalty", "tax")].status == "fail"
    assert len(eng.findings) == 1
    f = eng.findings[0]
    assert f["branches"] == ["fraud", "loyalty", "tax"]
    assert f["minimality"] == "proven_1_minimal"
    assert f["kind"] == "3-way interaction"
    rep = report.build(eng, [])
    assert rep["verdict"] == "interactions-found"
    paths = report.write(rep, tmp_path / "out")
    assert json.loads(paths[0].read_text())["findings"][0]["reproduction"].count("git merge") == 3
    assert "<svg" in paths[2].read_text()
    # workspace cleaned up
    assert list((tmp_path / "work").iterdir()) == []


def test_harmless_combination(fixtures, make_engine):
    _, repo = fixtures
    eng = make_engine(repo, ["feature/cache-warm", "feature/docs", "feature/log-wording"], CMD)
    eng.run()
    assert eng.findings == []
    assert all(r.status == "pass" for r in eng.combos.values())
    assert report.build(eng, [])["verdict"] == "no-failures-found"


def test_user_repo_untouched(fixtures, make_engine):
    repo, _ = fixtures
    git(repo, "checkout", "-q", "feature/tax-service")
    (repo / "scratch.txt").write_text("uncommitted")
    before = (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"),
              git(repo, "for-each-ref"), git(repo, "stash", "list"))
    make_engine(repo, THREE, CMD).run()
    after = (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"),
             git(repo, "for-each-ref"), git(repo, "stash", "list"))
    assert before == after


def test_deterministic_trees(fixtures, make_engine):
    repo, _ = fixtures
    e1 = make_engine(repo, THREE, CMD)
    e1.run()
    e2 = make_engine(repo, list(reversed(THREE)), CMD)
    e2.run()
    for key, rec in e1.combos.items():
        assert e2.combos[key].tree == rec.tree
        assert e2.combos[key].merge_commit == rec.merge_commit


def test_full_first_reduction(tmp_path, make_engine):
    """Four branches, failure needs exactly a+b+c; full set must reduce to the triple."""
    from conftest import make_repo
    test = ("import glob,sys\nn=len(glob.glob('flags/*'))\nfl=set(p[6:] for p in glob.glob('flags/*'))\n"
            "bad={'a','b','c'}<=fl\nprint('FAIL: AssertionError combo' if bad else 'ok')\nsys.exit(1 if bad else 0)\n")
    repo = make_repo(tmp_path / "r", {"t.py": test, "flags/.keep": ""},
                     {x: {f"flags/{x}": x} for x in "abcd"})
    eng = make_engine(repo, list("abcd"), "python3 t.py", full_first=True, max_size=1)
    eng.run()
    full = [f for f in eng.findings if f["reduced_from"] == "a+b+c+d"]
    assert full and full[0]["branches"] == ["a", "b", "c"]
    assert full[0]["minimality"] == "proven_1_minimal"
