# 先启动 PXEye，再部署 NICo

[English](nico-deployment.md) · **简体中文** · [文档中心](README.zh-CN.md)

PXEye 可独立启动在已有 Kubernetes/Kind 中。登录后使用 [NICo 集群页面](user-guide/nico-cluster.zh-CN.md) 在线或离线部署当前集群的 NICo 应用。默认在线，在页面填写来源、发布名和 values 即可；离线直接上传文件，无需登录服务器挂载部署包。Kubernetes、CNI、存储类及对外网络入口需要事先可用。

## 1. 准备运行环境

- PXEye 镜像包含兼容控制面架构的 `nico-admin-cli`、`grpcurl` 和 **Helm 3**，构建前放在 `bin/`。
- `/data` 持久保存任务、配置、部署记录与受限客户端身份；`/materials` 保存上传的 OS 材料。
- `/secrets/auth.json` 提供登录口令的 SHA256。初次启动不需要 Core 证书或 SSH 私钥，PXEye 在后端数据目录生成 SSH 身份。
- 页面上传及在线准备的 Chart 保存在 `/data/nico-deployment/`，由 PXEye 自动维护；上传不需要额外 PVC。既有 `/nico-packages` 挂载可继续作为可选材料来源。
- 现场离线包通过只读 `/nico-bundles` 挂载提供。PXEye 只读取清单和小型 `deployment/` recipe，不会把 17GiB OCI 归档复制到 `/data`。
- PXEye 与 PXE 使用同一份材料存储。单节点/RWO 存储须通过节点选择器将 PXE 调度到 PXEye 节点；多节点可使用 RWX 存储。

启动配置使用 [bootstrap-site.example.json](../examples/bootstrap-site.example.json)。保持 `core_url` 为空，启用 `nico_deployment.enabled`，命名空间与 Pod 所在命名空间一致。

## 2. 在线与离线部署

| 方式 | 页面操作 |
| --- | --- |
| 在线下载地址（默认） | 使用默认固定版本 NICo 源码，或填写 Chart `.tgz` / 源码归档的下载地址。PXEye 下载并准备 Chart。 |
| 在线 Helm 仓库 | 填仓库 URL、Chart 名称、可选版本及 values；PXEye 执行 `helm pull --repo`，随后安装固定的 Chart。 |
| 在线 OCI | 填 `oci://...` Chart 地址、可选版本及 values；PXEye 执行 `helm pull`。 |
| 离线 | 从页面上传带子 Chart 依赖的 `.tgz`，填写或读取 values。也可上传完整部署包 `.tar.gz` / `.zip`。 |

在线来源由 PXEye 下载，镜像由节点拉取；私有仓库需要已有的相应认证。普通 Chart 不要求 `deployment.json`、组件映射或文件摘要表。完整部署包使用下节格式，保留多阶段初始化和站点连接信息。

### 2.1 现场 bundle（推荐）

现场 bundle 是交付包的只读挂载，不是浏览器上传文件。目录至少包含：

```text
nico-x86-field-<version>/
├── bundle.json                         # 小型版本描述，可由工具生成
├── manifests/file-inventory.json
├── manifests/images-lock.json
├── images/nico-amd64.oci.tar            # 可为 17GiB，不复制到 /data
└── deployment/                          # 可选；包含 deployment.json、charts/、values/
```

`deployment/` 缺失时，页面仍会显示材料包、架构、镜像数量和缺口，但会明确禁止 Helm；这正是当前 `.50` 的 17GiB 包状态。部署 recipe 准备完成后，执行 `tools/package-nico-field-bundle.py` 生成 `bundle.json`，刷新 PXEye 即可自动发现，recipe 会按需复制到 `/data/nico-deployment/packages/bundle-<id>`。

PXEye Deployment 只需额外挂载一个只读目录，并在 `site.json` 中设置：

```json
{"nico_deployment":{"bundles_directory":"/nico-bundles"}}
```

