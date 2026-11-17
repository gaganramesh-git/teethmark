"""`teethmark init`: wire Teethmark into a project in one command.

Everything here is idempotent and never overwrites a file you wrote: the agent rules
live between two marker comments and are replaced in place; the workflow and the git
hook are created only if missing.
"""
from __future__ import annotations

import json
import os
import stat
from typing import Dict, List

from . import __version__

START = "<!-- teethmark:start -->"
END = "<!-- teethmark:end -->"

AGENT_RULES = """\
{start}
## Tests must not get weaker (Teethmark)

This project keeps a ledger of planted bugs its tests catch (`.teethmark/ledger.json`).

- After you change, add, skip or delete any test, and before you say a task is done, run
  `teethmark check`.
- If it says BLOCK, a bug the tests used to catch now slips through. Restore the assertion or
  test it shows, or write a test that fails on the `+` line. Then run it again.
- Never edit `.teethmark/ledger.json`, never add `# pragma: no mutate` to get past a BLOCK, and
  never run `teethmark record` to make a BLOCK go away. Re-recording accepts weaker tests and is
  the owner's decision. If weakening is intended, stop and say exactly what protection is lost.
{end}
"""

WORKFLOW = """\
name: teethmark

on:
  pull_request:

permissions:
  contents: read

jobs:
  tests-not-weaker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      # install your project and its test dependencies here, for example:
      # - run: pip install -e . pytest
      - uses: gaganramesh-git/teethmark@v{version}
        with:
          baseline-ref: origin/${{{{ github.base_ref }}}}
"""

HOOK = """\
#!/bin/sh
# installed by `teethmark init --git-hook`; remove this file to uninstall
if command -v teethmark >/dev/null 2>&1; then
  teethmark gate || exit 1
fi
"""


def _write_new(path: str, text: str, mode: int = 0) -> bool:
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)
    return True


def _agent_block() -> str:
    return AGENT_RULES.format(start=START, end=END)


def _upsert_rules(path: str) -> str:
    block = _agent_block()
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(block)
        return "created"
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if START in text and END in text:
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        new = head + block.rstrip("\n") + tail
        if new == text:
            return "unchanged"
        action = "updated"
    else:
        new = text.rstrip("\n") + "\n\n" + block
        action = "appended"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return action


def init_project(root: str, ci: bool = True, agents: bool = True, git_hook: bool = False) -> List[Dict[str, str]]:
    root = os.path.abspath(root)
    done: List[Dict[str, str]] = []

    cfg = os.path.join(root, ".teethmark", "config.json")
    body: Dict[str, object] = {}
    if os.path.isdir(os.path.join(root, "src")):
        body["source"] = ["src"]
    made = _write_new(cfg, json.dumps(body, indent=2) + "\n")
    done.append({"file": ".teethmark/config.json", "result": "created" if made else "kept (already there)"})

    if agents:
        done.append({"file": "AGENTS.md", "result": _upsert_rules(os.path.join(root, "AGENTS.md"))})
    if ci:
        made = _write_new(os.path.join(root, ".github", "workflows", "teethmark.yml"),
                          WORKFLOW.format(version=__version__))
        done.append({"file": ".github/workflows/teethmark.yml",
                     "result": "created" if made else "kept (already there)"})
    if git_hook:
        hooks = os.path.join(root, ".git", "hooks")
        if not os.path.isdir(hooks):
            done.append({"file": ".git/hooks/pre-push", "result": "skipped (not a git repository)"})
        else:
            made = _write_new(os.path.join(hooks, "pre-push"), HOOK,
                              stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
            done.append({"file": ".git/hooks/pre-push",
                         "result": "created" if made else "kept (a pre-push hook already exists)"})
    return done
