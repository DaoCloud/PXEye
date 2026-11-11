"""Expected Machine admission and first installation on discovered, unallocated hosts."""

import copy
import ipaddress
import json
import re
import time
import uuid

import yaml

from pxeye.services.resources import Resources
from pxeye.common import atomic_json, digest, value_id
from pxeye.installation.storage_policy import scout_disks, select_disk, selection_label

HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
GATE = {
    "NotDiscovered": "BMC 尚未进入 NICo 发现；检查管理网络、地址与 Site Explorer。",
    "WaitingForIngestion": "待管理员确认接管",
    "IngestionMachineNotCreated": "NICo 已有接管关联，尚未创建 Machine；需核对发现状态",
    "IngestionMachineCreated": "已创建 Machine",
}


NVLINK_GPU_COUNT = 4


def nvlink_gpu_configs(profile):
    """Return gpu_configs attaching every GPU to the profile's default logical partition."""
    cfg = profile.get("nvlink")
    # Missing block or missing/false `enabled` key means NVLink is not managed at all.
    if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
        return None
    partition = str(cfg.get("default_logical_partition_id") or "").strip()
    try:
        uuid.UUID(partition)
    except ValueError:
        raise ValueError("已启用 NVLink，但默认逻辑分区 ID 无效。") from None
    return [
        {"device_instance": i, "logical_partition_id": {"value": partition}}
        for i in range(NVLINK_GPU_COUNT)
    ]


def discovery_info(machine):
    return (
        (machine.get("status") or {}).get("discovery_info") or machine.get("discovery_info") or {}
    )


def architecture(info):
    return {0: "aarch64", 1: "x86_64", "AARCH64": "aarch64", "X86_64": "x86_64"}.get(
        info.get("machine_arch"), info.get("machine_type")
    )


def scout_boot_guard(override):
    """Recognize explicit Scout masks without executing or exposing user data."""
    pxe = override.get("customPxe", override.get("custom_pxe")) or ""
    lines = [line for line in pxe.splitlines() if not line.lstrip().startswith("#")]
    if re.search(
        r"\bsystemd\.(?:rd\.)?mask=[\"\']?forge-scout(?:\.service)?(?=[\"\']|\s|$)",
        "\n".join(lines),
    ):
        return True
    raw = override.get("customUserData", override.get("custom_user_data")) or ""
    try:
        cloud = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        raise ValueError("主机自定义 cloud-init 无法解析；请核对引导配置，未自动修改。") from None
    if not isinstance(cloud, dict):
        return False
    for key in ("bootcmd", "runcmd"):
        for entry in cloud.get(key) or []:
            command = " ".join(str(x) for x in entry) if isinstance(entry, list) else str(entry)
            if re.search(
                r"\bsystemctl\b[^\n;&|]*\bmask\b[^\n;&|]*\bforge-scout(?:\.service)?\b", command
            ):
                return True
    return False


def preparation_message(progress):
    state = str(progress.get("state") or "")
    if state.startswith("WaitingForCleanup/HostCleanup"):
        return (
            "等待 Scout 执行 NICo 接入清理并回报完成；尚未下发 ISO 安装。"
            "已有硬件记录不代表 Scout 当前在线；若长时间不变，请检查 Scout 服务、API 连通性及清理日志。"
        )
    if state.startswith("WaitingForCleanup"):
        return "NICo 正在准备或完成接入清理；尚未下发 ISO 安装。当前状态：" + state
    if state == "Ready":
        return "NICo 已 Ready，核对系统盘后下发安装。"
    return (
        "NICo："
        + (state or "等待创建 Machine")
        + (
            "；已保存 Scout 硬件记录，尚未下发 ISO 安装"
            if progress.get("scout_received")
            else "；等待 Scout 硬件回报"
        )
    )


