#!/usr/bin/env python3
"""Create an operator authentication file, preserving any existing password."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
p=argparse.ArgumentParser(description=__doc__);p.add_argument('path',type=Path);a=p.parse_args();path=a.path.resolve()
os.umask(0o077);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.parent.chmod(0o700)
if path.exists():
    assert re.fullmatch('[0-9a-f]{64}',json.loads(path.read_text()).get('password_sha256','')),'Existing file invalid; stopped'
    path.chmod(0o600);print('AUTH_PRESERVED')
else:
    password=getpass.getpass('PXEye password: ');confirmation=getpass.getpass('Repeat password: ')
    assert password and password==confirmation,'Passwords are empty/different'
    with path.open('x') as stream:json.dump({'password_sha256':hashlib.sha256(password.encode()).hexdigest()},stream);stream.write('\n')
    print('AUTH_CREATED_0600')
