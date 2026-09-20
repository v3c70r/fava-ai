#!/usr/bin/env python3
"""Verify the built wheel contains exactly the expected package files.

Usage:
    python -m build --wheel
    python scripts/check_wheel.py
"""

import glob
import pathlib
import sys
import zipfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

REQUIRED = [
    "fava_ai/__init__.py",
    "fava_ai/FavaAI.js",
    "fava_ai/templates/FavaAI.html",
    "fava_ai/agent/runtime.py",
    "fava_ai/tools/builtin/ledger.py",
]


def main() -> int:
    wheels = sorted(glob.glob(str(REPO_ROOT / "dist" / "*.whl")))
    if not wheels:
        print("No wheel found in dist/. Run `python -m build --wheel` first.")
        return 1

    wheel = wheels[-1]
    names = zipfile.ZipFile(wheel).namelist()

    missing = [name for name in REQUIRED if name not in names]
    if missing:
        print(f"FAIL: missing from wheel: {missing}")
        return 1

    forbidden = [
        name for name in names
        if name.startswith(("tests/", "docs/", "scripts/"))
        or name.endswith(".beancount")
        or "__pycache__" in name
    ]
    if forbidden:
        print(f"FAIL: unexpected files in wheel: {forbidden}")
        return 1

    print(f"OK: {pathlib.Path(wheel).name} contains {len(names)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
