"""Command line: teethmark [auto] | record | check | show | gate | init | mcp."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import __version__, report
from .engine import LEDGER, Engine, TeethmarkError, load_config
from .init import init_project

EXIT = {"PASS": 0, "BLOCK": 1, "REVIEW": 3}
FIRST_RUN_BUDGET = 120      # seconds the zero-config first recording may take
FAST_PER_FUNCTION = 1
FAST_MAX_MUTANTS = 150


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
    common.add_argument("--budget", type=int, help="stop planting new bugs after this many seconds (0 = no limit)")
    common.add_argument("--fast", action="store_true",
                        help="one planted bug per function, at most %d: a quick, coarse first pass" % FAST_MAX_MUTANTS)

    p = argparse.ArgumentParser(
        prog="teethmark",
        description="Prove that a test suite did not get weaker. With no command, it records a ledger on "
                    "first use and checks against it afterwards.")
    p.add_argument("--version", action="version", version="teethmark " + __version__)
    sub = p.add_subparsers(dest="command")

    auto = sub.add_parser("auto", parents=[common], help="(default) record on first use, check afterwards")
    _check_args(auto)
    rec = sub.add_parser("record", parents=[common], help="measure the tests and write the ledger")
    rec.add_argument("--fresh", action="store_true", help="ignore the existing ledger and re-run everything")
    chk = sub.add_parser("check", parents=[common], help="fail if the tests got weaker since the ledger")
    _check_args(chk)
    chk.add_argument("--update", action="store_true", help="on PASS, advance the ledger to the current code")
    chk.add_argument("--no-new", dest="no_new", action="store_true", help="skip measuring new or edited functions")
    chk.add_argument("--review-ok", dest="review_ok", action="store_true", help="exit 0 on REVIEW")
    chk.add_argument("--min-new-kill-rate", dest="min_new_kill_rate", type=float)
    gate = sub.add_parser("gate", parents=[common], help="quiet pass/block gate for hooks (exit 2 blocks)")
    _check_args(gate)
    gate.add_argument("--strict", action="store_true",
                      help="also block on REVIEW and on errors (default: only a real BLOCK blocks)")
    shw = sub.add_parser("show", parents=[common], help="summarise the ledger")
    shw.add_argument("--survivors", action="store_true", help="list every planted bug no test catches")
    ini = sub.add_parser("init", help="add CI, agent rules and (optionally) a git hook to a project")
    ini.add_argument("--root", default=".")
    ini.add_argument("--no-ci", action="store_true", help="do not write the GitHub workflow")
    ini.add_argument("--no-agents", action="store_true", help="do not touch AGENTS.md")
    ini.add_argument("--git-hook", action="store_true", help="also install a pre-push hook that runs the gate")
    sub.add_parser("mcp", help="run the MCP server on stdin/stdout (for agents that speak MCP)")
    return p


def _check_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--baseline-ref", dest="baseline_ref", default="",
                    help="read the ledger from this git ref (e.g. origin/main) so the change being "
                         "checked cannot rewrite its own baseline")
    sp.add_argument("--full", action="store_true", help="re-try every previously caught bug, not only affected ones")


def _emit(text: str, output: Optional[str]) -> None:
    print(text)
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")


def _overrides(args: argparse.Namespace, first_run: bool = False) -> Dict[str, Any]:
    keys = ["python", "runner", "test_cmd", "test_args", "workers", "timeout", "per_function",
            "max_mutants", "source", "exclude", "min_new_kill_rate", "budget"]
    out: Dict[str, Any] = {k: getattr(args, k, None) for k in keys}
    if getattr(args, "fast", False) or first_run:
        if out["per_function"] is None:
            out["per_function"] = FAST_PER_FUNCTION
        if out["max_mutants"] is None:
            out["max_mutants"] = FAST_MAX_MUTANTS
    if first_run and out["budget"] is None:
        out["budget"] = FIRST_RUN_BUDGET
    return out


def _do_record(args: argparse.Namespace, first_run: bool = False) -> int:
    log = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))
    engine = Engine(args.root, load_config(args.root, _overrides(args, first_run)), log)
    res = engine.record(fresh=getattr(args, "fresh", False))
    _emit(json.dumps(res, indent=1) if args.format == "json" else report.record_text(res), args.output)
    return 0


def _do_check(args: argparse.Namespace, gate: bool = False) -> int:
    log = (lambda msg: None) if args.quiet or gate else (lambda msg: print(msg, file=sys.stderr, flush=True))
    engine = Engine(args.root, load_config(args.root, _overrides(args)), log)
    rep = engine.check(baseline_ref=args.baseline_ref, full=args.full,
                       update=getattr(args, "update", False),
                       skip_new=True if gate else getattr(args, "no_new", False))
    if gate:
        return _gate_result(rep, args)
    if args.format == "json":
        _emit(json.dumps(rep, indent=1), args.output)
    elif args.format == "markdown":
        _emit(report.check_markdown(rep), args.output)
    else:
        _emit(report.check_text(rep), args.output)
    if rep["verdict"] == "REVIEW" and getattr(args, "review_ok", False):
        return 0
    return EXIT[rep["verdict"]]


def _gate_result(rep: Dict[str, Any], args: argparse.Namespace) -> int:
    if rep["verdict"] == "BLOCK":
        print(report.check_text(rep), file=sys.stderr)
        return 2
    if rep["verdict"] == "REVIEW":
        print("teethmark: REVIEW  " + "; ".join(rep["reasons"]), file=sys.stderr)
        return 2 if args.strict else 0
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "auto")
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            done = init_project(args.root, ci=not args.no_ci, agents=not args.no_agents, git_hook=args.git_hook)
            for item in done:
                print("%-34s %s" % (item["file"], item["result"]))
            print("\nNext: run `teethmark` once to record the ledger, then commit .teethmark/ledger.json.")
            return 0
        if args.command == "mcp":
            from .mcp import serve
            return serve()
        if args.command == "gate":
            ledger = os.path.join(os.path.abspath(args.root), LEDGER)
            if not args.baseline_ref and not os.path.exists(ledger):
                print("teethmark: no ledger yet (run `teethmark` once); gate skipped.", file=sys.stderr)
                return 0
            try:
                return _do_check(args, gate=True)
            except TeethmarkError as exc:
                print("teethmark: " + str(exc).splitlines()[0], file=sys.stderr)
                return 2 if args.strict else 0
        if args.command == "record":
            return _do_record(args)
        if args.command == "show":
            log = (lambda msg: None)
            engine = Engine(args.root, load_config(args.root, _overrides(args)), log)
            res = engine.show()
            _emit(json.dumps(res, indent=1) if args.format == "json"
                  else report.show_text(res, args.survivors), args.output)
            return 0
        if args.command == "check":
            return _do_check(args)
        # auto
        ledger = os.path.join(os.path.abspath(args.root), LEDGER)
        if os.path.exists(ledger) or getattr(args, "baseline_ref", ""):
            args.baseline_ref = getattr(args, "baseline_ref", "")
            for name, default in (("full", False), ("update", False), ("no_new", False), ("review_ok", False)):
                setattr(args, name, default)
            return _do_check(args)
        code = _do_record(args, first_run=True)
        print("\nFirst recording done. Make a change and run `teethmark` again to check it.")
        return code
    except TeethmarkError as exc:
        print("teethmark: " + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
