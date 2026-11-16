#!/usr/bin/env bash
# 20-second demo: record a ledger, weaken a test the way an agent would, get blocked.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"
cp -R "$here/shop" "$work/shop"
cd "$work/shop"
export PYTHONPATH="$here/..${PYTHONPATH:+:$PYTHONPATH}"
tm() { python3 -m teethmark "$@" --quiet; }

echo "== 1. Record which planted bugs the tests catch"
tm record --fresh
echo
echo "== 2. 'Fix' a failing build the lazy way: loosen two assertions"
python3 - <<'EOF'
p = "tests/test_cart.py"
s = open(p).read()
s = s.replace("assert line_total(1.0, 10) == 9.0", "assert line_total(1.0, 10) > 0")
s = s.replace("assert line_total(2.0, 10) == 18.0", "assert line_total(2.0, 10) > 0")
open(p, "w").write(s)
EOF
python3 -m pytest -q 2>&1 | tail -1
echo "   (tests still green, same number of tests, same coverage)"
echo
echo "== 3. teethmark check"
tm check
echo "exit code: $?"
