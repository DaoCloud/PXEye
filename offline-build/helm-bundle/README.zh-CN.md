# 第二步：构建离线交付包

[English](README.md) · **简体中文** · [三步总览](../README.zh-CN.md)

**目标：将 prepared 镜像和 Chart 打包为现场交付件。执行位置：构建机。** 不访问 Kubernetes，不填写现场参数，推荐路径不再构建材料镜像。

## 脚本会经历哪些阶段

| 阶段 | 做什么 | 关注什么 |
| --- | --- | --- |
| 输入与工具校验 | 核对 prepared 摘要及锁定工具 | 直接使用第一步生成的配置 |
| 镜像暂存 | 在本地 loopback Registry 中准备镜像 | 按 digest 复用已导入内容 |
| Chart 渲染 | 检查配置和真实镜像依赖 | 不允许引用未包含的镜像 |
| relok8s 打包 | 逐 Chart 收集离线镜像 | 完成的 Chart 验证后复用 |
| 压缩与验包 | 压缩交付包并逐文件读回 | 成功后发布完整版本目录 |
| 现场工具交付 | 导出小型执行工具包 | 与大包一起交付，不让现场临时找脚本 |

## 执行一个脚本

主要目标：沿用第一步的输入和版本，不再手工配置镜像列表。前提见[总览](../README.zh-CN.md#执行条件与路径)。

**推荐直接执行第一步打印的 `NEXT_COMMAND` 后面的完整命令。** 如果已换终端，也可以用下面两行选择第一步 `HELM_BUILD_CONFIG` 打印的真实路径：

```bash
read -r -p '粘贴 HELM_BUILD_CONFIG 的绝对路径: ' HELM_CONFIG
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config "$HELM_CONFIG"
```

确认：出现 `HELM_BUILD_COMPLETE`；`DELIVERY_FILES` 会列出要复制到火种机的三个文件。

配置由第一步生成，只包含 prepared 路径、输出父目录、包名、材料开关和工具路径。换构建机时修改本地路径即可。首次缺少工具时会准备锁定版本；完全断网需提前缓存工具及 Registry 镜像。

## 交付哪些文件

```text
output_root/<version>/
  bundle.tar.gz             # Chart、relok8s镜像包、清单及离线工具
  onsite-tools.tar.gz       # 第三步启动脚本及配置模板
  SHA256SUMS                # 同时校验上面两个归档
  build-result.json
  progress.json
  events.jsonl
  run.log
  logs/
  bundle/                   # 完整交付内容的解压树
```

**只需把前三个文件复制到火种机 `/srv/nico/`，然后执行[第三步](../onsite/README.zh-CN.md)。** 不复制 prepared、缓存或构建用 Registry 数据。大包内有完整文件清单；材料原文件位于镜像中。

## 失败续跑与日志

修复原因后重跑原命令。同配置自动记住版本；已完成的镜像、Chart 和完整归档验证后复用，未完成阶段重新执行。成功版本重跑会核验并输出 `HELM_BUILD_REUSED`。创建另一个交付版本才使用 `--version`。

| 位置 | 用途 |
| --- | --- |
| `output_root/.<version>.building/` | 失败现场，使用 `ls -la` 可见；不要删除 |
| `progress.json` | 当前阶段、次数、耗时、失败原因 |
| `events.jsonl` / `run.log` | 追加阶段历史和终端输出 |
| `logs/`、`*-relok8s.log` | 具体命令输出及退出结果 |

恢复粒度为阶段，不是文件字节偏移。输入、配置或源码版本改变时使用新版本，不能混用旧断点。Registry 容器退出时停止，失败保留其数据和端口；成功后清理本次临时数据。

兼容旧 `nico-materials` 输入，但它仍包含旧的材料构建逻辑；新任务使用第一步的 prepared 输入。依据：[relok8s 0.5.4](https://github.com/vmware-tanzu/asset-relocation-tool-for-kubernetes/tree/v0.5.4)、[Helm OCI](https://helm.sh/docs/v3/topics/registries/)。
