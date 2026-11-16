"""Turn results into text or markdown a person can act on."""
from __future__ import annotations

from typing import Any, Dict, List

_LIMIT = 12


def _func(unit: str) -> str:
    return unit.split("::", 1)[-1].split("#")[0] + "()"


def _diff(item: Dict[str, Any], indent: str) -> List[str]:
    out = [indent + "- " + line.strip() for line in str(item["before"]).splitlines()[:6]]
    out += [indent + "+ " + line.strip() for line in str(item["after"]).splitlines()[:6]]
    return out


def _stats(rep: Dict[str, Any]) -> List[str]:
    lines = []
    lines.append("Previously caught bugs re-tried: %d (still caught: %d, lost: %d). Not affected by this change: %d."
                 % (rep["verified"], rep["retained"], len(rep["lost"]), rep["untouched"]))
    new = rep["new_code"]
    if new["mutants"]:
        lines.append("New or edited functions: %d. Planted bugs caught there: %d of %d."
                     % (new["functions"], new["killed"], new["mutants"]))
    if rep["rehomed"]:
        lines.append("%d bug(s) are now caught by a different test than before (fine: tests were refactored, not weakened)."
                     % len(rep["rehomed"]))
    return lines


def check_text(rep: Dict[str, Any]) -> str:
    out = ["%s  %s" % (rep["verdict"], rep["reasons"][0] if rep["reasons"] else "")]
    out += ["       " + r for r in rep["reasons"][1:]]
    out.append("")
    for n, item in enumerate(rep["lost"][:_LIMIT], 1):
        out.append("Proof %d of %d   %s:%s   in %s%s" % (
            n, len(rep["lost"]), item["path"], item["line"], _func(item["unit"]),
            "   (function was edited; this logic is still there)" if item["function_edited"] else ""))
        out += _diff(item, "    ")
        out.append("  Before: caught by %s" % item["was_caught_by"])
        out.append("  Now:    %s" % item["now"])
        out.append("")
    if len(rep["lost"]) > _LIMIT:
        out.append("... and %d more (use --format json for all)." % (len(rep["lost"]) - _LIMIT))
        out.append("")
    if rep["lost"]:
        out.append("To fix: put back the check that caught each bug, or add a test that fails on the '+' line.")
        out.append("Accepting weaker tests on purpose is a human decision: run `teethmark record`.")
        out.append("")
    out += _stats(rep)
    survivors = rep["new_code"]["survivors"]
    if survivors:
        out.append("")
        out.append("Bugs in new or edited code that no test catches:")
        for item in survivors[:_LIMIT]:
            out.append("  %s:%s in %s" % (item["path"], item["line"], _func(item["unit"])))
            out += _diff(item, "      ")
        if len(survivors) > _LIMIT:
            out.append("  ... and %d more." % (len(survivors) - _LIMIT))
    if rep["test_notes"]:
        out.append("")
        out.append("Changes to the tests themselves:")
        for note in rep["test_notes"][:_LIMIT * 2]:
            out.append("  %-14s %s %s" % (note["kind"], note["test"], "(" + note["detail"] + ")"))
        if len(rep["test_notes"]) > _LIMIT * 2:
            out.append("  ... and %d more." % (len(rep["test_notes"]) - _LIMIT * 2))
    if rep["updated"]:
        out.append("")
        out.append("Ledger updated.")
    out.append("")
    out.append("Compared against %s in %.1fs." % (rep["baseline"], rep["seconds"]))
    return "\n".join(out)


def check_markdown(rep: Dict[str, Any]) -> str:
    icon = {"PASS": "✅", "REVIEW": "⚠️", "BLOCK": "⛔"}[rep["verdict"]]
    out = ["## %s Teethmark: %s" % (icon, rep["verdict"]), ""]
    out += ["- " + r for r in rep["reasons"]]
    out.append("")
    for n, item in enumerate(rep["lost"][:_LIMIT], 1):
        out.append("### Proof %d: `%s:%s` in `%s`" % (n, item["path"], item["line"], _func(item["unit"])))
        out.append("```diff")
        out += _diff(item, "")
        out.append("```")
        out.append("- **Before:** caught by `%s`" % item["was_caught_by"])
        out.append("- **Now:** %s" % item["now"])
        out.append("")
    out += ["- " + s for s in _stats(rep)]
    survivors = rep["new_code"]["survivors"]
    if survivors:
        out += ["", "<details><summary>Bugs in new or edited code that no test catches (%d)</summary>" % len(survivors), ""]
        for item in survivors[:_LIMIT]:
            out.append("`%s:%s` in `%s`" % (item["path"], item["line"], _func(item["unit"])))
            out.append("```diff")
            out += _diff(item, "")
            out.append("```")
        out.append("</details>")
    if rep["test_notes"]:
        out += ["", "| Change to tests | Test | Detail |", "|---|---|---|"]
        for note in rep["test_notes"][:_LIMIT * 2]:
            out.append("| %s | `%s` | %s |" % (note["kind"], note["test"], note["detail"]))
    return "\n".join(out) + "\n"


def record_text(res: Dict[str, Any]) -> str:
    rate = (100.0 * res["killed"] / res["mutants"]) if res["mutants"] else 0.0
    out = ["Recorded %d planted bugs across %d functions: the tests caught %d (%.0f%%), missed %d."
           % (res["mutants"], res["units"], res["killed"], rate, res["survived"])]
    if res["reused"]:
        out.append("Reused %d results from the previous ledger (nothing relevant changed)." % res["reused"])
    out += ["Warning: " + w for w in res["warnings"]]
    out.append("Ledger: %s  (commit this file). Took %.1fs." % (res["ledger"], res["seconds"]))
    out.append("Next: `teethmark check` after any change. `teethmark show --survivors` lists what the tests miss.")
    return "\n".join(out)


def show_text(res: Dict[str, Any], survivors: bool) -> str:
    if not res["mutants"]:
        return "The ledger is empty."
    out = ["%d functions, %d tests, %d planted bugs: %d caught (%.0f%%), %d missed."
           % (res["functions"], res["tests"], res["mutants"], res["killed"], res["rate"] * 100,
              res["mutants"] - res["killed"])]
    if res["seal"] != "ok":
        out.append("Ledger seal: %s" % res["seal"])
    out.append("")
    out.append("Weakest files:")
    files = sorted(res["files"].items(), key=lambda kv: (kv[1]["killed"] / kv[1]["mutants"], kv[0]))
    for path, s in files[:10]:
        out.append("  %3.0f%%  %d/%d  %s" % (100.0 * s["killed"] / s["mutants"], s["killed"], s["mutants"], path))
    if survivors:
        out.append("")
        out.append("Bugs no test catches (each one is a test worth writing):")
        for item in res["survivors"]:
            out.append("  %s:%s in %s" % (item["path"], item["line"], _func(item["unit"])))
            out += _diff(item, "      ")
    elif res["survivors"]:
        out.append("")
        out.append("Run `teethmark show --survivors` to list the %d missed bugs." % len(res["survivors"]))
    return "\n".join(out)
