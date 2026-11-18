# NICo REST 离线扩展材料

[English](README.md) · **简体中文**

## 原生子依赖与命名空间

| 组件 | 子 Chart | 显式启用时的 release / namespace |
| --- | --- | --- |
| REST 服务 | 上游 `nico-rest` | `nico-rest` / `nico-rest` |
| Site Agent | 上游 `nico-rest-site-agent` | `nico-rest-site-agent` / `nico-rest` |
| Temporal | 上游随 NICo 固定的 `temporal` | `temporal` / `temporal` |
| Keycloak | 项目 `pxeye-keycloak`（该 NICo 版本原来用前置清单，无独立上游 Chart） | `nico-keycloak` / `nico-rest`；Service 为 `keycloak` |

父 Chart 始终携带这些子依赖，一个管理 release 只启用一个组件。默认 release 名和 namespace 在父 values 的 `managementReleases` 唯一维护。使用**现场已迁移**的父 Chart 及现场 values，先预览，例如：

```bash
bash tools/management-release.sh template temporal "$PARENT_CHART" -f site-values.yaml
```

其他选择为 `rest`、`siteagent`、`keycloak`。只有显式使用 `upgrade` 才会执行 `helm upgrade --install --wait`；目标 namespace 须提前准备。同名原生 release 或其他组件的 release 不会被自动接管。通过现场 values 覆盖 `managementReleases.<组件>.namespace` 或 `.name` 时，也要核对 DNS、证书 SAN、RBAC 引用及站点注册配置。不要从 Core release 一次开齐这些开关。构建用的临时认证配置不会作为现场 values 下发。

材料随父 Chart 交付，不是自动安装或授权。默认 Core/PXEye 安装不创建 REST、Site Agent、Temporal、Keycloak 或 Site CRD。启用前先用现场 values 渲染，核对 namespace、资源名、RBAC、证书域名及镜像地址；不要把构建时各子依赖的校验值用于部署。Site Manager 默认不授予集群级权限；需要预先在目标 namespace 配置其专用 ServiceAccount 和授权。

| 材料 | 用途和现场输入 |
| --- | --- |
| `charts/nico-rest-*.tgz` | 含 REST API、凭据管理、Site Manager、云端/站点 Worker、数据库迁移 Job 及 Site CRD。`nico-rest-cert-manager` 不是 Kubernetes 的 cert-manager。使用已有 PostgreSQL 或配方内的 PostgreSQL；由 DBA 分配独立数据库、用户和迁移权限。`databases.sql.example` 不包含口令。 |
| `charts/temporal-*.tgz` | PostgreSQL 持久化方案，含 Frontend、History、Matching、Worker、Admin Tools 及 schema Jobs。`temporal-certificates.reference.yaml` 来自与 Chart 相同的固定源码，仅供配置：替换 namespace、issuer、Secret 名与服务 DNS，部署由受信签发器签发的证书。TLS 与 schema 就绪后，用随包 Admin Tools 查询并按需初始化逻辑 namespace `cloud`、`site` 和本站 UUID；它们不是 Kubernetes namespace。 |
| `charts/pxeye-keycloak-*.tgz` | 开发环境可选的身份源，有外部 OIDC 时不部署。`realm.blueprint.json` 保留官方的角色、客户端及 claim 映射，不含用户、密码或已有授权。配置站点组织、issuer、TLS、客户端凭据和实际角色；通过 existing Secret 交给 Chart，不能原样当作已配置的身份服务。 |
| `charts/nico-rest-site-agent-*.tgz` | 含站点注册 Hook、辅助镜像和代理工作负载。预先确认 Site UUID、Core 地址、受信的 Site Agent 专用 mTLS 身份、Temporal 证书及命名策略；不可复用其他应用的管理员私钥。此 REST/主机管理配置不依赖 NICo Flow。 |

父 Chart 开关：`components.{rest,siteagent,temporal,keycloak}.enabled`，四项均为 `false`。独立配置位于 `rest`、`siteagent`、`temporal`、`keycloak`。开关不是就绪编排器：先准备数据库、签发器和身份源，再准备 Temporal、运行数据库迁移和 REST 服务，最后接入 Site Agent。通过 `nicocli user get`、`nicocli site list` 和目标 Site 的 `expected-machine list` 验收；`Ready` Pod 不证明组织授权或站点关联成功。

`databases.sql.example` 仅用于新数据库，使用 `psql -v` 提供已批准的库名和已有角色名，不要对现有库重跑。本地部署 Keycloak 时也要为它准备数据库和独立身份，使用外部 OIDC 则不需要。构建机须预置或能获得父 Chart 中固定的 REST 制品（`nico-local` 是制品引用，不保证公网可拉取）。改变版本要同步发布并核对镜像锁；不把旧 REST 镜像解释为已和新 Core 通过联机验收。

离线包不应携带现场密钥、Token、数据库口令或已注册站点的 OTP。生产环境按 [NVIDIA Quick Start](https://docs.nvidia.com/infra-controller/documentation/getting-started/quick-start-guide) 选择认证与拓扑；本材料覆盖上述 PostgreSQL/REST 方案，不等于囊括 Temporal 的全部第三方可选后端或所有 NICo 硬件扩展。
