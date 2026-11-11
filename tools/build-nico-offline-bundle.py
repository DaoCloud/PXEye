#!/usr/bin/env python3
"""Compatibility entry point; the maintained builder lives in offline-build/."""
from pathlib import Path
import runpy
import sys

directory = Path(__file__).resolve().parents[1] / 'offline-build'
sys.path.insert(0, str(directory))
runpy.run_path(str(directory / 'build.py'), run_name='__main__')
