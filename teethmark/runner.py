"""Run a project's tests and say which test failed first."""
from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

TIMEOUT_KILLER = "<timeout>"
UNKNOWN_KILLER = "<unknown>"

_PYTEST_FAIL = re.compile(r"^(?:FAILED|ERROR) (\S+\.py(?:::.+?)?)(?: - .*)?$", re.M)
_PYTEST_SUMMARY = "short test summary info"
_UNITTEST_FAIL = re.compile(r"^(?:FAIL|ERROR): (\S+) \(([\w.]+)\)", re.M)


@dataclass
class RunResult:
    status: str  # pass | fail | timeout | notests | error
    killer: Optional[str]
    seconds: float
    tail: str


class Runner:
    """kind: 'pytest', 'unittest' or 'custom' (any shell command; exit code only)."""

    def __init__(self, python: str, kind: str, extra: Sequence[str] = (), test_cmd: str = "") -> None:
        self.python = python
        self.kind = kind
        self.extra = list(extra)
        self.test_cmd = test_cmd

    @property
    def can_target(self) -> bool:
        return self.kind in ("pytest", "unittest")

    def _command(self, targets: Optional[Sequence[str]]) -> List[str]:
        if self.kind == "custom":
            return shlex.split(self.test_cmd)
        if self.kind == "pytest":
            cmd = [self.python, "-m", "pytest", "-x", "-q", "-rfE", "-p", "no:cacheprovider"]
            return cmd + self.extra + list(targets or [])
        if targets:
            return [self.python, "-m", "unittest", "-f"] + list(targets)
        return [self.python, "-m", "unittest", "discover", "-f"] + self.extra

    def run(self, cwd: str, targets: Optional[Sequence[str]] = None, timeout: float = 600.0) -> RunResult:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # a stale .pyc would hide a mutant
        paths = [cwd] + ([os.path.join(cwd, "src")] if os.path.isdir(os.path.join(cwd, "src")) else [])
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        start = time.time()
        try:
            proc = subprocess.Popen(self._command(targets), cwd=cwd, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=(os.name == "posix"))
        except OSError as exc:
            return RunResult("error", None, 0.0, str(exc))
        try:
            raw, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except OSError:
                pass
            proc.communicate()
            return RunResult("timeout", TIMEOUT_KILLER, time.time() - start, "timed out")
        out = raw.decode("utf-8", "replace")
        return RunResult(*self._judge(proc.returncode, out), time.time() - start, out[-4000:])

    def _judge(self, code: int, out: str):
        if self.kind == "pytest":
            if code == 0:
                return "pass", None
            if code == 5:
                return "notests", None
            if code == 4:
                return "error", None
            # only the summary block names tests; captured log lines can also start with "ERROR "
            cut = out.rfind(_PYTEST_SUMMARY)
            m = _PYTEST_FAIL.search(out[cut:] if cut >= 0 else out)
            return "fail", (m.group(1).strip() if m else UNKNOWN_KILLER)
        if self.kind == "unittest":
            if re.search(r"^Ran 0 tests", out, re.M) or code == 5:
                return "notests", None
            if code == 0:
                return "pass", None
            m = _UNITTEST_FAIL.search(out)
            if not m:
                return "fail", UNKNOWN_KILLER
            name, where = m.group(1), m.group(2)
            return "fail", (where if where.endswith("." + name) else where + "." + name)
        return ("pass", None) if code == 0 else ("fail", UNKNOWN_KILLER)


def detect(python: str, kind: str, extra: Sequence[str], test_cmd: str) -> Runner:
    if test_cmd:
        return Runner(python, "custom", extra, test_cmd)
    if kind == "auto":
        try:
            ok = subprocess.run([python, "-m", "pytest", "--version"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=60).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        kind = "pytest" if ok else "unittest"
    return Runner(python, kind, extra)
