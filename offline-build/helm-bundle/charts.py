"""Generate real, independently installable Charts; no image-only fake workload."""
import copy

import yaml


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def pxeye(root, repo, image):
    """Use the repository Chart as the single source for deployment and packaging."""
    import shutil
    shutil.copytree(repo / 'charts/pxeye', root)
    values_path = root / 'values.yaml'
    values = yaml.safe_load(values_path.read_text())
    values['image'] = image
    write(values_path, yaml.safe_dump(values, sort_keys=False))


def materials(root, images, publisher):
    write(root / 'Chart.yaml', 'apiVersion: v2\nname: nico-materials\nversion: 0.1.0\ntype: application\n')
    write(root / 'values.yaml', yaml.safe_dump({
        'publisherImage': publisher, 'materials': {k: {'image': v} for k, v in images.items()},
        'storageClass': '', 'storage': '30Gi', 'nodeSelector': {}, 'imagePullSecrets': [],
        'service': {'type': 'ClusterIP', 'port': 8080},
    }, sort_keys=False))
    write(root / 'templates/resources.yaml', '''apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ .Release.Name }}
  annotations: {helm.sh/resource-policy: keep}
spec:
  accessModes: [ReadWriteOnce]
  {{- with .Values.storageClass }}
  storageClassName: {{ . | quote }}
  {{- end }}
  resources:
    requests: {storage: {{ .Values.storage | quote }}}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector:
    matchLabels: {app.kubernetes.io/instance: {{ .Release.Name }}}
  template:
    metadata:
      labels: {app.kubernetes.io/instance: {{ .Release.Name }}}
    spec:
      automountServiceAccountToken: false
      nodeSelector: {{ .Values.nodeSelector | toJson }}
      imagePullSecrets: {{ .Values.imagePullSecrets | toJson }}
      securityContext: {runAsNonRoot: true, runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000}
      {{- if .Values.materials }}
      initContainers:
      {{- range $name, $material := .Values.materials }}
        - name: {{ $name }}
          image: {{ $material.image | quote }}
          imagePullPolicy: IfNotPresent
          command: [python3, /publish.py]
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true}
          volumeMounts:
            - {name: materials, mountPath: /materials}
      {{- end }}
      {{- end }}
      containers:
        - name: http
          image: {{ .Values.publisherImage | quote }}
          imagePullPolicy: IfNotPresent
          command: [python3, -m, http.server, "8080", --bind, "0.0.0.0", --directory, /materials]
          ports: [{name: http, containerPort: 8080}]
          readinessProbe:
            httpGet: {path: /, port: http}
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true}
          volumeMounts:
            - {name: materials, mountPath: /materials, readOnly: true}
      volumes:
        - name: materials
          persistentVolumeClaim: {claimName: {{ .Release.Name }}}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
spec:
  type: {{ .Values.service.type }}
  selector: {app.kubernetes.io/instance: {{ .Release.Name }}}
  ports: [{name: http, port: {{ .Values.service.port }}, targetPort: http}]
''')


def merge(base, updates):
    result = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def bind_images(values, mapping):
    """Use local build sources, with rewritable scalar fields for every image."""
    repositories = {k.rsplit(':', 1)[0]: v.rsplit(':', 1)[0] for k, v in mapping.items()}
    hints = []

    def walk(item, path=()):
        if isinstance(item, dict):
            if isinstance(item.get('repository'), str) and isinstance(item.get('tag'), str):
                ref = item['repository'] + ':' + item['tag']
                if ref in mapping:
                    item['repository'], item['tag'] = mapping[ref].rsplit(':', 1)
                    item.pop('digest', None)
                    item.pop('registry', None)
                    prefix = '.' + '.'.join(path)
                    hints.append('{{ ' + prefix + '.repository }}:{{ ' + prefix + '.tag }}')
            for key, child in list(item.items()):
                # The upstream PXE template ranges over this value; map and list
                # have identical element fields. relok8s 0.5.4 cannot hint array indices.
                if key == 'bootArtifactContainers' and isinstance(child, list):
                    child = {str(i): row for i, row in enumerate(child)}
                    item[key] = child
                if isinstance(child, str):
                    if child in mapping:
                        item[key] = mapping[child]
                        hints.append('{{ .' + '.'.join(path + (key,)) + ' }}')
                    elif child in repositories:
                        item[key] = repositories[child]
                else:
                    walk(child, path + (str(key),))
        elif isinstance(item, list):
            if any(isinstance(v, dict) and isinstance(v.get('image'), str) for v in item):
                raise ValueError('Image array needs an explicit relok8s mapping: ' + '.'.join(path))
    walk(values)
    return sorted(set(hints))
