"""Bounded subprocess execution with credential-safe failures."""

import re
import subprocess
from pathlib import Path
from pxeye.clients.errors import RPCRequestError


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
        if Path(argv[0]).name in ("ssh", "sshpass"):
            if "REMOTE HOST IDENTIFICATION HAS CHANGED" in result.stderr:
                raise RuntimeError(
                    "SSH 主机密钥与本轮可信记录不同；请通过认证 BMC 控制台核实后继续验收。"
                )
            if "Permission denied" in result.stderr:
                raise RuntimeError("SSH 认证失败；请检查本轮安装的登录账号与认证配置。")
        raise RuntimeError(f"{Path(argv[0]).name} 执行失败（退出码 {result.returncode}）。")
    return result.stdout
