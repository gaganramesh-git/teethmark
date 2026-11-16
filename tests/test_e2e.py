"""End-to-end: record a ledger on the example shop, then try to cheat."""
from __future__ import annotations

import json
import os
import shutil
import sys

import pytest

from teethmark.cli import main
from teethmark.engine import LEDGER, Engine, load_config, read_ledger

SHOP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "shop")
TESTS = "tests/test_cart.py"
CART = "shop/cart.py"


def engine(root) -> Engine:
    return Engine(str(root), load_config(str(root), {"python": sys.executable, "per_function": 8}))


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    root = tmp_path_factory.mktemp("recorded") / "shop"
    shutil.copytree(SHOP, root, ignore=shutil.ignore_patterns(".teethmark", "__pycache__"))
    res = engine(root).record()
    assert res["mutants"] >= 15 and res["killed"] >= res["mutants"] - 2
    return root


@pytest.fixture
def proj(recorded, tmp_path):
    root = tmp_path / "shop"
    shutil.copytree(recorded, root)
    return root


def edit(root, rel, old, new):
    path = os.path.join(str(root), rel)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert old in text, old
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, new))


def snapshot(root):
    with open(os.path.join(str(root), CART), "rb") as fh:
        return fh.read()


def test_no_change_passes_without_running_anything(proj):
    rep = engine(proj).check()
    assert rep["verdict"] == "PASS" and rep["verified"] == 0 and rep["seal"] == "ok"


def test_loosened_assertion_is_blocked_with_proof(proj):
    before = snapshot(proj)
    edit(proj, TESTS, "assert line_total(1.0, 10) == 9.0", "assert line_total(1.0, 10) > 0")
    edit(proj, TESTS, "assert line_total(2.0, 10) == 18.0", "assert line_total(2.0, 10) > 0")
    rep = engine(proj).check()
    assert rep["verdict"] == "BLOCK"
    assert rep["lost"], rep
    proof = rep["lost"][0]
    assert proof["unit"] == "shop/cart.py::line_total"
    assert proof["was_caught_by"] == "tests/test_cart.py::test_bulk_discount_starts_at_ten"
    assert "still exists" in proof["now"]
    assert proof["before"] != proof["after"]
    assert snapshot(proj) == before, "the real source tree must never be modified"


def test_refactored_tests_pass(proj):
    # rename a test and split another one: same strength, different shape
    edit(proj, TESTS, "def test_shipping_rules():", "def test_shipping_is_priced_correctly():")
    edit(proj, TESTS, "    assert line_total(1.0, 10) == 9.0\n",
         "\n\ndef test_bulk_discount_applies():\n    assert line_total(1.0, 10) == 9.0\n")
    rep = engine(proj).check()
    assert rep["verdict"] == "PASS", rep
    assert rep["verified"] > 0 and rep["retained"] == rep["verified"]
    assert rep["rehomed"]
    assert any(n["kind"] == "removed" for n in rep["test_notes"])


def test_skipped_test_is_caught(proj):
    edit(proj, TESTS, "def test_shipping_rules():", "import pytest\n\n\n@pytest.mark.skip\ndef test_shipping_rules():")
    rep = engine(proj).check()
    assert rep["verdict"] == "BLOCK"
    assert all(item["unit"] == "shop/cart.py::shipping" for item in rep["lost"])
    assert any(n["kind"] == "skip-added" for n in rep["test_notes"])


def test_deleted_test_file_is_caught(proj):
    os.remove(os.path.join(str(proj), TESTS))
    with open(os.path.join(str(proj), "tests", "test_other.py"), "w") as fh:
        fh.write("def test_nothing():\n    assert True\n")
    rep = engine(proj).check()
    assert rep["verdict"] == "BLOCK"
    assert "gone" in rep["lost"][0]["now"]


