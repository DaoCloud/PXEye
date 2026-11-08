---
page_id: operating-systems
language: zh-CN
title: 操作系统
description: 导入 Ubuntu ISO、准备引导文件并登记可用于装机的 OS。
navigation_group: resources
updated_at: "2026-11-08"
product_version: "0.21.26"
---

# 操作系统

[English](operating-systems.md) · **简体中文** · [页面使用指南](README.zh-CN.md)

## 1. 用途与入口

进入 **资源 → 操作系统**，上传或选择服务器目录中的 ISO，准备引导材料并登记 NICo OS 定义。准备好的 OS 供[安装方案](installation-profiles.zh-CN.md)和设备系统配置选择。

使用前，PXEye 的材料目录须可写并持久保存，NICo PXE HTTP 须能发布同一份文件，目标主机须能访问发布 URL。配置方法见[部署指南](../deployment.zh-CN.md#4-挂载与发布材料)。

## 2. 字段填写

| 字段 | 填写要求 |
| --- | --- |
| OS 版本名称 | 必填，最多 100 个字符；建议标明发行版、版本和架构。 |
| ISO 文件 | 通过**上传 ISO**选择本机 `.iso` 文件；默认大小上限为 16 GiB，以部署配置为准。 |
| 目录中的 ISO | 通过**使用服务器 ISO**选择已挂载来源目录中的文件；不是浏览器本机路径，也不能输入任意服务器路径。 |
| SHA256 校验值 | 可选；填写材料来源提供的 64 位十六进制摘要，不填时系统仍计算摘要。 |
| 架构 / 安装器 | 自动从 ISO 元数据识别；支持 Ubuntu Server 的 `amd64 → x86_64`、`arm64 → aarch64`。 |

## 3. 操作步骤

### 浏览器上传

1. 点击**上传 ISO**，填写名称，选择文件和可选校验值，点击**上传并准备**。
2. 等待上传和提取完成；中断时点击**继续上传**并重新选择同名、同大小的原文件。
3. 系统提取后自动登记；如果停留在**已准备 · 待登记**，点击**继续准备并登记**。
4. 显示**已登记**后点击**设为可用**，再到安装方案中选择该 OS。

### 服务器目录导入

1. 将 ISO 放入已配置并挂载到 PXEye 的来源目录顶层，点击**使用服务器 ISO**。
2. 选择**目录中的 ISO**，填写名称和可选校验值，点击**导入并准备**。
3. 系统复制 ISO、提取引导文件并自动登记；登记完成后点击**设为可用**。

点击 OS 名称查看材料来源、NICo OS ID，以及 ISO、kernel、initrd 的发布 URL、大小和 SHA256。准备失败或需要核对时，使用**核对 / 重新准备**，检查错误后再继续。

## 4. 填写示例

| 项目 | 示例 |
| --- | --- |
| OS 版本名称 | `Ubuntu Server 24.04 ARM64` |
| ISO | 来源目录中的 `ubuntu-24.04-live-server-arm64.iso` |
| 校验值 | 文件提供方公布的 SHA256；没有时留空。 |

系统在材料目录创建独立版本目录：

```text
/materials/<OS-ID>/
  install.iso
  kernel
  initrd
  info.txt
```

本例目录对应 `os_library.directory=/materials`。前三个文件通过已配置的 `public_base_url/<OS-ID>/` 发布；`info.txt` 用于识别发行信息。URL 和内核启动参数由系统生成，无需修改 ISO。逐机自动安装配置在创建安装任务时另行生成。

## 5. 注意事项

- 当前支持 Ubuntu Server 自动安装；其他安装器或缺少标准 `/.disk/info`、`/casper/vmlinuz`、`/casper/initrd` 的 ISO 需另行适配。
- ARM64 ISO 登记成功只代表材料已准备；主机还需匹配的 ARM64 EFI、Scout 及安装方案。
- 有活动安装任务引用的 OS 不能停用、重新准备或取消。需要更新材料时导入独立版本。
- **取消此版本**会删除本版本准备文件；服务器来源 ISO 保留。NICo 既有记录不等于 PXEye 已准备完整材料。
- 材料服务检查从 PXEye 发起；现场仍须验证待安装主机的下载路径。

相关：[安装方案](installation-profiles.zh-CN.md) · [安装任务](installation-tasks.zh-CN.md) · [装机前检查](../pre-installation-checklist.zh-CN.md)
