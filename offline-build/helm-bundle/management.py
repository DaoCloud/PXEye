"""Locked optional dependencies and their build-only, credential-free render profile."""

import json
from pathlib import Path
import tarfile
import yaml

UPSTREAM = {
    "nico-rest": "helm/rest/nico-rest",
    "nico-rest-site-agent": "helm/rest/nico-rest-site-agent",
    "temporal": "rest-api/temporal-helm/temporal",
}
COMPONENTS = ("rest", "siteagent", "temporal", "keycloak")
REST_IMAGES = (
    "nico-rest-api",
    "nico-rest-cert-manager",
    "nico-rest-db",
    "nico-rest-site-manager",
    "nico-rest-workflow",
)


def dependencies(repo):
    rows = yaml.safe_load((repo / "charts/pxeye/Chart.yaml").read_text())["dependencies"]
    selected = {row["name"]: row["version"] for row in rows if row["name"] in UPSTREAM}
    if set(selected) != set(UPSTREAM):
        raise ValueError("Missing required offline management Chart dependency")
    return selected


def render_target(parent, mode, values, merge):
    if mode == "default":
        return parent, values
    rows = yaml.safe_load((parent / "Chart.yaml").read_text())["dependencies"]
    selected = [
        row
        for row in rows
        if (row.get("alias") or row["name"]) == mode
        and row.get("condition") == f"components.{mode}.enabled"
    ]
    if len(selected) != 1:
        raise ValueError(f"Missing or ambiguous native dependency for {mode}")
    row = selected[0]
    package = parent / "charts" / f"{row['name']}-{row['version']}.tgz"
    if not package.is_file():
        raise ValueError(f"Native dependency archive missing: {package.name}")
    child = values[mode]
    return package, merge(
        child, {"global": merge(child.get("global") or {}, values.get("global") or {})}
    )


def check_archived_materials(package, repo):
    rows = yaml.safe_load((repo / "charts/pxeye/Chart.yaml").read_text())["dependencies"]
    children = {
        f"charts/{row['name']}-{row['version']}.tgz"
        for row in rows
        if (row.get("alias") or row["name"]) in COMPONENTS
    }
    if len(children) != len(COMPONENTS):
        raise ValueError("Missing optional management dependencies in parent Chart")
    required = children | {
        "files/management/" + name
        for name in (
            "README.md",
            "README.zh-CN.md",
            "realm.blueprint.json",
            "temporal-certificates.reference.yaml",
            "management-release.sh",
            "databases.sql.example",
        )
    }
    with tarfile.open(package, "r:gz") as archive:
        actual = {
            entry.name.removeprefix("pxeye/") for entry in archive if entry.isfile() and entry.size
        }
    if required - actual:
        raise ValueError(
            "Management materials missing from packaged Chart: " + str(sorted(required - actual))
        )
    return sorted(required)


def prepare_archives(archive, core_subdir, deployment, repo, extract, pack):
    root = Path(core_subdir).parent
    for name, version in dependencies(repo).items():
        target = deployment.parent / "upstream-extensions" / name
        metadata = extract(archive, root / UPSTREAM[name], target)
        if (metadata["name"], str(metadata["version"])) != (name, version):
            raise ValueError("Unexpected management Chart identity: " + name)
        pack(target, deployment / "charts" / f"{name}-{version}.tgz", name)
    references = deployment / "management-files"
    references.mkdir()
    with tarfile.open(archive, "r:*") as pinned:

        def read(relative):
            member = pinned.getmember((root / relative).as_posix())
            if not member.isfile() or not 0 < member.size <= 1024 * 1024:
                raise ValueError("Unsafe management reference: " + relative)
            with pinned.extractfile(member) as stream:
                return stream.read()

        certificates = read("rest-api/deploy/kustomize/base/temporal-helm/certificates.yaml")
        (references / "temporal-certificates.reference.yaml").write_bytes(certificates)
        config = yaml.safe_load(read("helm-prereqs/keycloak/realm-configmap.yaml"))
        upstream = json.loads(config["data"]["nico-realm.json"])
    clients = [
        {
            key: item[key]
            for key in ("clientId", "protocol", "protocolMappers", "serviceAccountsEnabled")
            if key in item
        }
        | {"publicClient": False, "standardFlowEnabled": False, "directAccessGrantsEnabled": False}
        for item in upstream["clients"]
    ]
    blueprint = {
        "realm": upstream["realm"],
        "enabled": True,
        "sslRequired": "all",
        "registrationAllowed": False,
        "roles": upstream["roles"],
        "clients": clients,
    }
    (references / "realm.blueprint.json").write_text(json.dumps(blueprint, indent=2) + "\n")


