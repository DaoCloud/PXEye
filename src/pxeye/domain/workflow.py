"""Read-only impact descriptions and explicit authorization for native ingestion."""

from pxeye.common import digest


def installation_impact(check, config):
    pending = bool(check.get("deferred_first_install"))
    settings = config.get("site_explorer_settings", {})
    return {
        "system_disk": check.get("scope", {}).get("disk_serial")
        or check.get("scope", {}).get("disk_wwn"),
        "cleanup_scope": "all_disks" if pending else "none",
        "cleanup_detail": (
            "本设备全部磁盘，清单待采集或核对；原生接入可能清理所有磁盘，不能限制为OS系统盘。"
            if pending
            else "本任务无需重新放行原生接入清理；OS安装覆盖目标系统盘。"
        ),
        "policy_revision": digest(settings),
        "policy_source": "UI站点配置记录；不是NICo动态策略的实时读回",
        "evidence": "配置与API检查不代表已验证物理DHCP relay、PXE或Scout链路。",
    }


def authorize_impact(check, config, scope):
    impact = installation_impact(check, config)
    if impact["cleanup_scope"] == "all_disks" and scope != "all_disks":
        raise ValueError(
            "首次接入可能清理本设备全部磁盘；仅授权系统盘不能启动接入。请核对并明确确认全部磁盘范围。"
        )
    return impact