def test_editing_the_function_does_not_hide_a_weakened_test(proj):
    edit(proj, CART, "    total = price * qty\n", "    total = price * qty\n    unused = None\n")
    edit(proj, TESTS, "assert line_total(1.0, 10) == 9.0", "assert line_total(1.0, 10) > 0")
    edit(proj, TESTS, "assert line_total(2.0, 10) == 18.0", "assert line_total(2.0, 10) > 0")
    rep = engine(proj).check()
    assert rep["verdict"] == "BLOCK"
    assert any(item["function_edited"] for item in rep["lost"])


def test_untested_new_code_needs_review(proj):
    with open(os.path.join(str(proj), CART), "a") as fh:
        fh.write("\n\ndef refund(total, days):\n    if days > 30 or total <= 0:\n        return 0.0\n"
                 "    fee = 2 if total < 20 else 1\n    return total - fee\n")
    rep = engine(proj).check()
    assert rep["verdict"] == "REVIEW"
    assert rep["new_code"]["mutants"] >= 4 and rep["new_code"]["killed"] == 0
    assert rep["new_code"]["survivors"]


def test_hand_edited_ledger_is_blocked(proj):
    path = os.path.join(str(proj), LEDGER)
    with open(path) as fh:
        body = json.load(fh)
    unit = body["units"]["shop/cart.py::line_total"]
    unit["mutants"] = [m for m in unit["mutants"] if m["status"] != "killed"]
    with open(path, "w") as fh:
        json.dump(body, fh)
    rep = engine(proj).check()
    assert rep["verdict"] == "BLOCK" and rep["seal"] == "bad"


def test_update_advances_the_ledger_only_on_pass(proj):
    with open(os.path.join(str(proj), CART), "a") as fh:
        fh.write("\n\ndef refund(total, days):\n    if days > 30:\n        return 0.0\n    return total - 1\n")
    with open(os.path.join(str(proj), "tests", "test_refund.py"), "w") as fh:
        fh.write("from shop.cart import refund\n\n\ndef test_refund():\n    assert refund(10, 30) == 9\n"
                 "    assert refund(10, 31) == 0.0\n")
    rep = engine(proj).check(update=True)
    assert rep["verdict"] == "PASS" and rep["updated"]
    ledger, seal = read_ledger(str(proj))
    assert seal == "ok" and "shop/cart.py::refund" in ledger["units"]
    assert engine(proj).check()["verified"] == 0
    # now weaken the new test: the freshly recorded bites are protected too
    edit(proj, "tests/test_refund.py", "assert refund(10, 31) == 0.0", "assert refund(10, 31) is not None")
    edit(proj, "tests/test_refund.py", "assert refund(10, 30) == 9", "assert refund(10, 30)")
    rep = engine(proj).check(update=True)
    assert rep["verdict"] == "BLOCK" and not rep["updated"]


def test_cli_exit_codes_and_formats(proj, capsys):
    args = ["--root", str(proj), "--quiet", "--python", sys.executable]
    assert main(["check"] + args) == 0
    assert main(["show", "--survivors"] + args) == 0
    edit(proj, TESTS, "assert shipping(50) == 0.0", "assert shipping(50) >= 0")
    capsys.readouterr()
    assert main(["check", "--format", "markdown"] + args) == 1
    out = capsys.readouterr().out
    assert "BLOCK" in out and "```diff" in out and "test_shipping_rules" in out
    assert main(["check", "--format", "json"] + args) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "BLOCK"
    assert main(["check", "--root", str(proj / "nope")]) == 2


def test_unittest_runner(tmp_path):
    root = tmp_path / "u"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "calc.py").write_text("def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n"
                                           "    if x > hi:\n        return hi\n    return x\n")
    (root / "test_calc.py").write_text(
        "import unittest\nfrom pkg.calc import clamp\n\n\nclass T(unittest.TestCase):\n"
        "    def test_clamp(self):\n        self.assertEqual(clamp(5, 0, 3), 3)\n"
        "        self.assertEqual(clamp(-1, 0, 3), 0)\n        self.assertEqual(clamp(2, 0, 3), 2)\n"
        "        self.assertEqual(clamp(0, 0, 3), 0)\n        self.assertEqual(clamp(3, 0, 3), 3)\n")
    cfg = load_config(str(root), {"python": sys.executable, "runner": "unittest", "per_function": 8})
    res = Engine(str(root), cfg).record()
    assert res["killed"] >= 3
    ledger, _ = read_ledger(str(root))
    killers = {m["killer"] for m in ledger["units"]["pkg/calc.py::clamp"]["mutants"] if m["status"] == "killed"}
    assert killers == {"test_calc.T.test_clamp"}
    edit(root, "test_calc.py", "self.assertEqual(clamp(5, 0, 3), 3)", "clamp(5, 0, 3)")
    edit(root, "test_calc.py", "self.assertEqual(clamp(-1, 0, 3), 0)", "clamp(-1, 0, 3)")
    rep = Engine(str(root), cfg).check()
    assert rep["verdict"] == "BLOCK" and rep["lost"][0]["was_caught_by"] == "test_calc.T.test_clamp"