class Onboarding:
    def __init__(self, adapter, store, resources=None):
        self.adapter, self.store = adapter, store
        self.resources = resources or Resources(adapter, store)
        self.directory = adapter.data / "config" / "admissions"

    def profiles(self):
        from pxeye.services.profiles import InstallProfiles

        return InstallProfiles(self.adapter).selectable()

    def profile(self, key):
        from pxeye.services.profiles import InstallProfiles

        return InstallProfiles(self.adapter).get(key)

    def inventory_row(self, serial):
        matches = [
            r for r in self.resources.planned_inventory() if r["chassis_serial_number"] == serial
        ]
        if len(matches) != 1:
            raise ValueError("设备序列号不存在或关联不唯一。")
        return matches[0]

    def observed(self, rows=None):
        rows = self.resources.planned_inventory() if rows is None else rows
        machines = self.adapter.core(["machine", "show", "--hosts"], data=True)["machines"]
        instances = self.adapter.core(["instance", "show"], data=True)["instances"]
        from pxeye.services.instances import reconcile_releases

        reconcile_releases(self.adapter, instances, machines)
        result = {}
        for row in rows:
            mac = row["bmc_mac_address"].lower()
            matches = [
                m
                for m in machines
                if (m.get("bmc") or m.get("bmc_info") or {}).get("mac", "").lower() == mac
            ]
            # Older Core may omit BMC MAC; the interface binding is checked separately before installation.
            if not matches and row.get("bmc_ip_address"):
                matches = [
                    m
                    for m in machines
                    if (m.get("bmc") or m.get("bmc_info") or {}).get("ip") == row["bmc_ip_address"]
                ]
            if len(matches) > 1:
                raise ValueError("BMC 关联多个 Machine，须先核对硬件身份。")
            machine = matches[0] if matches else None
            assigned = [i for i in instances if i.get("machine_id") == (machine or {}).get("id")]
            info = discovery_info(machine or {})
            disks = scout_disks(info)
            identity_matches = bool(
                machine
                and (machine.get("bmc") or machine.get("bmc_info") or {}).get("mac", "").lower()
                == mac
                and row["chassis_serial_number"]
                in {
                    info.get("dmi_data", {}).get("product_serial"),
                    info.get("dmi_data", {}).get("chassis_serial"),
                }
            )
            ready = bool(
                machine
                and machine["state"] == "Ready"
                and not assigned
                and info
                and identity_matches
            )
            result[row["chassis_serial_number"]] = {
                "machine": machine,
                "instances": assigned,
                "disks": disks,
                "architecture": architecture(info),
                "first_install_ready": ready,
                "discovery_state": "assigned"
                if assigned
                else "ready"
                if ready
                else "discovering"
                if machine
                else "registered",
                "discovery_reason": "已有 Instance；请使用重装"
                if assigned
                else "可配置首次安装"
                if ready
                else (machine or {}).get("state", "已登记；先检查 BMC 发现并确认接管"),
                "failure_details": (machine or {}).get("status", {}).get("failure_details"),
            }
        return result

    def view(self, serial):
        row = self.inventory_row(serial)
        self.resources.check_address_operation(row)
        observed = self.observed([row])[serial]
        from pxeye.services.bmc_addresses import BMCAddresses

        address = BMCAddresses(self.adapter, self.resources).view(row)
        endpoint = {
            "ip_address": address["current_ip"] or row.get("bmc_ip_address", ""),
            "mac_address": row["bmc_mac_address"],
        }
        gate = self.adapter.rpc("DetermineMachineIngestionState", endpoint).get(
            "machineIngestionState", "NotDiscovered"
        )
        return {
            k: observed[k]
            for k in (
                "disks",
                "architecture",
                "first_install_ready",
                "discovery_state",
                "discovery_reason",
                "failure_details",
            )
        } | {
            "serial": serial,
            "machine_id": (observed["machine"] or {}).get("id"),
            "gate": gate,
            "gate_reason": GATE.get(gate, gate),
            "revision": digest(row),
            "bmc_ip": endpoint["ip_address"],
            "site_explorer_settings": self.adapter.config.get("site_explorer_settings", {}),
            "admission": self.admission(row["id"]),
        }

    def admission(self, key):
        path = self.directory / (str(uuid.UUID(key)) + ".json")
        return json.loads(path.read_text()) if path.exists() else None

    def admission_preview(self, body, owner):
        if (
            set(body) != {"serials"}
            or not isinstance(body["serials"], list)
            or not 1 <= len(body["serials"]) <= 50
            or len(set(body["serials"])) != len(body["serials"])
        ):
            raise ValueError("请选择 1–50 台不重复的设备。")
        checks = []
        for serial in body["serials"]:
            row = self.inventory_row(serial)
            check = {"serial": serial, "revision": digest(row), "passed": False}
            items = []
            check["items"] = items

            def inspect(key, label, action):
                try:
                    detail = action()
                    items.append({"key": key, "label": label, "status": "pass", "detail": detail})
                    return detail
                except (ValueError, RuntimeError) as error:
                    items.append(
                        {"key": key, "label": label, "status": "fail", "detail": str(error)}
                    )
                    return None

            observed = None

            def scope():
                nonlocal observed
                observed = self.observed([row])[serial]
                if self.store.active(serial):
                    raise ValueError("设备有活动任务或待处理现场；先查看安装任务。")
                previous = self.admission(row["id"])
                if previous:
                    raise ValueError(
                        "已有接管请求（" + previous["status"] + "）；先核对状态，不重复发送。"
                    )
                if observed["machine"] or observed["instances"]:
                    raise ValueError("设备已关联 Machine/Instance；请查看硬件准备状态。")
                return "无活动安装任务，无重复接管请求"

            inspect("scope", "任务与重复请求", scope)

            def credentials():
                if not row.get("bmc_retain_credentials"):
                    self.adapter.credentials(
                        {"credential_source": "managed", "bmc_retain_credentials": False}
                    )
                return (
                    "保留设备 BMC 凭据"
                    if row.get("bmc_retain_credentials")
                    else "已配置轮换后的站点 BMC 凭据"
                )

            inspect("credentials", "接管后 BMC 凭据", credentials)
            items.extend(self.preparation_checks(row))
            device = None

            def identity():
                nonlocal device
                device, system = self.probe(row)
                check["bmc_ip"] = device["bmc_ip"]
                return "HTTPS/Redfish 认证通过，SN=" + serial + "；BMC=" + device["bmc_ip"]

            inspect("identity", "BMC 可达、认证与主机 SN", identity)

            def gate_state():
                from pxeye.services.bmc_addresses import BMCAddresses

                current = (
                    device["bmc_ip"]
                    if device
                    else BMCAddresses(self.adapter, self.resources).view(row)["current_ip"]
                )
                gate = self.adapter.rpc(
                    "DetermineMachineIngestionState",
                    {
                        "ip_address": current or row.get("bmc_ip_address", ""),
                        "mac_address": row["bmc_mac_address"],
                    },
                ).get("machineIngestionState")
                check["gate"] = gate
                status = (
                    "pass"
                    if gate == "WaitingForIngestion"
                    else "wait"
                    if gate in ("IngestionMachineNotCreated", "IngestionMachineCreated")
                    else "fail"
                )
                items.append(
                    {
                        "key": "gate",
                        "label": "NICo 接管门控",
                        "status": status,
                        "detail": GATE.get(gate, "未知接管状态") + "（" + str(gate) + "）",
                    }
                )

            try:
                gate_state()
            except (ValueError, RuntimeError) as error:
                items.append(
                    {
                        "key": "gate",
                        "label": "NICo 接管门控",
                        "status": "fail",
                        "detail": str(error),
                    }
                )
            settings = self.adapter.config.get("site_explorer_settings", {})
            check["site_explorer_settings"] = settings
            items.append(
                {
                    "key": "scout",
                    "label": "Scout 硬件采集与 Ready",
                    "status": "pass" if observed and observed["first_install_ready"] else "wait",
                    "detail": "Scout 已采集硬件，Machine Ready"
                    if observed and observed["first_install_ready"]
                    else "尚未完成；需要主机经 PXE/iPXE 启动 Scout，回报网卡、磁盘和架构。",
                }
            )
            check["passed"] = all(i["status"] == "pass" for i in items if i["key"] != "scout")
            check["phase"] = (
                "approval"
                if check["passed"]
                else "waiting"
                if check.get("gate") in ("IngestionMachineNotCreated", "IngestionMachineCreated")
                else "blocked"
            )
            check["detail"] = (
                "检查通过，可确认放行硬件准备"
                if check["passed"]
                else "; ".join(i["detail"] for i in items if i["status"] == "fail")
                or GATE.get(check.get("gate"), "准备条件未通过")
            )
            check["next_action"] = (
                "确认后允许 NICo 开机并执行站点接管策略；完成 Scout 后返回安装任务。"
                if check["passed"]
                else "NICo 已有接管关联，本次不重复放行。查看硬件准备状态，核对 Site Explorer、主机网络启动与 Scout 注册。"
                if check["phase"] == "waiting"
                else "按未通过项目修改设备规划或站点条件，然后重新检查。"
            )
            if any(i["status"] == "fail" for i in items):
                check["next_action"] += " 同时按表中未通过项目修正准备条件。"
            if settings.get("create_machines") is False:
                check["next_action"] += (
                    " UI 站点配置记录 create_machines=false：依赖 Scout 自注册；该记录不是 NICo 动态配置的实时读回。"
                )
            checks.append(check)
        result = {
            "id": uuid.uuid4().hex,
            "type": "admission",
            "owner": owner,
            "checks": checks,
            "passed": all(c["passed"] for c in checks),
        }
        self.store.preflight(result["id"], result, lifetime=900)
        return {k: v for k, v in result.items() if k != "owner"}

    def admit_batch(self, body, owner, actor):
        if (
            set(body) != {"preflight_id", "confirm_serials", "confirm_ingestion", "cleanup_scope"}
            or body["confirm_ingestion"] is not True
            or body["cleanup_scope"] != "all_disks"
        ):
            raise ValueError("请确认设备范围及站点接管策略。")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM preflights WHERE id=?", (body["preflight_id"],)
            ).fetchone()
            if not row or row["used"] or row["expires"] < time.time():
                raise ValueError("接管预检失效或已发送；先核对当前状态。")
            check = json.loads(row["data"])
            if (
                check.get("type") != "admission"
                or check["owner"] != owner
                or not check["passed"]
                or body["confirm_serials"] != [c["serial"] for c in check["checks"]]
            ):
                raise ValueError("接管预检与设备确认不匹配。")
            db.execute("UPDATE preflights SET used=1 WHERE id=?", (body["preflight_id"],))
        record = {
            "id": body["preflight_id"],
            "status": "applying",
            "actor": actor,
            "at": time.time(),
            "results": [],
        }
        path = self.directory / ("batch-" + check["id"] + ".json")
        atomic_json(path, record)
        for c in check["checks"]:
            try:
                result = self.admit(
                    {
                        "serial": c["serial"],
                        "revision": c["revision"],
                        "confirm_serial": c["serial"],
                        "confirm_ingestion": True,
                        "cleanup_scope": "all_disks",
                    },
                    actor,
                )
                record["results"].append({"serial": c["serial"], "status": result["status"]})
            except (ValueError, RuntimeError) as error:
                record["results"].append(
                    {"serial": c["serial"], "status": "needs_attention", "detail": str(error)}
                )
            atomic_json(path, record)
        record["status"] = (
            "accepted"
            if all(r["status"] == "accepted" for r in record["results"])
            else "needs_attention"
        )
        atomic_json(path, record)
        return record

    def probe(self, row, managed=False):
        from pxeye.services.bmc_addresses import BMCAddresses

        address = BMCAddresses(self.adapter, self.resources).view(row)
        device = {
            "serial": row["chassis_serial_number"],
            "bmc_ip": row.get("bmc_ip_address"),
            "bmc_mac": row["bmc_mac_address"],
            "expected_id": row["id"],
            "credential_source": "managed" if managed else "expected",
            "bmc_retain_credentials": row.get("bmc_retain_credentials") is True,
            "bmc_accept_self_signed": self.adapter.config.get("bmc_accept_self_signed", True),
            "redfish_system": "/redfish/v1/Systems",
        }
        if address["current_ip"]:
            device["bmc_ip"] = address["current_ip"]
        from pxeye.services.device_plans import use_current_bmc

        blocked = (
            ("assigning", "waiting_address", "needs_attention")
            if use_current_bmc(row["chassis_serial_number"])
            else ("planned", "assigning", "waiting_address", "needs_attention")
        )
        if address["status"] in blocked:
            raise ValueError("BMC 规划地址尚未应用并验证；先在设备配置完成地址应用。")
        if not device["bmc_ip"]:
            raise ValueError("首次接管请先填写并核对 BMC 地址。")
        collection = self.adapter.redfish(device)
        members = collection.get("Members", [])
        systems = []
        for member in members[:16]:
            path = member.get("@odata.id", "")
            if not re.fullmatch(r"/redfish/v1/Systems/[A-Za-z0-9_.-]+", path):
                raise ValueError("BMC 返回了无效系统路径。")
            candidate = device | {"redfish_system": path}
            system = self.adapter.redfish(candidate)
            if system.get("SerialNumber") == device["serial"]:
                systems.append((candidate, system))
        if len(systems) != 1:
            raise ValueError("BMC 没有返回唯一匹配的主机序列号。")
        return systems[0]

    def admit(self, body, actor, *, task_id=None):
        if set(body) - {
            "serial",
            "revision",
            "confirm_serial",
            "confirm_ingestion",
            "cleanup_scope",
        } or not {"serial", "revision", "confirm_serial", "confirm_ingestion"} <= set(body):
            raise ValueError("接管确认字段不完整。")
        from pxeye.services.instances import check_release_pending

        check_release_pending(self.adapter, body["serial"])
        if task_id:
            grant = (self.store.get(task_id) or {}).get("impact_authorization", {})
            scope = grant.get("cleanup_scope")
        else:
            scope = body.get("cleanup_scope")
        if scope != "all_disks":
            raise ValueError("原生接入可能清理本设备全部磁盘，必须明确确认该范围。")
        row = self.inventory_row(body["serial"])
        if (
            digest(row) != body["revision"]
            or body["confirm_serial"] != body["serial"]
            or body["confirm_ingestion"] is not True
        ):
            raise ValueError("请刷新后核对 SN 并确认站点接管策略。")
        active = self.store.active(body["serial"])
        if active and (task_id is None or active["id"] != task_id):
            raise ValueError("设备已有安装任务或待处理现场。")
        observed = self.observed([row])[body["serial"]]
        if observed["machine"] or observed["instances"]:
            raise ValueError("设备已进入接管流程；不能重复放行。")
        previous = self.admission(row["id"])
        if previous:
            if (
                task_id
                and previous["status"] == "accepted"
                and previous.get("bmc_mac") == row["bmc_mac_address"]
            ):
                return previous
            raise ValueError("已有接管请求记录；请检查 NICo 当前状态，不重复发送。")
        self.check_preparation(row)
        if not row.get("bmc_retain_credentials") and not self.adapter.config.get(
            "bmc_site_credential_file"
        ):
            raise ValueError(
                "先配置轮换后的站点 BMC 凭据，或在设备清单明确保留 BMC 凭据，再允许接管。"
            )
        if not row.get("bmc_retain_credentials"):
            self.adapter.credentials(
                {"credential_source": "managed", "bmc_retain_credentials": False}
            )
        device, system = self.probe(row)
        endpoint = {"ip_address": device["bmc_ip"], "mac_address": row["bmc_mac_address"]}
        gate = self.adapter.rpc("DetermineMachineIngestionState", endpoint).get(
            "machineIngestionState"
        )
        if gate != "WaitingForIngestion":
            raise ValueError(GATE.get(gate, "NICo 接管门控状态不允许放行。"))
        record = {
            "serial": body["serial"],
            "actor": actor,
            "at": time.time(),
            "status": "requesting",
            "bmc_ip": device["bmc_ip"],
            "bmc_mac": row["bmc_mac_address"],
            "revision": body["revision"],
        }
        path = self.directory / (row["id"] + ".json")
        atomic_json(path, record)
        try:
            from pxeye.services.device_plans import DevicePlans

            DevicePlans(self.adapter, self.resources).synchronize(body["serial"], "hardware")
            self.adapter.rpc("AllowIngestionAndPowerOn", endpoint)
            record["status"] = "accepted"
            record["gate_after"] = self.adapter.rpc("DetermineMachineIngestionState", endpoint).get(
                "machineIngestionState"
            )
            atomic_json(path, record)
            self.resources.inventory(persist=True)
            return record
        except Exception:
            record["status"] = "needs_attention"
            atomic_json(path, record)
            raise

    def preparation_checks(self, row):
        from pxeye.services.bmc_addresses import BMCAddresses
        from pxeye.services.device_plans import use_current_bmc
        from pxeye.services.device_config import DeviceConfig

        checks = []
        host = None

        def run(key, label, action):
            try:
                checks.append({"key": key, "label": label, "status": "pass", "detail": action()})
            except (ValueError, RuntimeError) as error:
                checks.append({"key": key, "label": label, "status": "fail", "detail": str(error)})

        def bmc():
            address = BMCAddresses(self.adapter, self.resources).view(row)
            blocked = (
                ("assigning", "waiting_address", "needs_attention")
                if use_current_bmc(row["chassis_serial_number"])
                else ("planned", "assigning", "waiting_address", "needs_attention")
            )
            if address["status"] in blocked:
                raise ValueError("BMC 地址未就绪，请先应用并验证规划地址。")
            if not address["current_ip"]:
                raise ValueError("未找到可用 BMC 地址；先完成发现并读取身份。")
            return "当前可联系地址：" + address["current_ip"]

        run("bmc_address", "BMC 地址规划", bmc)

        def startup():
            nonlocal host
            hosts = [
                n
                for n in row.get("interfaces", [])
                if n.get("role", "host") in ("host", "unspecified") and n.get("primary")
            ]
            if (
                len(hosts) != 1
                or not hosts[0].get("mac_address")
                or hosts[0]["mac_address"].lower() == row["bmc_mac_address"].lower()
            ):
                raise ValueError("请先在设备配置中选择唯一主机启动 MAC；发现不会自动选择启动口。")
            host = hosts[0]
            return "主机启动 MAC：" + host["mac_address"]

        run("boot_interface", "主机 PXE/iPXE 启动口", startup)

        def network():
            bindings = (
                DeviceConfig(self.adapter, self.resources)
                .get(row["chassis_serial_number"])
                .get("network_bindings", {})
            )
            networks = [
                n
                for n in self.resources.networks()
                if n["segment_type"] == "HOST_INBAND" and n["state"] == "READY"
            ]
            if bindings.get(host["mac_address"]):
                networks = [n for n in networks if n["id"] == bindings[host["mac_address"]]]
            if host.get("fixed_ip"):
                networks = [
                    n
                    for n in networks
                    if any(
                        ipaddress.ip_address(host["fixed_ip"]) in ipaddress.ip_network(p["prefix"])
                        for p in n["prefixes"]
                    )
                ]
            if len(networks) != 1 or (
                not host.get("fixed_ip") and networks[0]["allocation_strategy"] != "DYNAMIC"
            ):
                raise ValueError("请先绑定就绪的 HostInband 启动网络；动态启动还需允许动态分配。")
            return (
                networks[0]["name"]
                + "；"
                + ("固定地址 " + host["fixed_ip"] if host.get("fixed_ip") else "动态分配")
                + "；此项核对配置，未实测 DHCP/Relay 和引导文件可达性"
            )

        if host:
            run("boot_network", "HostInband 启动网络", network)
        else:
            checks.append(
                {
                    "key": "boot_network",
                    "label": "HostInband 启动网络",
                    "status": "skipped",
                    "detail": "先选择有效的主机启动口，再核对网络。",
                }
            )
        return checks

    def check_preparation(self, row):
        for check in self.preparation_checks(row):
            if check["status"] != "pass":
                raise ValueError(check["detail"])

    def check_scout_boot_guard(self, row, machine=None):
        hosts = {
            n.get("mac_address", "").lower()
            for n in row.get("interfaces", [])
            if n.get("primary") and n.get("role", "host") in ("host", "unspecified", 0, 1)
        }
        interfaces = self.adapter.rpc("FindInterfaces", {}).get("interfaces", [])
        machine_id = (machine or {}).get("id")
        matches = []
        for interface in interfaces:
            owner = interface.get("machineId", interface.get("machine_id"))
            owner = owner.get("id", owner.get("value")) if isinstance(owner, dict) else owner
            planned = interface.get("macAddress", interface.get("mac_address", "")).lower() in hosts
            if planned and machine_id and owner and owner != machine_id:
                raise ValueError("规划的主机启动 MAC 已属于另一台 Machine，停止准备。")
            if planned or (
                machine_id
                and owner == machine_id
                and not interface.get("isBmc", interface.get("is_bmc"))
            ):
                matches.append(interface)
        for interface in matches:
            ident = value_id(interface.get("id"))
            if not ident:
                raise ValueError("NICo 主机启动接口缺少 ID，无法核对引导保护。")
            override = self.adapter.rpc("GetMachineBootOverride", {"value": ident})
            if scout_boot_guard(override):
                raise ValueError(
                    "主机自定义引导配置停用了 forge-scout.service；可能是仅采集硬件时保留的保护。"
                    "尚未下发 ISO 安装。请先核对接入清理涉及的磁盘范围，再恢复 Scout 引导和服务，"
                    "然后继续原任务；系统不会自动解除停用或清盘。"
                )

    def plan(self, serial, profile_id, disk_serial):
        from pxeye.services.instances import check_release_pending

        check_release_pending(self.adapter, serial)
        if not isinstance(serial, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", serial
        ):
            raise ValueError("执行用序列号需为 1–128 位字母、数字、点、下划线或短横线。")
        row = self.inventory_row(serial)
        self.resources.check_address_operation(row)
        observed = self.observed([row])[serial]
        machine = observed["machine"]
        if not observed["first_install_ready"]:
            raise ValueError(observed["discovery_reason"])
        info = discovery_info(machine)
        if serial not in {
            info.get("dmi_data", {}).get("product_serial"),
            info.get("dmi_data", {}).get("chassis_serial"),
        }:
            raise ValueError("Scout 主机 SN 与设备声明不匹配。")
        profile = self.profile(profile_id)
        if observed["architecture"] != profile["architecture"]:
            raise ValueError("OS 方案架构与 Scout 发现的 CPU 架构不兼容。")
        selection = select_disk(
            observed["disks"], profile.get("settings", {}).get("storage"), disk_serial
        )
        from pxeye.services.device_config import DeviceConfig

        selection["source"] = (
            "设备指定"
            if DeviceConfig(self.adapter, self.resources).get(serial).get("disk_serial")
            else "方案规则"
        )
        disk_serial = selection["serial"]
        dpus = machine.get("status", {}).get("associated_dpu_machine_ids", [])
        allocation = copy.deepcopy(profile["allocation"])
        if profile["network_mode"] == "flat":
            if dpus or not allocation.get("network", {}).get("auto_config", {}).get("vpc_id"):
                raise ValueError("Flat 安装方案仅支持零受管 DPU 主机，并需要明确 VPC。")
            vpc_id = value_id(allocation["network"]["auto_config"]["vpc_id"])
            response = self.adapter.rpc("FindVpcsByIds", {"vpc_ids": [{"value": vpc_id}]})
            vpcs = [
                v
                for v in response.get("vpcs", [])
                if value_id(v["id"]) == vpc_id and not v.get("deleted")
            ]
            if (
                len(vpcs) != 1
                or vpcs[0]["config"].get("networkVirtualizationType") != "FLAT"
                or vpcs[0]["config"].get("tenantOrganizationId")
                != allocation.get("tenant", {}).get("tenant_organization_id")
            ):
                raise ValueError("首次安装方案的 VPC 不存在、非 Flat 或租户不匹配。")
        elif profile["network_mode"] == "dpu":
            if not dpus or not allocation.get("network", {}).get("interfaces"):
                raise ValueError("受管 DPU 方案需要明确租户接口配置。")
            if allocation["network"].get("auto") or allocation["network"].get("auto_config"):
                raise ValueError("受管 DPU 不能使用 Flat 自动网络。")
            card_names = [
                n.get("pci_properties", {}).get("device")
                for n in info.get("network_interfaces", [])
            ]
            for nic in allocation["network"]["interfaces"]:
                if (
                    not nic.get("device")
                    or card_names.count(nic["device"]) <= nic.get("device_instance", 0)
                    or nic.get("ip_address")
                    or not (
                        nic.get("network_segment_id")
                        or nic.get("segment_id")
                        or nic.get("vpc_prefix_id")
                    )
                ):
                    raise ValueError(
                        "DPU 方案接口需匹配发现的设备型号/实例，并绑定既有租户网段或前缀；批量 IP 由 NICo 分配。"
                    )
        else:
            raise ValueError("安装方案网络类型无效。")
        gpu_configs = nvlink_gpu_configs(profile)
        if gpu_configs:
            partition_id = gpu_configs[0]["logical_partition_id"]["value"]
            response = self.adapter.rpc(
                "FindNVLinkLogicalPartitionsByIds", {"partition_ids": [{"value": partition_id}]}
            )
            partitions = [
                p for p in response.get("partitions", []) if value_id(p["id"]) == partition_id
            ]
            if len(partitions) != 1 or partitions[0]["config"].get(
                "tenantOrganizationId"
            ) != allocation.get("tenant", {}).get("tenant_organization_id"):
                raise ValueError("NVLink 默认逻辑分区不存在或租户不匹配。")
        host = next(
            (
                n
                for n in row.get("interfaces", [])
                if n.get("primary") and n.get("role", "host") in ("host", "unspecified", 0, 1)
            ),
            {},
        )
        device = {
            k: profile[k]
            for k in (
                "architecture",
                "os_release",
                "ssh_user",
                "dns",
                "timezone",
                "dns_checks",
                "http_checks",
            )
        }
        device.update(
            serial=serial,
            profile=profile_id,
            first_install_profile=profile_id,
            machine_id=machine["id"],
            instance_id=None,
            bmc_ip=row.get("bmc_ip_address")
            or (machine.get("bmc") or machine.get("bmc_info") or {})["ip"],
            bmc_mac=row["bmc_mac_address"],
            expected_id=row["id"],
            boot_mac=host.get("mac_address", ""),
            management_ip=host.get("fixed_ip"),
            disk_serial=disk_serial,
            disk_wwn=None,
            credential_source="managed",
            bmc_accept_self_signed=self.adapter.config.get("bmc_accept_self_signed", True),
            bmc_retain_credentials=row.get("bmc_retain_credentials") is True,
            boot_adapter="standard",
            baseline_file=profile["baseline_file"],
        )
        if (
            len(
                [
                    n
                    for n in info.get("network_interfaces", [])
                    if n.get("mac_address", "").lower() == device["boot_mac"].lower()
                ]
            )
            != 1
        ):
            raise ValueError("Scout 没有报告唯一匹配的主启动 MAC。")
        # Reuse the already proven network/identity checks, with a discovered device rather than static allowlist.
        plan = self.resources.execution_plan(serial, device=device)
        plan.update(
            mode="first_install",
            machine_id=machine["id"],
            profile_id=profile_id,
            disk_serial=disk_serial,
            disk_selection=selection,
            discovery_revision=digest(
                {
                    "dmi": info.get("dmi_data"),
                    "nics": info.get("network_interfaces"),
                    "disks": info.get("block_devices"),
                    "nvme_devices": info.get("nvme_devices"),
                    "architecture": observed["architecture"],
                }
            ),
            profile_revision=digest(profile),
            current_management_ip=None,
        )
        device.update({k: plan[k] for k in ("management_ip", "prefixlen", "gateway")})
        from pxeye.services.device_config import DeviceConfig

        DeviceConfig(self.adapter, self.resources).bind(plan, device)
        return plan, device, observed

    def preflight(self, serial, hostname, profile_id, disk_serial):
        if not isinstance(hostname, str) or not HOSTNAME.fullmatch(hostname):
            raise ValueError("hostname 使用 1–63 位小写字母、数字和短横线。")
        checks, snapshot, plan, device = [], {}, None, None
        try:
            plan, device, observed = self.plan(serial, profile_id, disk_serial)
            checks.append(
                {
                    "name": "Ready、无 Instance、Scout 身份/系统盘与网络规划",
                    "passed": True,
                    "detail": "实际检查通过",
                }
            )
            probe, system = self.probe(self.inventory_row(serial), managed=True)
            device["redfish_system"] = probe["redfish_system"]
            checks.append(
                {"name": "当前 BMC 认证及主机序列号", "passed": True, "detail": "实际检查通过"}
            )
            rendered = self.adapter.render(
                device,
                {
                    "id": "PREFLIGHT",
                    "hostname": hostname,
                    "actor": "preflight",
                    "mode": "first_install",
                    "installation_plan": plan,
                },
            )
            snapshot["baseline_sha256"] = digest(self.adapter.baseline(device))
            snapshot["discovery"] = {k: observed[k] for k in ("disks", "architecture")}
            snapshot["rendered_network"] = yaml.safe_load(rendered["user_data"])["autoinstall"][
                "network"
            ]
            if device.get("materials"):
                self.adapter.check_materials(device)
            else:
                self.adapter.check_materials()
            checks.append(
                {
                    "name": "逐机安装配置与材料 HTTP/长度",
                    "passed": True,
                    "detail": "实际检查通过；执行前另做完整摘要校验",
                }
            )
        except (ValueError, RuntimeError) as error:
            checks.append({"name": "首次安装条件", "passed": False, "detail": str(error)})
        disk_serial = (plan or {}).get("disk_serial", disk_serial)
        return {
            "mode": "first_install",
            "device": serial,
            "hostname": hostname,
            "profile_id": profile_id,
            "disk_serial": disk_serial,
            "disk_selection": (plan or {}).get("disk_selection"),
            "hardware_checked_at": time.time() if plan else None,
            "passed": all(c["passed"] for c in checks),
            "checked_at": time.time(),
            "checks": checks,
            "snapshot": snapshot,
            "installation_plan": plan,
            "execution_device": device,
            "scope": {
                "disk_serial": disk_serial,
                "management_ip": (plan or {}).get("management_ip"),
                "current_management_ip": None,
                "instance_id": None,
                "profile": profile_id,
            },
        }

    def deferred_preflight(self, serial, hostname, profile_id, disk_serial, *, task_id=None):
        """Validate a first-install *plan* without requiring Scout or a Machine.

        A new host is allowed to queue work while NICo is still discovering it.
        This deliberately contains no NICo write and does not invent a Machine,
        Instance, disk or execution address.  The executor repeats the native
        checks after admission and freezes the real plan immediately before
        AllocateInstance.
        """
        from pxeye.services.instances import check_release_pending

        check_release_pending(self.adapter, serial)
        if not isinstance(hostname, str) or not HOSTNAME.fullmatch(hostname):
            raise ValueError("hostname 使用 1–63 位小写字母、数字和短横线。")
        row = self.inventory_row(serial)
        profile = self.profile(profile_id)
        if not profile:
            raise ValueError("安装方案不存在。")
        if disk_serial is not None and (
            not isinstance(disk_serial, str)
            or not 1 <= len(disk_serial) <= 128
            or any(c in disk_serial for c in "*?[]\n\r")
        ):
            raise ValueError("系统盘序列号格式无效；可在硬件回报后补齐。")
        active = self.store.active(serial)
        if active and (task_id is None or active["id"] != task_id):
            raise ValueError(serial + " 已有任务或待处理现场。")
        # These checks only inspect the saved declaration.  The native network
        # binding, BMC identity and disk uniqueness are checked again later.
        hosts = [
            n
            for n in row.get("interfaces", [])
            if n.get("primary") and n.get("role", "host") in ("host", "unspecified", 0, 1)
        ]
        if len(hosts) != 1 or not hosts[0].get("mac_address"):
            raise ValueError("请先在设备规划中选择唯一主机启动 MAC。")
        host = hosts[0]
        if not all(host.get(k) for k in ("fixed_ip", "fixed_mask", "fixed_gateway")):
            raise ValueError("请先保存 HostInband 管理地址、掩码和网关规划。")
        try:
            target = ipaddress.IPv4Interface(host["fixed_ip"] + "/" + host["fixed_mask"])
            gateway = ipaddress.IPv4Address(host["fixed_gateway"])
            if (
                gateway not in target.network
                or gateway == target.ip
                or any(
                    a in (target.network.network_address, target.network.broadcast_address)
                    for a in (target.ip, gateway)
                )
            ):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ValueError("管理地址、掩码和网关必须属于同一有效 IPv4 子网。") from None
        plan = {
            "serial": serial,
            "management_ip": str(target.ip),
            "prefixlen": target.network.prefixlen,
            "gateway": str(gateway),
            "boot_mac": host["mac_address"],
            "declaration_revision": digest(row),
            "profile_id": profile_id,
            "disk_serial": disk_serial,
            "deferred": True,
            "current_management_ip": None,
            "profile_revision": digest(profile),
            "execution_revision": digest(self.adapter.config),
        }
        from pxeye.services.device_plans import DevicePlans, use_current_bmc

        saved = DevicePlans(self.adapter, self.resources).get(serial)
        if saved:
            plan["device_plan_revision"] = digest(saved)
        if use_current_bmc(serial):
            plan["bmc_choice"] = "use_current"
        from pxeye.services.device_config import DeviceConfig

        device = {
            k: profile[k]
            for k in (
                "architecture",
                "os_release",
                "ssh_user",
                "dns",
                "timezone",
                "dns_checks",
                "http_checks",
                "baseline_file",
            )
        }
        device.update(
            serial=serial,
            profile=profile_id,
            first_install_profile=profile_id,
            disk_serial=disk_serial,
        )
        DeviceConfig(self.adapter, self.resources).bind(plan, device)
        baseline_revision = digest(self.adapter.baseline(device))
        if device.get("materials"):
            self.adapter.check_materials(device)
        else:
            self.adapter.check_materials()
        checks = [
            {
                "name": "设备规划、hostname 与安装方案",
                "passed": True,
                "detail": "已保存；执行前重新校验",
            },
            {
                "name": "Machine / Scout / Ready",
                "passed": True,
                "deferred": True,
                "detail": "当前未要求 Ready；创建任务后由后台自动接入并等待 NICo Ready",
            },
            {
                "name": "目标盘",
                "passed": True,
                "deferred": True,
                "detail": "执行前读取 Scout；"
                + (
                    "匹配规划序列号"
                    if disk_serial
                    else "按方案规则解析唯一系统盘："
                    + selection_label(profile.get("settings", {}).get("storage"))
                ),
            },
            {
                "name": "安装材料 HTTP 与固定长度（执行前另做完整摘要校验）",
                "passed": True,
                "detail": "实际检查通过",
            },
        ]
        return {
            "mode": "first_install",
            "device": serial,
            "hostname": hostname,
            "profile_id": profile_id,
            "disk_serial": disk_serial,
            "disk_selection": None,
            "hardware_checked_at": None,
            "deferred_first_install": True,
            "passed": True,
            "checked_at": time.time(),
            "checks": checks,
            "snapshot": {"declaration_sha256": digest(row), "baseline_sha256": baseline_revision},
            "installation_plan": plan,
            "execution_device": None,
            "scope": {
                "disk_serial": disk_serial,
                "management_ip": str(target.ip),
                "current_management_ip": None,
                "instance_id": None,
                "profile": profile_id,
            },
        }