不要把该目录挂到 `/data`，也不要通过浏览器上传 OCI 归档。示例挂载清单见 [`deploy/nico-bundle-mount.example.yaml`](../deploy/nico-bundle-mount.example.yaml)。

如果现场明确要求单一 PXEye 镜像携带全部材料，可把 bundle 作为独立的大镜像层构建：先构建常规 PXEye，再在包含 bundle 目录的构建上下文执行 `docker build -f Dockerfile.bundle --build-arg PXEYE_BASE_IMAGE=<pxeye-image> --build-arg BUNDLE_DIRECTORY=<bundle-dir> -t <pxeye-with-bundle> .`。这会产生约 17GiB 的额外层，升级、缓存和回滚成本高，默认不采用。

检查通过后在确认窗口查看将执行的命令：

```bash
helm upgrade --install mmzhou ./chart.tgz \
  -n mmzhou -f values.yaml --wait --wait-for-jobs --timeout 900s
```

实际命令还使用当前 Pod 的 Kubernetes 身份和 PXEye 的命名/挂载适配器，在部署流程中展示。NICo Core Chart 自动使用 `mmzhou` 工作负载命名和共享材料 PVC；自定义材料 PVC 名称可在 `nico_deployment.materials_claim` 中指定。单个 Chart 成功表示本次 Helm 完成；完整服务、Boot、站点连接仍分别核对。

## 3. 完整 Helm 部署包（可选）

需要一次部署 Core、REST 及依赖时，可使用完整包。一台站点的配置集中保存在 `values/`：

```text
site-recipe/
├── deployment.json
├── charts/
│   ├── cert-manager-v1.17.1.tgz
│   ├── pxeye-nico-platform-0.1.0.tgz
│   ├── nico-0.1.1.tgz
│   ├── temporal-0.35.0.tgz
│   ├── site-keycloak.tgz
│   ├── nico-rest-0.1.13.tgz
│   └── nico-rest-site-agent-0.1.9.tgz
└── values/
    ├── cert-manager.yaml
    ├── platform.yaml
    ├── vault.yaml
    ├── core.yaml
    ├── temporal.yaml
    ├── keycloak.yaml
    ├── rest.yaml
    └── site-agent.yaml
```

从 [deployment.example.json](../deploy/nico/deployment.example.json) 复制配方，按实际 Chart/values 修改名称和版本。此文件是完整服务的格式示例；它不包含完整的现场 values、镜像或所有 Chart。旧离线包只有 Chart 与直接 apply 的 JSON 时，需要先补齐本格式和初始化阶段。

| 阶段 | 材料与要求 |
| --- | --- |
| 证书管理 | cert-manager Chart 和镜像；可复用已健康的 controller、cainjector、webhook。共享组件在 `observe_namespaces` 中声明，其命名空间需要只读权限。 |
| 数据库与证书 | 本仓库 [nico-platform Chart](../deploy/nico-platform/Chart.yaml) 的 `infrastructure` 模式提供单副本 PostgreSQL、Vault、PVC、站点 CA 和客户端证书；[values 示例](../deploy/nico/platform-values.example.yaml)。 |
| Vault 初始化 | 同一 Chart 的 `vault-bootstrap` 模式，使用新 PXEye 镜像内的初始化命令；[values 示例](../deploy/nico/vault-values.example.yaml)。恢复信息只写入受限 Kubernetes Secret，并提供周期性续期/解封作业。 |
| Core 与网络引导 | 与运行镜像匹配的 NICo Chart；配置数据库/Vault Secret、Issuer、管理客户端信任、完整站点 TOML、各服务入口及 Boot 材料。关闭自动接管与固件自动更新。 |
| Temporal | Chart、数据库/证书配置与 schema 初始化 Job。 |
| Keycloak | 配置了数据库、Realm 和 REST 客户端的站点 Chart；示例名称 `site-keycloak.tgz` 指现场准备的 Chart，不是 NICo 自带文件。 |
| REST | NICo REST Chart、迁移镜像、数据库凭据、CA 签发 Secret、Temporal namespace/queue 及认证配置；依赖 Secret 必须在 pre-install 迁移之前创建。 |
| Site Agent | Chart、站点注册 hook、Core mTLS 与 Temporal/数据库配置。 |

