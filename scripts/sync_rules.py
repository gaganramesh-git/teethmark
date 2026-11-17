"""Write the one set of agent rules to every place an agent looks for it.

    python3 scripts/sync_rules.py          # rewrite the copies
    python3 scripts/sync_rules.py --check  # exit 1 if any copy is out of date
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE = "Teethmark: tests must not get weaker"
BODY = """\
# Teethmark: tests must not get weaker

Teethmark keeps a ledger (`.teethmark/ledger.json`) of planted bugs this project's tests catch.
`teethmark check` re-plants them: a bug the tests used to catch and now miss means the tests got weaker.

## Do this

- After you change, add, skip or delete any test, and before you say a task is done, run `teethmark check`.
- No ledger yet? Run `teethmark` once. It records a quick first ledger. Tell the owner to commit it.
- **PASS**: say so in one line.
- **BLOCK**: each "Proof" is a planted bug (`-` real line, `+` bug) that a named test used to catch. Restore
  that assertion or test, or write a test that fails on the `+` line. Then run the check again.
- **REVIEW**: a test was skipped or hollowed out, or new code has few tests that would notice a bug. Fix it
  or report it.

## Never do this

- Never edit `.teethmark/ledger.json`.
- Never add `# pragma: no mutate` to get past a BLOCK.
- Never run `teethmark record` (or `--fresh`, or the MCP `confirm_rerecord`) to make a BLOCK go away.
  Re-recording accepts the weaker tests as the new baseline. That is the owner's decision. If weakening is
  intended, stop and say exactly which protections would be dropped.

## Tools

`teethmark check` | `teethmark show --survivors` (bugs no test catches, each one a test worth writing) |
`teethmark gate` (quiet, exit 2 on BLOCK, for hooks) | `teethmark mcp` (MCP server).
"""

CURSOR_HEAD = ("---\ndescription: Teethmark: run the check after touching tests; never weaken tests to get green.\n"
               "globs:\nalwaysApply: true\n---\n\n")
KIRO_HEAD = "---\ntitle: %s\ninclusion: always\n---\n\n" % TITLE

TARGETS = {
    "AGENTS.md": "",
    ".cursor/rules/teethmark.mdc": CURSOR_HEAD,
    ".windsurf/rules/teethmark.md": "",
    ".clinerules/teethmark.md": "",
    ".kiro/steering/teethmark.md": KIRO_HEAD,
    ".agents/rules/teethmark.md": "",
    ".github/copilot-instructions.md": "",
}


def main() -> int:
    stale = []
    for rel, head in TARGETS.items():
        path = os.path.join(ROOT, rel)
        want = head + BODY
        have = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if have == want:
            continue
        stale.append(rel)
        if "--check" not in sys.argv:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(want)
    if "--check" in sys.argv:
        for rel in stale:
            print("out of date:", rel)
        return 1 if stale else 0
    print("updated %d file(s)" % len(stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
