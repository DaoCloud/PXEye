# 第三步：一个脚本导入并部署 NICo

[English](README.md) · **简体中文**

一个用户配置文件、一个执行命令，完成校验解压 → 现场配置与预检 → 镜像及 Chart 入库 → 冻结安装配方 → 可选 PXEye 启动 → 证书管理 → 平台依赖 → Vault → 可选材料 → Core。沿用官方 Helm Chart 和兼容补丁；不构建镜像、不改 containerd、不发起设备发现、Redfish 或 OS 安装。

## 1. 准备一个配置文件

主要目标：在火种机 Linux amd64 上准备 Python 3.11+/PyYAML、kubectl、归档及 SHA256SUMS。Registry 项目、认证权限和节点镜像拉取能力必须已有。工作目录任意，不依赖当前 kubectl context。

现场工具目录统一为 `/srv/nico/nico-onsite-tools/tools/onsite`。旧大包可用 `export.py` 单独交付小工具包；第二步新归档也包含同一工具目录。不要通过旧包内的旧脚本执行新入口。

执行命令（火种机，工具已放置完成后，仅首次）：

```bash
cp /srv/nico/nico-onsite-tools/tools/onsite/run-config.example.json /srv/nico/onsite-run.json
```

确认命令：

```bash
python3 -m json.tool /srv/nico/onsite-run.json
```

只编辑 `onsite-run.json`，无需手工生成资源 YAML、环境变量或第二份站点配置。

| 参数 | 如何填写 |
| --- | --- |
| `archive` / `checksums` | 离线归档和校验文件绝对路径 |
| `extract_directory` | 本次独立解压目录，脚本创建，完成后验证复用 |
| `work_directory` | 本次独立进度、日志和派生配置目录；与解压目录分开 |
| `bootstrap_pxeye` | 已有 PXEye 填 false；全新需要启动 PXEye 时填 true |
| `site.context` | 推荐明确指定；null 时只允许唯一 Kind context，不采用当前默认 context |
| `site.namespace` | 默认 `nico-system` |
| `site.mode` | 保留旧数据恢复为 restore；全新为 new |
| `site.release_prefix` | restore 留空时读取唯一原 Core release；new 留空时为 nico |
| `site.registry.url` | null 自动从集群线索探测唯一可用 Registry V2；没有线索或多个端点时明确填写 |
| `site.registry.ca_file` / `skip_tls_verify` | CA 文件或明确允许跳过 Registry TLS 校验，默认严格校验 |
| `site.registry.docker_config_directory` | 认证 config.json 所在目录；不把密码写入脚本或参数 |
| `site.service_ips` / `host_network` | restore 留空时复用旧地址和网络；new 必须提供 DNS/PXE/NTP IPv4 与网络 name/prefix/gateway/mtu |
| `site.storage_class` | 按现场存储填写；null 使用 Chart/集群默认 |
| `site.publish_materials` | 默认 false；true 部署材料服务，消费者 URL 仍须独立核对 |
| `site.phase_values` | 如需定制，引用对应阶段 YAML 的绝对路径，摘要纳入本次身份 |

模板默认为恢复模式、保留已有 PXEye。缺少现场必填信息时停止并记录阶段；不要将其他现场的 IP 或凭据复制为通用默认值。

## 2. 执行唯一入口

主要目标：自动按依赖顺序完成部署。执行位置为火种机；首次和失败后执行同一命令。

执行命令：

```bash
python3 /srv/nico/nico-onsite-tools/tools/onsite/run.py --config /srv/nico/onsite-run.json
```

确认命令（工作目录使用模板默认值时）：

```bash
cat /srv/nico/onsite/field-install-01/progress.json
```

终端按阶段输出 `STAGE`、`DONE`、`FAILED`、`REUSE_*` 或 `ALREADY_INSTALLED`；完成输出 `ONSITE_COMPLETE`。保留逐 Chart 和逐 Helm 阶段断点，不需要手工再运行 preflight/import/recipe/install，也无需 source 环境文件。

## 3. 查看日志并继续

主要目标：定位失败；修复网络、权限、镜像拉取、工作负载等实际原因后继续。

执行命令：

```bash
tail -n 60 /srv/nico/onsite/field-install-01/run.log
```

确认命令：

```bash
cat /srv/nico/onsite/field-install-01/progress.json
ls /srv/nico/onsite/field-install-01/deployment/logs
```

再次执行第2节原命令即可。不会在同一次执行里无限重试：

- 完成的解包校验复用，已入库 Chart 从 Registry 读回核对后复用。
- 冻结配方核对摘要后复用；已完成 Helm 阶段检查 deployed、工作负载健康和原 PVC 身份后跳过。
- 上次失败阶段仅在 Helm 已明确 failed 或 release 不存在时重试；仍为 pending 时停止，交由操作者排查，不自动解锁、回滚或删除资源。
- Helm 已完成而进度尚未落盘时，核对安装意图、Chart 版本、实际 values、健康和 PVC 后补记成功，避免重放初始化。
- 不支持文件字节级续传；未完成的 Chart 迁移或 Helm 阶段重新执行。配置、归档清单、定制 values 或工具源码变化时，使用新工作目录，防止混用旧断点。

不要同时在 UI 和 CLI 安装。进度记录和站点锁阻止本工具并发操作，但旧 UI 不共享该锁。

```text
work_directory/
  progress.json                 # 原子保存当前阶段、状态、次数、耗时、错误
  events.jsonl                  # 追加阶段历史，保留失败
  run.log                       # 自动追加终端日志，不用 tee
  site-config.json              # 自动解析并冻结，不手工编辑
  environment.sh                # 可选诊断入口，不是执行前提
  deployment/
    state.json                  # 逐 Chart / Helm 阶段及安装意图
    timings.jsonl               # 实际命令耗时和退出码
    catalog.json
    recipe/                     # 冻结 Charts、values、摘要
    logs/                       # 追加命令日志，保留每次退出码
    private/                    # 权限700；快照、敏感values和安装输出
```

日志和进度可能包含内部路径与地址，默认限制权限；凭据仍使用受限文件引用。不要把现场目录提交仓库。

## 4. 验收范围

主要目标：区分 Helm 就绪与装机能力。确认命令使用配置中明确的目标 context，不依赖默认集群。

执行命令（context 为示例现场名称）：

```bash
kubectl --context kind-fireseed -n nico-system get deploy,sts,pods,jobs,pvc
```

确认命令：

```bash
cat /srv/nico/onsite/field-install-01/deployment/state.json
```

脚本保留原包、旧镜像与 PVC，不自动备份后端卷、不清空数据、不重建 Kind。完成只代表包导入与 Helm 阶段通过；严格 Core mTLS、材料 HTTP 和物理网络/Scout/OS 验收仍需按对应清单进行。

手动分阶段的 `onsite.py` 命令保留作为诊断工具，不是推荐安装流程。`export.py` 可为旧归档发布小型工具包；不需要因此重新构建 Scout/BFB 等大镜像。

依据：[NICo Reference Installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation)、[Helm OCI](https://helm.sh/docs/v3/topics/registries/)。恢复机制为本项目实现，不是 NICo 官方安装器功能。
