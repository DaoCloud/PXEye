"""Kubernetes API access using only the Pod's projected service account."""

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from pxeye.common import atomic_json


class ClusterError(ValueError):
    """A credential-safe Kubernetes failure suitable for the operator."""


class CurrentCluster:
    def __init__(self, settings, directory):
        self.settings = settings
        self.directory = Path(directory)
        self.account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.namespace = (
            settings.get("namespace")
            or os.environ.get("POD_NAMESPACE")
            or (
                (self.account / "namespace").read_text().strip()
                if (self.account / "namespace").exists()
                else "nico-system"
            )
        )
        self.namespaces = list(
            dict.fromkeys([self.namespace] + settings.get("observe_namespaces", []))
        )
        self.host = os.environ.get("KUBERNETES_SERVICE_HOST", "")
        port = os.environ.get("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        if ":" in self.host:
            self.host = "[" + self.host + "]"
        self.server = f"https://{self.host}:{port}"

    @property
    def available(self):
        return bool(self.host and (self.account / "token").is_file())

    def request(self, path, body=None, *, timeout=8, method=None, content_type="application/json"):
        if not self.available:
            raise ClusterError("未取得当前集群身份，请挂载 ServiceAccount 并启用部署权限。")
        context = ssl.create_default_context(cafile=str(self.account / "ca.crt"))
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
        )
        request = urllib.request.Request(
            self.server + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": "Bearer " + (self.account / "token").read_text().strip(),
                "Content-Type": content_type,
            },
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 403:
                raise ClusterError(
                    "集群访问被拒绝，请检查 PXEye ServiceAccount 的 RBAC 权限。"
                ) from None
            raise ClusterError(f"Kubernetes API 返回 HTTP {error.code}。") from None
        except (OSError, ValueError):
            raise ClusterError("无法读取当前 Kubernetes API，请检查服务账户和集群连接。") from None

    @staticmethod
    def path(resource, namespace, name=""):
        group = {
            "deployments": "/apis/apps/v1",
            "statefulsets": "/apis/apps/v1",
            "daemonsets": "/apis/apps/v1",
            "jobs": "/apis/batch/v1",
            "certificates": "/apis/cert-manager.io/v1",
        }.get(resource, "/api/v1")
        return f"{group}/namespaces/{quote(namespace, safe='')}/{resource}" + (
            "/" + quote(name, safe="") if name else ""
        )

    def get(self, resource, name, namespace=None):
        return self.request(self.path(resource, namespace or self.namespace, name))

    def list(self, resource, namespace=None):
        row = self.request(self.path(resource, namespace or self.namespace))
        return (row or {}).get("items", [])

    def create(self, resource, body, namespace=None):
        return self.request(self.path(resource, namespace or self.namespace), body, method="POST")

    def patch(self, resource, name, body, namespace=None):
        return self.request(
            self.path(resource, namespace or self.namespace, name),
            body,
            method="PATCH",
            content_type="application/merge-patch+json",
        )

    def delete(self, resource, name, namespace=None):
        return self.request(self.path(resource, namespace or self.namespace, name), method="DELETE")

    def allowed(self, verb, resource, group="", namespace=None):
        result = self.request(
            "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews",
            {
                "apiVersion": "authorization.k8s.io/v1",
                "kind": "SelfSubjectAccessReview",
                "spec": {
                    "resourceAttributes": {
                        "verb": verb,
                        "resource": resource,
                        "group": group,
                        **({"namespace": namespace} if namespace else {}),
                    }
                },
            },
        )
        return bool((result or {}).get("status", {}).get("allowed"))

    def kubeconfig(self):
        if not self.available:
            raise ClusterError("只能在当前 Kubernetes 集群内执行 Helm 部署。")
        path = self.directory / "kubeconfig.json"
        atomic_json(
            path,
            {
                "apiVersion": "v1",
                "kind": "Config",
                "current-context": "pxeye-current",
                "clusters": [
                    {
                        "name": "current",
                        "cluster": {
                            "server": self.server,
                            "certificate-authority": str(self.account / "ca.crt"),
                        },
                    }
                ],
                "users": [{"name": "pod", "user": {"tokenFile": str(self.account / "token")}}],
                "contexts": [
                    {
                        "name": "pxeye-current",
                        "context": {
                            "cluster": "current",
                            "user": "pod",
                            "namespace": self.namespace,
                        },
                    }
                ],
            },
        )
        return path
