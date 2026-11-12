"""Adapt a containerd export and downloaded Charts to the existing packager."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import chart_sources

HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME.parent / 'material-prepare'))
import containerd_export
import prepared


def configuration(path):
    value = json.loads(path.read_text())
    prepared.require({'work_directory'} <= set(value) <= {'work_directory', 'sources', 'tools'}, 'Use work_directory, optional sources and tools')
    work = Path(value['work_directory']).expanduser()
    prepared.require(work.is_absolute(), 'work_directory must be absolute or start with ~/')
    value['work_directory'] = work.resolve()
    prepared.require(not value['work_directory'].is_relative_to(HOME.parents[1]) and
                     not any(c in str(work) for c in ',\n\r'), 'Keep work_directory outside the checkout, without commas/newlines')
    source = value.setdefault('sources', {})
    prepared.require(set(source) <= {'charts', 'materials', 'images'}, 'Unknown packaging source fields')
    chart_sources.settings(source.get('charts'))
    materials = source.setdefault('materials', {})
    prepared.require(set(materials) <= {'aarch64', 'apt', 'bfb'}, 'Unknown material group')
    for key, raw in list(materials.items()):
        root = Path(raw).expanduser()
        materials[key] = str((path.parent / root).resolve() if not root.is_absolute() else root.resolve())
    tools = {'docker': 'docker', 'helm': 'helm', 'relok8s': None} | value.get('tools', {})
    prepared.require(set(tools) == {'docker', 'helm', 'relok8s'}, 'Unknown packaging tools')
    value['tools'] = tools
    return value


def inputs(value):
    work = value['work_directory']
    source = work / 'offline-images'
    descriptor = json.loads((source / 'export.json').read_text())
    prepared.require(descriptor.get('kind') == 'containerd-image-export' and descriptor.get('complete'), 'Complete step-one export required')
    recipe = json.loads((HOME.parent / 'material-prepare/recipe-e703.json').read_text())
    roles = {r['kind']: r['reference'] for r in recipe['images'] if r['kind'] in ('ui', 'bootstrap')}
    overrides = value['sources'].get('images', {})
    prepared.require(set(overrides) <= set(roles), 'Only ui and bootstrap image role overrides are supported')
    roles.update(overrides)
    rows = json.loads((source / 'manifests/images-lock.json').read_text())
    refs = {r['image'] for r in rows}
    prepared.require(len(refs) == len(rows) and all(ref in refs for ref in roles.values()),
                     'Export must contain the configured UI/bootstrap references; set sources.images to their exact references')
    groups = [r for r in recipe['materials'] if r['group'] in value['sources']['materials']]
    for row in groups:
        path = prepared.relative(Path(value['sources']['materials'][row['group']]), row['target'])
        prepared.require(path.is_file() and path.stat().st_size == row['bytes'], 'Missing material source: ' + str(path))
    return source, descriptor, rows, roles, groups


def plan(value):
    source, _, rows, _, groups = inputs(value)
    print('PACKAGE_PLAN', json.dumps({'image_export': str(source), 'images': len(rows),
          'chart_sources': chart_sources.settings(value['sources'].get('charts')),
          'repository_charts': ['charts/pxeye', 'deploy/nico-platform'],
          'build_material_images': sorted({r['group'] for r in groups}),
          'output': str(value['work_directory'] / 'output')}, ensure_ascii=False), flush=True)


def prepare(value, h):
    b = h.b
    work = value['work_directory']
    b.require(not work.is_relative_to(h.REPO), 'Keep work_directory outside the checkout')
    source, descriptor, rows, roles, groups = inputs(value)
    containerd_export.verify_output(source, descriptor['identity'])
    charts = chart_sources.prepare(work, value['sources'].get('charts'), b, helm=value['tools']['helm'])
    helm = shutil.which(value['tools']['helm'])
    b.require(helm, 'Helm is required to prepare packaging input')
    for row in groups:
        material = prepared.relative(Path(value['sources']['materials'][row['group']]), row['target'])
        b.require(b.sha(material) == row['sha256'], 'Material source checksum differs: ' + str(material))
    identity = hashlib.sha256(json.dumps({'export': b.sha(source / 'export.json'),
                  'charts': b.sha(charts / 'sources.json'), 'roles': roles, 'groups': groups,
                  'helm': b.sha(helm), 'adapter': b.sha(Path(__file__))}, sort_keys=True).encode()).hexdigest()
    root = work / 'package-input' / identity[:24]
    include = {key: key in value['sources']['materials'] for key in ('aarch64', 'apt', 'bfb')}
    if root.exists():
        prepared.verify(root, kinds=('nico-package-input',))
    else:
        root.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.input-', dir=root.parent))
        try:
            h.unpack_oci(source / 'images/nico-amd64.oci.tar', stage / 'images/layout')
            images = []
            for row in rows:
                kind = next((role for role, ref in roles.items() if ref == row['image']), 'core')
                images.append({'image': row['image'], 'digest': row.get('amd64_manifest') or row['digest'], 'kind': kind})
            shutil.copytree(charts / 'deployment', stage / 'deployment')
            for row in groups:
                target = prepared.relative(stage, row['path']); target.parent.mkdir(parents=True, exist_ok=True)
                original = prepared.relative(Path(value['sources']['materials'][row['group']]), row['target'])
                shutil.copyfile(original, target)
            (stage / 'tools').mkdir(); shutil.copyfile(helm, stage / 'tools/helm'); (stage / 'tools/helm').chmod(0o755)
            b.dump(stage / 'manifests/images-lock.json', images)
            b.dump(stage / 'manifests/materials.json', [])
            b.dump(stage / 'prepared.json', {'schema_version': 1, 'kind': 'nico-package-input', 'complete': True,
                   'include': include, 'image_roles': roles, 'raw_material_groups': sorted(value['sources']['materials']),
                   'export_identity': descriptor['identity'], 'fingerprint': identity})
            prepared.inventory(stage); prepared.verify(stage, kinds=('nico-package-input',))
            stage.rename(root)
        except BaseException:
            print('PACKAGE_INPUT_FAILED; staging retained at', stage, flush=True)
            raise
    return {'schema_version': 1, 'materials_bundle': root, 'output_root': work / 'output',
            'bundle_id': 'pxeye-nico-offline', 'include': include, 'tools': value['tools']}
