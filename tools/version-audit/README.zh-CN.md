# 环境与离线打包版本核对

[English](README.md) · **简体中文**

只读导出两份清单，核对环境与仓库已提交的离线打包配置是否一致。不构建或拉取镜像，不修改 Kubernetes、部署配置或现有离线包。

## 使用

在能访问 Kubernetes 和构建镜像缓存的 Linux 主机执行，需要 Python 3.11+、PyYAML、Git、Helm 3、kubectl。读取本机 containerd 内容存储需要相应权限，通常使用 root。

```bash
cd /path/to/PXEye
AUDIT=tools/version-audit/audit.py

# 1. 导出当前提交对应的打包清单；忽略未提交的 Chart、脚本等修改。
python3 "$AUDIT" package --repo "$PWD" \
  --registry 127.0.0.1:1027 --registry-http --output /tmp/pxeye-audit/package.json

# 2. 导出环境；请替换为实际 context。
python3 "$AUDIT" runtime --context kubernetes-admin@kubernetes \
  --output /tmp/pxeye-audit/runtime.json

# 3. 展示对比，并生成 comparison.json 与易读的 comparison.txt。
python3 "$AUDIT" compare \
  --package /tmp/pxeye-audit/package.json \
  --runtime /tmp/pxeye-audit/runtime.json \
  --output /tmp/pxeye-audit/comparison.json
```

两份清单也可以在不同主机导出，复制到一起后比较。`--help` 和各子命令的 `--help` 提供参数说明。

## 比较了什么

| 对象 | 打包侧 | 环境侧 | 判断依据 |
| --- | --- | --- | --- |
| 镜像 | 从 Git 提交快照复用打包器，渲染父 Chart 及依赖的完整镜像清单；读取对应 Registry/本地内容 | 所选活动 Pod 的主容器和 init container，包括实际 imageID、Pod UID、节点 | 同一镜像角色的 Linux 平台 manifest digest |
| x86 Boot / Scout | 从已提交配置引用的 Boot 镜像本地层中计算文件摘要 | 从 NICo PXE 容器实际发布目录计算摘要，包括外挂材料 | 相对路径及文件 SHA256 |
| ARM Boot / Scout | 加 `--include-arm64` 后，读取提交中的 ARM 文件配方 | 同一 PXE 发布目录中的 `aarch64/` 文件 | 相对路径及文件 SHA256 |
| ISO 等额外材料 | 默认打包流程不包含外部 ISO | 导出已发布的 ISO、BFB、deb、kernel/initrd 等文件摘要 | 标为“仅环境”，不假定它们应进入默认包 |

镜像标签和可用的 OCI 版本、源码提交标签保存在 JSON；Scout 的 `BUILD-INFO.json` 声明提交也会读取，但最终一致性以实际文件摘要为准。文件内容及凭据不导出，cloud-init/user-data 不在扫描范围。

## 结果含义

| 结果 | 含义 |
| --- | --- |
| 一致 | 已取得双方内容摘要，且完全相同 |
| 不一致 | 双方摘要不同，或同一角色/路径出现多个内容版本 |
| 仅打包 | 只有打包侧存在；例如环境以外置目录替代 Boot init 镜像，需同时看文件结果 |
| 仅环境 | 只有环境侧存在；例如外部 ISO 或额外服务 |
| 无法确认 | 镜像/文件无法读取、内容层缺失或运行身份无法绑定；不会因 tag 相同判为一致 |

终端和文本报告按镜像、文件分组，文件每种结果最多展示 12 项并显示总数；JSON 保留所有项目、完整摘要、引用和采集错误。退出码：`0` 完整导出/全部一致，`2` 存在差异或无法确认，`1` 命令失败。差异退出码不代表脚本崩溃。

## 常用参数与范围

- `package --revision <commit>`：默认 `HEAD`；仅使用该提交中的打包实现、Chart、补丁和材料配方，不读取旧包锁或未提交修改。
- `package --registry <host:port>`：与 `make bundles REGISTRY=...` 的缓存地址映射一致；指定后从 Registry 读取当前标签摘要，避免采用过期本地标签。HTTP 必须显式加 `--registry-http`。不提供 Registry 时按本地 containerd 记录解析。
- `package --chart-cache <目录>`：复用构建工作区 `cache/charts` 中的 SHA 命名归档，复用前重新校验。缺少时可能下载固定上游 Chart；不要求已有离线包。
- `package --include-arm64`：对应 `make bundles INCLUDE_ARM64_MATERIALS=1`。默认关闭，与仓库 Make 默认一致；ARM 材料镜像在构建时生成，本脚本只导出配方中的文件身份。
- `runtime --namespace <名称>`：可重复；默认 `nico-system`、`mmzhou`，Pod 名默认匹配 `nico|pxeye|os-install-console|cert-manager`，可用 `--name-pattern` 调整。已结束和正在删除的 Pod 不纳入。
- `runtime --boot-root <路径>`：默认 PXE 容器内 `/forge-boot-artifacts/blobs/internal`。计算真实文件摘要可能耗时，尤其是 ISO；需要容器具备 `sh`、`find`、`sha256sum`，读取构建说明还需 `head`。
- `--architecture amd64|arm64`：控制面容器运行平台，默认 `amd64`，与待安装主机的 ARM 架构分别处理。
- `--content-dir`、`--ctr`、`--containerd-namespace`：适配本机 containerd；Kind 的内容存储在节点容器内，需使用对应可访问的存储路径和工具。无法访问时明确显示无法确认。

Registry 元数据访问使用系统 CA，当前不读取私有 Registry 登录凭据；可预先缓存镜像内容并省略 `--registry`。Boot 镜像文件只读取本机内容层，不自动下载大型层；链接文件标为无法确认。运行采集不主动扫描其他节点的容器存储，跨节点缺失的身份或内容也会明确显示。

这是“已提交打包配置与环境”的核对，不是已生成归档的验包，也不代表物理装机验收。可读 tag 会变化，因此报告保存采集时间和完整 digest；需要发布版本时应使用固定 tag/digest 并保留报告。
