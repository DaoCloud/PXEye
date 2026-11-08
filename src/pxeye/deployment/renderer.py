"""Helm post-renderer for explicit Pod mounts and consistent workload labels."""

import json
import os
import sys
from pathlib import Path

import yaml

INSTANCE = "app.kubernetes.io/instance"


def _align_selectors(objects):
    """Keep Pod identity labels and Chart service/workload selectors consistent."""
    templates = []
    for obj in objects:
        if obj.get("kind") in ("Deployment", "StatefulSet", "DaemonSet"):
            labels = obj["spec"]["template"].get("metadata", {}).get("labels", {}).copy()
            templates.append((labels, obj["metadata"]["name"]))
            selector = obj["spec"].get("selector", {}).get("matchLabels", {})
            if INSTANCE in selector:
                selector[INSTANCE] = obj["metadata"]["name"]
    for obj in objects:
        if obj.get("kind") == "Service":
            selector = obj.get("spec", {}).get("selector", {})
            if INSTANCE not in selector:
                continue
            selected = {
                name
                for labels, name in templates
                if all(labels.get(k) == v for k, v in selector.items())
            }
            if len(selected) != 1:
                raise ValueError(
                    "Service identity selector must resolve one workload; configure Chart selectors explicitly"
                )
            selector[INSTANCE] = selected.pop()
        if obj.get("kind") == "NetworkPolicy":

            def align(value):
                if not isinstance(value, dict):
                    return
                labels = value.get("matchLabels", {})
                if INSTANCE in labels:
                    selected = sorted(
                        {
                            name
                            for original, name in templates
                            if all(original.get(k) == v for k, v in labels.items())
                        }
                    )
                    if not selected:
                        raise ValueError(
                            "NetworkPolicy identity selector did not resolve a local workload"
                        )
                    del labels[INSTANCE]
                    value.setdefault("matchExpressions", []).append(
                        {"key": INSTANCE, "operator": "In", "values": selected}
                    )
                for child in value.values():
                    for entry in child if isinstance(child, list) else [child]:
                        align(entry)

            align(obj.get("spec", {}))


def validate_workload(obj, namespace, prefix):
    """Helm hooks bypass post-renderers and must satisfy the contract in the Chart."""
    kind = obj.get("kind")
    if kind not in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
        return
    metadata = obj["metadata"]
    if metadata.get("namespace", namespace) != namespace or not metadata["name"].startswith(
        prefix + "-"
    ):
        raise ValueError(
            "Workload names and namespaces must match the deployment prefix and namespace"
        )
    spec = obj["spec"]["jobTemplate"]["spec"] if kind == "CronJob" else obj["spec"]
    labels = spec["template"].get("metadata", {}).get("labels", {})
    if labels.get(INSTANCE) != metadata["name"]:
        raise ValueError(
            f"{metadata['name']}: configure the Chart Pod instance label to match the workload name"
        )
    if kind in ("Job", "CronJob") and not 1 <= spec.get("activeDeadlineSeconds", 0) <= 1800:
        raise ValueError(
            f"{metadata['name']}: configure a Job deadline of 1–1800 seconds in the Chart"
        )
    selector = spec.get("selector", {}).get("matchLabels", {})
    if any(labels.get(k) != v for k, v in selector.items()):
        raise ValueError(f"{metadata['name']}: Pod labels and workload selectors differ")


def render(objects, overrides, namespace, prefix):
    """Apply declared mounts to exact workloads without rewriting identities or DNS."""
    _align_selectors(objects)
    remaining = set(range(len(overrides)))
    for obj in objects:
        if obj.get("kind") == "List":
            raise ValueError("Charts must render individual resources")
        kind = obj.get("kind")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
            continue
        metadata = obj["metadata"]
        if metadata.get("namespace", namespace) != namespace or not metadata["name"].startswith(
            prefix + "-"
        ):
            raise ValueError(
                "Workload names and namespaces must match the deployment prefix and namespace"
            )
        metadata.setdefault("labels", {})["app.kubernetes.io/instance"] = metadata["name"]
        spec = obj["spec"]["jobTemplate"]["spec"] if kind == "CronJob" else obj["spec"]
        if kind in ("Job", "CronJob"):
            spec.setdefault("activeDeadlineSeconds", 900)
        template = spec["template"]
        template.setdefault("metadata", {}).setdefault("labels", {})[
            "app.kubernetes.io/instance"
        ] = metadata["name"]
        pod = template["spec"]
        for index, override in enumerate(overrides):
            if override["kind"] != kind or override["name"] != metadata["name"]:
                continue
            remaining.discard(index)
            pod.setdefault("nodeSelector", {}).update(override.get("nodeSelector", {}))
            if "fsGroup" in override:
                pod.setdefault("securityContext", {})["fsGroup"] = override["fsGroup"]
            for volume in override.get("volumes", []):
                if any(v["name"] == volume["name"] for v in pod.get("volumes", [])):
                    raise ValueError("A declared Pod volume already exists")
                pod.setdefault("volumes", []).append(volume)
            for target in override.get("containers", []):
                matches = [c for c in pod.get("containers", []) if c["name"] == target["name"]]
                if len(matches) != 1:
                    raise ValueError("A mount override did not resolve a unique container")
                for mount in target.get("volumeMounts", []):
                    if any(
                        m["mountPath"] == mount["mountPath"]
                        for m in matches[0].get("volumeMounts", [])
                    ):
                        raise ValueError("A declared mount path already exists")
                    matches[0].setdefault("volumeMounts", []).append(mount)
        validate_workload(obj, namespace, prefix)
    if remaining:
        raise ValueError("Pod override target was not rendered by this Helm phase")
    return objects


def main():
    try:
        plan = json.loads(Path(os.environ["NICO_RENDER_PLAN"]).read_text())
        objects = [o for o in yaml.safe_load_all(sys.stdin) if o]
        rendered = render(objects, plan.get("overrides", []), plan["namespace"], plan["prefix"])
        sys.stdout.write(yaml.safe_dump_all(rendered, sort_keys=False))
    except Exception:
        # Parsing failures may reference Secret data; only return a safe error to Helm.
        print("PXEye Pod mount / namespace render plan is invalid", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
