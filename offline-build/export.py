#!/usr/bin/env python3
"""Export committed build sources and one explicit configuration as a standalone kit."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]

def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args])

def safe(value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Unsafe source path: ' + value)
    return value

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--destination', required=True, type=Path)
p.add_argument('--revision')
p.add_argument('--config', type=Path)
p.add_argument('--site-config', type=Path)
p.add_argument('--source-bundle')
p.add_argument('--output-root')
a = p.parse_args()
rev = a.revision or git('rev-parse', 'HEAD').decode().strip()
if not re.fullmatch('[0-9a-f]{40}', rev):
    raise SystemExit('A full committed source revision is required')
config = json.loads(a.config.read_text() if a.config else git('show', rev + ':offline-build/build-config.example.json'))
if a.site_config and config.get('schema_version') in (3, 4):
    raise SystemExit('Reusable materials have no site inputs; initialize site-config.example.json at the deployment site')
if a.site_config:
    site = json.loads(a.site_config.read_text())
    for purpose in ('ui', 'bootstrap'):
        if any(site[purpose][key] != config['site'][purpose][key] for key in ('tag', 'digest')):
            raise SystemExit('Image changed: update the archive bytes/SHA256 in the full build config, then pass --config')
        path = Path(site[purpose]['archive'])
        site[purpose]['archive'] = str(path if path.is_absolute() else (a.site_config.parent / path).resolve())
    config['site'] = site
if a.source_bundle:config['build']['source_bundle'] = a.source_bundle
if a.output_root:config['build']['output_root'] = a.output_root
output = a.destination.resolve()
if output.exists() or output == REPO or output.is_relative_to(REPO):
    raise SystemExit('Export to a new directory outside the source checkout')
output.parent.mkdir(parents=True, exist_ok=True)
stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.export-', dir=output.parent))
try:
    files = config['files'] if config.get('schema_version') != 4 else json.loads(git('show', rev + ':offline-build/materials-lock.json'))['files']
    mappings = [(s, s) for s in files['repository']]
    mappings += [(r['source'], r['target']) for r in files['toolkit']]
    targets = set()
    for source, target in mappings:
        safe(source);safe(target)
        if target in targets:raise ValueError('Duplicate toolkit output: ' + target)
        targets.add(target)
        mode = git('ls-tree', rev, '--', source).decode().split()[0]
        if mode not in ('100644', '100755'):raise ValueError('Only regular committed files are supported: ' + source)
        dest = stage / target;dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(git('show', rev + ':' + source));dest.chmod(0o755 if mode == '100755' else 0o644)
    (stage / 'build-config.json').write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n')
    (stage / 'source-revision.txt').write_text(rev + '\n')
    result = subprocess.run([__import__('sys').executable, str(stage / 'build.py'), '--config', str(stage / 'build-config.json'), '--plan'], capture_output=True, text=True, timeout=30)
    if result.returncode:raise ValueError(result.stderr)
    (stage / 'FILE-PLAN.txt').write_text(result.stdout)
    stage.rename(output)
    print('BUILD_KIT_EXPORTED', output)
    print(result.stdout.splitlines()[-1])
except BaseException:
    print('Export staging retained:', stage)
    raise
