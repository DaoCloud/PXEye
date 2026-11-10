#!/usr/bin/env python3
"""Probe DHCP with a chosen client MAC using Nmap's broadcast script."""

import argparse
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


def mac_address(value):
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", value):
        raise argparse.ArgumentTypeError("MAC 格式应为 02:00:00:00:00:01")
    if int(value[:2], 16) & 1 or value.lower() == "00:00:00:00:00:00":
        raise argparse.ArgumentTypeError("请使用非全零的单播 MAC 地址")
    return value.lower()


def interface_name(value):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", value):
        raise argparse.ArgumentTypeError("网卡名称无效")
    return value


def timeout_seconds(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("等待时间应为 1–120 秒的整数") from None
    if not 1 <= number <= 120:
        raise argparse.ArgumentTypeError("等待时间应为 1–120 秒的整数")
    return number


def arguments():
    parser = argparse.ArgumentParser(
        description="使用指定 MAC 发送 DHCP Discover，查看服务器返回的 Offer。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例（在待测试的 Linux 主机上执行，需要 Python 3 和 Nmap）：
  # 使用 eno1 的本机 MAC
  sudo python3 tools/dhcp-discover.py --interface eno1

  # 指定客户端 MAC，通过 eno1 发包，等待最多 10 秒
  sudo python3 tools/dhcp-discover.py -i eno1 --mac 02:00:00:00:00:01 --timeout 10

  # 使用其他位置的原始 Nmap 脚本
  sudo python3 tools/dhcp-discover.py -i eno1 --mac 02:00:00:00:00:02 \\
    --nmap-script /usr/share/nmap/scripts/broadcast-dhcp-discover.nse

仅执行 Discover/Offer 探测，不发送 DHCP Request，不修改网卡 IP。
临时副本会替换 Nmap 7.80 脚本中硬编码的客户端 MAC，结束后自动删除。
已有固定预留的 MAC 可能收到动态池外的预留地址。
Nmap 的 “No targets were specified” 提示不表示测试失败。
退出码：0=收到 Offer，1=未收到 Offer/环境错误，2=参数错误，124=执行超时。
""",
    )
    parser.add_argument(
        "-i", "-e", "--interface", required=True, type=interface_name, help="发送接口，例如 eno1"
    )
    parser.add_argument("--mac", type=mac_address, help="客户端 MAC；默认读取指定接口的本机 MAC")
    parser.add_argument(
        "--timeout", type=timeout_seconds, default=10, metavar="SECONDS", help="等待 Offer 的秒数，默认 10"
    )
    parser.add_argument("--nmap-script", type=Path, help="原始 broadcast-dhcp-discover.nse 路径")
    return parser.parse_args()


def find_script(nmap):
    candidates = (
        Path("/usr/share/nmap/scripts/broadcast-dhcp-discover.nse"),
        Path("/usr/local/share/nmap/scripts/broadcast-dhcp-discover.nse"),
        Path(nmap).resolve().parent.parent / "share/nmap/scripts/broadcast-dhcp-discover.nse",
    )
    return next((path for path in candidates if path.is_file()), None)


def probe(args):
    interface = Path("/sys/class/net") / args.interface
    if not interface.is_dir():
        raise ValueError(f"找不到 Linux 网卡：{args.interface}")
    nmap = shutil.which("nmap")
    if nmap is None:
        raise ValueError("未找到 nmap，请先安装 Nmap")
    mac = args.mac or mac_address((interface / "address").read_text().strip())
    script = args.nmap_script or find_script(nmap)
    if script is None:
        raise ValueError("找不到原始 Nmap 脚本，请通过 --nmap-script 指定")
    source = script.read_text()
    # Fail explicitly if a different Nmap version changes this assignment.
    pattern = r'(?m)^([ \t]*)local mac = "(?:\\x[0-9A-Fa-f]{2}){6}"[ \t]*$'
    replacement = 'local mac = "' + "".join("\\x" + part for part in mac.split(":")) + '"'
    updated, count = re.subn(pattern, lambda match: match[1] + replacement, source)
    if count != 1:
        raise ValueError("原始脚本不包含预期的硬编码 MAC 定义，未执行；请核对 Nmap 脚本版本")
    print(f"发送接口：{args.interface}；客户端 MAC：{mac}；等待：{args.timeout} 秒", flush=True)
    with tempfile.TemporaryDirectory(prefix="mmzhou-dhcp-") as directory:
        temporary = Path(directory) / "broadcast-dhcp-discover.nse"
        temporary.write_text(updated)
        command = [
            nmap, "-e", args.interface, "--script", str(temporary),
            "--script-args", f"broadcast-dhcp-discover.timeout={args.timeout}",
        ]
        print("执行命令：" + shlex.join(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout + 6)
        print(result.stdout, end="", flush=True)
        print(result.stderr, end="", file=sys.stderr, flush=True)
        if result.returncode:
            return result.returncode
        if "DHCPOFFER" not in result.stdout:
            print("未收到 DHCP Offer。", file=sys.stderr)
            return 1
        return 0


def main():
    args = arguments()
    try:
        return probe(args)
    except subprocess.TimeoutExpired:
        print("执行超时，Nmap 已终止，临时脚本已清理。", file=sys.stderr)
        return 124
    except (OSError, ValueError, argparse.ArgumentTypeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("测试已中断，临时脚本已清理。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
