"""Command line: teethmark record | check | show."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from . import __version__, report
from .engine import Engine, TeethmarkError, load_config

EXIT = {"PASS": 0, "BLOCK": 1, "REVIEW": 3}


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=".", help="project folder (default: current folder)")
    common.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    common.add_argument("--output", help="also write the report to this file")
    common.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
    common.add_argument("--python", help="interpreter that runs the tests (default: ./.venv, else this one)")
    common.add_argument("--runner", choices=["auto", "pytest", "unittest"])
    common.add_argument("--test-cmd", dest="test_cmd", help="any shell command that runs the tests")
    common.add_argument("--test-arg", dest="test_args", action="append", help="extra argument for the test runner (repeatable)")
    common.add_argument("--workers", type=int)
    common.add_argument("--timeout", type=float, help="seconds per test run")
    common.add_argument("--per-function", dest="per_function", type=int, help="planted bugs per function (default 3)")
    common.add_argument("--max-mutants", dest="max_mutants", type=int, help="ceiling per run (default 300)")
    common.add_argument("--source", action="append", help="only mutate files under this path (repeatable)")
    common.add_argument("--exclude", action="append", help="never mutate files matching this pattern (repeatable)")

    p = argparse.ArgumentParser(
        prog="teethmark",
        description="Prove that a test suite did not get weaker. Records which planted bugs your tests "
                    "catch, then fails any change after which a previously caught bug slips through.")
    p.add_argument("--version", action="version", version="teethmark " + __version__)
    sub = p.add_subparsers(dest="command")
    rec = sub.add_parser("record", parents=[common], help="measure the tests and write the ledger")
    rec.add_argument("--fresh", action="store_true", help="ignore the existing ledger and re-run everything")
    chk = sub.add_parser("check", parents=[common], help="fail if the tests got weaker since the ledger")
    chk.add_argument("--baseline-ref", dest="baseline_ref", default="",
                     help="read the ledger from this git ref (e.g. origin/main) so the change being "
                          "checked cannot rewrite its own baseline")
    chk.add_argument("--full", action="store_true", help="re-try every previously caught bug, not only affected ones")
    chk.add_argument("--update", action="store_true", help="on PASS, advance the ledger to the current code")
    chk.add_argument("--no-new", dest="no_new", action="store_true", help="skip measuring new or edited functions")
    chk.add_argument("--review-ok", dest="review_ok", action="store_true", help="exit 0 on REVIEW")
    chk.add_argument("--min-new-kill-rate", dest="min_new_kill_rate", type=float)
    shw = sub.add_parser("show", parents=[common], help="summarise the ledger")
    shw.add_argument("--survivors", action="store_true", help="list every planted bug no test catches")
    return p


def _emit(text: str, output: Optional[str]) -> None:
    print(text)
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    keys = ["python", "runner", "test_cmd", "test_args", "workers", "timeout", "per_function",
            "max_mutants", "source", "exclude", "min_new_kill_rate"]
    overrides: Dict[str, Any] = {k: getattr(args, k, None) for k in keys}
    log = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))
    try:
        engine = Engine(args.root, load_config(args.root, overrides), log)
        if args.command == "record":
            res = engine.record(fresh=args.fresh)
            _emit(json.dumps(res, indent=1) if args.format == "json" else report.record_text(res), args.output)
            return 0
        if args.command == "show":
            res = engine.show()
            _emit(json.dumps(res, indent=1) if args.format == "json"
                  else report.show_text(res, args.survivors), args.output)
            return 0
        rep = engine.check(baseline_ref=args.baseline_ref, full=args.full, update=args.update,
                           skip_new=args.no_new)
        if args.format == "json":
            _emit(json.dumps(rep, indent=1), args.output)
        elif args.format == "markdown":
            _emit(report.check_markdown(rep), args.output)
        else:
            _emit(report.check_text(rep), args.output)
        if rep["verdict"] == "REVIEW" and args.review_ok:
            return 0
        return EXIT[rep["verdict"]]
    except TeethmarkError as exc:
        print("teethmark: " + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
