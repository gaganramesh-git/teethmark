---
title: Teethmark: tests must not get weaker
inclusion: always
---

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
