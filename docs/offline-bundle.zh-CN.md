# 制作完整的 NICo Core 离线安装包

[English](offline-bundle.md) · **简体中文** · [文档索引](README.zh-CN.md)

在 Linux amd64 制作机执行 `tools/build-nico-offline-bundle.py`。它组装已经构建好的镜像和材料，不编译NICo、不构建PXEye镜像、不部署Kubernetes资源，也不读取运行站点的凭据。依赖Python3.11+/PyYAML、GNU patch、Helm3及足够磁盘空间；导入阶段的PXEye镜像需Python3.12+以安全解包。

## 输入与执行命令

准备固定e703126e4原始离线包、两张单镜像OCI归档（UI至少0.22.16，Vault初始化使用已核验包含CLI的镜像），以及基于[build.example.json](../deploy/offline-core/build.example.json)的站点构建配置。归档路径相对配置文件解析。示例不是现场配置，须填写实际规划的Registry、context、服务地址和归档内原始引用；不填写密码、私钥或Secret。

在制作机干净且已提交的PXEye源码目录执行：

```bash
python3 tools/build-nico-offline-bundle.py \
  --source-bundle /srv/nico-input/base-bundle \
  --config /srv/nico-input/site-build.json \
  --version 20261110T180000Z \
  --source-revision "$(git rev-parse HEAD)" \
  --output /srv/nico-output/20261110T180000Z
```

如果源码来自Git archive，直接提供导出时的完整commit。输出目录必须不存在且在输入目录之外。重复制作使用新的版本和输出目录；同一路径有构建锁，旧产物不会覆盖；失败保留`.building-*`目录供排查。

产物包含`bundle/`、`bundle.tar.gz`、`SHA256SUMS`、`build-result.json`，四项一起交付。复制后确认：

```bash
cd /srv/nico-output/20261110T180000Z
sha256sum -c SHA256SUMS
python3 bundle/tools/verify-bundle.py bundle
```

包内`bundle/docs/INSTALL.md`根据实际构建输入生成，按依赖顺序给出执行/确认命令。两张PXEye镜像、runtime配置、namespaced及cluster RBAC、首个Pod就带挂载的完整Deployment、正常登录API工具、镜像导入工具和验收工具均随包提供；口令在包外交互生成。本配方针对已有`/home/kind` bind mount的Podman Kind节点，以及已有无认证HTTPS Registry Service；不创建这些基础设施，也不配置Harbor认证。

## 已固化的故障修复和门禁

- 原始Chart与OCI固定SHA256，验证完整OCI blob和amd64镜像图。
- UI/Vault初始化两张额外OCI归档、源引用及目标manifest锁，不再只交付23镜像。
- 原始boot/DPU/HTTP/source材料按原清单逐项验证后复制。
- cert-manager选举namespace，以及startup检查Job/SA/RBAC的全部hook依赖。
- PostgreSQL TLS、Vault初始化/维护SA角色、带前缀的生成Secret引用。
- 证书CN长度、规范SPIFFE身份、管理员中间CA公钥信任和完整API FQDN；不绕过认证。
- migration截止时间与标签、当前Kea插件路径、硬件健康API环境变量。
- DNS/PXE/NTP Service IP与Kea DHCP参数共用输入，服务地址明确固定并核对。
- 四阶段Helm真实渲染：13个单副本工作负载、namespace一致、无未替换字段、全部镜像在锁内。
- 配方/文件清单/descriptor/外层归档摘要和源码溯源；不硬链接输入，不复制运行数据库、kubeconfig或站点私密状态。清单只排除其自身。

其他上游Chart版本会被拒绝，须评审后新增兼容配方，不能强行复用补丁。虽然保留原包ARM/DPU材料，本recipe只配置x86引导镜像路径；不代表ARM OS装机、完整DPU管理、物理DHCP/PXE或生产HA已通过。构建检查成功与新集群冷启动验收必须分别记录。
