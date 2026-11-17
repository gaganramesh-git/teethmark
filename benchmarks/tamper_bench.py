"""Does Teethmark notice when tests are weakened, and do the usual signals?

For each subject project we:
  1. record a small ledger (what a user gets by default) and a much larger "truth" ledger
     (25 planted bugs per function, close to exhaustive on small modules);
  2. apply "tampers" a rushed person or an agent might use to get green: loosen an assertion,
     delete assertions, skip a test, gut it, delete it, swallow its errors;
  3. keep only tampers where the suite is still green (the dangerous ones);
  4. call a tamper "truly weakening" if the truth ledger says some bug the original tests caught
     now slips through;
  5. score each detector: how many truly weakening tampers it flags (recall), and how often it
     flags a tamper that did not weaken anything (false alarm).

Detectors: tests still pass, test count dropped, assertion count dropped, executed-line count
dropped (stdlib `trace`), Teethmark with a one-bug-per-function ledger, Teethmark with the default
three-per-function ledger. The truth ledger is produced by Teethmark itself with a larger sample,
so "truth" means "what a ~10x larger sample says", not a mathematical proof.

    python3 benchmarks/tamper_bench.py [--tests 6] [--subject NAME ...] [--out benchmarks/results]
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from teethmark.engine import LEDGER, Engine, load_config  # noqa: E402
from teethmark.project import copy_tree, scan  # noqa: E402

TACTICS = ["loosen", "truthy", "no-asserts", "skip", "gut", "delete", "swallow"]
HOME = os.path.expanduser("~")

# name -> how to run it. Paths outside this repo are used read-only (copied first).
SUBJECTS: Dict[str, Dict[str, Any]] = {
    "shop (example)": dict(root=os.path.join(os.path.dirname(HERE), "examples", "shop"),
                           source=["shop"], test_args=[], python=sys.executable),
    "bioproof coldchain": dict(root=os.path.join(HOME, "bioproof"), source=["engine/coldchain.py"],
                               test_args=["tests/test_coldchain.py"],
                               python=os.path.join(HOME, "bioproof", ".venv", "bin", "python")),
    "railway checker+importer": dict(root=os.path.join(HOME, "railway-scheduler-tests"),
                                     source=["src/trackservice/checker.py", "src/trackservice/importer.py"],
                                     test_args=["tests/test_checker.py", "tests/test_importer.py"],
                                     python=os.path.join(HOME, "railway scheduler", ".venv", "bin", "python")),
}


# ------------------------------------------------------------------ tampering
def _lines(src: str) -> List[str]:
    return src.splitlines(keepends=True)


def _find(tree: ast.AST, name: str) -> Optional[ast.AST]:
    hits = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    return hits[0] if len(hits) == 1 else None


def _unittest_assert(stmt: ast.stmt) -> Optional[ast.Call]:
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        f = stmt.value.func
        if isinstance(f, ast.Attribute) and f.attr.startswith("assert") and stmt.value.args:
            return stmt.value
    return None


def _splice(src: str, edits: List[Tuple[int, int, int, int, str]]) -> str:
    """Replace (lineno, byte col, end_lineno, end byte col) spans, last first."""
    starts, pos = [], 0
    for line in _lines(src):
        starts.append(pos)
        pos += len(line.encode("utf-8"))
    data = src.encode("utf-8")
    for l1, c1, l2, c2, text in sorted(edits, reverse=True):
        a, b = starts[l1 - 1] + c1, starts[l2 - 1] + c2
        data = data[:a] + text.encode("utf-8") + data[b:]
    return data.decode("utf-8")


def tamper(src: str, test_name: str, tactic: str) -> Optional[str]:
    """The tampered source, or None if the tactic does not apply to this test."""
    tree = ast.parse(src)
    func = _find(tree, test_name)
    if func is None:
        return None
    lines = _lines(src)
    body_first, last = func.body[0].lineno, func.end_lineno
    indent = " " * func.body[0].col_offset
    first = min([func.lineno] + [d.lineno for d in func.decorator_list])
    if tactic == "delete":
        return "".join(lines[:first - 1] + lines[last:])
    if tactic == "skip":
        pad = " " * func.col_offset
        return "".join(lines[:first - 1] + [pad + '@__import__("pytest").mark.skip(reason="flaky")\n'] + lines[first - 1:])
    if tactic == "gut":
        return "".join(lines[:body_first - 1] + [indent + "pass\n"] + lines[last:])
    if tactic == "swallow":
        inner = "".join(("    " + l) if l.strip() else l for l in lines[body_first - 1:last])
        return "".join(lines[:body_first - 1] + [indent + "try:\n", inner, indent + "except BaseException:\n",
                                                  indent + "    pass\n"] + lines[last:])
    edits: List[Tuple[int, int, int, int, str]] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            t = node.test
            if tactic == "no-asserts":
                edits.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, "pass"))
            elif isinstance(t, ast.Compare):
                left = ast.unparse(t.left)
                new = "(%s) is not None" % left if tactic == "loosen" else "(%s)" % left
                edits.append((t.lineno, t.col_offset, t.end_lineno, t.end_col_offset, new))
        elif isinstance(node, ast.Expr):
            call = _unittest_assert(node)
            if call is not None:
                arg = ast.unparse(call.args[0])
                text = {"no-asserts": "pass", "loosen": "self.assertIsNotNone(%s)" % arg,
                        "truthy": "self.assertTrue(%s)" % arg}[tactic]
                edits.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, text))
    if not edits:
        return None
    out = _splice(src, edits)
    ast.parse(out)
    return out


# ------------------------------------------------------------------- measuring
COVERAGE_RUNNER = r'''
import json, os, sys, trace
import pytest
root = os.getcwd()
t = trace.Trace(count=1, trace=0, ignoredirs=[sys.prefix, sys.exec_prefix, os.path.dirname(os.__file__)])
rc = t.runfunc(pytest.main, ["-q", "-p", "no:cacheprovider"] + sys.argv[1:])
seen = {}
for (fn, ln) in t.results().counts:
    rel = os.path.relpath(fn, root)
    base = os.path.basename(fn)
    if rel.startswith("..") or "site-packages" in fn or base.startswith("test_") or base == "conftest.py":
        continue
    seen.setdefault(rel, set()).add(ln)
print("__RESULT__" + json.dumps({"rc": int(rc), "lines": sum(len(v) for v in seen.values())}))
'''


def run_suite(subject: Dict[str, Any], root: str, timeout: int = 900) -> Tuple[bool, int]:
    """(suite is green, number of distinct source lines executed)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    paths = [root] + ([os.path.join(root, "src")] if os.path.isdir(os.path.join(root, "src")) else [])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    p = subprocess.run([subject["python"], "-c", COVERAGE_RUNNER] + list(subject["test_args"]), cwd=root, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=timeout)
    for line in p.stdout.splitlines()[::-1]:
        if line.startswith("__RESULT__"):
            r = json.loads(line[len("__RESULT__"):])
            return r["rc"] == 0, r["lines"]
    return False, 0


