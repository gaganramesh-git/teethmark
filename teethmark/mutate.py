"""Deterministic, formatting-stable mutants for Python source.

A *unit* is a function or method. A *mutant* is one small behavioural change
inside a unit (a planted bug). Mutant ids depend only on the unit's AST, never
on line numbers or formatting, so a ledger entry keeps pointing at the same
planted bug while the file around it is edited.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

PRAGMA = b"pragma: no mutate"
BOM = b"\xef\xbb\xbf"

_CMP = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_BIN = {
    ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
    ast.FloorDiv: ast.Mult, ast.Mod: ast.Mult, ast.Pow: ast.Mult,
}
_AUG = {ast.Add: ast.Sub, ast.Sub: ast.Add}
_QUIET_CALLS = {"print", "debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _sha(text: str, n: int = 12) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


@dataclass
class Site:
    op: str
    lineno: int
    col: int
    end_lineno: int
    end_col: int
    replacement: str
    ordinal: int = 0
    sig: str = ""  # what was changed into what, independent of where it sits
    occ: int = 0   # n-th site with this sig inside the unit


@dataclass
class Unit:
    path: str
    qualname: str
    hash: str
    lineno: int
    sites: List[Site] = field(default_factory=list)

    @property
    def key(self) -> str:
        return "%s::%s" % (self.path, self.qualname)


@dataclass
class Mutant:
    id: str
    unit_key: str
    path: str
    op: str
    lineno: int
    before: str
    after: str
    data: bytes  # full mutated file content
    sig: str = ""
    occ: int = 0

    def describe(self) -> Dict[str, object]:
        return {"id": self.id, "op": self.op, "line": self.lineno, "before": self.before,
                "after": self.after, "sig": self.sig, "occ": self.occ}


def _is_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))


def _docstring_node(func: ast.AST) -> Optional[ast.AST]:
    body = getattr(func, "body", None)
    if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and _is_str(body[0].value):
        return body[0]
    return None


def _unit_hash(func: ast.AST) -> str:
    doc = _docstring_node(func)
    parts = [type(func).__name__, func.name, ast.dump(func.args)]  # type: ignore[attr-defined]
    parts += [ast.dump(d) for d in func.decorator_list]  # type: ignore[attr-defined]
    parts += [ast.dump(s) for s in func.body if s is not doc]  # type: ignore[attr-defined]
    return _sha("\n".join(parts), 16)


def _find_functions(tree: ast.Module) -> List[Tuple[str, ast.AST]]:
    out: List[Tuple[str, ast.AST]] = []

    def visit(body: List[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, _FUNCS):
                out.append((prefix + node.name, node))
            elif isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + ".")
            else:
                for name in ("body", "orelse", "finalbody"):
                    sub = getattr(node, name, None)
                    if isinstance(sub, list):
                        visit(sub, prefix)
                for handler in getattr(node, "handlers", []) or []:
                    visit(handler.body, prefix)

    visit(tree.body, "")
    return out


def _gen(node: ast.AST) -> Iterator[Tuple[str, ast.AST, str]]:
    """Yield (operator, node-to-replace, replacement-source) for one AST node."""
    if isinstance(node, ast.Compare) and type(node.ops[0]) in _CMP:
        new = copy.copy(node)
        new.ops = [_CMP[type(node.ops[0])]()] + list(node.ops[1:])
        yield "compare", node, "(" + ast.unparse(new) + ")"
    elif isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        if _is_str(node.left) or _is_str(node.right) or isinstance(node.left, ast.JoinedStr):
            return
        new = copy.copy(node)
        new.op = _BIN[type(node.op)]()
        yield "arith", node, "(" + ast.unparse(new) + ")"
    elif isinstance(node, ast.BoolOp):
        new = copy.copy(node)
        new.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        yield "logic", node, "(" + ast.unparse(new) + ")"
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        yield "drop-not", node, "(" + ast.unparse(node.operand) + ")"
    elif isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            yield "const", node, "False" if v else "True"
        elif isinstance(v, int):
            yield "const", node, str(v + 1)
        elif isinstance(v, float):
            yield "const", node, repr(v + 1.0)
    elif isinstance(node, ast.Return):
        v = node.value
        if v is not None and not (isinstance(v, ast.Constant) and v.value is None):
            yield "return-none", v, "None"
    elif isinstance(node, (ast.If, ast.IfExp)):
        if not isinstance(node.test, ast.Constant):
            yield "negate-if", node.test, "(not (" + ast.unparse(node.test) + "))"
    elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        f = node.value.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name not in _QUIET_CALLS:
            yield "drop-call", node, "pass"
    elif isinstance(node, ast.AugAssign) and type(node.op) in _AUG:
        if _is_str(node.value):
            return
        new = copy.copy(node)
        new.op = _AUG[type(node.op)]()
        yield "aug", node, ast.unparse(new)


def _walk(node: ast.AST, top: bool = True) -> Iterator[ast.AST]:
    """Walk a function in a fixed order, skipping places where a mutation is
    meaningless or unsafe: docstrings, annotations, decorators, f-strings."""
    if isinstance(node, ast.JoinedStr):
        return
    if not top:
        yield node
    if isinstance(node, _FUNCS + (ast.Lambda,)):
        args = node.args
        children: List[ast.AST] = list(args.defaults) + [d for d in args.kw_defaults if d is not None]
        doc = _docstring_node(node)
        body = node.body
        children += [s for s in body if s is not doc] if isinstance(body, list) else [body]
    elif isinstance(node, ast.AnnAssign):
        children = [node.target] + ([node.value] if node.value is not None else [])
    else:
        children = list(ast.iter_child_nodes(node))
    for child in children:
        for n in _walk(child, False):
            yield n


class SourceFile:
    """One parsed source file and the units/mutants it can produce."""

    def __init__(self, path: str, data: bytes) -> None:
        self.path = path
        self.prefix = BOM if data.startswith(BOM) else b""
        self.body = data[len(self.prefix):]
        self.tree = ast.parse(self.body.decode("utf-8"))
        self._dump = ast.dump(self.tree)
        self._lines = self.body.splitlines(keepends=True)
        self._starts: List[int] = []
        pos = 0
        for line in self._lines:
            self._starts.append(pos)
            pos += len(line)
        self.units: List[Unit] = []
        seen: Dict[str, int] = {}
        for qual, node in _find_functions(self.tree):
            seen[qual] = seen.get(qual, 0) + 1
            if seen[qual] > 1:
                qual = "%s#%d" % (qual, seen[qual])
            unit = Unit(path, qual, _unit_hash(node), node.lineno)
            counts: Dict[str, int] = {}
            for n in _walk(node):
                for op, target, repl in _gen(n):
                    if PRAGMA in self._lines[target.lineno - 1]:
                        continue
                    sig = _sha("\0".join([op, ast.unparse(target), repl]))
                    counts[sig] = counts.get(sig, 0) + 1
                    unit.sites.append(Site(op, target.lineno, target.col_offset, target.end_lineno,
                                           target.end_col_offset, repl, len(unit.sites), sig, counts[sig] - 1))
            self.units.append(unit)

    def _id(self, unit: Unit, site: Site) -> str:
        return _sha("\0".join([unit.path, unit.qualname, unit.hash, site.op,
                               str(site.ordinal), site.replacement]))

    def build(self, unit: Unit, site: Site) -> Optional[Mutant]:
        """Splice one site into the file. Returns None if the result is not a
        real change (does not parse, or parses to the same program)."""
        a = self._starts[site.lineno - 1] + site.col
        b = self._starts[site.end_lineno - 1] + site.end_col
        repl = site.replacement.encode("utf-8")
        mutated = self.body[:a] + repl + self.body[b:]
        try:
            if ast.dump(ast.parse(mutated.decode("utf-8"))) == self._dump:
                return None
        except (SyntaxError, ValueError, UnicodeDecodeError):
            return None
        first = self._starts[site.lineno - 1]
        old_end = self._starts[site.end_lineno] if site.end_lineno < len(self._starts) else len(self.body)
        new_end = mutated.find(b"\n", a + len(repl))
        new_end = len(mutated) if new_end < 0 else new_end
        before = self.body[first:old_end].decode("utf-8").rstrip("\r\n")
        after = mutated[first:new_end].decode("utf-8").rstrip("\r\n")
        return Mutant(self._id(unit, site), unit.key, self.path, site.op, site.lineno,
                      before, after, self.prefix + mutated, site.sig, site.occ)

    def _ordered(self, unit: Unit) -> List[Site]:
        """Stable pseudo-random order that interleaves operator kinds, so a
        small sample still covers different kinds of bug."""
        groups: Dict[str, List[Site]] = {}
        for s in sorted(unit.sites, key=lambda s: self._id(unit, s)):
            groups.setdefault(s.op, []).append(s)
        order = sorted(groups, key=lambda op: self._id(unit, groups[op][0]))
        out: List[Site] = []
        i = 0
        while len(out) < len(unit.sites):
            for op in order:
                if i < len(groups[op]):
                    out.append(groups[op][i])
            i += 1
        return out

    def sample(self, unit: Unit, n: int) -> List[Mutant]:
        out: List[Mutant] = []
        for site in self._ordered(unit):
            if len(out) >= n:
                break
            m = self.build(unit, site)
            if m is not None:
                out.append(m)
        return out

    def find(self, unit: Unit, mutant_id: str) -> Optional[Mutant]:
        for site in unit.sites:
            if self._id(unit, site) == mutant_id:
                return self.build(unit, site)
        return None

    def find_sig(self, unit: Unit, sig: str, occ: int) -> Optional[Mutant]:
        """Find the same planted bug in an edited unit: same change to the same
        expression, wherever it now sits."""
        for site in unit.sites:
            if site.sig == sig and site.occ == occ:
                return self.build(unit, site)
        return None


def load(path: str, data: bytes) -> Optional[SourceFile]:
    try:
        return SourceFile(path, data)
    except (SyntaxError, ValueError, UnicodeDecodeError, RecursionError):
        return None
