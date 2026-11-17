"""Render a terminal-style image of the real demo output (assets/demo.svg).

    bash examples/demo.sh 2>/dev/null | python3 scripts/make_demo_svg.py > assets/demo.svg
"""
from __future__ import annotations

import sys
from xml.sax.saxutils import escape

SKIP = ("Ledger:", "Next:")
lines = [l.rstrip("\n") for l in sys.stdin if not l.startswith(SKIP)]
while lines and not lines[-1].strip():
    lines.pop()
lh, w = 21, 860
h = 56 + lh * len(lines) + 24
out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" role="img" '
       'aria-label="Teethmark demo: a weakened test is blocked with proof">' % (w, h, w),
       '<rect width="%d" height="%d" rx="12" fill="#14161a"/>' % (w, h),
       '<circle cx="24" cy="22" r="6" fill="#ff5f56"/><circle cx="44" cy="22" r="6" fill="#ffbd2e"/>'
       '<circle cx="64" cy="22" r="6" fill="#27c93f"/>',
       '<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="14" fill="#d7dae0" xml:space="preserve">']
for i, line in enumerate(lines):
    color = "#d7dae0"
    if line.startswith("BLOCK"):
        color = "#ff6b6b"
    elif line.startswith("==") or line.startswith("Proof"):
        color = "#ffd166" if line.startswith("Proof") else "#7aa2f7"
    elif line.lstrip().startswith("- "):
        color = "#ff8f8f"
    elif line.lstrip().startswith("+ "):
        color = "#8fe388"
    out.append('<text x="24" y="%d" fill="%s">%s</text>' % (56 + lh * i, color, escape(line)))
out.append("</g></svg>")
print("\n".join(out))
