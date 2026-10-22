#!/usr/bin/env python3
"""Repository entry point for the Vera campaign runner.

The implementation lives in :mod:`vera_cycle.cli`; this file keeps the
operator-facing path (``python3 neutrino_cycle.py``) stable across the package
reorganisation. Run without arguments for the interactive wizard.
"""
from __future__ import annotations

import sys

from vera_cycle.cli import BASE, main

__all__ = ["BASE", "main"]


if __name__ == "__main__":
    sys.exit(main())
