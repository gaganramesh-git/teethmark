"""Repository hygiene: the agent rule copies agree, manifests are valid JSON, versions match,
the shipped skill binary is current, and a stated naming requirement holds across every file."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile

from teethmark import __version__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", "dist", "build", ".teethmark"}
# Built from fragments so this file does not contain the words it forbids.
FORBIDDEN = re.compile(b"cl" + b"aude|anthr" + b"opic", re.I)


def test_rule_copies_are_in_sync():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "sync_rules.py"), "--check"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    assert r.returncode == 0, r.stdout


def test_manifests_parse_and_carry_the_same_version():
    paths = [".codex-plugin/plugin.json", ".github/plugin/plugin.json", ".github/plugin/marketplace.json",
             ".kimi-plugin/plugin.json", "gemini-extension.json", ".agents/plugins/marketplace.json"]
    for rel in paths:
        data = json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))
        assert data["name"] == "teethmark", rel
        if "version" in data:
            assert data["version"] == __version__, rel


def test_packaged_version_matches_pyproject():
    text = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert 'version = "%s"' % __version__ in text


def test_the_shipped_skill_binary_is_current_and_runs():
    pyz = os.path.join(ROOT, "skills", "teethmark", "scripts", "teethmark.pyz")
    r = subprocess.run([sys.executable, pyz, "--version"], stdout=subprocess.PIPE, universal_newlines=True)
    assert r.stdout.strip() == "teethmark " + __version__
    with zipfile.ZipFile(pyz) as z:
        shipped = {n: z.read(n) for n in z.namelist() if n.endswith(".py") and n != "__main__.py"}
    assert shipped
    for name, data in shipped.items():
        assert data == open(os.path.join(ROOT, name), "rb").read(), "%s is stale: run scripts/build_pyz.py" % name


def test_the_forbidden_name_appears_nowhere():
    hits = []
    for parent, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files + dirs:
            if FORBIDDEN.search(name.encode()):
                hits.append(os.path.join(parent, name))
        for name in files:
            path = os.path.join(parent, name)
            if path.endswith(".pyz"):
                with zipfile.ZipFile(path) as z:
                    blobs = [z.read(n) for n in z.namelist()]
            else:
                blobs = [open(path, "rb").read()]
            if any(FORBIDDEN.search(b) for b in blobs):
                hits.append(path)
    assert not hits, hits
