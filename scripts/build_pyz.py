"""Build the single-file teethmark.pyz that ships inside the agent skill."""
from __future__ import annotations

import os
import shutil
import tempfile
import zipapp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "skills", "teethmark", "scripts", "teethmark.pyz")


def main() -> None:
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copytree(os.path.join(ROOT, "teethmark"), os.path.join(tmp, "teethmark"),
                        ignore=shutil.ignore_patterns("__pycache__", "__main__.py"))
        zipapp.create_archive(tmp, TARGET, interpreter="/usr/bin/env python3", main="teethmark.cli:main")
    print("built", os.path.relpath(TARGET, ROOT), os.path.getsize(TARGET), "bytes")


if __name__ == "__main__":
    main()
