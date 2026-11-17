{{/* Installed into the pinned NICo PXE child Chart by the bundle builder. */}}
{{- define "pxeye.pxe.storageLabel" -}}
{{- if .Values.pxeyeStorage.enabled }}
pxeye.io/storage-reader: {{ required "pxeyeStorage.claimName is required" .Values.pxeyeStorage.claimName | quote }}
{{- end }}
{{- end }}

{{- define "pxeye.pxe.affinity" -}}
{{- if .Values.pxeyeStorage.enabled }}
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          pxeye.io/storage-owner: {{ required "pxeyeStorage.ownerRelease is required" .Values.pxeyeStorage.ownerRelease | quote }}
      topologyKey: kubernetes.io/hostname
{{- end }}
{{- end }}

{{- define "pxeye.pxe.materialMount" -}}
{{- if .Values.pxeyeStorage.enabled }}
- name: pxeye-storage
  mountPath: {{ printf "%s/blobs/internal/nico" (trimSuffix "/" .Values.bootArtifacts.servePath) | quote }}
  subPath: http/nico
  readOnly: true
{{- end }}
{{- end }}

{{- define "pxeye.pxe.materialVolume" -}}
{{- if .Values.pxeyeStorage.enabled }}
- name: pxeye-storage
  persistentVolumeClaim:
    claimName: {{ required "pxeyeStorage.claimName is required" .Values.pxeyeStorage.claimName | quote }}
    readOnly: true
{{- end }}
{{- end }}
