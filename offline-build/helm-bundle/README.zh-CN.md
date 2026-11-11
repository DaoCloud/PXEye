# 第二步：一键构建 Helm 离线交付包

[English](README.md) · **简体中文**

输入为[第一步](../material-prepare/README.zh-CN.md)生成的 `nico-prepared` 目录和自动生成的 `*.helm-build.json`。一个配置、一个执行入口；不填写现场 Registry、namespace 或网络参数，不访问 Kubernetes。推荐路径只打包镜像，不再构建材料镜像。

## 1. 准备配置

主要目标：使用第一步输出的配置文件。执行位置为 Linux amd64 构建机；前提为 Python 3.11+/PyYAML、Docker、本地 Unix Docker endpoint、Helm 3、已提交的源码，以及足够存储。第一步终端会打印第二步配置的绝对路径，将这份文件保存为 `/srv/nico-build/helm-build.json`；只维护该文件。

配置字段：

| 字段 | 内容 |
| --- | --- |
| `materials_bundle` | 第一步生成的完整 prepared 目录 |
| `output_root` | 交付包输出父目录，位于源码与输入目录之外 |
| `bundle_id` | 归档解压后的根目录名 |
| `include` | 必须与第一步的材料开关一致 |
| `tools` | Docker、Helm 与可选的已缓存 relok8s 绝对路径 |

首次未指定 relok8s 时下载并校验固定版本；断网构建必须提前提供该工具和锁定的 Registry 镜像。兼容旧 `nico-materials` 输入，但该路径仍会构建材料镜像；新构建优先使用第一步产物。

执行命令：

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config /srv/nico-build/helm-build.json
```

确认命令：

```bash
ls -la /srv/nico-build/output
```

`output_root` 以配置为准。成功输出 `HELM_BUILD_COMPLETE` 和最终目录；重复执行完成的版本输出 `HELM_BUILD_REUSED`。

## 2. 阶段、日志与失败续跑

主要目标：终端明确显示当前阶段；失败后修复原因，再运行原命令。

| 阶段 | 动作与恢复粒度 |
| --- | --- |
| 输入与工具 | 校验输入摘要、构建工具；续跑仍核对输入 |
| 镜像暂存 | 私有本地 Registry 持久存储；按 manifest digest 复用已导入镜像 |
| Chart 渲染 | 重新生成小型配置，校验实际镜像消费者 |
| Chart 离线打包 | 逐 Chart 校验并复用完成的 relok8s 包；失败的 Chart 重新执行 |
| 压缩 | 完整归档匹配清单与摘要时复用；未完成的压缩重新执行 |
| 验收 | 逐文件读回压缩包；成功后发布最终目录 |

执行命令（失败续跑与首次相同）：

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config /srv/nico-build/helm-build.json
```

确认命令：

```bash
find /srv/nico-build/output -name progress.json -o -name run.log -o -name events.jsonl
```

首次自动生成并记住版本，同配置重跑会继续该版本；创建另一个交付版本时才添加 `--version`。配置、输入清单或源码版本改变时拒绝混用旧记录，应选择新版本。不能跨文件字节偏移续传；恢复粒度为镜像、Chart 和归档阶段。初次旧脚本产生的随机 `.building-*` 目录不自动接管。

失败目录为 `output_root/.<version>.building/`，隐藏目录可以用 `ls -la` 查看。原始 Registry 数据和端口记录保留以便恢复，Registry 容器退出时停止，续跑恢复同一地址；端口被其他服务占用时明确失败，不改变旧引用。不会执行全局清理。

`progress.json` 原子更新阶段状态、尝试次数、起止时间、耗时、失败原因；`events.jsonl` 追加每次阶段结果；`run.log` 自动追加终端输出，无需手工 `tee`。命令日志保留实际退出码。不要修改或删除断点记录。

## 3. 交付目录与验包

主要目标：确认最终归档及清单。以下变量在本节设置为成功命令输出的绝对目录；示例版本为 `field-01`。

执行命令：

```bash
cd /srv/nico-build/output/field-01
sha256sum -c SHA256SUMS
python3 bundle/tools/verify.py bundle
```

确认命令：

```bash
cat build-result.json
cat progress.json
```

```text
output_root/
  .active-<config-hash>.json      # 记住本配置的版本；无需手工管理
  .<version>.building/           # 失败现场，成功后改名
  <version>/
    bundle.tar.gz
    SHA256SUMS
    build-result.json
    progress.json
    events.jsonl
    run.log
    logs/                       # Registry、镜像命令记录
    *-relok8s.log
    render/
    bundle/
      bundle.json
      charts/
      relocation/
      profiles/
      manifests/                # 文件清单、镜像锁、材料及构建报告
      tools/
        helm
        relok8s
        verify.py
        onsite/
          run.py                # 第三步唯一推荐执行入口
          run-config.example.json
      docs/
```

归档只包含 `bundle/` 交付内容，解压根名为 `bundle_id`；构建日志与进度保留在归档外。成功后删除本次 Registry 数据和临时构建目录。交付只需复制归档与 `SHA256SUMS`；现场运行见[第三步](../onsite/README.zh-CN.md)。已有旧大包可另行导出小型现场工具包，不必重建镜像。

Helm 打包成功不等于控制面安装、严格 mTLS、材料 HTTP、物理 DHCP 或 OS 装机验收通过。新包当前仍不支持旧 UI 自动读取 OCI 目录。

依据：[Helm OCI](https://helm.sh/docs/v3/topics/registries/)、[relok8s 0.5.4](https://github.com/vmware-tanzu/asset-relocation-tool-for-kubernetes/tree/v0.5.4)、[NICo Reference Installation](https://docs.nvidia.com/infra-controller/documentation/getting-started/installation-options/reference-installation)。
