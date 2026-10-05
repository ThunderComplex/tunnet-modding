#!/usr/bin/env python3
"""Shared, user-configurable path resolution for the Tunnet analysis scripts.

The game executable and output directory are never hardcoded. Resolution order:

  exe:   --exe PATH   ->   $TUNNET_EXE   ->   ./tunnet.exe
         -> <repo>/tunnet.exe   -> <repo>/game/tunnet.exe
  data:  --data DIR   ->   $TUNNET_DATA  -> <repo>/data

Every script imports this module and uses `common_parser()` so the flags work
uniformly, e.g.:

    python analysis/xref.py --exe "C:/Games/Tunnet/tunnet.exe" "pattern"
    TUNNET_EXE=/path/to/tunnet.exe python analysis/scan_paths.py
"""
import argparse
import os
import sys
from pathlib import Path

# Repository root = parent of this file's directory.
REPO = Path(__file__).resolve().parent.parent


def _default_exe_candidates():
    return [
        Path.cwd() / "tunnet.exe",
        REPO / "tunnet.exe",
        REPO / "game" / "tunnet.exe",
    ]


def resolve_exe(explicit=None) -> Path:
    cand = explicit or os.environ.get("TUNNET_EXE")
    if cand:
        p = Path(cand)
        if not p.is_file():
            sys.exit(f"error: tunnet.exe not found at {p}")
        return p
    for p in _default_exe_candidates():
        if p.is_file():
            return p
    sys.exit(
        "error: tunnet.exe not found. Pass --exe PATH or set TUNNET_EXE "
        "(defaults checked: ./tunnet.exe, <repo>/tunnet.exe)"
    )


def resolve_data(explicit=None) -> Path:
    cand = explicit or os.environ.get("TUNNET_DATA")
    d = Path(cand) if cand else REPO / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def common_parser(description="", positional=None):
    """Argparse parser with --exe/--data plus an optional positional argument.

    positional: None, or a dict with keys: name, nargs, help, type.
    """
    p = argparse.ArgumentParser(description=description)
    p.add_argument(
        "--exe",
        default=None,
        help="path to tunnet.exe (or set TUNNET_EXE)",
    )
    p.add_argument(
        "--data",
        default=None,
        help="data/output directory (or set TUNNET_DATA)",
    )
    if positional:
        kwargs = {
            "nargs": positional.get("nargs", "*"),
            "help": positional.get("help", ""),
        }
        if positional.get("type"):
            kwargs["type"] = positional["type"]
        p.add_argument(positional.get("name", "args"), **kwargs)
    return p