def shape(root: str) -> Dict[str, int]:
    proj = scan(root)
    return {"tests": len(proj.tests), "asserts": sum(t["asserts"] for t in proj.tests.values()),
            "skips": sum(t["skip"] for t in proj.tests.values())}


def engine(subject: Dict[str, Any], root: str, **over: Any) -> Engine:
    cfg = dict(python=subject["python"], source=subject["source"], test_args=subject["test_args"], workers=4)
    cfg.update(over)
    return Engine(root, load_config(root, cfg))


def record(subject: Dict[str, Any], base: str, per_function: int, max_mutants: int) -> bytes:
    engine(subject, base, per_function=per_function, max_mutants=max_mutants).record(fresh=True)
    path = os.path.join(base, LEDGER)
    with open(path, "rb") as fh:
        data = fh.read()
    os.remove(path)
    return data


def check(subject: Dict[str, Any], root: str, ledger: bytes, full: bool) -> str:
    path = os.path.join(root, LEDGER)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(ledger)
    try:
        return engine(subject, root).check(full=full, skip_new=True)["verdict"]
    finally:
        os.remove(path)


# --------------------------------------------------------------------- driver
def pick_tests(truth: bytes, k: int, seed: int) -> List[Tuple[str, str]]:
    """(test file, test function) pairs that catch planted bugs: half the busiest, half random."""
    ledger = json.loads(truth)
    count: Dict[str, int] = {}
    for unit in ledger["units"].values():
        for m in unit["mutants"]:
            kl = (m.get("killer") or "").split("[")[0]
            if m["status"] == "killed" and "::" in kl:
                count[kl] = count.get(kl, 0) + 1
    ranked = sorted(count, key=lambda t: (-count[t], t))
    chosen = ranked[: k // 2]
    rest = ranked[k // 2:]
    random.Random(seed).shuffle(rest)
    chosen += rest[: k - len(chosen)]
    return [(kl.split("::")[0], kl.split("::")[-1]) for kl in chosen]


def run_subject(name: str, subject: Dict[str, Any], k: int, log) -> List[Dict[str, Any]]:
    work = tempfile.mkdtemp(prefix="tmbench-")
    try:
        base = os.path.join(work, "base")
        copy_tree(subject["root"], base)
        shutil.rmtree(os.path.join(base, ".teethmark"), ignore_errors=True)
        log("[%s] recording ledgers" % name)
        small = record(subject, base, 3, 300)
        fast = record(subject, base, 1, 150)
        truth = record(subject, base, 25, 3000)
        count = lambda b: sum(len(u["mutants"]) for u in json.loads(b)["units"].values())
        log("[%s] planted bugs: truth %d, default %d, fast %d" % (name, count(truth), count(small), count(fast)))
        green0, lines0 = run_suite(subject, base)
        if not green0:
            raise SystemExit("subject %s is not green on its own" % name)
        shape0 = shape(base)
        rows: List[Dict[str, Any]] = []
        for rel, test in pick_tests(truth, k, seed=7):
            for tactic in TACTICS:
                with open(os.path.join(base, rel), encoding="utf-8") as fh:
                    src = fh.read()
                try:
                    new = tamper(src, test, tactic)
                except (SyntaxError, ValueError):
                    new = None
                if new is None or new == src:
                    continue
                trial = os.path.join(work, "trial")
                shutil.rmtree(trial, ignore_errors=True)
                copy_tree(base, trial)
                with open(os.path.join(trial, rel), "w", encoding="utf-8") as fh:
                    fh.write(new)
                t0 = time.time()
                green, lines = run_suite(subject, trial)
                row: Dict[str, Any] = {"subject": name, "test": "%s::%s" % (rel, test), "tactic": tactic, "green": green}
                if green:
                    s = shape(trial)
                    row.update({
                        "d_count": s["tests"] < shape0["tests"],
                        "d_asserts": s["asserts"] < shape0["asserts"],
                        "d_lines": lines < lines0,
                        "tm_fast": check(subject, trial, fast, False),
                        "tm_default": check(subject, trial, small, False),
                        "truth": check(subject, trial, truth, True),
                    })
                rows.append(row)
                log("  %-10s %-58s green=%-5s %s (%.0fs)" % (
                    tactic, row["test"][-58:], green,
                    "truth=%s default=%s" % (row.get("truth"), row.get("tm_default")) if green else "",
                    time.time() - t0))
        return rows
    finally:
        shutil.rmtree(work, ignore_errors=True)


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    green = [r for r in rows if r["green"]]
    weak = [r for r in green if r["truth"] == "BLOCK"]
    fine = [r for r in green if r["truth"] != "BLOCK"]
    detectors = {
        "Tests still pass": lambda r: False,
        "Test count dropped": lambda r: r["d_count"],
        "Assertion count dropped": lambda r: r["d_asserts"],
        "Executed-line count dropped": lambda r: r["d_lines"],
        "Teethmark, fast ledger (1 bug/function)": lambda r: r["tm_fast"] != "PASS",
        "Teethmark, default ledger (3 bugs/function)": lambda r: r["tm_default"] != "PASS",
        "Teethmark, default ledger, hard BLOCK only": lambda r: r["tm_default"] == "BLOCK",
    }
    out: Dict[str, Any] = {"tampers_tried": len(rows), "tampers_still_green": len(green),
                           "truly_weakening": len(weak), "harmless": len(fine), "detectors": {}}
    for label, fn in detectors.items():
        out["detectors"][label] = {
            "caught": sum(1 for r in weak if fn(r)), "of": len(weak),
            "false_alarms": sum(1 for r in fine if fn(r)), "of_harmless": len(fine)}
    return out


def markdown(rows: List[Dict[str, Any]], per_subject: Dict[str, Dict[str, Any]]) -> str:
    total = summarise(rows)
    pct = lambda a, b: ("%d/%d (%.0f%%)" % (a, b, 100.0 * a / b)) if b else "n/a"
    out = ["# Tamper benchmark\n",
           "Tests were weakened in ways that keep the suite green. A tamper is **truly weakening** when a larger "
           "ground-truth ledger (25 planted bugs per function) says a bug the original tests caught now slips "
           "through.\n",
           "%d tampers tried, %d kept the suite green, of which %d truly weakened the tests and %d did not.\n" % (
               total["tampers_tried"], total["tampers_still_green"], total["truly_weakening"], total["harmless"]),
           "| Detector | Weakening tampers caught | False alarms on harmless tampers |", "|---|---|---|"]
    for label, d in total["detectors"].items():
        out.append("| %s | %s | %s |" % (label, pct(d["caught"], d["of"]), pct(d["false_alarms"], d["of_harmless"])))
    out += ["", "## By subject", "",
            "| Subject | Still green | Truly weakening | Teethmark (default ledger) caught |", "|---|---|---|---|"]
    for name, s in per_subject.items():
        d = s["detectors"]["Teethmark, default ledger (3 bugs/function)"]
        out.append("| %s | %d | %d | %s |" % (name, s["tampers_still_green"], s["truly_weakening"], pct(d["caught"], d["of"])))
    out += ["", "## By tactic (truly weakening tampers only)", "",
            "| Tactic | Truly weakening | Teethmark default | Assertion count | Line count |", "|---|---|---|---|---|"]
    for tactic in TACTICS:
        w = [r for r in rows if r["green"] and r["truth"] == "BLOCK" and r["tactic"] == tactic]
        if w:
            out.append("| %s | %d | %s | %s | %s |" % (
                tactic, len(w), pct(sum(r["tm_default"] != "PASS" for r in w), len(w)),
                pct(sum(r["d_asserts"] for r in w), len(w)), pct(sum(r["d_lines"] for r in w), len(w))))
    miss = [r for r in rows if r["green"] and r["truth"] == "BLOCK" and r["tm_default"] == "PASS"]
    out += ["", "## Weakening tampers Teethmark's default ledger missed", ""]
    out += ["- `%s` (%s) in %s" % (r["test"], r["tactic"], r["subject"]) for r in miss] or ["None."]
    alarms = [r for r in rows if r["green"] and r["truth"] != "BLOCK" and r["tm_default"] != "PASS"]
    out += ["", "## Harmless tampers Teethmark's default ledger flagged", ""]
    out += ["- `%s` (%s) in %s: %s" % (r["test"], r["tactic"], r["subject"], r["tm_default"]) for r in alarms] or ["None."]
    out += ["", "## Method notes", "",
            "- Ground truth comes from the same tool with a larger sample, so it is an estimate, not a proof.",
            "- Line counts use the standard library `trace` module, not a coverage tool.",
            "- Subjects are small modules plus the tests that target them; larger code bases were not measured.",
            "- Tampers were chosen from tests that catch planted bugs (half the busiest, half random), so they "
            "are weighted toward tests that matter."]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tests", type=int, default=6, help="tests to tamper with per subject")
    ap.add_argument("--subject", action="append", help="only these subjects")
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    log = lambda m: print(m, file=sys.stderr, flush=True)
    rows: List[Dict[str, Any]] = []
    per_subject: Dict[str, Dict[str, Any]] = {}
    for name, subject in SUBJECTS.items():
        if args.subject and name not in args.subject:
            continue
        if not os.path.isdir(subject["root"]) or not os.path.exists(subject["python"]):
            log("skipping %s: not found on this machine" % name)
            continue
        got = run_subject(name, subject, args.tests, log)
        rows += got
        per_subject[name] = summarise(got)
        with open(os.path.join(args.out, "raw.json"), "w") as fh:
            json.dump(rows, fh, indent=1)
    text = markdown(rows, per_subject)
    with open(os.path.join(args.out, "RESULTS.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
