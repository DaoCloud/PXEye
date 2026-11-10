"""Prepare online Charts and browser uploads as private, frozen Helm inputs."""

import hashlib
import json
import posixpath
import re
import shutil
import tarfile
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml

from pxeye.common import atomic_json, atomic_text
from pxeye.deployment.bundles import FieldBundles
from pxeye.deployment.packages import Packages

ARCHIVE_LIMIT = 128 * 1024**2
FILE_LIMIT = 64 * 1024**2
EXPANDED_LIMIT = 256 * 1024**2
DEFAULT_CHART_URL = (
    "https://github.com/dsx-ai-factory/infra-controller/archive/"
    "e703126e4a7a2fe1d4dab5f96cba9bdf055e0921.tar.gz"
)


def source_url(value, *, oci=False):
    value = str(value).strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in (("https", "http", "oci") if oci else ("https", "http"))
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(c.isspace() for c in value)
    ):
        raise ValueError("请填写 HTTP/HTTPS 地址或 OCI Chart 地址，不包含登录凭据或查询参数。")
    return value


def extract_input(archive, destination):
    """Extract only a Chart or recipe subtree, never links or unrelated source files."""
    archive = Path(archive)
    is_zip = zipfile.is_zipfile(archive)
    try:
        container = zipfile.ZipFile(archive) if is_zip else tarfile.open(archive, "r:*")
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        raise ValueError("文件不是有效的 .tgz、.tar.gz 或 .zip 部署材料。") from None
    with container:
        members = container.infolist() if is_zip else container.getmembers()
        if len(members) > 50000:
            raise ValueError("压缩包文件数量超过限制。")
        records = []
        for member in members:
            name = member.filename if is_zip else member.name
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("压缩包包含越界路径。")
            regular = not member.is_dir() if is_zip else member.isfile()
            if regular:
                records.append((path, member))
        recipes = [p.parent for p, _ in records if p.name == "deployment.json"]
        charts = [p.parent for p, _ in records if p.name == "Chart.yaml"]
        roots = recipes or charts
        if not roots:
            raise ValueError("压缩包中未找到 Helm Chart.yaml 或 deployment.json。")
        depth = min(len(p.parts) for p in roots)
        candidates = [p for p in roots if len(p.parts) == depth]
        if not recipes and len(candidates) > 1:
            nico = [p for p in candidates if p.name == "helm"]
            candidates = nico or candidates
        if len(candidates) != 1:
            raise ValueError("压缩包中有多个顶层 Chart，请分别上传要安装的 Chart。")
        root = candidates[0]
        if not is_zip:
            by_name = {PurePosixPath(m.name): m for m in members}
            for member in members:
                path = PurePosixPath(member.name)
                if not (member.issym() or member.islnk()) or not path.is_relative_to(root):
                    continue
                target = member
                seen = set()
                while target.issym() or target.islnk():
                    if target.name in seen:
                        raise ValueError("部署材料包含循环链接。")
                    seen.add(target.name)
                    reference = (
                        PurePosixPath(target.name).parent / target.linkname
                        if target.issym()
                        else PurePosixPath(target.linkname)
                    )
                    reference = PurePosixPath(posixpath.normpath(str(reference)))
                    if not reference.is_relative_to(root) or reference not in by_name:
                        raise ValueError("部署材料链接必须指向 Chart 内部已有文件。")
                    target = by_name[reference]
                if not target.isfile():
                    raise ValueError("部署材料只支持内部普通文件链接。")
                records.append((path, target))
        total = 0
        for path, member in records:
            if not path.is_relative_to(root):
                continue
            size = member.file_size if is_zip else member.size
            total += size
            if size > FILE_LIMIT or total > EXPANDED_LIMIT:
                raise ValueError("解压后的部署材料超过大小限制。")
            if is_zip and (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("部署材料不能包含符号链接。")
            target = destination / str(path.relative_to(root))
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source = container.open(member) if is_zip else container.extractfile(member)
            with source, target.open("xb") as output:
                copied = 0
                while chunk := source.read(1024**2):
                    copied += len(chunk)
                    if copied > size or copied > FILE_LIMIT:
                        raise ValueError("部署材料文件大小与声明不符。")
                    output.write(chunk)
            target.chmod(0o600)
    return "recipe" if recipes else "chart"


class Sources:
    def __init__(self, directory, mounted, bundles_directory="/nico-bundles"):
        self.root = directory / "packages"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.uploads = directory / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.local = Packages(self.root)
        self.mounted = mounted
        self.bundles = FieldBundles(bundles_directory)
        self.bundle_packages = {}
        self._sync_bundles()

    def _sync_bundles(self):
        self.bundle_packages = self.bundles.materialize_recipes(self.root)

    def list(self):
        self._sync_bundles()
        result = self.mounted.list()
        local = self.local.list()
        for row in local:
            source = self.root / row["id"] / ".bundle-source.json"
            if source.is_file():
                try:
                    marker = json.loads(source.read_text())
                except (OSError, ValueError):
                    continue
                bundle = self.bundle_packages.get(marker.get("bundle_id"), {})
                row.update(
                    source="field-bundle",
                    bundle_id=marker.get("bundle_id", ""),
                    bundle_version=marker.get("version", ""),
                    image_count=bundle.get("image_count", 0),
                    image_bytes=bundle.get("image_bytes", 0),
                )
            result.append(row)
        for path in sorted(self.uploads.glob("*/input.json")):
            record = json.loads(path.read_text())
            result.append(record | {"id": "upload-" + path.parent.name, "valid": True})
        return result

    def upload(self, stream, length, filename):
        identifier = uuid.uuid4().hex
        target = self.uploads / identifier
        target.mkdir(mode=0o700)
        try:
            archive = target / "input.archive"
            with archive.open("xb") as output:
                remaining = length
                while remaining:
                    chunk = stream.read(min(1024**2, remaining))
                    if not chunk:
                        raise ValueError("上传中断，请重新选择文件。")
                    output.write(chunk)
                    remaining -= len(chunk)
            archive.chmod(0o600)
            content = target / "content"
            content.mkdir(mode=0o700)
            kind = extract_input(archive, content)
            try:
                metadata = (
                    json.loads((content / "deployment.json").read_text())
                    if kind == "recipe"
                    else yaml.safe_load((content / "Chart.yaml").read_text())
                )
            except (ValueError, yaml.YAMLError):
                raise ValueError("Chart 或部署包描述文件格式错误。") from None
            if not isinstance(metadata, dict) or not metadata.get("name"):
                raise ValueError("Chart 或部署包名称无效。")
            record = {
                "name": str(metadata["name"]),
                "version": str(metadata.get("version", "")),
                "kind": kind,
                "filename": Path(filename).name[:150],
            }
            atomic_json(target / "input.json", record)
            archive.unlink()
            return record | {"id": "upload-" + identifier}
        except Exception:
            shutil.rmtree(target)
            raise

    def load(self, settings):
        self._sync_bundles()
        if (self.root / settings["package_id"] / "deployment.json").is_file():
            return self.local.load(settings)
        return self.mounted.load(settings)

    def prepare(self, settings, run, event):
        mode = settings.get("mode")
        if mode is None:
            return self.load(settings)
        destination = self.root / ("prepared-" + uuid.uuid4().hex)
        destination.mkdir(mode=0o700)
        content = destination / "content"
        content.mkdir(mode=0o700)
        if mode == "offline":
            identifier = settings["package_id"].removeprefix("upload-")
            if not re.fullmatch(r"[a-f0-9]{32}", identifier):
                # Previously mounted complete recipes remain usable.
                package = self.load(settings)
                if settings.get("values_yaml", "").strip():
                    raise ValueError(
                        "完整部署包请使用包内各阶段 values；页面 values 用于单个 Chart。"
                    )
                return package
            upload = self.uploads / identifier
            if not (upload / "input.json").is_file():
                raise ValueError("请选择并上传离线 Chart 或完整部署包。")
            shutil.copytree(upload / "content", content, dirs_exist_ok=True)
            kind = json.loads((upload / "input.json").read_text())["kind"]
            event("已读取页面上传的离线材料")
        else:
            source = settings["chart_source"]
            source_type = settings["source_type"]
            if source_type == "url":
                event("正在下载在线 Chart 或源码归档")
                request = urllib.request.Request(source, headers={"User-Agent": "PXEye"})
                archive = destination / "download.archive"
                try:
                    with (
                        urllib.request.urlopen(request, timeout=60) as response,
                        archive.open("xb") as output,
                    ):
                        total = 0
                        while chunk := response.read(1024**2):
                            total += len(chunk)
                            if total > ARCHIVE_LIMIT:
                                raise ValueError("在线材料超过 128 MiB，请提供 Chart 压缩包地址。")
                            output.write(chunk)
                except OSError:
                    raise ValueError("在线材料下载失败，请检查地址和 PXEye 的网络连接。") from None
                kind = extract_input(archive, content)
                archive.unlink()
            else:
                arguments = ["pull", source, "--destination", str(content)]
                if source_type == "repository":
                    arguments += ["--repo", settings["repository_url"]]
                if settings.get("chart_version"):
                    arguments += ["--version", settings["chart_version"]]
                run(arguments, timeout=180)
                archives = list(content.glob("*.tgz"))
                if len(archives) != 1:
                    raise ValueError("Helm 未返回唯一 Chart 文件。")
                kind = extract_input(archives[0], destination / "unpacked")
                shutil.rmtree(content)
                (destination / "unpacked").rename(content)
        if kind == "recipe":
            if settings.get("values_yaml", "").strip():
                raise ValueError("完整部署包使用包内 values；页面 values 用于单个 Chart。")
            for path in content.iterdir():
                path.rename(destination / path.name)
            content.rmdir()
        else:
            metadata = yaml.safe_load((content / "Chart.yaml").read_text())
            # The upstream NICo Chart names subcharts independently of the Helm release.
            # Apply namespace conventions as normal Helm values, without rewriting templates.
            if metadata.get("name") == "nico":
                values = yaml.safe_load(settings.get("values_yaml") or "{}")
                for dependency in metadata.get("dependencies", []):
                    name = dependency["name"]
                    values.setdefault(name, {}).setdefault("nameOverride", "mmzhou-" + name)
                settings["values_yaml"] = yaml.safe_dump(values, allow_unicode=True)
            dependencies = metadata.get("dependencies", [])
            missing = [
                row
                for row in dependencies
                if not (content / "charts" / row["name"] / "Chart.yaml").is_file()
                and not list((content / "charts").glob(row["name"] + "-*.tgz"))
            ]
            if missing:
                if mode == "offline":
                    raise ValueError("离线 Chart 缺少子 Chart，请上传已包含依赖的包。")
                run(["dependency", "build", str(content)], timeout=180)
            charts = destination / "charts"
            charts.mkdir(mode=0o700)
            run(["package", str(content), "--destination", str(charts)], timeout=120)
            chart = next(charts.glob("*.tgz"))
            atomic_text(destination / "values.yaml", settings.get("values_yaml", "") or "{}\n")
            manifest = {
                "schema_version": 1,
                "profile": "helm",
                "name": str(metadata["name"]),
                "version": str(metadata["version"]),
                "phases": [
                    {
                        "id": "helm",
                        "name": "Helm 安装",
                        "release": "@{release_prefix}",
                        "chart": str(chart.relative_to(destination)),
                        "values": ["values.yaml"],
                        "timeout_seconds": settings["timeout_seconds"],
                    }
                ],
                "components": [],
                "initialization": {},
                "connection": {},
                "boot_checks": [],
                "files": {
                    str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (chart, destination / "values.yaml")
                },
            }
            atomic_json(destination / "deployment.json", manifest)
            shutil.rmtree(content)
        settings["package_id"] = destination.name
        return self.local.load(settings)
