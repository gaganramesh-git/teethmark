"""Find source files, test files and the shape of each test in a project."""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import os
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".tox", ".nox", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".eggs", ".teethmark",
    ".idea", ".vscode", "htmlcov",
}
TEST_DIRS = {"tests", "test", "testing"}
ROOT_CONFIG = {"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}
DEFAULT_EXCLUDE = ["setup.py", "noxfile.py", "fabfile.py", "docs/*", "*/migrations/*"]


def _ignored_dir(parent: str, name: str) -> bool:
    if name in IGNORE_DIRS or name.endswith(".egg-info"):
        return True
    return os.path.exists(os.path.join(parent, name, "pyvenv.cfg"))


def is_test_module(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(name, "test_*.py") or fnmatch.fnmatch(name, "*_test.py")


def is_test_side(rel: str) -> bool:
    parts = rel.split("/")
    return (any(p in TEST_DIRS for p in parts[:-1]) or is_test_module(rel)
            or parts[-1] == "conftest.py")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


@dataclass
class Project:
    root: str
    sources: Dict[str, bytes] = field(default_factory=dict)     # rel path -> content
    test_files: Dict[str, str] = field(default_factory=dict)    # test module -> hash
    shared_hash: str = ""                                       # conftest, helpers, data, config
    tests: Dict[str, Dict[str, int]] = field(default_factory=dict)  # test id -> shape


def scan(root: str, source: Sequence[str] = (), exclude: Sequence[str] = ()) -> Project:
    """Classify every file under ``root``.

    ``source``: optional path prefixes; when given, only files under them are
    mutated. ``exclude``: fnmatch patterns of files that are never mutated.
    """
    proj = Project(root)
    exclude = list(exclude) + DEFAULT_EXCLUDE
    prefixes = [p.strip("/") for p in source if p.strip("/")]
    shared = hashlib.sha256()
    for parent, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not _ignored_dir(parent, d))
        for name in sorted(files):
            full = os.path.join(parent, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            test_side = is_test_side(rel)
            is_py = name.endswith(".py")
            if not (test_side or is_py or rel in ROOT_CONFIG):
                continue
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            if is_test_module(rel):
                proj.test_files[rel] = _digest(data)
                proj.tests.update(scan_tests(rel, data))
            elif test_side or rel in ROOT_CONFIG:
                shared.update(rel.encode() + b"\0" + data + b"\0")
            elif is_py:
                if prefixes and not any(rel == p or rel.startswith(p + "/") for p in prefixes):
                    continue
                if any(fnmatch.fnmatch(rel, pat) for pat in exclude):
                    continue
                proj.sources[rel] = data
    proj.shared_hash = shared.hexdigest()[:16]
    return proj


def walk_files(root: str):
    """Yield (relative path, full path) for every regular file a copy contains."""
    for parent, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not _ignored_dir(parent, d)]
        for name in files:
            full = os.path.join(parent, name)
            if not os.path.islink(full):
                yield os.path.relpath(full, root).replace(os.sep, "/"), full


def copy_tree(root: str, dst: str) -> None:
    def ignore(parent: str, names: List[str]) -> List[str]:
        return [n for n in names if os.path.isdir(os.path.join(parent, n)) and _ignored_dir(parent, n)]

    shutil.copytree(root, dst, ignore=ignore, symlinks=True)


# -- static shape of tests ---------------------------------------------------
_SKIP_WORDS = ("skip", "xfail")
_RAISES = {"raises", "warns", "deprecated_call"}


def _has_skip(decorators: List[ast.expr]) -> bool:
    return any(w in ast.unparse(d).lower() for d in decorators for w in _SKIP_WORDS)


def _shape(func: ast.AST, inherited_skip: bool) -> Dict[str, int]:
    asserts = trivial = 0
    skip = inherited_skip or _has_skip(func.decorator_list)  # type: ignore[attr-defined]
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            asserts += 1
            if isinstance(node.test, ast.Constant) and node.test.value:
                trivial += 1
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name.startswith("assert") or name in _RAISES:
                asserts += 1
            elif name in ("skip", "skipTest", "xfail") and node in [
                    getattr(s, "value", None) for s in func.body]:  # type: ignore[attr-defined]
                skip = True  # unconditional skip at the top level of the test body
    return {"asserts": asserts, "trivial": trivial, "skip": int(skip)}


def scan_tests(rel: str, data: bytes) -> Dict[str, Dict[str, int]]:
    """Map pytest-style test ids to a small description of each test."""
    try:
        tree = ast.parse(data.decode("utf-8-sig"))
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return {}
    out: Dict[str, Dict[str, int]] = {}

    def visit(body: List[ast.stmt], prefix: str, skip: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                out[prefix + node.name] = _shape(node, skip)
            elif isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + "::", skip or _has_skip(node.decorator_list))

    visit(tree.body, rel + "::", False)
    return out