单副本平台 Chart 用于与单节点装机环境相同的基础能力；高可用部署需使用经配置的数据库/Vault/存储方案替换对应阶段。

打包本仓库的平台 Chart，随后冻结完整站点材料：

```bash
helm package deploy/nico-platform --destination /srv/site-recipe/charts
python3 tools/package-nico-deployment.py \
  --source /srv/site-recipe \
  --destination /srv/nico-packages/site-v1
```

打包工具复制配方声明的 Chart/values，生成文件 SHA256，拒绝覆盖已有目标。把输出目录打成压缩包，从离线部署页面上传：

```bash
tar -C /srv/nico-packages -czf /srv/site-v1.tar.gz site-v1
```

也可继续使用已有 `/nico-packages` 只读挂载。离线材料必须已包含子 Chart 依赖。

### 2.2 Harbor 镜像导入

Helm 不会读取 OCI tar；Kubernetes 节点需要从 Harbor（或其它 OCI registry）拉取镜像。PXEye 镜像包含 `skopeo` 和 `/usr/local/bin/pxeye-import-oci-bundle`，可在 PXEye Pod 内执行一次性导入，不挂载宿主机 Docker/containerd socket：

```bash
kubectl -n mmzhou exec deploy/mmzhou-os-install-console -- \
  pxeye-import-oci-bundle \
  --archive /nico-bundles/nico-x86-field-<version>/images/nico-amd64.oci.tar \
  --lock /nico-bundles/nico-x86-field-<version>/manifests/images-lock.json \
  --registry https://harbor.example.com \
  --repository-prefix nico-offline \
  --authfile /secrets/harbor-auth.json
```

认证文件由平台以只读 Secret 挂载，权限必须为 `0600`；命令不会把认证信息写入部署事件。导入结果的目标引用应写入部署 recipe 的 values（或在 recipe 构建时使用同一映射），再执行页面的预检和 Helm。一个节点完成“推送”即可，但所有 Kubernetes 节点仍必须能访问 Harbor；只 `docker load` 到火种机不能替代 registry。

## 4. 配方字段与材料共享

| 字段 | 用途 |
| --- | --- |
| `schema_version` | 当前为 `1`。 |
| `name` / `version` / `defaults` | 部署包标识与表单默认值。 |
| `phases` | 依赖顺序；每项指定发布名、Chart、values 文件及超时。 |
| `components` | 服务 ID、工作负载 kind/name/namespace 和所在阶段；需要覆盖示例中的全部 25 项必需服务。 |
| `initialization` | 指明 Vault、Core、Temporal、REST 初始化所在阶段，该阶段必须实际渲染 Job。 |
| `connection` | Core 客户端 Secret 与 CA Secret 名称和键；可指定 PXE 内部 URL。 |
| `boot_checks` | 按目标架构声明 EFI、Scout 和 rootfs 的内部 HTTP URL 与最小大小。 |
| `files` | 由打包工具生成的 Chart/values SHA256。 |

values 支持 `@{site_name}`、`@{release_prefix}`、`@{namespace}`、`@{core_url}`、`@{pxe_url}`。`@{pxeye_node}` 来自 Pod 的 `POD_NODE_NAME`，用于 RWO 材料的正常节点调度。没有变量的值保持包内原值；发布名不会自动改写 Service DNS、SPIFFE 或 Secret 引用，这些引用需要在 values 中保持一致。

Helm hook 不经过 post-renderer，其 Pod 的 instance 标签和 Job 超时必须直接在 Chart 中配置，预检会检查实际 hook 输出。普通服务选择器随工作负载标签同步；跨多个工作负载的 Service 选择器需要在 Chart 中明确配置。

