---
name: teethmark
description: Proves a Python test suite did not get weaker. Re-plants bugs the tests used to catch and blocks if one now slips through, showing the exact bug and the test that used to catch it. Use after editing, deleting, skipping or rewriting any test, before saying a task is done in a repo that has .teethmark/ledger.json, when the user asks "did you weaken the tests", "are my tests any good", "what do my tests miss", or runs /teethmark.
---

# Teethmark

A ledger (`.teethmark/ledger.json`) records which planted bugs the tests catch and which test catches each.
`check` re-plants them. A bug that used to be caught and now slips through means the tests got weaker.

One file, no install: it sits in `scripts/` next to this SKILL.md.

```bash
python3 <this skill folder>/scripts/teethmark.pyz <command>
```

If `teethmark` is already installed (`pipx install teethmark`), use that instead. If the project has its own
interpreter (`.venv`, poetry, uv), pass `--python <path>`; `./.venv/bin/python` is picked up automatically.

## No ledger yet

Run it with no command. It records a quick first ledger (one planted bug per function, about two minutes at
most), then prints what to do next. Tell the user to commit `.teethmark/ledger.json`. For a fuller ledger the
user can run `record` (3 bugs per function) later.

Never run `record`, `record --fresh` or the MCP `confirm_rerecord` to make a failing `check` pass.
Re-recording accepts weaker tests as the baseline. That is the user's decision, not yours.

## After you changed anything

Run `check`. Exit codes: 0 PASS, 3 REVIEW, 1 BLOCK, 2 could not run.

- **PASS**: say so in one line. If asked to keep the ledger current, use `check --update`.
- **BLOCK**: each "Proof" shows a planted bug (`-` real line, `+` bug), the test that used to catch it, and what
  happened to that test. Fix it properly: restore the assertion or test, or write a test that fails on the `+`
  line. Run `check` again. Do not edit the ledger and do not add `# pragma: no mutate`. If the weakening is
  intended (behaviour was deliberately removed), stop and tell the user exactly which protections would be
  dropped.
- **REVIEW**: a test was skipped or hollowed out, or new code has few tests that would notice a bug. Write the
  missing tests or report them.
- **Exit 2**: read the message. Usually the tests fail on clean code; fix that first.

## What do the tests miss?

`show --survivors` lists planted bugs no test catches. Offer to write a test for each; a good test fails with
the `+` line and passes with the `-` line.

## Other commands and options

- `gate`: quiet, exit 2 only on BLOCK. For hooks, pre-push and CI steps.
- `init`: adds the CI workflow, agent rules and optionally a pre-push hook to a project.
- `mcp`: an MCP server with `teethmark_check`, `teethmark_show`, `teethmark_record`.
- `--baseline-ref origin/main`: read the trusted ledger from git. Use in CI or when the working-tree ledger may
  have been touched.
- `--fast`, `--budget SECONDS`, `--full`, `--format markdown|json`, `--output FILE`, `--per-function N`,
  `--max-mutants N`, `--source DIR`, `--exclude PATTERN`, `--test-arg ARG`, `--test-cmd CMD`.

## Reporting

Lead with the verdict. For BLOCK, quote each proof block as printed. Keep it short and plain.
