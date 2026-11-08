# 装机前检查清单

[English](pre-installation-checklist.md) · **简体中文** · [文档中心](README.zh-CN.md)

本表用于站点准备和首台服务器装机：首次 Scout 启动前完成第 1 节，写入主机 OS 前完成第 2 节，使用受管 DPU 时追加第 3 节；OS 材料和设备配置可以在部署 PXEye 后通过界面准备。

本表列出装机准备要求，PXEye 自动预检只覆盖所选流程中已经实现的检查。

## 1. 发现与首次 Scout 启动前

### 平台与 NICo

- NICo 及依赖已部署并记录版本，Core、DHCP、PXE、DNS、NTP 和凭据服务可用。
- 控制面镜像和管理客户端与各自执行节点的 CPU 架构匹配，且在目标环境可获取。
- PXEye 运行环境能使用已配置的 CA、客户端证书和私钥访问 Core 并完成认证。
- PXEye 配置、凭据、数据和安装材料已配置所需挂载、权限、容量及备份方式。
- K8s/Kind 的实际 DHCP、引导 HTTP、Core、UI 和安装回执入口可从对应网络访问。

配置方法、文件名和挂载位置见[部署指南](deployment.zh-CN.md)。

### 硬件与访问

- 每台主机的序列号、CPU 架构、BMC/PXE 永久 MAC 和交换机接线与设备清单一致。
- 控制面实际路径可通过 HTTPS 访问正确的 BMC，账号具备读取身份及所需启动、电源和管理权限。
- 接管前已安全配置初始 BMC 凭据及所用 NICo 版本要求的站点 BMC/UEFI 默认凭据。
- 设备所有者已确认维护窗口、数据备份和首次接管允许清理的磁盘范围。
- 主机 UEFI 网络启动、相关固件和 Secure Boot 设置兼容所选引导材料，且有可用救援控制台。

接管准备见 NVIDIA [BMC and Out-of-Band Setup](https://docs.nvidia.com/infra-controller/documentation/getting-started/prerequisites/bmc-and-out-of-band-setup)。

### 网络与 DHCP

- BMC 与主机引导/管理网络已明确 CIDR、网关、VLAN/VRF、MTU、DNS 和 NTP 配置。
- 所需 DHCP Relay 已指向 NICo 实际 DHCP 入口，`giaddr` 或已启用的 Link Selection 地址可匹配目标 NICo 子网。
- NICo 子网策略和逐 MAC 固定预留已生效，且与动态池、基础设施地址及其他 DHCP 服务无冲突。
- 路由、ACL、防火墙及 DHCP snooping 放行请求和回程，动态 PXE/元数据路径保留 NICo 所需的客户端身份。
- 每个装机网络的授权测试客户端已完成 Discover、Offer、Request、ACK，并取得正确地址和引导选项。
- 真实装机网络的测试客户端可访问所需引导 HTTP、Core、DNS、NTP 和软件源。

配置与验证方法见 NVIDIA [IP and Network Configuration](https://docs.nvidia.com/infra-controller/documentation/provisioning-day-0/ip-and-network-configuration)。

## 2. 写入主机 OS 前

责任方：OS 供应方、硬件/网络团队及 PXEye 操作员；按[首台装机指南](getting-started.zh-CN.md)准备并核对实际生效配置。

- Scout 已回报目标主机的身份、引导接口和磁盘，且机器达到所选安装路径的就绪要求。
- ISO 已记录来源、版本、CPU 架构和校验值，支持所需无人值守接口，kernel/initrd 来自同一 ISO。
- 所选 OS 已登记到 NICo，启动 URL 和参数正确，并保留匹配架构的 EFI 与 Scout 发现材料。
- 安装方案的选盘和分区规则解析到已批准的目标存储，使用硬件 RAID 时已通过对应硬件工具准备阵列。
- 实际 hostname、接口 MAC、地址、网关和 DNS 与设备规划及所选安装方案一致。
- 已配置目标系统账号、SSH 认证和验收访问方式，并与 BMC 凭据分别管理。
- 真实主机网络能下载并校验已发布的 ISO、kernel/initrd 和安装元数据，且能访问所需软件包及安装回执入口。
- 操作员已核对目标设备、OS 和清理范围，任务预检已按实际生效的安装配置通过。

PXEye 在执行流程中准备或复用所需 Machine/Instance 和逐机安装数据，无需为填写本表再手工创建一份配置；首次接管清理范围可能大于 OS 系统盘选择范围。

## 3. 受管 DPU 追加检查

责任方：硬件、网络、平台及 NICo 团队；所选流程不安装 DPU OS 时本节可标为不适用，仍需另行确认适用的硬件和网络前提。

- 每块 DPU 的型号、PN/PSID、序列号、所属主机、工作模式及 NICo 管理策略已登记，并受所选软件组合支持。
- DPU BMC/OOB 接口、地址和凭据与清单一致，且实际访问路径和供给所需权限可用。
- 匹配型号的 BFB 系统包、固件/DOCA 版本及所需 DPF Chart 和容器依赖齐全，实际取件组件可下载。
- DPU 运行镜像与 DPU 架构匹配，分别核对 NICo 控制节点和主机 OS 的架构。
- 所选 DPU 流程需要的管理/Underlay 和租户网络已配置，并在适用时完成路由与 Fabric 配置。
- DPU 恢复材料和救援入口已准备，分别定义 DPU 供给、服务和主机 OS 安装的验收条件。

BFB 是 DPU 系统包，DPF 是管理框架；PXEye 的服务器 OS 安装任务不能替代 NICo/DPF 的 DPU 供给配置。

## 清单维护

每项保持一句话，命令和解释放到对应指南并在本表链接；同步维护中英文版本，完整检查统一更新本页，根 README 只保留简版摘要。

NVIDIA 文档是主要技术依据，要求仍需与集成 NICo 版本及实际硬件流程核对；ARM64 材料齐备、Pod Ready 或模拟通过不代表 ARM64/Grace 实机兼容验证，支持范围见[功能与边界](features.zh-CN.md)。
