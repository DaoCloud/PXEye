#!/usr/bin/env python3
"""Convenient repository-root entry for the artifact version audit."""
from pathlib import Path
import runpy


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parent / 'tools/version-audit/audit.py'),
                   run_name='__main__')