def bind_rest_helper(tree, name):
    helper = tree / "templates/_helpers.tpl"
    upstream = "{{ .Values.global.image.repository }}/{{ .Values.image.name }}:{{ .Values.global.image.tag }}"
    text = helper.read_text()
    if text.count(upstream) != 1 or f'define "{name}.image"' not in text:
        raise ValueError("Unsupported upstream REST image helper: " + name)
    helper.write_text(
        text.replace(
            upstream,
            '{{ default (printf "%s/%s:%s" .Values.global.image.repository .Values.image.name .Values.global.image.tag) .Values.image.offlineReference }}',
        )
    )


def profiles(defaults, release, namespace):
    yield "default", release, namespace, {}
    fixtures = {
        "rest": {
            "nico-rest-api": {
                "config": {
                    "keycloak": {
                        "enabled": True,
                        "baseURL": "https://idp.invalid",
                        "externalBaseURL": "https://idp.invalid",
                        "realm": "render",
                        "clientID": "render",
                    }
                }
            }
        },
        "siteagent": {
            "bootstrap": {"enabled": True},
            "envConfig": {"CLUSTER_ID": "00000000-0000-4000-8000-000000000001"},
        },
        "temporal": {},
        "keycloak": {
            "admin": {"existingSecret": "render-only-admin"},
            "database": {
                "url": "jdbc:postgresql://db.invalid/keycloak",
                "existingSecret": "render-only-db",
            },
            "realm": {"existingSecret": "render-only-realm"},
            "startup": {"args": ["start", "--import-realm"]},
        },
    }
    for component in COMPONENTS:
        target = defaults["managementReleases"][component]
        flags = {key: {"enabled": key == component} for key in defaults["components"]}
        yield (
            component,
            target["name"],
            target["namespace"],
            {"components": flags, component: fixtures[component]},
        )


def images(documents):
    refs = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("image"), str):
                refs.add(value["image"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(documents)
    return refs


def check_profile(mode, values, documents, namespace):
    def tagged(image):
        return image["repository"] + ":" + image["tag"]

    rest = {name: values["rest"][name]["image"]["offlineReference"] for name in REST_IMAGES}
    admin = tagged(values["temporal"]["admintools"]["image"])
    required = {
        "rest": {
            ("Deployment", "api", rest["nico-rest-api"]),
            ("Deployment", "cert-manager", rest["nico-rest-cert-manager"]),
            ("Deployment", "site-manager", rest["nico-rest-site-manager"]),
            ("Deployment", "nico-rest-cloud-worker", rest["nico-rest-workflow"]),
            ("Deployment", "nico-rest-site-worker", rest["nico-rest-workflow"]),
            ("Job", "migrations", rest["nico-rest-db"]),
            (
                "Job",
                "wait-for-postgres",
                values["rest"]["nico-rest-db"]["waitForPostgres"]["image"],
            ),
        },
        "siteagent": {
            ("StatefulSet", "site-agent", values["siteagent"]["image"]["offlineReference"]),
            ("Job", "bootstrap", values["siteagent"]["bootstrap"]["image"]),
        },
        "keycloak": {("Deployment", "keycloak", tagged(values["keycloak"]["image"]))},
        "temporal": {("Deployment", "admin-tools", admin)},
    }
    for role in ("frontend", "history", "matching", "worker"):
        required["temporal"].add(
            ("Deployment", "temporal-" + role, tagged(values["temporal"]["server"]["image"]))
        )
    for phase in ("setup", "update"):
        required["temporal"].update(
            (f"Job/schema-{phase}", store, admin)
            for store in ("default-schema", "visibility-schema")
        )
    seen = set()
    for obj in documents:
        if not obj:
            continue
        if mode != "default" and obj["metadata"].get("namespace", namespace) != namespace:
            raise ValueError(
                f"{mode} rendered {obj['kind']}/{obj['metadata']['name']} outside {namespace}"
            )
        if mode != "default" and obj["kind"] in ("RoleBinding", "ClusterRoleBinding"):
            if any(
                subject["kind"] == "ServiceAccount"
                and subject.get("namespace", namespace) != namespace
                for subject in obj.get("subjects", [])
            ):
                raise ValueError(f"{mode} rendered a ServiceAccount binding outside {namespace}")
        if obj["kind"] not in ("Deployment", "StatefulSet", "Job"):
            continue
        kind = obj["kind"]
        for phase in ("setup", "update"):
            if kind == "Job" and obj["metadata"]["name"].endswith("-schema-" + phase):
                kind += "/schema-" + phase
        spec = obj["spec"]["template"]["spec"]
        for container in (spec.get("initContainers") or []) + spec["containers"]:
            seen.add((kind, container["name"], container["image"]))
    needed = required.get(mode, set())
    prohibited = set().union(*required.values()) - needed
    difference = (needed - seen) | (prohibited & seen)
    if difference:
        raise ValueError(f"Unexpected management workload coverage in {mode}: {sorted(difference)}")
