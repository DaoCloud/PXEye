#!/usr/bin/env python3
"""Compatibility entry point; the maintained builder lives in offline-build/."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parents[1] / 'offline-build/build.py'), run_name='__main__')
