# Teethmark

**Proof that your tests did not get weaker.**

AI coding agents (and tired humans) have a quiet way of turning a red build green: loosen an
assertion, skip a test, delete the awkward case. Coverage stays the same. The test count stays the
same. The suite just stops catching bugs.

Teethmark catches that, and shows the proof:

```text
BLOCK  The tests got weaker: 1 bug(s) they used to catch now slip through.

Proof 1 of 1   shop/cart.py:7   in line_total()
    - if qty >= 10:
    + if (qty > 10):
  Before: caught by tests/test_cart.py::test_bulk_discount_starts_at_ten
  Now:    that test still exists but now passes with the bug in place
```

That is not a score or a guess. It is a specific bug your tests caught yesterday and do not catch
today.

## How it works, in three lines

1. **`teethmark record`** plants small bugs in each function (flip a `>=`, drop a call, return
   `None`), runs your tests, and writes down which bugs were caught *and which test caught each
   one*. This is the **ledger** (`.teethmark/ledger.json`). Commit it.
2. **`teethmark check`** runs after any change. For every caught bug whose catching test could
   have been affected, it re-plants the bug and runs that one test first. Usually one test per
   bug, so it is fast.
3. If a bug that used to be caught now slips through, the verdict is **BLOCK**, with the diff
   above. If the tests were only refactored (renamed, split, moved), the bugs are still caught
   and the verdict is **PASS**.

| Verdict | Exit code | Meaning |
|---|---|---|
| `PASS` | 0 | No previously caught bug slips through. |
| `REVIEW` | 3 | A test was skipped/xfailed, or new code is thinly tested. |
| `BLOCK` | 1 | A previously caught bug now slips through, or the ledger was hand-edited. |

## Install

No dependencies. Python 3.9+. Works with pytest and unittest.

```bash
pip install git+https://github.com/gaganramesh-git/teethmark
```

Or run the single file with nothing installed:

```bash
python3 skills/teethmark/scripts/teethmark.pyz --help
```

## Use

```bash
teethmark record            # once, on a commit you trust. Commit .teethmark/ledger.json
teethmark check             # after any change
teethmark check --update    # same, and on PASS move the ledger forward
teethmark show --survivors  # the bugs no test catches: a to-do list of tests worth writing
```

Try the 20-second demo:

```bash
bash examples/demo.sh
```

### In an AI agent loop

Run it as the last step of your verify script. The agent cannot go green by weakening tests:

```bash
pytest -q && teethmark check --update
```

### As an agent skill

`skills/teethmark/` is a ready-made skill folder (a `SKILL.md` plus the single-file tool). Copy it
into your coding agent's skills folder and the agent will run the check itself whenever it has
touched tests, and will refuse to "fix" a BLOCK by weakening tests further.

### In GitHub Actions

Compare a pull request against the ledger on the base branch, so the pull request cannot rewrite
its own baseline:

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- uses: actions/setup-python@v5
  with: { python-version: "3.12" }
- run: pip install -r requirements.txt pytest
- uses: gaganramesh-git/teethmark@v0.1.0
  with:
    baseline-ref: origin/${{ github.base_ref }}
```

The result appears in the job summary with the proof diffs.

## What makes it hard to cheat

- **Ledger from a trusted place.** `--baseline-ref origin/main` reads the ledger from git, not
  from the working tree the agent can write to.
- **Sealed ledger.** A hand-edited ledger is a BLOCK. Set `TEETHMARK_KEY` in CI and the seal
  becomes an HMAC the agent cannot forge.
- **Editing the function does not reset it.** If a function is edited, each recorded bug is
  matched by *what* it changes (for example `qty >= 10` to `qty > 10`), not by line number, and
  is re-tried in the edited function.
- **Your real files are never touched.** Bugs are planted in throw-away copies.

## Settings

Optional `.teethmark/config.json` (every key has a matching command-line flag):

```json
{
  "per_function": 3,
  "max_mutants": 300,
  "min_new_kill_rate": 0.5,
  "source": ["src"],
  "exclude": ["*/generated/*"],
  "test_args": ["-m", "not slow"],
  "test_cmd": ""
}
```

Put `# pragma: no mutate` on a line to leave it alone.

## Honest limits

- **Python only** in this version.
- **It samples.** Three planted bugs per function by default. A weakened check that none of the
  sampled bugs depends on is not seen. Raise `per_function` for more sensitivity.
- **Recording costs test runs.** One (usually partial) test run per planted bug, so a slow suite
  means a slow first recording. Measured on a real Flask project (235 tests, 17 s suite, 4
  workers): recording 60 planted bugs took about 6 minutes; a check after gutting two tests took
  about 1 minute and returned BLOCK with three proofs. Checking is cheaper because it only
  re-tries bugs whose catching test changed, and runs that one test first.
- **Tests that write files are handled, tests that write elsewhere are not.** Each run starts
  from a pristine copy of the folder, so a database or cache inside the project cannot leak
  between planted bugs. State outside the folder (a shared server, `/tmp`, a real database) can.
- **Flaky tests confuse it**, like any test-based tool. Fix or exclude them first.
- **Tests must run from a copy of the folder.** If your tests import an installed copy of the
  code from somewhere else, teethmark warns that nothing was caught.
- By default, a change to non-test source only re-checks functions that changed. Use
  `teethmark check --full` to re-try everything.

## Develop

```bash
python3 -m pytest          # includes every cheating scenario
python3 scripts/build_pyz.py
```

MIT licensed. See [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) for the design.
