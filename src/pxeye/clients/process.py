"""Bounded subprocess execution with credential-safe failures."""

import re
import subprocess
from pathlib import Path
from pxeye.clients.errors import RPCRequestError, RPCMethodUnavailableError


def run(argv, *, text=None, timeout=40, env=None):
    try:
        result = subprocess.run(
            argv, input=text, capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{Path(argv[0]).name} 执行超时（{timeout} 秒）。") from None
    if result.returncode:
        # CLI arguments may contain installation data. Never include argv or stderr in public errors.
        if (
            Path(argv[0]).name == "grpcurl"
            and result.returncode == 1
            and result.stderr.strip().startswith(
                f'Error invoking method "{argv[-1]}": error getting request data:'
            )
        ):
            method = argv[-1].rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9]+", method):
                method = "RPC"
            raise RPCRequestError(
                f"NICo {method} 请求数据解析失败，请求未发送；请检查接口字段编码。"
            )
        if Path(argv[0]).name == "grpcurl" and argv[-1].rsplit("/", 1)[-1] in (
            "FindNetworkSegmentDhcpRanges",
            "SetNetworkSegmentDhcpRange",
            "CreateNetworkSegmentWithDhcpRange",
        ):
            if re.search(r"does not include a method named|Code: Unimplemented\b", result.stderr):
                raise RPCMethodUnavailableError(
                    "当前 NICo Core 不支持 DHCP 地址池范围，请先升级 Core。"
                )
            # Only these bounded, server-owned diagnostics are safe to expose.
            outside = re.search(
                r"DHCP pool: existing dynamic addresses outside range: ([0-9., ]+)",
                result.stderr,
            )
            if outside:
                raise RuntimeError(
                    "新范围外仍有动态分配（最多列出20个）："
                    + outside[1][:320].strip()
                    + "。未修改地址池，请先处理这些分配。"
                )
            if "object of type DHCP pool" in result.stderr:
                raise RuntimeError("DHCP 地址池已变化，请刷新后重新配置。")
            if "DHCP pool: invalid IPv4 range or includes gateway/SVI" in result.stderr:
                raise RuntimeError("DHCP 范围无效，不能包含网关或交换机虚拟接口地址。")
            if "DHCP pool: only active site segments are supported" in result.stderr:
                raise RuntimeError("仅活动的站点子网可以配置 DHCP 地址池。")
        if Path(argv[0]).name in ("ssh", "sshpass"):
            if "REMOTE HOST IDENTIFICATION HAS CHANGED" in result.stderr:
                raise RuntimeError(
                    "SSH 主机密钥与本轮可信记录不同；请通过认证 BMC 控制台核实后继续验收。"
                )
            if "Permission denied" in result.stderr:
                raise RuntimeError("SSH 认证失败；请检查本轮安装的登录账号与认证配置。")
        raise RuntimeError(f"{Path(argv[0]).name} 执行失败（退出码 {result.returncode}）。")
    return result.stdout
