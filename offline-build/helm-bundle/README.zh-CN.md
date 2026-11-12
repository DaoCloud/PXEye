# 第二步：构建离线交付包

[English](README.md) · **简体中文** · [三步总览](../README.zh-CN.md)

`build.py` 在构建机上将 prepared 镜像和 Chart 打包为离线交付件。prepared 输入包含已构建的材料镜像；部署环境参数由第三步配置。

## 构建阶段

| 阶段 | 处理内容 | 约束与产物 |
| --- | --- | --- |
| 输入与工具校验 | 核对 prepared 摘要及锁定工具 | 直接使用第一步生成的配置 |
| 镜像暂存 | 在本地 loopback Registry 中准备镜像 | 按 digest 复用已导入内容 |
| Chart 渲染 | 检查配置和真实镜像依赖 | 不允许引用未包含的镜像 |
| relok8s 打包 | 逐 Chart 收集离线镜像 | 完成的 Chart 验证后复用 |
| 压缩与验包 | 压缩交付包并逐文件读回 | 成功后发布完整版本目录 |
| 现场工具交付 | 导出小型执行工具包 | 提供第三步执行入口及配置模板 |

## 构建命令

构建使用第一步生成的配置，沿用 prepared 中的镜像清单与版本。环境要求见[总览](../README.zh-CN.md#执行条件与路径)。

第一步的 `NEXT_COMMAND` 输出完整构建命令，`HELM_BUILD_CONFIG` 输出配置文件路径。以下示例通过交互输入指定该配置：

```bash
read -r -p '粘贴 HELM_BUILD_CONFIG 的绝对路径: ' HELM_CONFIG
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config "$HELM_CONFIG"
```

确认：出现 `HELM_BUILD_COMPLETE`；`DELIVERY_FILES` 会列出要复制到火种机的三个文件。

配置由第一步生成，只包含 prepared 路径、输出父目录、包名、材料开关和工具路径。换构建机时修改本地路径即可。首次缺少工具时会准备锁定版本；完全断网需提前缓存工具及 Registry 镜像。

## 交付产物

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

前三个文件组成[第三步](../onsite/README.zh-CN.md)的部署输入，示例交付目录为火种机 `/srv/nico/`。prepared、缓存和构建 Registry 数据仅供构建使用。大包包含完整文件清单；材料原文件封装在镜像中。

## 失败续跑与日志

修复原因后重跑原命令。同配置自动记住版本；已完成的镜像、Chart 和完整归档验证后复用，未完成阶段重新执行。成功版本重跑会核验并输出 `HELM_BUILD_REUSED`。创建另一个交付版本才使用 `--version`。

| 位置 | 用途 |
| --- | --- |
| `output_root/.<version>.building/` | 构建暂存目录，保留恢复所需的中间产物 |
| `progress.json` | 当前阶段、次数、耗时、失败原因 |
| `events.jsonl` / `run.log` | 追加阶段历史和终端输出 |
| `logs/`、`*-relok8s.log` | 具体命令输出及退出结果 |

恢复粒度为阶段，不是文件字节偏移。输入、配置或源码版本改变时使用新版本，不能混用旧断点。Registry 容器退出时停止，失败保留其数据和端口；成功后清理本次临时数据。

兼容 `nico-materials` 输入及其内置材料构建逻辑；prepared 输入使用第一步生成的材料镜像。依据：[relok8s 0.5.4](https://github.com/vmware-tanzu/asset-relocation-tool-for-kubernetes/tree/v0.5.4)、[Helm OCI](https://helm.sh/docs/v3/topics/registries/)。