`phases[].pod_overrides` 为指定工作负载补充节点选择、文件卷和挂载。默认配方将 `mmzhou-pxeye-materials` 的内容只读挂到 PXE 的 `/forge-boot-artifacts/blobs/internal/nico/os-library`，使用共享 `fsGroup: 1000`。因此上传文件对应：

```text
PXEye：/materials/<os-id>/install.iso
PXE： /forge-boot-artifacts/blobs/internal/nico/os-library/<os-id>/install.iso
HTTP：<pxe-url>/public/blobs/internal/nico/os-library/<os-id>/install.iso
```

Boot initContainer 同时在 Core 和 PXE 中配置；自建 x86 Boot 镜像和 Grace ARM64 文件树都需要按实际供货版本加入，不能只凭控制面 x86 架构选择引导文件。

## 5. 启动 PXEye

按存储类设置数据/材料 PVC；启动清单不需要部署包 PVC。创建配置和登录凭据文件：

```bash
mkdir -p deploy/local/bootstrap
cp examples/bootstrap-site.example.json deploy/local/bootstrap/site.json
python3 - <<'PY'
import getpass, hashlib, json, os
from pathlib import Path
os.umask(0o077)
password = getpass.getpass('PXEye operator password: ')
if not password:
    raise SystemExit('Empty password refused')
Path('deploy/local/bootstrap/auth.json').write_text(
    json.dumps({'password_sha256': hashlib.sha256(password.encode()).hexdigest()}))
PY
```

以下在已确认的目标 context 执行，把 `SITE_CONTEXT` 改为实际值；应用示例 Deployment 前替换 `image: pxeye:dev` 为本次构建的版本镜像。

```bash
SITE_CONTEXT=your-cluster
kubectl --context "$SITE_CONTEXT" create namespace mmzhou --dry-run=client -o yaml \
  | kubectl --context "$SITE_CONTEXT" apply -f -
kubectl --context "$SITE_CONTEXT" -n mmzhou create configmap mmzhou-pxeye \
  --from-file=site.json=deploy/local/bootstrap/site.json --dry-run=client -o yaml \
  | kubectl --context "$SITE_CONTEXT" apply -f -
kubectl --context "$SITE_CONTEXT" -n mmzhou create secret generic mmzhou-pxeye \
  --from-file=auth.json=deploy/local/bootstrap/auth.json --dry-run=client -o yaml \
  | kubectl --context "$SITE_CONTEXT" apply -f -
kubectl --context "$SITE_CONTEXT" apply -f deploy/bootstrap-kubernetes.yaml
kubectl --context "$SITE_CONTEXT" -n mmzhou rollout status deployment/mmzhou-pxeye --timeout=180s
```

示例暴露 `31808/TCP`。打开实际节点的该端口登录；Kind 需要已配置节点端口映射，或使用平台提供的访问入口。

基础清单授予当前命名空间的应用安装权限。安装 cert-manager CRD/集群 RBAC 或本仓库平台 Chart 的 Vault TokenReview 绑定时，管理员需另行应用 [集群安装权限](../deploy/nico-cluster-permissions.yaml)，并在启动配置设置 `allow_cluster_resources: true`。权限不允许时，使用已准备依赖的部署包。完成部署后可撤销安装权限，保留状态观察和指定身份 Secret 的读取权限。

## 6. 在页面部署和确认

按 [页面指南](user-guide/nico-cluster.zh-CN.md) 检查、部署和应用站点。命令与退出码在**部署流程 → 操作与命令**按阶段显示；可能包含凭据的 Helm 原始输出仅保留在 `/data/nico-deployment/` 受限文件中。

包内服务和初始化全部就绪后，再验证物理机到 DHCP/PXE 的路径。部署失败时保留 PVC 与 Secret，不删除数据库重试；Vault 的恢复 Secret 需要另行受限备份。

参考：[NVIDIA Quick Start](https://docs.nvidia.com/infra-controller/documentation/getting-started/quick-start-guide) · [Reference Installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation) · [Architecture](https://docs.nvidia.com/infra-controller/documentation/architecture/overview-and-components)
