# 第一步：准备 NICo / PXEye 离线材料

[English](README.md) · **简体中文**

本目录与第二步 `../helm-bundle/` 并列。第一步只运行 `build.py`，用户只维护一份 `build-config.json`。脚本自行检查输入、导入选定镜像、构建材料镜像、校验镜像内材料、准备兼容 Chart、生成清单和第二步配置，不访问 Kubernetes、不部署服务。

当前版本配方为 `recipe-e703.json`：11张Core/基础依赖镜像、1张PXEye应用镜像、1张离线工具镜像，以及按开关构建的ARM64 Scout、APT、BFB镜像。镜像用途、引用、不可变摘要及15项材料文件由配方维护。它是明确锁定的e703基线，不自动取运行集群最新镜像；不包含REST/Temporal/Keycloak、独立DNS Resolver或DPF服务。Ubuntu ISO不包含。现有NICo程序镜像复用发行归档，本脚本构建的是材料镜像，不重新编译NICo。

## 1. 准备配置

主要目标：构建机具备Linux x86_64、Python3.11+/PyYAML、Docker本地服务、Helm3、足够空间；输入目录含配方要求的原始Chart与材料，归档路径可独立指定。源码仓库假定为`/srv/PXEye`。不需要先生成旧版通用材料包。

执行命令（构建机Bash）：

```bash
mkdir -p /srv/nico-build
cp /srv/PXEye/offline-build/material-prepare/build-config.example.json /srv/nico-build/build-config.json
${EDITOR:-vi} /srv/nico-build/build-config.json
```

确认命令：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json --plan
```

| 配置字段 | 填写内容 |
| --- | --- |
| recipe | 维护者版本配方；默认`recipe-e703.json`在脚本目录解析，用户无需复制或编辑锁清单 |
| input_root | 原始Chart和材料的绝对根目录；下含`charts/`、`boot/aarch64/`、`boot/apt/`、`http/nico/dpu/` |
| archives.base / ui / bootstrap | OCI归档绝对路径，或相对于input_root；允许首轮显式迁移已有归档，归档和镜像摘要均核对 |
| output_root | prepared输出父目录；不能位于Git仓库或输入目录内 |
| cache_directory | 材料镜像缓存；与prepared分开，丢失后可重新构建，不是唯一交接产物 |
| package_output_root | 自动生成的第二步配置使用的最终归档输出父目录 |
| include.aarch64 / apt / bfb | 是否构建这些材料镜像；开关对应输入缺失时提前报错 |
| tools.docker / helm / relok8s | 构建工具；relok8s仅传给第二步，null表示由第二步按锁准备 |

不填写现场Registry、namespace、IP、BMC或认证参数。默认配方使用本地归档；维护者可将普通镜像来源改为`registry`，必须锁定amd64 manifest摘要，并使用构建机受信任的Registry。该扩展尚需单独验证；bootstrap工具仍要求归档。当前没有通用源码编译模式，不能把材料构建成功当成NICo源码重编译通过。

## 2. 一条命令完成第一步

主要目标：执行整个材料准备过程。无需手动启动Registry、逐张导入、构建或导出。

执行命令：

```bash
python3 /srv/PXEye/offline-build/material-prepare/build.py --config /srv/nico-build/build-config.json
```

确认命令：

```bash
ls /srv/nico-build/prepared/*.result.json
```

成功标志为`MATERIAL_PREPARE_COMPLETE <目录>`和`HELM_BUILD_CONFIG <文件>`。真实命令输出及详细日志由脚本保留；长步骤在执行前显示命令，Docker构建/Push日志保存在暂存目录，成功后转入logs。失败保留`.building-*`，不覆盖旧成功产物，不全局清理Docker。相同输入和构建源码生成相同prepared标识，重复执行全量验收后输出REUSE；配置输出路径改变时需选新output_root。材料缓存键只包含文件内容、发布脚本、基础镜像、平台与构建配方，不含发行包日期。

脚本只启动本轮临时loopback Registry并在退出时停止，不建立持久Registry。Docker底层构建缓存可能保留；只移除本轮创建的工具/输出标签，不删除他人镜像或容器。材料基础镜像当前复用锁定的离线工具镜像，包含Python和skopeo，不称为最小基础镜像。

## 3. 产物与第二步衔接

主要目标：明确第一步全部产物的位置。第一步不生成最终`bundle.tar.gz`；该压缩包由第二步生成。

```text
/srv/nico-build/
  build-config.json
  cache/materials/<内容摘要>/       # 可复用OCI材料镜像
  prepared/
    <输入及构建实现标识>/
      prepared.json                # 完整完成标记、范围和源码版本
      images/layout/               # 独立OCI布局，包含所有选定镜像和blob
      deployment/charts/           # Core、cert-manager、平台Chart
      deployment/patches/          # 已应用的兼容补丁证据
      tools/helm
      manifests/images-lock.json   # 镜像用途、来源、digest
      manifests/materials.json     # 镜像内材料路径、SHA及发布路径
      manifests/files.json         # 全部产物文件大小与SHA
      reports/sources.json         # 配方、实现摘要和来源
      reports/timings.json         # IMPORT/FETCH/BUILD/REUSE逐项耗时
      logs/                        # Docker与Registry真实日志
    <同一标识>.helm-build.json      # 自动生成的第二步配置
    <同一标识>.result.json
  output/<第二步版本>/
    bundle.tar.gz
    SHA256SUMS
    build-result.json
    bundle/                        # 最终交付包的解压树
```

执行命令（第二步，替换为第一步打印的真实配置路径）：

```bash
python3 /srv/PXEye/offline-build/helm-bundle/build.py --config /srv/nico-build/prepared/实际标识.helm-build.json
```

确认命令：

```bash
ls /srv/nico-build/output/*/build-result.json
```

第二步识别`nico-prepared`后只导入已准备镜像、渲染、relok8s打包和压缩读回，不执行材料镜像build。它仍需Docker临时Registry和锁定relok8s工具；prepared可独立搬到其他打包机，不依赖第一步缓存或容器。转移时修改第二步配置的`materials_bundle`和本地工具/输出路径。第二步选项必须与prepared开关一致。详见[第二步说明](../helm-bundle/README.zh-CN.md)。
