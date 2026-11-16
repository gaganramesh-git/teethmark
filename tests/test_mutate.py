from __future__ import annotations

import ast

from teethmark.mutate import load
from teethmark.project import is_test_side, scan_tests

SRC = b'''\
def price(qty, unit):
    """Doc with 1 number and a < sign."""
    total = qty * unit
    if qty >= 10 and unit > 0:
        total -= 1
    log.info("total %s", total)
    notify(total)
    return total
'''


def _unit(data=SRC, path="m.py"):
    sf = load(path, data)
    assert sf is not None
    return sf, sf.units[0]


def test_every_mutant_parses_and_differs():
    sf, unit = _unit()
    mutants = sf.sample(unit, 100)
    ops = {m.op for m in mutants}
    assert {"compare", "arith", "logic", "const", "return-none", "negate-if", "drop-call", "aug"} <= ops
    original = ast.dump(ast.parse(SRC))
    for m in mutants:
        assert ast.dump(ast.parse(m.data)) != original
        assert m.before != m.after


def test_docstrings_logging_and_fstrings_are_left_alone():
    sf, unit = _unit(b'def f(a):\n    """1 < 2"""\n    print(a * 3)\n    return f"{a + 1}"\n')
    mutants = sf.sample(unit, 100)
    assert all('"""1 < 2"""' not in m.before for m in mutants)  # docstring untouched
    assert all(m.op != "drop-call" for m in mutants)            # print() is not worth planting
    assert all("return" not in m.before or m.op == "return-none" for m in mutants)  # f-string untouched
    assert any(m.op == "arith" for m in mutants)                # ...but real code still is


def test_ids_survive_reformatting_comments_and_moves():
    sf1, u1 = _unit()
    moved = b"import os\n\n\n# a comment\n" + SRC.replace(b"total = qty * unit", b"total = qty  *  unit  # hi")
    sf2, u2 = _unit(moved)
    assert u1.hash == u2.hash
    assert [m.id for m in sf1.sample(u1, 100)] == [m.id for m in sf2.sample(u2, 100)]
    assert sf2.sample(u2, 1)[0].lineno == sf1.sample(u1, 1)[0].lineno + 4


def test_ids_change_when_the_function_changes_but_signature_carries_over():
    sf1, u1 = _unit()
    edited = SRC.replace(b"    notify(total)\n", b"    notify(total)\n    unused = 0\n")
    sf2, u2 = _unit(edited)
    assert u1.hash != u2.hash
    m1 = next(m for m in sf1.sample(u1, 100) if m.op == "compare")
    assert sf2.find(u2, m1.id) is None
    carried = sf2.find_sig(u2, m1.sig, m1.occ)
    assert carried is not None and carried.after == m1.after


def test_byte_offsets_with_non_ascii_text():
    data = "def f(a):\n    s = 'héllo ✓'; return a + 1\n".encode("utf-8")
    sf, unit = _unit(data)
    afters = {m.after.strip() for m in sf.sample(unit, 100)}
    assert "s = 'héllo ✓'; return (a - 1)" in afters


def test_pragma_and_methods_and_duplicates():
    data = (b"class A:\n    def m(self, x):\n        return x + 1  # pragma: no mutate\n"
            b"    def n(self, x):\n        return x + 1\n"
            b"    def n(self, x):\n        return x + 2\n")
    sf = load("a.py", data)
    assert [u.qualname for u in sf.units] == ["A.m", "A.n", "A.n#2"]
    assert sf.units[0].sites == []
    assert sf.units[1].sites


def test_broken_source_is_skipped_not_fatal():
    assert load("bad.py", b"def f(:\n") is None
    assert load("bin.py", b"\xff\xfe\x00") is None


def test_test_shapes():
    data = (b"import pytest\n"
            b"def test_a():\n    assert f() == 1\n    assert True\n"
            b"@pytest.mark.skip\ndef test_b():\n    assert f()\n"
            b"class TestC:\n    def test_d(self):\n        with pytest.raises(ValueError):\n            f()\n"
            b"def helper():\n    assert 1\n")
    shapes = scan_tests("tests/test_x.py", data)
    assert shapes == {
        "tests/test_x.py::test_a": {"asserts": 2, "trivial": 1, "skip": 0},
        "tests/test_x.py::test_b": {"asserts": 1, "trivial": 0, "skip": 1},
        "tests/test_x.py::TestC::test_d": {"asserts": 1, "trivial": 0, "skip": 0},
    }
    assert is_test_side("tests/helpers.py") and is_test_side("pkg/test_x.py") and not is_test_side("pkg/x.py")


def test_pytest_killer_is_read_from_the_summary_not_from_captured_logs():
    from teethmark.runner import Runner
    out = ("------ Captured log call ------\n"
           "ERROR bioproof:app.py:73 unhandled: Traceback (most recent call last):\n"
           "=========== short test summary info ===========\n"
           "FAILED tests/test_api.py::test_x[a b] - AssertionError: nope\n")
    r = Runner("python3", "pytest")
    assert r._judge(1, out) == ("fail", "tests/test_api.py::test_x[a b]")
    assert r._judge(2, "ERROR tests/test_api.py\n") == ("fail", "tests/test_api.py")
    assert r._judge(1, "ERROR some log line\n") == ("fail", "<unknown>")
    assert r._judge(0, "") == ("pass", None) and r._judge(5, "")[0] == "notests"
