# Tamper benchmark

Tests were weakened in ways that keep the suite green. A tamper is **truly weakening** when a larger ground-truth ledger (25 planted bugs per function) says a bug the original tests caught now slips through.

111 tampers tried, 108 kept the suite green, of which 72 truly weakened the tests and 36 did not.

| Detector | Weakening tampers caught | False alarms on harmless tampers |
|---|---|---|
| Tests still pass | 0/72 (0%) | 0/36 (0%) |
| Test count dropped | 11/72 (15%) | 6/36 (17%) |
| Assertion count dropped | 33/72 (46%) | 18/36 (50%) |
| Executed-line count dropped | 19/72 (26%) | 0/36 (0%) |
| Teethmark, fast ledger (1 bug/function) | 33/72 (46%) | 6/36 (17%) |
| Teethmark, default ledger (3 bugs/function) | 33/72 (46%) | 6/36 (17%) |
| Teethmark, default ledger, hard BLOCK only | 26/72 (36%) | 0/36 (0%) |

## By subject

| Subject | Still green | Truly weakening | Teethmark (default ledger) caught |
|---|---|---|---|
| shop (example) | 34 | 20 | 20/20 (100%) |
| bioproof coldchain | 36 | 31 | 10/31 (32%) |
| railway checker+importer | 38 | 21 | 3/21 (14%) |

## By tactic (truly weakening tampers only)

| Tactic | Truly weakening | Teethmark default | Assertion count | Line count |
|---|---|---|---|---|
| loosen | 10 | 4/10 (40%) | 0/10 (0%) | 0/10 (0%) |
| truthy | 7 | 2/7 (29%) | 0/7 (0%) | 0/7 (0%) |
| no-asserts | 11 | 4/11 (36%) | 11/11 (100%) | 4/11 (36%) |
| skip | 11 | 11/11 (100%) | 0/11 (0%) | 5/11 (45%) |
| gut | 11 | 4/11 (36%) | 11/11 (100%) | 5/11 (45%) |
| delete | 11 | 4/11 (36%) | 11/11 (100%) | 5/11 (45%) |
| swallow | 11 | 4/11 (36%) | 0/11 (0%) | 0/11 (0%) |

## Weakening tampers Teethmark's default ledger missed

