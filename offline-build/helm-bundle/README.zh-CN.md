# 旧版 Helm 离线打包兼容入口

[English](README.md) · **简体中文**

本目录仅保留给早期 schema-1 prepared-materials 工作流的兼容用途。它是内部实现路径，
不是新的 PXEye/NICo 离线交付的标准入口。

请使用仓库根级工作流：

```bash
cd ~/pxeye-build/PXEye
REGISTRY=<registry-host:port> make images
REGISTRY=<registry-host:port> make cache-images
REGISTRY=<registry-host:port> make bundles
```

标准 `make bundles` 会渲染锁定的 PXEye 父 Chart，只导出该 Registry 的精确镜像闭包，
执行一次 relocation，并将交付件写入 `outputs_/output/`。可选 ARM64 引导材料只能通过
`INCLUDE_ARM64_MATERIALS=1` 和 `ARM64_MATERIALS_DIR` 启用；此行为必须由根级入口处理，
以保证材料镜像在第一次渲染 Chart 前已经进入闭包。

`build.py` 仍可用于迁移或检查已经生成的 schema-1 `materials_bundle`。它要求旧输入契约，
并且可能自行构建历史材料组。不要把它的 `output_root`、`bundle_id` 或 `include` 字段
与当前 `build-config.json` 混用，也不要用它制作标准现场交付包。

当前配置、产物、断点恢复和现场交接请参阅[离线交付说明](../README.zh-CN.md)。
