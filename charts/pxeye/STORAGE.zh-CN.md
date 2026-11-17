# 共享存储

[English](STORAGE.md) · **简体中文**

PXEye 使用一个 PVC 保存应用数据、来源 ISO 和导入材料。NICo PXE 只读挂载其中的 HTTP 子目录，通过现有 HTTP 服务提供文件下载；不新增 HTTP 服务或材料 PVC。数据库和 Vault 保留各自的 PVC。

## 目录

| PVC 子目录 | PXEye 路径 | 用途 | NICo PXE 是否挂载 |
| --- | --- | --- | --- |
| `data` | `/data` | 应用配置、数据库、任务记录 | 否 |
| `iso-sources` | `/iso-sources` | 待导入的 ISO | 否 |
| `staging` | `/staging` | 预留的准备空间；现有导入逻辑保持不变 | 否 |
| `http/nico/os-library` | `/materials` | 导入后的 ISO、kernel、initrd | 是，只读挂载其父目录 `http/nico` |

NICo PXE 挂载位置为 `<servePath>/blobs/internal/nico`，材料 URL 保持 `/public/blobs/internal/nico/os-library/<OS-ID>/<文件名>`。现有 `blobs/internal/x86_64`、`aarch64` 等 Boot 材料和动态 NoCloud 路由保持原有处理。

initContainer 使用现有 PXEye 镜像中的 Python 与 ConfigMap 脚本，在主容器启动前补齐目录并登记默认 ISO 来源。已有目录和文件保留，不执行递归权限重设；冲突文件、符号链接或权限不足会阻止启动并说明原因。旧保存配置缺少 ISO 来源时仅补默认值，保留其余字段。

## 参数与调度

```yaml
storageClass: your-storage-class
sharedStorage:
  size: 200Gi
  accessMode: ReadWriteOnce
  existingClaim: ''
```

未指定 `existingClaim` 时创建 `<PXEye release>-storage`；指定时复用同 namespace 下的现有卷，不创建新 PVC。容量需要同时包括来源 ISO 和导入后的副本、提取文件、应用数据及预留空间。`size` 是新建卷的申请容量；现有卷需按存储类能力另行扩容。

离线第二步为固定 NICo PXE 子 Chart 注入共享挂载扩展；第三步自动设置：

```yaml
nicoCore:
  nico-pxe:
    pxeyeStorage:
      enabled: true
      claimName: <PXEye release>-storage
      ownerRelease: <PXEye release>
```

该扩展只适用于已包含它的交付 Chart；不能仅把这些 values 传给未扩展的上游 Chart。若使用 `existingClaim`，NICo PXE 的 `claimName` 必须同步填写实际卷名；第三步默认使用自动创建的卷。

NICo PXE 通过 required Pod affinity 与 PXEye 共节点，PXEye 仅对 PXE 使用 preferred affinity，避免双方启动互锁。两者必须在同一 namespace，节点需满足各自的资源与 nodeSelector 条件。PXE 启用共享后使用 Recreate 更新策略。

RWO 需要存储驱动允许同节点多个 Pod 同时挂载；同节点亲和性不能修复不支持此行为的驱动。RWX 也可使用，但本方案仍保持同节点调度。RWOP 不适用。不要设置 `nodeName` 绕过调度。

## 放入 ISO

在能够使用 kubectl 的终端执行：

```bash
kubectl --context "$CONTEXT" -n "$NAMESPACE" cp \
  ./ubuntu-server.iso "$PXEYE_POD:/iso-sources/ubuntu-server.iso.part"
kubectl --context "$CONTEXT" -n "$NAMESPACE" exec "$PXEYE_POD" -- \
  mv /iso-sources/ubuntu-server.iso.part /iso-sources/ubuntu-server.iso
```

在“操作系统 → 使用服务器 ISO”选择文件并导入。只扫描顶层普通 `.iso` 文件，不递归、不接受符号链接。无需在 Pod 内手工创建目录，也不需要登录节点寻找 PVC 底层路径。

## 从双 PVC 升级

不要直接用空卷覆盖旧数据。确认无活动安装任务，暂停 PXEye 写入，备份并复制旧 data 和 materials 到对应子目录，核对后切换。保留旧 PVC 作为回退；切换后旧卷不会自动删除。材料保持相同 OS-ID 与 URL，不能重新导入代替迁移。

最小验证包括：两个 Pod 共节点、目录初始化、来源扫描、PXEye 写入后 PXE HTTP 下载字节一致、只读挂载、私有目录不发布、重建后文件保留。Pod Ready 不代表真实装机验证完成。
