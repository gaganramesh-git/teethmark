---
name: teethmark
description: Proves a Python test suite did not get weaker. Re-plants bugs the tests used to catch and blocks if one now slips through, showing the exact bug and the test that used to catch it. Use after editing, deleting, skipping or rewriting any test, before saying a task is done in a repo that has .teethmark/ledger.json, when the user asks "did you weaken the tests", "are my tests any good", "what do my tests miss", or runs /teethmark.
---

# Teethmark

A ledger (`.teethmark/ledger.json`) records which planted bugs the tests catch and which test
catches each. `check` re-plants them. A bug that used to be caught and now slips through means the
tests got weaker.

The tool is one file, no install needed. It sits in `scripts/` next to this SKILL.md:

```bash
python3 <this skill folder>/scripts/teethmark.pyz <command> [options]
```

If the project has its own interpreter (`.venv`, poetry, uv), pass `--python <path>` so the tests
run with the right packages. `./.venv/bin/python` is picked up automatically.

## When there is no ledger yet

1. Make sure the tests pass.
2. Run `record`. It takes roughly (number of functions x 3) partial test runs. Tell the user it
   may take a few minutes on a slow suite; use `--max-mutants 100` for a quick first pass.
3. Report the one-line result and tell the user to commit `.teethmark/ledger.json`.

Never run `record` to make a failing `check` pass. Re-recording accepts weaker tests, and that is
the user's decision, not yours. Ask first.

## After you changed anything

Run `check`. Exit codes: 0 PASS, 3 REVIEW, 1 BLOCK, 2 could not run.

- **PASS**: say so in one line. If you were asked to keep the ledger current, use
  `check --update`.
- **BLOCK**: each "Proof" shows a planted bug (`-` real line, `+` bug), the test that used to
  catch it, and what happened to that test. Fix it properly:
  - restore the assertion, test or case that caught it, or
  - write a test that fails when the `+` line is in place.
  Then run `check` again. Do not edit the ledger, do not add `# pragma: no mutate`, and do not
  re-record. If the weakening was intended (the behaviour was deliberately removed), stop and
  tell the user exactly which protections would be dropped, and let them run `record`.
- **REVIEW**: a test was skipped/xfailed, or new code has few tests that would notice a bug.
  Show the listed survivors and either write the missing tests or report them to the user.
- **Exit 2**: read the message. Usually the tests fail on clean code; fix that first.

## When asked what the tests miss

Run `show --survivors`. Each entry is a real bug no test notices. Offer to write a test for each;
a good test fails with the `+` line and passes with the `-` line.

## Useful options

- `--baseline-ref origin/main`: compare against the ledger on a git ref instead of the working
  tree. Use this in CI or whenever the working-tree ledger may have been touched.
- `--full`: re-try every recorded bug, not only the ones whose test changed.
- `--format markdown|json`, `--output FILE`: for reports and PR comments.
- `--per-function N`, `--max-mutants N`, `--source DIR`, `--exclude PATTERN`, `--test-arg ARG`.

## Reporting

Lead with the verdict. For BLOCK, quote each proof block as printed. Keep it short and plain.