def test_baseline_ref_ignores_a_rewritten_working_tree_ledger(proj):
    import subprocess
    if not shutil.which("git"):
        pytest.skip("git not installed")

    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                        "-c", "commit.gpgsign=false"] + list(args), cwd=str(proj), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "--no-verify", "-m", "trusted baseline")
    edit(proj, TESTS, "assert shipping(50) == 0.0", "assert shipping(50) >= 0")
    engine(proj).record()  # the cheat: re-record so the weaker suite becomes the baseline
    assert engine(proj).check()["verdict"] == "PASS"
    rep = engine(proj).check(baseline_ref="HEAD")
    assert rep["verdict"] == "BLOCK" and rep["baseline"] == "HEAD"


def test_keyed_seal(proj, monkeypatch):
    monkeypatch.setenv("TEETHMARK_KEY", "ci-secret")
    assert engine(proj).record()["reused"] > 0  # nothing changed: no test runs needed
    assert read_ledger(str(proj))[1] == "ok"
    monkeypatch.setenv("TEETHMARK_KEY", "forged")
    assert read_ledger(str(proj))[1] == "bad"
    monkeypatch.delenv("TEETHMARK_KEY")
    assert read_ledger(str(proj))[1] == "unverified"
    # a plain-hash seal must not be accepted once a key is required
    engine(proj).record()
    monkeypatch.setenv("TEETHMARK_KEY", "ci-secret")
    assert engine(proj).check()["verdict"] == "BLOCK"


def test_hollowed_out_test_needs_review_even_when_other_tests_cover_it(proj):
    # test_line_total_plain is redundant with the bulk test for most bugs; hollow it out
    edit(proj, TESTS, "    assert line_total(2.5, 4) == 10.0", "    assert True")
    rep = engine(proj).check(skip_new=True)
    assert rep["verdict"] in ("REVIEW", "BLOCK")
    assert any(n["kind"] == "always-true" for n in rep["test_notes"])


def test_tests_that_write_files_do_not_leak_state_between_planted_bugs(tmp_path):
    root = tmp_path / "s"
    (root / "tests").mkdir(parents=True)
    (root / "state.txt").write_text("0")
    (root / "calc.py").write_text("def double(x):\n    return x * 2\n\n\ndef untested(x):\n    return x + 1\n")
    # passes only on a pristine tree: a second run in a dirty copy would fail for the wrong reason
    (root / "tests" / "test_calc.py").write_text(
        "import os\nfrom calc import double\n\nHERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n\n\n"
        "def test_double():\n    path = os.path.join(HERE, 'state.txt')\n    assert open(path).read() == '0'\n"
        "    open(path, 'w').write('1')\n    open(os.path.join(HERE, 'extra.tmp'), 'x').write('junk')\n"
        "    assert double(3) == 6\n")
    cfg = load_config(str(root), {"python": sys.executable, "per_function": 4, "workers": 1})
    res = Engine(str(root), cfg).record()
    ledger, _ = read_ledger(str(root))
    statuses = {m["status"] for m in ledger["units"]["calc.py::untested"]["mutants"]}
    assert statuses == {"survived"}, "a dirty working copy would make every bug look caught"
    assert res["killed"] >= 1
    assert (root / "state.txt").read_text() == "0" and not (root / "extra.tmp").exists()