- `tests/test_coldchain.py::test_method_picks_the_zone_that_matters` (no-asserts) in bioproof coldchain
- `tests/test_coldchain.py::test_method_picks_the_zone_that_matters` (gut) in bioproof coldchain
- `tests/test_coldchain.py::test_method_picks_the_zone_that_matters` (delete) in bioproof coldchain
- `tests/test_coldchain.py::test_method_picks_the_zone_that_matters` (swallow) in bioproof coldchain
- `tests/test_coldchain.py::test_cooling_keeps_every_sensor_under_the_safe_limit_on_the_hottest_days` (loosen) in bioproof coldchain
- `tests/test_coldchain.py::test_cooling_keeps_every_sensor_under_the_safe_limit_on_the_hottest_days` (no-asserts) in bioproof coldchain
- `tests/test_coldchain.py::test_cooling_keeps_every_sensor_under_the_safe_limit_on_the_hottest_days` (gut) in bioproof coldchain
- `tests/test_coldchain.py::test_cooling_keeps_every_sensor_under_the_safe_limit_on_the_hottest_days` (delete) in bioproof coldchain
- `tests/test_coldchain.py::test_cooling_keeps_every_sensor_under_the_safe_limit_on_the_hottest_days` (swallow) in bioproof coldchain
- `tests/test_coldchain.py::test_ph_outside_the_range_is_fix_first` (loosen) in bioproof coldchain
- `tests/test_coldchain.py::test_ph_outside_the_range_is_fix_first` (truthy) in bioproof coldchain
- `tests/test_coldchain.py::test_ph_outside_the_range_is_fix_first` (no-asserts) in bioproof coldchain
- `tests/test_coldchain.py::test_ph_outside_the_range_is_fix_first` (gut) in bioproof coldchain
- `tests/test_coldchain.py::test_ph_outside_the_range_is_fix_first` (delete) in bioproof coldchain
- `tests/test_coldchain.py::test_ph_outside_the_range_is_fix_first` (swallow) in bioproof coldchain
- `tests/test_coldchain.py::test_without_cooling_the_same_trip_breaks_the_limit_and_raises_the_alarm` (loosen) in bioproof coldchain
- `tests/test_coldchain.py::test_without_cooling_the_same_trip_breaks_the_limit_and_raises_the_alarm` (truthy) in bioproof coldchain
- `tests/test_coldchain.py::test_without_cooling_the_same_trip_breaks_the_limit_and_raises_the_alarm` (no-asserts) in bioproof coldchain
- `tests/test_coldchain.py::test_without_cooling_the_same_trip_breaks_the_limit_and_raises_the_alarm` (gut) in bioproof coldchain
- `tests/test_coldchain.py::test_without_cooling_the_same_trip_breaks_the_limit_and_raises_the_alarm` (delete) in bioproof coldchain
- `tests/test_coldchain.py::test_without_cooling_the_same_trip_breaks_the_limit_and_raises_the_alarm` (swallow) in bioproof coldchain
- `tests/test_importer.py::test_a_valid_row_is_converted_field_by_field` (loosen) in railway checker+importer
- `tests/test_importer.py::test_a_valid_row_is_converted_field_by_field` (truthy) in railway checker+importer
- `tests/test_importer.py::test_a_valid_row_is_converted_field_by_field` (no-asserts) in railway checker+importer
- `tests/test_importer.py::test_a_valid_row_is_converted_field_by_field` (gut) in railway checker+importer
- `tests/test_importer.py::test_a_valid_row_is_converted_field_by_field` (delete) in railway checker+importer
- `tests/test_importer.py::test_a_valid_row_is_converted_field_by_field` (swallow) in railway checker+importer
- `tests/test_checker.py::test_a_valid_plan_passes_and_counts_its_checks` (loosen) in railway checker+importer
- `tests/test_checker.py::test_a_valid_plan_passes_and_counts_its_checks` (truthy) in railway checker+importer
- `tests/test_checker.py::test_a_valid_plan_passes_and_counts_its_checks` (no-asserts) in railway checker+importer
- `tests/test_checker.py::test_a_valid_plan_passes_and_counts_its_checks` (gut) in railway checker+importer
- `tests/test_checker.py::test_a_valid_plan_passes_and_counts_its_checks` (delete) in railway checker+importer
- `tests/test_checker.py::test_a_valid_plan_passes_and_counts_its_checks` (swallow) in railway checker+importer
- `tests/test_importer.py::test_night_range_is_clamped_to_the_horizon` (loosen) in railway checker+importer
- `tests/test_importer.py::test_night_range_is_clamped_to_the_horizon` (truthy) in railway checker+importer
- `tests/test_importer.py::test_night_range_is_clamped_to_the_horizon` (no-asserts) in railway checker+importer
- `tests/test_importer.py::test_night_range_is_clamped_to_the_horizon` (gut) in railway checker+importer
- `tests/test_importer.py::test_night_range_is_clamped_to_the_horizon` (delete) in railway checker+importer
- `tests/test_importer.py::test_night_range_is_clamped_to_the_horizon` (swallow) in railway checker+importer

## Harmless tampers Teethmark's default ledger flagged

- `tests/test_cart.py::test_line_total_plain` (skip) in shop (example): REVIEW
- `tests/test_cart.py::test_cart_total_adds_lines` (skip) in shop (example): REVIEW
- `tests/test_coldchain.py::test_ready_soil_gives_go` (skip) in bioproof coldchain: REVIEW
- `tests/test_checker.py::test_crew_peak_concurrency_over_capacity` (skip) in railway checker+importer: REVIEW
- `tests/test_checker.py::test_equipment_over_capacity_but_none_is_never_limited` (skip) in railway checker+importer: REVIEW
- `tests/test_importer.py::test_priorities_accept_words_and_numbers` (skip) in railway checker+importer: REVIEW

## Method notes

- Ground truth comes from the same tool with a larger sample, so it is an estimate, not a proof.
- Line counts use the standard library `trace` module, not a coverage tool.
- Subjects are small modules plus the tests that target them; larger code bases were not measured.
- Tampers were chosen from tests that catch planted bugs (half the busiest, half random), so they are weighted toward tests that matter.
