"""Zero-config default, time budget, hook gate, init and the MCP server."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys

import pytest

from teethmark import mcp
from teethmark.cli import main
from teethmark.engine import LEDGER, Engine, load_config, read_ledger
from teethmark.init import END, START, init_project

SHOP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "shop")
TESTS = "tests/test_cart.py"
CART = "shop/cart.py"


@pytest.fixture
def shop(tmp_path):
    root = tmp_path / "shop"
    shutil.copytree(SHOP, root, ignore=shutil.ignore_patterns(".teethmark", "__pycache__"))
    return root


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    root = tmp_path_factory.mktemp("rec") / "shop"
    shutil.copytree(SHOP, root, ignore=shutil.ignore_patterns(".teethmark", "__pycache__"))
    Engine(str(root), load_config(str(root), {"python": sys.executable, "per_function": 6})).record()
    return root


@pytest.fixture
def ledgered(recorded, tmp_path):
    root = tmp_path / "ledgered"
    shutil.copytree(recorded, root)
    return root


def edit(root, rel, old, new):
    path = os.path.join(str(root), rel)
    text = open(path, encoding="utf-8").read()
    assert old in text, old
    open(path, "w", encoding="utf-8").write(text.replace(old, new))


def run(*args):
    return main(list(args))


# ------------------------------------------------------------------ zero config
def test_bare_command_records_on_first_use_then_checks(shop, capsys):
    argv = ["--root", str(shop), "--quiet", "--python", sys.executable]
    assert run(*argv) == 0
    out = capsys.readouterr().out
    assert "Recorded" in out and "First recording done" in out
    assert (shop / LEDGER).exists()
    ledger, _ = read_ledger(str(shop))
    assert max(len(u["mutants"]) for u in ledger["units"].values()) <= 1   # first run is the fast pass
    assert run(*argv) == 0
    assert "PASS" in capsys.readouterr().out    # second run checks


def test_bare_command_blocks_after_weakening(ledgered, capsys):
    edit(ledgered, TESTS, "assert line_total(1.0, 10) == 9.0", "assert line_total(1.0, 10) > 0")
    edit(ledgered, TESTS, "assert line_total(2.0, 10) == 18.0", "assert line_total(2.0, 10) > 0")
    assert run("--root", str(ledgered), "--quiet", "--python", sys.executable) == 1
    assert "BLOCK" in capsys.readouterr().out


def test_version_and_help(capsys):
    with pytest.raises(SystemExit) as exc:
        run("--version")
    assert exc.value.code == 0 and "teethmark" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        run("--help")
    text = capsys.readouterr().out
    assert "gate" in text and "init" in text and "mcp" in text


# ----------------------------------------------------------------- fast + budget
def test_fast_flag_means_one_bug_per_function(shop):
    assert run("record", "--fast", "--root", str(shop), "--quiet", "--python", sys.executable) == 0
    ledger, _ = read_ledger(str(shop))
    assert all(len(u["mutants"]) == 1 for u in ledger["units"].values())


def test_explicit_numbers_beat_fast(shop):
    run("record", "--fast", "--per-function", "2", "--root", str(shop), "--quiet", "--python", sys.executable)
    ledger, _ = read_ledger(str(shop))
    assert max(len(u["mutants"]) for u in ledger["units"].values()) == 2


def test_budget_stops_planting_and_says_so(tmp_path):
    root = tmp_path / "slow"
    (root / "tests").mkdir(parents=True)
    (root / "calc.py").write_text("".join("def f%d(x):\n    return x + %d\n\n\n" % (i, i + 1) for i in range(12)))
    (root / "tests" / "test_calc.py").write_text(
        "import time\nfrom calc import *\n\n\ndef test_all():\n    time.sleep(0.4)\n"
        + "".join("    assert f%d(1) == %d\n" % (i, i + 2) for i in range(12)))
    cfg = load_config(str(root), {"python": sys.executable, "per_function": 1, "workers": 1, "budget": 2})
    res = Engine(str(root), cfg).record()
    assert res["skipped"] > 0 and res["mutants"] + res["skipped"] >= 12
    assert any("Stopped after the 2s budget" in w for w in res["warnings"])
    ledger, _ = read_ledger(str(root))
    assert sum(len(u["mutants"]) for u in ledger["units"].values()) == res["mutants"]   # skipped are not recorded
    # again with no budget: the finished work is reused and the rest is added
    cfg = load_config(str(root), {"python": sys.executable, "per_function": 1, "workers": 2})
    full = Engine(str(root), cfg).record()
    assert full["skipped"] == 0 and full["mutants"] == 12 and full["reused"] >= res["mutants"] - 1


# -------------------------------------------------------------------------- gate
def test_gate_is_silent_and_zero_when_nothing_got_weaker(ledgered, capsys):
    assert run("gate", "--root", str(ledgered), "--python", sys.executable) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_gate_blocks_with_exit_2_and_the_proof_on_stderr(ledgered, capsys):
    edit(ledgered, TESTS, "assert line_total(1.0, 10) == 9.0", "assert line_total(1.0, 10) > 0")
    edit(ledgered, TESTS, "assert line_total(2.0, 10) == 18.0", "assert line_total(2.0, 10) > 0")
    assert run("gate", "--root", str(ledgered), "--python", sys.executable) == 2
    err = capsys.readouterr().err
    assert "BLOCK" in err and "Proof 1" in err and "shop/cart.py" in err


def test_gate_does_nothing_without_a_ledger(shop, capsys):
    assert run("gate", "--root", str(shop)) == 0
    assert "no ledger yet" in capsys.readouterr().err


def test_gate_fails_open_on_errors_unless_strict(ledgered, capsys):
    edit(ledgered, TESTS, "assert shipping(50) == 0.0", "assert shipping(50) >= 0")
    edit(ledgered, CART, "    return round(total, 2)\n\n\ndef cart_total", "    return 0\n\n\ndef cart_total")
    argv = ["gate", "--root", str(ledgered), "--python", sys.executable]
    assert run(*argv) == 0
    assert "must pass on clean code" in capsys.readouterr().err
    assert run(*argv, "--strict") == 2


# -------------------------------------------------------------------------- init
def test_init_creates_everything_once_and_is_idempotent(tmp_path):
    (tmp_path / "src").mkdir()
    first = {d["file"]: d["result"] for d in init_project(str(tmp_path))}
    assert first == {".teethmark/config.json": "created", "AGENTS.md": "created",
                     ".github/workflows/teethmark.yml": "created"}
    assert json.loads((tmp_path / ".teethmark" / "config.json").read_text()) == {"source": ["src"]}
    wf = (tmp_path / ".github" / "workflows" / "teethmark.yml").read_text()
    assert "gaganramesh-git/teethmark@v" in wf and "${{ github.base_ref }}" in wf
    second = {d["file"]: d["result"] for d in init_project(str(tmp_path))}
    assert second[".teethmark/config.json"].startswith("kept") and second["AGENTS.md"] == "unchanged"
    assert second[".github/workflows/teethmark.yml"].startswith("kept")


def test_init_appends_to_existing_agent_rules_without_touching_them(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# House rules\n\nBe kind.\n")
    assert init_project(str(tmp_path))[1]["result"] == "appended"
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("# House rules\n\nBe kind.\n") and text.count(START) == 1 and END in text
    (tmp_path / "AGENTS.md").write_text(text.replace("teethmark check", "teethmark OLD"))
    assert init_project(str(tmp_path))[1]["result"] == "updated"
    assert "teethmark OLD" not in (tmp_path / "AGENTS.md").read_text()


def test_init_flags_and_git_hook(tmp_path):
    res = {d["file"]: d["result"] for d in init_project(str(tmp_path), ci=False, agents=False, git_hook=True)}
    assert set(res) == {".teethmark/config.json", ".git/hooks/pre-push"}
    assert res[".git/hooks/pre-push"].startswith("skipped")
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    res = {d["file"]: d["result"] for d in init_project(str(tmp_path), ci=False, agents=False, git_hook=True)}
    hook = tmp_path / ".git" / "hooks" / "pre-push"
    assert res[".git/hooks/pre-push"] == "created" and os.access(str(hook), os.X_OK)
    assert "teethmark gate" in hook.read_text()
    hook.write_text("#!/bin/sh\necho mine\n")
    again = {d["file"]: d["result"] for d in init_project(str(tmp_path), ci=False, agents=False, git_hook=True)}
    assert again[".git/hooks/pre-push"].startswith("kept") and "mine" in hook.read_text()


def test_init_command_prints_a_summary(tmp_path, capsys):
    assert run("init", "--root", str(tmp_path), "--no-ci") == 0
    out = capsys.readouterr().out
    assert "AGENTS.md" in out and "teethmark.yml" not in out and "run `teethmark` once" in out


# --------------------------------------------------------------------------- MCP
def rpc(*messages):
    out = io.StringIO()
    mcp.serve(io.StringIO("".join(json.dumps(m) + "\n" for m in messages)), out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_mcp_handshake_and_tool_list():
    replies = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05", "capabilities": {}}},
                  {"jsonrpc": "2.0", "method": "notifications/initialized"},
                  {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                  {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert [r["id"] for r in replies] == [1, 2, 3]            # the notification gets no reply
    init = replies[0]["result"]
    assert init["protocolVersion"] == "2024-11-05" and init["serverInfo"]["name"] == "teethmark"
    assert init["capabilities"] == {"tools": {}}
    tools = {t["name"]: t for t in replies[2]["result"]["tools"]}
    assert set(tools) == {"teethmark_check", "teethmark_show", "teethmark_record"}
    assert tools["teethmark_check"]["annotations"]["readOnlyHint"] is True
    assert tools["teethmark_record"]["annotations"]["destructiveHint"] is True
    assert all(t["inputSchema"]["type"] == "object" for t in tools.values())


def test_mcp_unknown_protocol_falls_back_to_newest():
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert r[0]["result"]["protocolVersion"] == mcp.PROTOCOLS[0]


def test_mcp_errors_are_json_rpc_errors():
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "nope"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope"}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "teethmark_show", "arguments": 5}})
    assert [x["error"]["code"] for x in r] == [-32601, -32602, -32602]
    out = io.StringIO()
    mcp.serve(io.StringIO("not json\n\n5\n"), out)
    codes = [json.loads(l)["error"]["code"] for l in out.getvalue().splitlines()]
    assert codes == [-32700, -32600]


def call(name, **arguments):
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return r[0]["result"]


def test_mcp_check_passes_then_reports_a_block(ledgered):
    ok = call("teethmark_check", root=str(ledgered), python=sys.executable)
    assert ok["isError"] is False and ok["content"][0]["text"].startswith("PASS")
    edit(ledgered, TESTS, "assert line_total(1.0, 10) == 9.0", "assert line_total(1.0, 10) > 0")
    edit(ledgered, TESTS, "assert line_total(2.0, 10) == 18.0", "assert line_total(2.0, 10) > 0")
    bad = call("teethmark_check", root=str(ledgered), python=sys.executable)
    assert bad["isError"] is True and "BLOCK" in bad["content"][0]["text"] and "Proof 1" in bad["content"][0]["text"]


def test_mcp_show_lists_survivors(ledgered):
    text = call("teethmark_show", root=str(ledgered), survivors=True)["content"][0]["text"]
    assert "planted bugs" in text and "Bugs no test catches" in text


def test_mcp_check_without_a_ledger_is_a_clean_error(shop):
    out = call("teethmark_check", root=str(shop))
    assert out["isError"] and "No ledger yet" in out["content"][0]["text"]


def test_mcp_record_refuses_to_overwrite_and_can_be_disabled(ledgered, shop, monkeypatch):
    refused = call("teethmark_record", root=str(ledgered))
    assert refused["isError"] and "confirm_rerecord" in refused["content"][0]["text"]
    monkeypatch.setenv("TEETHMARK_MCP_READONLY", "1")
    off = call("teethmark_record", root=str(shop))
    assert off["isError"] and "disabled" in off["content"][0]["text"] and not (shop / LEDGER).exists()
    off2 = call("teethmark_record", root=str(ledgered), confirm_rerecord=True)
    assert off2["isError"] and "disabled" in off2["content"][0]["text"]


def test_mcp_record_creates_a_ledger_and_allows_confirmed_rerecord(shop):
    out = call("teethmark_record", root=str(shop), python=sys.executable)
    assert out["isError"] is False and "Recorded" in out["content"][0]["text"]
    assert (shop / LEDGER).exists()
    again = call("teethmark_record", root=str(shop), python=sys.executable, confirm_rerecord=True, fast=False)
    assert again["isError"] is False


def test_mcp_as_a_real_subprocess(ledgered):
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "teethmark_check", "arguments": {"root": str(ledgered), "python": sys.executable}}}]
    env = dict(os.environ, PYTHONPATH=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    p = subprocess.run([sys.executable, "-m", "teethmark", "mcp"], input="".join(json.dumps(m) + "\n" for m in msgs),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env, timeout=120)
    lines = [json.loads(l) for l in p.stdout.splitlines()]
    assert p.returncode == 0 and [l["id"] for l in lines] == [1, 2]
    assert lines[1]["result"]["content"][0]["text"].startswith("PASS")


def test_a_relative_python_path_is_resolved_against_the_caller(shop, monkeypatch, tmp_path):
    link = tmp_path / "py"
    os.symlink(sys.executable, str(link))
    monkeypatch.chdir(tmp_path)
    assert run("record", "--fast", "--root", str(shop), "--python", "./py", "--quiet") == 0


def test_source_can_name_a_single_file(shop):
    from teethmark.project import scan
    assert set(scan(str(shop), source=["shop/cart.py"]).sources) == {"shop/cart.py"}
    assert set(scan(str(shop), source=["shop"]).sources) == {"shop/cart.py", "shop/__init__.py"}
    assert scan(str(shop), source=["sho"]).sources == {}      # a prefix of a name is not a match
