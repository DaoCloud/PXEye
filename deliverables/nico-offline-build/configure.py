#!/usr/bin/env python3
"""Generate onsite files from a locked generic or legacy builder bundle."""
import sys

sys.dont_write_bytecode = True
from generic import configure_main

if __name__ == '__main__':
    try:
        configure_main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise SystemExit(str(error)) from None
