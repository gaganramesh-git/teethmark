"""The ledger and the ratchet.

``record`` plants small bugs in every function, runs the tests, and writes down
which bugs the tests caught and which test caught each one (the ledger).

``check`` re-plants the bugs the ledger says were caught. A bug that used to be
caught and now slips through is proof that the tests got weaker.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__
from .mutate import Mutant, SourceFile, Unit, load
from .project import copy_tree, scan, walk_files
from .runner import TIMEOUT_KILLER, UNKNOWN_KILLER, detect

LEDGER = ".teethmark/ledger.json"
CONFIG = ".teethmark/config.json"
DEFAULTS: Dict[str, Any] = {
    "per_function": 3,         # planted bugs sampled per function
    "max_mutants": 300,        # ceiling per run
    "min_new_kill_rate": 0.5,  # new/changed code below this -> REVIEW
    "workers": 0,              # 0 = min(4, cpu count)
    "timeout": 0,              # seconds per test run; 0 = 4x the clean run + 5s
    "runner": "auto",          # auto | pytest | unittest
    "python": "",              # interpreter that runs the tests
    "test_cmd": "",            # any shell command instead of pytest/unittest
    "test_args": [],           # extra arguments for pytest/unittest
    "source": [],              # path prefixes to mutate (default: every non-test .py)
    "exclude": [],             # fnmatch patterns never mutated
}


class TeethmarkError(Exception):
    pass


def load_config(root: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    path = os.path.join(root, CONFIG)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            raise TeethmarkError("Cannot read %s: %s" % (CONFIG, exc))
        unknown = sorted(set(data) - set(DEFAULTS))
        if unknown:
            raise TeethmarkError("Unknown keys in %s: %s" % (CONFIG, ", ".join(unknown)))
        cfg.update(data)
    cfg.update({k: v for k, v in overrides.items() if v not in (None, "", [])})
    return cfg


# -- ledger -------------------------------------------------------------------
def _seal(body: Dict[str, Any]) -> str:
    payload = json.dumps({k: v for k, v in body.items() if k != "seal"},
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = os.environ.get("TEETHMARK_KEY")
    if key:
        return "hmac:" + hmac.new(key.encode("utf-8"), payload, "sha256").hexdigest()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def write_ledger(root: str, body: Dict[str, Any]) -> str:
    body = dict(body)
    body["seal"] = _seal(body)
    path = os.path.join(root, LEDGER)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def read_ledger(root: str, ref: str = "") -> Tuple[Dict[str, Any], str]:
    """Returns (ledger, seal state). Seal state: ok | bad | unverified."""
    if ref:
        try:
            raw = subprocess.run(["git", "-C", root, "show", "%s:./%s" % (ref, LEDGER)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", b"") or b""
            raise TeethmarkError("No ledger at git ref %r (%s). Run `teethmark record` on that branch first."
                                 % (ref, detail.decode("utf-8", "replace").strip() or exc))
        text = raw.decode("utf-8")
    else:
        path = os.path.join(root, LEDGER)
        if not os.path.exists(path):
            raise TeethmarkError("No ledger yet. Run `teethmark record` first.")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    try:
        body = json.loads(text)
        if not isinstance(body["units"], dict) or body.get("version") != 1:
            raise ValueError("wrong shape")
    except (ValueError, KeyError, TypeError):
        raise TeethmarkError("The ledger is not a valid teethmark ledger (version 1).")
    stored = str(body.get("seal", ""))
    has_key = bool(os.environ.get("TEETHMARK_KEY"))
    if stored.startswith("hmac:") and not has_key:
        return body, "unverified"
    return body, ("ok" if hmac.compare_digest(stored, _seal(body)) else "bad")


# -- isolated working copies --------------------------------------------------
class Workspace:
    """Throw-away copies of the project, one per worker. The real tree is never
    modified, so a crash can never leave a planted bug behind."""

    def __init__(self, root: str, workers: int) -> None:
        self.root = root
        self.base = tempfile.mkdtemp(prefix="teethmark-")
        self.name = os.path.basename(root.rstrip(os.sep)) or "project"
        self.slots: "queue.Queue[int]" = queue.Queue()
        for i in range(workers):
            self.slots.put(i)
        self.ready: set = set()
        self.snapshots: Dict[int, Dict[str, Tuple[int, int]]] = {}

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(self, *exc: Any) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def acquire(self) -> Tuple[int, str]:
        i = self.slots.get()
        path = os.path.join(self.base, "w%d" % i, self.name)
        if i not in self.ready:
            copy_tree(self.root, path)
            self.snapshots[i] = {rel: _stamp(full) for rel, full in walk_files(path)}
            self.ready.add(i)
        return i, path

    def heal(self, i: int, keep: str = "") -> None:
        """Put the copy back to how it was made: tests that write files (a
        database, a cache) must not leak state from one planted bug to the next."""
        path = os.path.join(self.base, "w%d" % i, self.name)
        snap = self.snapshots[i]
        seen = set()
        for rel, full in walk_files(path):
            seen.add(rel)
            if rel == keep:
                continue
            if rel not in snap:
                try:
                    os.remove(full)
                except OSError:
                    pass
            elif _stamp(full) != snap[rel]:
                self._restore(i, rel, full)
        for rel in set(snap) - seen:
            self._restore(i, rel, os.path.join(path, rel))

    def _restore(self, i: int, rel: str, full: str) -> None:
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            shutil.copy2(os.path.join(self.root, rel), full)
            self.snapshots[i][rel] = _stamp(full)
        except OSError:
            pass

    def release(self, i: int) -> None:
        self.slots.put(i)


def _stamp(path: str) -> Tuple[int, int]:
    st = os.lstat(path)
    return (st.st_size, st.st_mtime_ns)


def _round_robin(groups: List[List[Mutant]], limit: int) -> List[Mutant]:
    out: List[Mutant] = []
    depth = 0
    while len(out) < limit and any(depth < len(g) for g in groups):
        for g in groups:
            if depth < len(g) and len(out) < limit:
                out.append(g[depth])
        depth += 1
    return out


def _entry(m: Mutant, status: str, killer: Optional[str]) -> Dict[str, Any]:
    d = m.describe()
    d["status"] = status
    d["killer"] = killer
    return d


class Engine:
    def __init__(self, root: str, cfg: Dict[str, Any], log: Optional[Callable[[str], None]] = None) -> None:
        self.root = os.path.abspath(root)
        if not os.path.isdir(self.root):
            raise TeethmarkError("Not a directory: %s" % root)
        self.cfg = cfg
        self.log = log or (lambda msg: None)
        venv = os.path.join(self.root, ".venv", "bin", "python")
        python = cfg["python"] or (venv if os.path.exists(venv) else sys.executable)
        self.runner = detect(python, cfg["runner"], cfg["test_args"], cfg["test_cmd"])
        self.workers = int(cfg["workers"]) or min(4, os.cpu_count() or 2)
        self.project = scan(self.root, cfg["source"], cfg["exclude"])
        self.units: Dict[str, Tuple[SourceFile, Unit]] = {}
        for rel in sorted(self.project.sources):
            sf = load(rel, self.project.sources[rel])
            if sf is None:
                continue
            for unit in sf.units:
                if unit.sites:
                    self.units[unit.key] = (sf, unit)
        self.timeout = float(cfg["timeout"] or 0)
        self.baseline_seconds = 0.0
        # which test files have caught bugs in which source file, learned as we go
        self._affinity: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()

    # -- running ------------------------------------------------------------
    def _baseline(self, ws: Workspace) -> None:
        self.log("Running the tests once on clean code (%s)..." % self.runner.kind)
        i, path = ws.acquire()
        try:
            r = self.runner.run(path, timeout=self.timeout or 3600.0)
            ws.heal(i)
        finally:
            ws.release(i)
        if r.status == "notests":
            raise TeethmarkError("No tests were found. Point teethmark at the project root, or set "
                                 "test_args / test_cmd in %s." % CONFIG)
        if r.status != "pass":
            raise TeethmarkError("The tests must pass on clean code before teethmark can measure them "
                                 "(status: %s).\n\n%s" % (r.status, r.tail.strip()))
        self.baseline_seconds = r.seconds
        if not self.timeout:
            self.timeout = max(10.0, r.seconds * 4 + 5)

    def _killer_target(self, killer: Optional[str]) -> Optional[str]:
        """The test file (pytest) or test module (unittest) a killer lives in."""
        k = killer or ""
        if self.runner.kind == "pytest" and ("::" in k or k.endswith(".py")):
            return k.split("::")[0]
        if self.runner.kind == "unittest" and k.count(".") >= 2 and not k.startswith("<"):
            return k.rsplit(".", 2)[0]
        return None

    def _guess(self, source_path: str) -> List[str]:
        """Tests most likely to catch a bug in this file, so a caught bug costs
        a few tests instead of the whole suite: files that already caught bugs
        here, then test files named after the source file."""
        with self._lock:
            learned = sorted(self._affinity.get(source_path, {}).items(), key=lambda kv: (-kv[1], kv[0]))
        out = [t for t, _ in learned[:2]]
        if self.runner.kind == "pytest":
            stem = os.path.splitext(os.path.basename(source_path))[0]
            if stem == "__init__":
                stem = os.path.basename(os.path.dirname(source_path))
            if len(stem) >= 3:
                for t in sorted(self.project.test_files):
                    if stem in os.path.basename(t) and t not in out and len(out) < 3:
                        out.append(t)
        return out

    def _evaluate(self, ws: Workspace, m: Mutant, target: Optional[str]) -> Tuple[str, Optional[str]]:
        status, killer = self._evaluate_once(ws, m, target)
        t = self._killer_target(killer)
        if t:
            with self._lock:
                seen = self._affinity.setdefault(m.path, {})
                seen[t] = seen.get(t, 0) + 1
        return status, killer

    def _evaluate_once(self, ws: Workspace, m: Mutant, target: Optional[str]) -> Tuple[str, Optional[str]]:
        i, path = ws.acquire()
        try:
            full = os.path.join(path, m.path)
            with open(full, "rb") as fh:
                original = fh.read()
            try:
                with open(full, "wb") as fh:
                    fh.write(m.data)
                if target and self.runner.can_target:
                    # cheap path: the test that caught this bug last time
                    r = self.runner.run(path, [target], self.timeout)
                    if r.status in ("fail", "timeout"):
                        return "killed", (target if r.status == "fail" else TIMEOUT_KILLER)
                    ws.heal(i, keep=m.path)
                elif self.runner.can_target:
                    guess = self._guess(m.path)
                    if guess:
                        r = self.runner.run(path, guess, self.timeout)
                        if r.status == "fail" and r.killer:
                            return "killed", r.killer
                        ws.heal(i, keep=m.path)
                r = self.runner.run(path, None, self.timeout)
                if r.status == "pass":
                    return "survived", None
                return "killed", r.killer or UNKNOWN_KILLER
            finally:
                with open(full, "wb") as fh:
                    fh.write(original)
                ws.heal(i)
        finally:
            ws.release(i)

    def _run_all(self, ws: Workspace, jobs: List[Tuple[Mutant, Optional[str]]]) -> List[Tuple[str, Optional[str]]]:
        total = len(jobs)
        done = [0]
        lock = threading.Lock()
        step = max(1, total // 10)

        def one(job: Tuple[Mutant, Optional[str]]) -> Tuple[str, Optional[str]]:
            result = self._evaluate(ws, job[0], job[1])
            with lock:
                done[0] += 1
                if done[0] % step == 0 or done[0] == total:
                    self.log("  %d/%d planted bugs tried" % (done[0], total))
            return result

        if not jobs:
            return []
        self.log("Planting %d bugs, one at a time, in %d isolated copies..." % (total, min(self.workers, total)))
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(one, jobs))

    def _header(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "tool": "teethmark %s" % __version__,
            "runner": self.runner.kind,
            "shared_hash": self.project.shared_hash,
            "test_files": dict(self.project.test_files),
            "tests": dict(self.project.tests),
        }

    # -- record -------------------------------------------------------------
    def record(self, fresh: bool = False) -> Dict[str, Any]:
        start = time.time()
        if not self.units:
            raise TeethmarkError("No Python functions to measure were found under %s." % self.root)
        old: Dict[str, Any] = {}
        if not fresh:
            try:
                old, _ = read_ledger(self.root)
            except TeethmarkError:
                old = {}
        reusable: Dict[str, Dict[str, Any]] = {}
        if (old and old.get("shared_hash") == self.project.shared_hash
                and old.get("test_files") == self.project.test_files
                and old.get("runner") == self.runner.kind):
            for key, rec in old["units"].items():
                cur = self.units.get(key)
                if cur and cur[1].hash == rec.get("hash"):
                    for m in rec["mutants"]:
                        reusable[m["id"]] = m
        groups = [self.units[k][0].sample(self.units[k][1], int(self.cfg["per_function"]))
                  for k in sorted(self.units)]
        mutants = _round_robin(groups, int(self.cfg["max_mutants"]))
        todo = [m for m in mutants if m.id not in reusable]
        results: Dict[str, Tuple[str, Optional[str]]] = {
            m.id: (reusable[m.id]["status"], reusable[m.id]["killer"]) for m in mutants if m.id in reusable}
        if todo:
            with Workspace(self.root, self.workers) as ws:
                self._baseline(ws)
                for m, res in zip(todo, self._run_all(ws, [(m, None) for m in todo])):
                    results[m.id] = res
        body = self._header()
        units: Dict[str, Any] = {}
        for m in mutants:
            sf, unit = self.units[m.unit_key]
            rec = units.setdefault(m.unit_key, {"hash": unit.hash, "mutants": []})
            rec["mutants"].append(_entry(m, *results[m.id]))
        body["units"] = units
        path = write_ledger(self.root, body)
        killed = sum(1 for r in results.values() if r[0] == "killed")
        warnings = []
        if len(mutants) >= 8 and killed == 0:
            warnings.append("No planted bug was caught at all. The tests are probably importing an "
                            "installed copy of the code instead of this folder (editable install?).")
        if sum(len(g) for g in groups) > len(mutants):
            warnings.append("Sampling was capped at max_mutants=%d; raise it to cover more."
                            % int(self.cfg["max_mutants"]))
        return {"ledger": path, "units": len(units), "mutants": len(mutants), "killed": killed,
                "survived": len(mutants) - killed, "reused": len(mutants) - len(todo),
                "baseline_seconds": round(self.baseline_seconds, 2),
                "seconds": round(time.time() - start, 2), "warnings": warnings}

    # -- check --------------------------------------------------------------
    def _killer_state(self, killer: Optional[str]) -> str:
        k = killer or ""
        if "::" not in k and not k.endswith(".py"):
            return "no test fails on this bug any more"
        path = k.split("::")[0]
        if not os.path.exists(os.path.join(self.root, path)):
            return "its test file is gone"
        if "::" in k and path in self.project.test_files and re.sub(r"\[.*\]$", "", k) not in self.project.tests:
            return "that test was removed or renamed, and no other test catches the bug"
        return "that test still exists but now passes with the bug in place"

    def check(self, baseline_ref: str = "", full: bool = False, update: bool = False,
              skip_new: bool = False) -> Dict[str, Any]:
        start = time.time()
        old, seal_state = read_ledger(self.root, baseline_ref)
        cur = self.project
        shared_changed = old.get("shared_hash") != cur.shared_hash
        changed_tests = {p for p, h in old.get("test_files", {}).items() if cur.test_files.get(p) != h}
        any_change = shared_changed or bool(changed_tests)

        def must_verify(killer: Optional[str]) -> bool:
            if full or shared_changed:
                return True
            k = killer or ""
            if "::" not in k and not k.endswith(".py"):
                return any_change  # cannot tell which file the killer lives in
            path = k.split("::")[0]
            return path in changed_tests or path not in cur.test_files

        # 1. bugs the old suite caught, which the current suite must still catch
        verify: List[Tuple[str, Dict[str, Any], Mutant, bool]] = []  # key, old entry, mutant, carried
        removed_units: List[str] = []
        untouched = 0
        new_keys: List[str] = []
        for key in sorted(old["units"]):
            rec = old["units"][key]
            found = self.units.get(key)
            if found is None:
                removed_units.append(key)
                continue
            sf, unit = found
            same = unit.hash == rec.get("hash")
            for entry in rec["mutants"]:
                if entry.get("status") != "killed":
                    continue
                if same and not must_verify(entry.get("killer")):
                    untouched += 1
                    continue
                m = (sf.find(unit, entry["id"]) if same
                     else sf.find_sig(unit, entry.get("sig", ""), int(entry.get("occ", 0))))
                if m is not None:
                    verify.append((key, entry, m, not same))
        for key in sorted(self.units):
            rec = old["units"].get(key)
            if rec is None or rec.get("hash") != self.units[key][1].hash:
                new_keys.append(key)

        # 2. fresh bugs in new or edited functions
        fresh: List[Mutant] = []
        if not skip_new:
            taken = {v[2].id for v in verify}
            groups = [[m for m in self.units[k][0].sample(self.units[k][1], int(self.cfg["per_function"]))
                       if m.id not in taken] for k in new_keys]
            fresh = _round_robin(groups, int(self.cfg["max_mutants"]))

        results: List[Tuple[str, Optional[str]]] = []
        if verify or fresh:
            jobs: List[Tuple[Mutant, Optional[str]]] = []
            for _, entry, m, _carried in verify:
                k = entry.get("killer")
                jobs.append((m, None if k in (None, TIMEOUT_KILLER, UNKNOWN_KILLER) else k))
            jobs += [(m, None) for m in fresh]
            with Workspace(self.root, self.workers) as ws:
                self._baseline(ws)
                results = self._run_all(ws, jobs)

        lost: List[Dict[str, Any]] = []
        rehomed: List[Dict[str, Any]] = []
        retained = 0
        verified: Dict[str, List[Dict[str, Any]]] = {}  # unit key -> current entries
        for (key, entry, m, carried), (status, killer) in zip(verify, results):
            verified.setdefault(key, []).append(_entry(m, status, killer))
            if status == "killed":
                retained += 1
                if killer != entry.get("killer"):
                    rehomed.append({"id": m.id, "unit": key, "was": entry.get("killer"), "now": killer})
                continue
            item = m.describe()
            item.update({"unit": key, "path": m.path, "was_caught_by": entry.get("killer"),
                         "now": self._killer_state(entry.get("killer")), "function_edited": carried})
            lost.append(item)

        new_entries: Dict[str, List[Dict[str, Any]]] = {}
        survivors: List[Dict[str, Any]] = []
        new_killed = 0
        for m, (status, killer) in zip(fresh, results[len(verify):]):
            new_entries.setdefault(m.unit_key, []).append(_entry(m, status, killer))
            if status == "killed":
                new_killed += 1
            else:
                item = m.describe()
                item.update({"unit": m.unit_key, "path": m.path})
                survivors.append(item)
        rate = (new_killed / len(fresh)) if fresh else None

        # 3. what the test files themselves look like now
        notes: List[Dict[str, str]] = []
        old_tests = old.get("tests", {})
        for tid in sorted(old_tests):
            was, now = old_tests[tid], cur.tests.get(tid)
            if now is None:
                notes.append({"kind": "removed", "test": tid, "detail": "test removed or renamed"})
                continue
            if now.get("skip") and not was.get("skip"):
                notes.append({"kind": "skip-added", "test": tid, "detail": "test is now skipped or xfail"})
            if now.get("asserts", 0) < was.get("asserts", 0):
                notes.append({"kind": "fewer-asserts", "test": tid,
                              "detail": "assertions went from %d to %d" % (was.get("asserts", 0), now.get("asserts", 0))})
            if now.get("trivial", 0) > was.get("trivial", 0):
                notes.append({"kind": "always-true", "test": tid, "detail": "an assertion that can never fail was added"})

        # 4. verdict
        reasons: List[str] = []
        verdict = "PASS"
        min_rate = float(self.cfg["min_new_kill_rate"])
        if rate is not None and len(fresh) >= 4 and rate < min_rate:
            verdict = "REVIEW"
            reasons.append("New or edited code is thinly tested: only %d of %d planted bugs were caught (%.0f%%, floor %.0f%%)."
                           % (new_killed, len(fresh), rate * 100, min_rate * 100))
        skipped = [n for n in notes if n["kind"] == "skip-added"]
        if skipped:
            verdict = "REVIEW"
            reasons.append("%d test(s) were switched off with skip/xfail." % len(skipped))
        hollow = [n for n in notes if n["kind"] == "always-true"]
        if hollow:
            verdict = "REVIEW"
            reasons.append("%d test(s) gained an assertion that can never fail (e.g. `assert True`)." % len(hollow))
        if seal_state == "bad":
            verdict = "BLOCK"
            reasons.append("The ledger was edited by hand (its seal does not match). Restore it from git, "
                           "or re-baseline deliberately with `teethmark record`.")
        if lost:
            verdict = "BLOCK"
            reasons.insert(0, "The tests got weaker: %d bug(s) they used to catch now slip through." % len(lost))
        if verdict == "PASS":
            if verify:
                reasons.append("Every one of the %d previously caught bugs that could be affected is still caught." % len(verify))
            else:
                reasons.append("Nothing that could weaken the tests has changed since the ledger was recorded.")
        if seal_state == "unverified":
            notes.append({"kind": "seal", "test": "", "detail": "ledger is HMAC-sealed but TEETHMARK_KEY is not set, so the seal was not verified"})

        updated = False
        if update and verdict == "PASS":
            body = self._header()
            units: Dict[str, Any] = {}
            for key in sorted(self.units):
                unit = self.units[key][1]
                rec = old["units"].get(key)
                entries: List[Dict[str, Any]]
                if rec is not None and rec.get("hash") == unit.hash:
                    now = {e["id"]: e for e in verified.get(key, [])}
                    entries = [now.get(e["id"], e) for e in rec["mutants"]]
                else:
                    entries = verified.get(key, []) + new_entries.get(key, [])
                if entries:
                    units[key] = {"hash": unit.hash, "mutants": entries}
            body["units"] = units
            write_ledger(self.root, body)
            updated = True

        return {
            "verdict": verdict, "reasons": reasons, "lost": lost, "rehomed": rehomed,
            "verified": len(verify), "retained": retained, "untouched": untouched,
            "new_code": {"functions": len(new_keys), "mutants": len(fresh), "killed": new_killed,
                         "rate": rate, "survivors": survivors},
            "test_notes": notes, "removed_functions": removed_units, "seal": seal_state,
            "baseline": baseline_ref or LEDGER, "updated": updated,
            "seconds": round(time.time() - start, 2),
        }

    # -- show ---------------------------------------------------------------
    def show(self) -> Dict[str, Any]:
        old, seal_state = read_ledger(self.root)
        total = killed = 0
        survivors: List[Dict[str, Any]] = []
        per_file: Dict[str, List[int]] = {}
        for key in sorted(old["units"]):
            path = key.split("::")[0]
            for e in old["units"][key]["mutants"]:
                total += 1
                stat = per_file.setdefault(path, [0, 0])
                stat[1] += 1
                if e.get("status") == "killed":
                    killed += 1
                    stat[0] += 1
                else:
                    item = dict(e)
                    item.update({"unit": key, "path": path})
                    survivors.append(item)
        return {"functions": len(old["units"]), "mutants": total, "killed": killed,
                "rate": (killed / total) if total else None, "survivors": survivors,
                "files": {p: {"killed": s[0], "mutants": s[1]} for p, s in per_file.items()},
                "tests": len(old.get("tests", {})), "seal": seal_state}
