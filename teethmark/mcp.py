"""A small MCP server (stdio, JSON-RPC 2.0, newline-delimited) so any agent that speaks the
Model Context Protocol can use Teethmark without a per-agent plugin. Standard library only.

Tools:
  teethmark_check      did the tests get weaker? (read-only)
  teethmark_show       what do the tests catch and miss? (read-only)
  teethmark_record     create the ledger. Refuses to overwrite one unless the caller passes
                       confirm_rerecord=true, and is disabled entirely when
                       TEETHMARK_MCP_READONLY=1, because re-recording is how a weakened suite
                       would be accepted.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Dict, IO, List, Optional

from . import __version__, report
from .engine import LEDGER, Engine, TeethmarkError, load_config

PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
FIRST_RUN_BUDGET = 120

_ROOT = {"type": "string", "description": "Project folder (default: the server's working directory)."}
_FAST = {"type": "boolean", "description": "One planted bug per function: quick and coarse."}

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "teethmark_check",
        "description": ("Check whether the project's tests got weaker since the recorded ledger. Returns PASS, "
                        "REVIEW or BLOCK. BLOCK includes proof: a planted bug the tests used to catch and "
                        "no longer do. Run after changing, skipping or deleting any test, and before "
                        "declaring a task done. On BLOCK, restore the protection or write a test that fails "
                        "on the planted bug; never edit the ledger or re-record to get past it."),
        "inputSchema": {"type": "object", "properties": {
            "root": _ROOT,
            "baseline_ref": {"type": "string", "description": "Git ref holding the trusted ledger, e.g. origin/main."},
            "full": {"type": "boolean", "description": "Re-try every recorded bug, not only affected ones."},
            "python": {"type": "string", "description": "Interpreter that runs the tests."}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "teethmark_show",
        "description": ("Summarise what the tests catch: share of planted bugs caught, weakest files, and "
                        "optionally every planted bug no test catches (each is a test worth writing)."),
        "inputSchema": {"type": "object", "properties": {
            "root": _ROOT,
            "survivors": {"type": "boolean", "description": "List every bug no test catches."}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "teethmark_record",
        "description": ("Create the ledger of planted bugs the tests catch. Only for a project with no ledger, "
                        "or when the project owner has explicitly asked to re-record. Re-recording accepts a "
                        "weaker suite as the new baseline, so do not use it to clear a BLOCK."),
        "inputSchema": {"type": "object", "properties": {
            "root": _ROOT, "fast": _FAST,
            "budget": {"type": "integer", "description": "Stop planting new bugs after this many seconds (default 120)."},
            "python": {"type": "string", "description": "Interpreter that runs the tests."},
            "confirm_rerecord": {"type": "boolean",
                                 "description": "Required to overwrite an existing ledger; only with the owner's permission."}}},
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False},
    },
]


def _engine(args: Dict[str, Any], **extra: Any) -> Engine:
    root = os.path.abspath(args.get("root") or ".")
    over: Dict[str, Any] = {"python": args.get("python") or None}
    over.update(extra)
    return Engine(root, load_config(root, over))


def _text(text: str, error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if name == "teethmark_check":
            rep = _engine(args).check(baseline_ref=args.get("baseline_ref") or "", full=bool(args.get("full")))
            return _text(report.check_text(rep), error=rep["verdict"] == "BLOCK")
        if name == "teethmark_show":
            res = _engine(args).show()
            return _text(report.show_text(res, bool(args.get("survivors"))))
        if name == "teethmark_record":
            if os.environ.get("TEETHMARK_MCP_READONLY"):
                return _text("teethmark_record is disabled on this server (TEETHMARK_MCP_READONLY is set). "
                             "Ask the project owner to run `teethmark record`.", error=True)
            root = os.path.abspath(args.get("root") or ".")
            if os.path.exists(os.path.join(root, LEDGER)) and not args.get("confirm_rerecord"):
                return _text("A ledger already exists. Re-recording would accept the current tests as the new "
                             "baseline, which is the project owner's decision. If they have asked for it, call again "
                             "with confirm_rerecord=true. To see whether tests got weaker, use teethmark_check.",
                             error=True)
            extra: Dict[str, Any] = {"budget": args.get("budget") or FIRST_RUN_BUDGET}
            if args.get("fast", True):
                extra.update({"per_function": 1, "max_mutants": 150})
            return _text(report.record_text(_engine(args, **extra).record()))
        return _text("Unknown tool: %s" % name, error=True)
    except TeethmarkError as exc:
        return _text(str(exc), error=True)
    except Exception as exc:  # a tool must never take the server down
        return _text("teethmark failed: %s: %s" % (type(exc).__name__, exc), error=True)


def handle(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the response for one request, or None for a notification."""
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None  # notifications (initialized, cancelled, ...) need no reply

    def ok(result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code: int, text: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": "teethmark", "version": __version__}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if name not in {t["name"] for t in TOOLS}:
            return err(-32602, "Unknown tool: %s" % name)
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return err(-32602, "arguments must be an object")
        return ok(call_tool(name, args))
    return err(-32601, "Method not found: %s" % method)


def serve(stdin: Optional[IO[str]] = None, stdout: Optional[IO[str]] = None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout

    def send(obj: Dict[str, Any]) -> None:
        stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
        stdout.flush()

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if isinstance(msg, list):
            replies = [r for r in (handle(m) for m in msg if isinstance(m, dict)) if r]
            if replies:
                stdout.write(json.dumps(replies, separators=(",", ":")) + "\n")
                stdout.flush()
            continue
        if not isinstance(msg, dict):
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            continue
        reply = handle(msg)
        if reply is not None:
            send(reply)
    return 0


def main() -> int:
    return serve()


if __name__ == "__main__":
    sys.exit(main())
