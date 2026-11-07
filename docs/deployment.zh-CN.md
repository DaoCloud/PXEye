# 部署指南

[English](deployment.md) · **简体中文** · [文档中心](README.zh-CN.md)

PXEye 当前采用 Kubernetes 单副本部署。提供的清单是部署骨架，不负责安装 NICo。以下命令为通用示例，请使用已授权的 context 和命名空间；共享环境应遵守现场的资源命名规则。

## 1. 准备依赖

准备可访问的 NICo Core、DHCP 和 PXE 服务，兼容的 Linux `nico-admin-cli` 和 `grpcurl`，Core CA、客户端证书与私钥，以及验收专用 SSH 密钥。二进制架构必须与镜像一致。已有实机路径在 amd64 验证，arm64 镜像需要独立验证。

PXEye 运行环境需要访问 Core 和硬件控制器。目标主机需要访问 DHCP/relay、引导文件、ISO、autoinstall 数据和安装器回调。UI 能打开不代表这些网络路径成立。

## 2. 构建镜像

在仓库根目录准备[外部工具](../bin/README.zh-CN.md)：

```bash
install -m 0755 /path/to/nico-admin-cli bin/nico-admin-cli
install -m 0755 /path/to/grpcurl bin/grpcurl
make image IMAGE=pxeye:dev BASE_IMAGE=ubuntu:24.04
```

将镜像导入目标集群，或推送到已授权的仓库并修改清单中的镜像引用。PXEye 不会自动下载 NICo 客户端。

## 3. 配置站点和凭据

复制 [site.example.json](../examples/site.example.json) 为私有 `site.json`，配置 Core 端点、站点标识、材料路径和发布 URL。初始设备和材料可以为空，之后在页面添加。根据所选安装路径，还需准备执行默认值及相关基线文件。

在受限目录准备以下文件，名称必须与代码一致：

| 文件 | 用途 |
| --- | --- |
| `auth.json` | 操作员认证：`{"password_sha256":"<所选口令的 SHA256>"}`。 |
| `ca.crt` | Core 的可信 CA。 |
| `client.crt`、`client.key` | Core mTLS 客户端身份。 |
| `ssh_key`、`ssh_key.pub` | OS 验收专用私钥和公钥。 |
| `known_hosts` | 需要访问已有系统的路径所用 SSH 信任基线。 |
| 配置引用的其他文件 | 所选路径需要的旧基线或 BMC 凭据文件。 |

不要使用占位符作为真实凭据。可通过以下方式生成口令摘要，输入不会回显：

```bash
python3 - <<'PYTHON'
import getpass, hashlib, json, os
from pathlib import Path
os.umask(0o077)
Path('/private/pxeye-secrets/auth.json').write_text(json.dumps({
    'password_sha256': hashlib.sha256(getpass.getpass('Operator password: ').encode()).hexdigest()
}) + '\n')
PYTHON
```

先创建 `/private/pxeye-secrets`，并将路径替换成实际受限目录。Secret 只读挂载，不进入 ConfigMap、镜像或 Git。

通用清单使用 `pxeye` 命名空间。选择实际 context 后，创建配置资源：

```bash
kubectl create namespace pxeye
kubectl -n pxeye create configmap pxeye --from-file=site.json=/private/site.json
kubectl -n pxeye create secret generic pxeye --from-file=/private/pxeye-secrets
kubectl apply -f deploy/kubernetes.yaml
kubectl -n pxeye rollout status deployment/pxeye --timeout=120s
```

应用前核对存储类、镜像可用性、资源限制和命名空间。清单不创建 NICo、Ingress、StorageClass 或 DHCP relay。

## 4. 挂载与发布材料

| 路径 | 挂载类型 | 内容 |
| --- | --- | --- |
| `/config/site.json` | ConfigMap，只读 | 站点和执行配置。 |
| `/secrets` | Secret，只读 | 认证和可信身份。 |
| `/data` | PVC，可写 | `console.sqlite3`、规划、任务、日志和恢复文件。 |
| `/materials` | 持久卷，可写 | 导入 ISO 和提取后的引导材料。 |
| `/iso-sources` | 可选持久卷，只读 | 管理员提前放置的 ISO。 |
| `/tmp` | 有大小限制的 `emptyDir` | 临时文件。 |

`os_library.directory` 是服务可写的材料目录。`sources[].directory` 必须存在于 **PXEye 容器内部**；Kubernetes 节点上的文件未经挂载，容器无法读取。使用目录导入时，另行添加 `/iso-sources` 的 volume 和 volumeMount。

`public_base_url` 必须向目标主机提供这些已准备的文件；`verification_base_url` 是 PXEye 检查材料服务时使用的路径。仅挂载 PVC 不会自动发布 HTTP 文件，需要配置可达的静态材料服务或 NICo PXE 挂载映射。当前 Deployment 不会把 `/materials` 自动挂入 NICo PXE。还需配置 NICo 面向主机的元数据和安装回调路由。

使用自己的 ISO 时，仍保留 NICo 提供的 Scout 发现材料。

## 5. 访问与检查

本地查看服务可以使用：

```bash
kubectl -n pxeye port-forward service/pxeye 8080:80
```

打开 `http://127.0.0.1:8080`，使用已配置的操作员口令。port-forward 只向本机开放浏览器入口，不是目标主机使用的 PXE 或材料路径。长期部署应使用受控 TLS 入口。

`GET /healthz` 只说明 HTTP 进程可用，不代表 NICo 或硬件流程已通过。站点设置提供有限组件探测，使用时核对每项检查的层级。

## 存储与更新

服务读取 `CONSOLE_CONFIG`（默认 `/config/site.json`）、`CONSOLE_SECRETS`（`/secrets`）、`CONSOLE_DATA`（`/data`）、`CONSOLE_STATIC`（包内 `pxeye/web`）和 `PORT`（`8080`）。采用单副本和 `Recreate`，本地文件锁会再次阻止重复执行器启动。

替换前停止接收写操作，并等待运行中或结果待核对的操作结束。保留数据和材料 PVC。使用 SQLite backup API 或停服务方式获取一致备份；WAL 写入期间只复制数据库主文件不完整。恢复备份还应包含相关配置、任务和身份文件。更新镜像不会删除 PVC 中的历史，删除 PVC 会。

清单采用非 root UID、只读根文件系统和受限 capabilities。当前认证边界见[安全说明](../SECURITY.zh-CN.md)。
