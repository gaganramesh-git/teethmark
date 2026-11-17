# Contributing

Teethmark is standard library only, Python 3.9+. Please keep it that way.

```bash
python3 -m pytest                      # the whole suite, including the cheating scenarios
python3 scripts/sync_rules.py          # after editing the agent rules in that script
python3 scripts/build_pyz.py           # after editing anything in teethmark/ (a test fails if it is stale)
python3 benchmarks/tamper_bench.py     # the tamper benchmark (slow; see benchmarks/results/RESULTS.md)
```

Good first contributions:

- A runner for another test framework (see `teethmark/runner.py`).
- Another planted-bug operator (see `teethmark/mutate.py`; keep it deterministic and formatting-independent).
- A tamper the benchmark does not try yet (see `tamper()` in `benchmarks/tamper_bench.py`).
- Reports of a false alarm or a missed weakening, with the smallest project that shows it.

Any change that makes `check` miss a weakening it used to catch needs a test in `tests/test_e2e.py`.
