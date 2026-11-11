# 第一步：准备离线材料

[English](README.md) · **简体中文** · [三步总览](../README.zh-CN.md)

**目标：把原始输入整理成可独立交接的 prepared 目录。执行位置：构建机。** 不访问 Kubernetes，不部署服务，不填写现场地址。

## 脚本会经历哪些阶段

| 阶段 | 做什么 | 关注什么 |
| --- | --- | --- |
| 输入与版本校验 | 按固定配方检查镜像归档、Chart 和材料摘要 | 使用明确版本，不自动取运行集群最新镜像 |
| 镜像准备 | 导入选中的 Core、PXEye 和工具镜像 | 当前为13张输入镜像 |
| 材料镜像构建 | 按开关构建 ARM64 Scout、APT、BFB 镜像 | 全部开启时共16张镜像；已有有效缓存可复用 |
| Chart 与内容验收 | 准备兼容 Chart，校验 OCI 和材料镜像内文件 | 不重新编译 NICo；x86启动材料只做镜像层校验 |
| 发布产物 | 生成文件清单、来源、日志和第二步配置 | 复制终端输出的下一步完整命令 |

## 配置一次，执行一个脚本

主要目标：指定原始文件位置、输出位置和材料开关。前提见[总览](../README.zh-CN.md#执行条件与路径)，仓库位于 `/srv/PXEye`。以下准备命令只执行一次：

```bash
mkdir -p /srv/nico-build
test ! -e /srv/nico-build/build-config.json &&
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json /srv/nico-build/build-config.json &&
${EDITOR:-vi} /srv/nico-build/build-config.json
```

只维护 `build-config.json`：

| 配置 | 填什么 |
| --- | --- |
| `input_root` / `archives` | 原始 Chart、材料根目录及三份镜像归档路径 |
| `output_root` / `cache_directory` | prepared 目录与独立缓存位置，放在源码和输入目录之外 |
| `package_output_root` | 第二步交付包的输出父目录 |
| `include` | 是否包含 ARM64 Scout、APT、BFB |
| `recipe` / `tools` | 维护者锁定配方及本地工具；完全断网时提供已缓存 relok8s 路径 |

执行命令：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json
```

确认：出现 `MATERIAL_PREPARE_COMPLETE`、`HELM_BUILD_CONFIG` 和 `NEXT_COMMAND`。执行 `NEXT_COMMAND` 后面的完整命令即可进入[第二步](../helm-bundle/README.zh-CN.md)，无需手工创建第二步配置。

## 输出与失败处理

```text
output_root/
  <id>/
    prepared.json
    images/layout/          # 独立OCI镜像布局
    deployment/             # Chart及补丁证据
    tools/helm
    manifests/              # 镜像锁、材料文件、完整文件清单
    reports/                # 来源与耗时
    logs/
  <id>.helm-build.json       # 第二步直接使用
  <id>.result.json
```

失败后修复原因，再运行原命令；保留暂存目录和日志，核验后复用有效材料缓存或完整 prepared 产物。第一步不采用第二、三步的阶段断点格式，也不生成最终压缩包。

prepared 可以独立搬到其他打包机；此时修改生成配置中的本地路径，材料开关必须与 prepared 一致。当前配方范围见[总览](../README.zh-CN.md)，不支持通用 NICo 源码编译。
