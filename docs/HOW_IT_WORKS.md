# How Teethmark works

## The problem

A test suite has one job: fail when the code is wrong. The usual numbers do not measure that.

| Number | What weakening does to it |
|---|---|
| Tests passing | Goes *up* |
| Test count | Unchanged if an assertion is loosened |
| Line coverage | Unchanged: the line still runs, nothing checks the result |

So an agent told "make the build green" can loosen `== 9.0` to `> 0` and every dashboard improves.

## The idea

Measure the suite by the only thing that matters: **which wrong programs it rejects**. Write that
down once. Afterwards, any change that makes the suite accept a wrong program it used to reject
has weakened it, and that wrong program is the proof.

## The pieces

**Planted bugs (mutants).** For each function, Teethmark makes small edits that change behaviour:
swap a comparison, swap arithmetic, `and`/`or`, bump a constant, return `None`, negate an `if`,
drop a call. Each edit is spliced into the original bytes of the file, so nothing else in the
file changes. Docstrings, annotations, f-strings and logging calls are left alone.

**Stable identity.** A planted bug is named by a hash of the function's syntax tree plus which
edit it is. Line numbers, comments, formatting and moving the function around the file do not
change the name. So a ledger entry keeps meaning the same bug for as long as the function is the
same function.

**The ledger.** `record` runs the tests against each planted bug and stores, per bug: caught or
missed, and the *first test that failed*. It also stores a hash of every test file, a hash of the
shared test support (conftest, helpers, config), and the shape of each test (assert count, skip
markers).

**The ratchet (`check`).**

1. Work out what changed on the test side by comparing hashes.
2. For each caught bug in an unchanged function: if the test that caught it lives in an unchanged
   file and shared support is unchanged, skip it. Otherwise re-plant the bug and run *that one
   test*. Still fails: done. Passes or gone: run the whole suite. Something else fails: the bug
   is still caught, by a different test (a refactor). Nothing fails: **lost**.
3. For each caught bug in an *edited* function: find the same edit to the same expression in the
   new version (matched by content, not position) and do the same. This closes the loophole of
   touching a function just to reset its history.
4. For new and edited functions: plant fresh bugs and measure how many are caught.
5. Verdict: any lost bug or a broken ledger seal is BLOCK; a newly skipped test or thinly tested
   new code is REVIEW; otherwise PASS.

**Isolation.** Bugs are planted in temporary copies of the project, one per worker. Python's
bytecode cache is disabled in those runs so a stale cache can never hide a planted bug. The real
tree is read-only to Teethmark, apart from `.teethmark/ledger.json`.

**Speed.** While recording, Teethmark learns which test files catch bugs in which source files
and tries those first (plus test files named after the source file), falling back to the whole
suite only when they pass. Results are reused when neither the function nor the tests changed.

## Trust model

| Threat | Defence |
|---|---|
| Loosen/delete/skip a test | The bug it caught is re-planted and slips through: BLOCK with proof |
| Edit the ledger to hide it | Content seal mismatch: BLOCK |
| Recompute the seal too | `TEETHMARK_KEY` makes the seal an HMAC; or read the ledger from `--baseline-ref` |
| Touch the function to reset its bugs | Bugs carry over by content signature |
| Re-record to accept the weaker suite | Not preventable in the working tree; `--baseline-ref` in CI ignores it |
| Add `# pragma: no mutate` | Only affects future sampling; see the note below |

Note on pragmas: a recorded bug on a line that later gains `# pragma: no mutate` is no longer
generated, so it is not re-tried. The pragma is visible in the diff; review it like a skip marker.

## What it is not

It is not a full mutation-testing run (it samples, and it only re-runs what a change can affect),
and it does not judge whether the *source* is correct. It answers one question: did the tests
lose the ability to notice something they used to notice?
