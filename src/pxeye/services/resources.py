"""Inventory and subnet management using the pinned Forge contracts."""

import copy
import csv
import io
import ipaddress
import json
import re
import time
import uuid
from pxeye.common import atomic_json, atomic_text, digest, value_id
from pxeye.domain.machines import (
    CSV_FIELDS,
    SEGMENT_TYPE,
    public_machine,
    confirms_fields,
    validate_machine,
    machine_rpc,
    machine_from_rpc,
)
from pxeye.domain.csv import convert


class ImportReadbackError(RuntimeError):
    """A safe description of an import whose committed fields need verification."""


def segment_revision(segment):
    config = copy.deepcopy(segment["config"])
    for prefix in config.get("prefixes", []):
        for key in ["freeIpCount", "freeIpCountV2", "freeIpCountSaturated"]:
            prefix.pop(key, None)
    return digest({"id": segment["id"], "config": config, "metadata": segment.get("metadata")})


class Resources:
    def __init__(self, adapter, store):
        self.adapter, self.store = adapter, store
        self.directory = adapter.data / "config"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def recover_network_operations(self):
        for path in (self.directory / "networks").glob("*.json"):
            record = json.loads(path.read_text())
            if record["status"] in ("applying", "waiting_deletion"):
                record["status"] = "needs_attention"
                record["error"] = "服务重启；请核对旧段回收和新段创建结果，不自动重放写操作。"
                atomic_json(path, record)
        self.write_network_file()

    def planned_inventory(self):
        from pxeye.services.device_plans import DevicePlans

        return DevicePlans(self.adapter, self).inventory()

    def inventory(self, persist=False):
        rows = [
            machine_from_rpc(x)
            for x in self.adapter.core(["expected-machine", "show"], data=True).get(
                "expected_machines", []
            )
        ]
        if persist:
            atomic_json(self.directory / "expected-machines.json", {"expected_machines": rows})
            target = self.directory / "machines.csv"
            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        k: json.dumps(row[k], ensure_ascii=False)
                        if isinstance(row.get(k), (dict, list, bool))
                        else row.get(k, "")
                        for k in CSV_FIELDS
                    }
                )
            atomic_text(target, stream.getvalue())
        return rows

    def refresh_inventory(self):
        """Explicitly reconcile native declarations into local planning and exports."""
        from pxeye.services.device_plans import DevicePlans

        rows = self.inventory(persist=True)
        DevicePlans(self.adapter, self).seed(rows)
        from pxeye.services.equipment_planning import EquipmentPlanning

        EquipmentPlanning(self.adapter, self).migrate_legacy(rows)
        return {"status": "refreshed", "count": len(rows), "observed_at": time.time()}

    def devices(self):
        from pxeye.services.device_view import DeviceProjection

        return DeviceProjection(self).read()

    def execution_plan(self, serial, *, rows=None, networks=None, interfaces=None, device=None):
        """Bind a next-install plan; existing DHCP allocation and OS are untouched."""
        from pxeye.services.instances import check_release_pending

        check_release_pending(self.adapter, serial)
        device = self.adapter.device(serial) if device is None else device
        rows = self.planned_inventory() if rows is None else rows
        matches = [x for x in rows if x["chassis_serial_number"] == serial]
        if len(matches) != 1:
            raise ValueError("没有唯一设备声明，请核对序列号。")
        row = matches[0]
        self.check_address_operation(row)
        hosts = [
            n
            for n in row.get("interfaces", [])
            if n.get("primary") and n.get("role", "host") in ("host", "unspecified", 0, 1)
        ]
        if len(hosts) != 1:
            raise ValueError("重装需要唯一的主机主启动接口声明。")
        host = hosts[0]
        if host.get("mac_address", "").lower() != device["boot_mac"].lower():
            raise ValueError("主启动网卡 MAC 已改变，需重新核对硬件接入。")
        from pxeye.services.device_plans import use_current_bmc

        if (
            row.get("bmc_ip_address")
            and row["bmc_ip_address"] != device["bmc_ip"]
            and not use_current_bmc(serial)
        ):
            raise ValueError("BMC 规划与已接管管理入口不同，需先核对 BMC 接入。")
        if host.get("ip_allocation") not in (None, "unspecified", "fixed", 0, 2) or host.get(
            "network_segment_type"
        ) not in (None, 3):
            raise ValueError("当前重装支持 HostInband 固定 IPv4 管理地址。")
        try:
            target = ipaddress.IPv4Interface(host["fixed_ip"] + "/" + host["fixed_mask"])
            gateway = ipaddress.IPv4Address(host["fixed_gateway"])
            if (
                target.ip in (target.network.network_address, target.network.broadcast_address)
                or gateway not in target.network
                or gateway == target.ip
            ):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ValueError("管理地址、掩码和网关必须完整且属于同一有效 IPv4 子网。") from None
        interfaces = (
            self.adapter.rpc("FindInterfaces", {}).get("interfaces", [])
            if interfaces is None
            else interfaces
        )
        bound = [
            n
            for n in interfaces
            if n.get("macAddress", "").lower() == device["boot_mac"].lower()
            and n.get("machineId", {}).get("id") == device["machine_id"]
            and n.get("primaryInterface")
            and not n.get("isBmc")
        ]
        bmc = [
            n
            for n in interfaces
            if n.get("isBmc") and n.get("machineId", {}).get("id") == device["machine_id"]
        ]
        if (
            len(bound) != 1
            or len(bmc) != 1
            or bmc[0].get("macAddress", "").lower() != row["bmc_mac_address"].lower()
        ):
            raise ValueError("NICo 主启动口或 BMC MAC 与已接管 Machine 不匹配。")
        networks = self.networks() if networks is None else networks
        segment = next(
            (n for n in networks if n["id"] == value_id(bound[0].get("segmentId"))), None
        )
        if not segment or segment["segment_type"] != "HOST_INBAND" or segment["state"] != "READY":
            raise ValueError("已接管接口的 HostInband 子网尚未就绪。")
        prefixes = [
            p
            for p in segment["prefixes"]
            if p["prefix"] == str(target.network) and p.get("gateway") == str(gateway)
        ]
        if len(prefixes) != 1:
            raise ValueError("规划地址不匹配当前引导子网；请先完成网络迁移。")
        prefix = prefixes[0]
        if gateway in (target.network.network_address, target.network.broadcast_address) or int(
            target.ip
        ) - int(target.network.network_address) < int(prefix.get("reserveFirst", 0)):
            raise ValueError("规划地址或网关使用了子网保留地址。")
        for other in rows:
            if other["id"] == row["id"]:
                continue
            if other.get("bmc_ip_address") == str(target.ip) or any(
                n.get("fixed_ip") == str(target.ip) for n in other.get("interfaces", [])
            ):
                raise ValueError("目标地址已在其他设备声明中使用。")
        for nic in interfaces:
            if str(target.ip) in nic.get("address", []) and value_id(nic.get("id")) != value_id(
                bound[0]["id"]
            ):
                raise ValueError("目标地址已由其他 NICo 接口占用。")
        services = segment.get("services") or self.network_services(segment)
        protected = {device.get("bmc_ip"), device.get("dns"), str(gateway)} | set(
            services["dns_servers"]
        )
        from urllib.parse import urlsplit

        protected.add(urlsplit(self.adapter.config.get("core_url", "")).hostname)
        protected.update(
            urlsplit(m["url"]).hostname for m in self.adapter.config.get("materials", [])
        )
        if str(target.ip) in protected:
            raise ValueError("目标地址与站点服务或网关冲突。")
        plan = {
            "serial": serial,
            "current_management_ip": device["management_ip"],
            "management_ip": str(target.ip),
            "prefixlen": target.network.prefixlen,
            "gateway": str(gateway),
            "boot_mac": device["boot_mac"],
            "declaration_revision": digest(row),
            "segment_id": segment["id"],
            "segment_revision": segment["revision"],
            "interface_id": value_id(bound[0]["id"]),
            "boot_addresses": bound[0].get("address", []),
            "execution_revision": digest(self.adapter.config),
            "binding_revision": digest(
                {
                    k: bound[0].get(k)
                    for k in (
                        "id",
                        "machineId",
                        "segmentId",
                        "primaryInterface",
                        "macAddress",
                        "address",
                    )
                }
            ),
        }
        services = segment.get("services") or self.network_services(segment)
        plan.update(
            dns_servers=services["dns_servers"],
            dns_source=services["source"],
            dns_revision=services["revision"],
        )
        from pxeye.services.device_plans import DevicePlans

        saved = DevicePlans(self.adapter, self).get(serial)
        if saved:
            plan["device_plan_revision"] = digest(saved)
        if use_current_bmc(serial):
            plan["bmc_choice"] = "use_current"
            plan["current_bmc_ip"] = device["bmc_ip"]
        if device.get("first_install_profile"):
            from pxeye.services.device_config import DeviceConfig

            DeviceConfig(self.adapter, self).bind(plan, device)
        return plan

    def preview(self, text, owner):
        if not isinstance(text, str) or len(text.encode()) > 1024 * 1024:
            raise ValueError("CSV 最大 1 MiB。")
        try:
            incoming = [
                validate_machine(m)
                for m in convert(io.StringIO(text.lstrip("\ufeff")))["expected_machines"]
            ]
        except csv.Error:
            raise ValueError("CSV 引号或行格式无效。") from None
        if len(incoming) > 500:
            raise ValueError("每批最多 500 台设备。")
        before = self.inventory()
        plans = []
        for row in incoming:
            matches = [
                x for x in before if x["bmc_mac_address"].lower() == row["bmc_mac_address"].lower()
            ]
            existing = matches[0] if matches else None
            if existing:
                self.check_address_operation(existing)
                if (
                    row.get("default_pause_ingestion_and_poweron") is False
                    and existing.get("default_pause_ingestion_and_poweron") is not False
                ):
                    raise ValueError("清单保存不能放行接管；请使用独立的硬件准备功能。")
            if any(
                x["chassis_serial_number"] == row["chassis_serial_number"] and x is not existing
                for x in before
            ):
                raise ValueError("序列号已绑定另一 BMC MAC；请修改原条目。")
            if row.get("id") and (existing and value_id(row["id"]) != existing["id"]):
                raise ValueError("CSV ID 与已登记的 BMC MAC 不一致。")
            if not existing:
                if row.get("default_pause_ingestion_and_poweron") is False:
                    raise ValueError("新增登记须保持发现/自动开机暂停；CSV 请设为 true。")
                row["default_pause_ingestion_and_poweron"] = True
                row.setdefault("id", str(uuid.uuid4()))
            plans.append(
                {
                    "operation": "update" if existing else "create",
                    "incoming": row,
                    "before_revision": digest(existing) if existing else None,
                    "id": existing["id"] if existing else value_id(row["id"]),
                }
            )
        from pxeye.services.equipment import Equipment

        Equipment(self.adapter, self).validate_server_import(incoming)
        token = uuid.uuid4().hex
        record = {
            "id": token,
            "owner": owner,
            "expires": time.time() + 900,
            "status": "preview",
            "plans": plans,
        }
        atomic_json(self.directory / "imports" / (token + ".json"), record)
        return {
            "preview_id": token,
            "rows": [public_machine(p["incoming"]) | {"operation": p["operation"]} for p in plans],
            "counts": {op: sum(p["operation"] == op for p in plans) for op in ["create", "update"]},
        }

    def apply_import(self, token, owner):
        if not isinstance(token, str) or not re.fullmatch("[a-f0-9]{32}", token):
            raise ValueError("导入预览无效。")
        path = self.directory / "imports" / (token + ".json")
        if not path.exists():
            raise ValueError("导入预览不存在。")
        record = json.loads(path.read_text())
        if (
            record["owner"] != owner
            or record["expires"] < time.time()
            or record["status"] != "preview"
        ):
            raise ValueError("预览过期、已应用或需检查，请重新预览。")
        current = self.inventory()
        for plan in record["plans"]:
            row = plan["incoming"]
            old = next(
                (
                    x
                    for x in current
                    if x["bmc_mac_address"].lower() == row["bmc_mac_address"].lower()
                ),
                None,
            )
            if old:
                self.check_address_operation(old)
            if (digest(old) if old else None) != plan["before_revision"]:
                raise ValueError("NICo 设备已变化，请重新预览。")
            if (
                self.store.active(row["chassis_serial_number"])
                or old
                and self.store.active(old["chassis_serial_number"])
            ):
                raise ValueError("设备有活动装机任务或待处理现场，暂不能修改。")
            if old and "server_name" in row and row["server_name"] != old.get("server_name"):
                raise ValueError("本版 Core PATCH 不支持修改 server_name；可在新登记时设置。")
        from pxeye.services.equipment import Equipment

        Equipment(self.adapter, self).validate_server_import(
            [p["incoming"] for p in record["plans"]]
        )
        record["status"] = "applying"
        atomic_json(path, record)
        try:
            creates = [
                machine_rpc(p["incoming"]) for p in record["plans"] if p["operation"] == "create"
            ]
            if creates:
                result = self.adapter.rpc(
                    "CreateExpectedMachines",
                    {
                        "expected_machines": {"expected_machines": creates},
                        "accept_partial_results": False,
                    },
                )
                if len(result.get("results", [])) != len(creates) or not all(
                    x.get("success") for x in result["results"]
                ):
                    raise RuntimeError("NICo 批量登记未全部成功，请核对已写入条目。")
            patches = []
            for plan in record["plans"]:
                if plan["operation"] != "update":
                    continue
                body = machine_rpc(plan["incoming"]) | {"id": {"value": plan["id"]}}
                if "server_name" in body:
                    old = next(x for x in current if x["id"] == plan["id"])
                    if body["server_name"] != old.get("server_name"):
                        raise ValueError(
                            "本版 Core PATCH 不支持修改 server_name；可在新登记时设置。"
                        )
                    body.pop("server_name")
                mask = [k for k in body if k not in ("id", "bmc_mac_address")]
                if "metadata" in mask:
                    mask.remove("metadata")
                    mask += ["metadata." + k for k in body["metadata"]]
                if "host_lifecycle_profile" in mask:
                    mask.remove("host_lifecycle_profile")
                    mask += ["host_lifecycle_profile." + k for k in body["host_lifecycle_profile"]]
                patches.append({"expected_machine": body, "update_mask": {"paths": mask}})
            if patches:
                self.adapter.rpc("PatchExpectedMachines", {"patches": patches})
            return self.verify_import(token)
        except Exception:
            record["status"] = "needs_attention"
            atomic_json(path, record)
            # The remote request may have committed before a timeout. Never blindly replay it.
            raise

    def verify_import(self, token):
        """Reconcile saved import results through reads; never repeat a Core write."""
        if not isinstance(token, str) or not re.fullmatch("[a-f0-9]{32}", token):
            raise ValueError("导入记录无效。")
        path = self.directory / "imports" / (token + ".json")
        record = json.loads(path.read_text())
        if record["status"] not in ("applying", "needs_attention", "applied"):
            raise ValueError("导入尚未提交，不能核对写入结果。")
        readback = self.inventory()
        for plan in record["plans"]:
            row = next((x for x in readback if x["id"] == plan["id"]), None)
            expected = machine_from_rpc(machine_rpc(plan["incoming"]))
            expected = {k: v for k, v in expected.items() if k in plan["incoming"]}
            if row is None or not confirms_fields(row, expected):
                raise ImportReadbackError(
                    "NICo 登记请求已提交，但设备字段尚未核对通过。请刷新设备清单核对实际记录；不要重复加入设备。"
                )
        self.inventory(persist=True)
        if record["status"] == "needs_attention":
            record["recovered_from"] = "needs_attention"
        record.update(status="applied", verified_at=time.time())
        record.setdefault("applied_at", time.time())
        atomic_json(path, record)
        self.invalidate()
        return {
            "status": "applied",
            "count": len(record["plans"]),
            "files": ["/data/config/machines.csv", "/data/config/expected-machines.json"],
        }

    def edit(self, body, owner):
        if set(body) != {"id", "revision", "machine"}:
            raise ValueError("设备编辑字段不完整。")
        rows = self.inventory()
        old = next((x for x in rows if x["id"] == body["id"]), None)
        if not old or digest(old) != body["revision"]:
            raise ValueError("设备已变化，请刷新后编辑。")
        self.check_address_operation(old)
        changes = copy.deepcopy(body["machine"])
        if not isinstance(changes, dict):
            raise ValueError("设备内容无效。")
        for k in ["id", "bmc_mac_address", "chassis_serial_number"]:
            if k in changes and value_id(changes[k]) != value_id(old[k]):
                raise ValueError("编辑时保留设备 ID、BMC MAC 和序列号；新设备请新增登记。")
        if not changes.get("bmc_password"):
            changes["bmc_password"] = old["bmc_password"]
        machine = validate_machine(old | changes)
        stream = io.StringIO()
        w = csv.DictWriter(stream, fieldnames=list(machine))
        w.writeheader()
        w.writerow(
            {
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, bool)) else v
                for k, v in machine.items()
            }
        )
        preview = self.preview(stream.getvalue(), owner)
        return self.apply_import(preview["preview_id"], owner)

    def check_address_operation(self, row):
        macs = {row["bmc_mac_address"].lower()} | {
            n.get("mac_address", "").lower() for n in row.get("interfaces", [])
        }
        from pxeye.services.addresses import STATES

        for path in (self.adapter.data / "config" / "management-addresses" / "operations").glob(
            "*.json"
        ):
            operation = json.loads(path.read_text())
            if operation.get("mac_address") in macs and operation.get("status") in STATES:
                raise ValueError("设备有未完成的管理地址操作，请先核对实际地址。")
        from pxeye.services.bmc_addresses import BMCAddresses

        if BMCAddresses(self.adapter, self).record(row["chassis_serial_number"]).get("status") in (
            "assigning",
            "waiting_address",
            "needs_attention",
        ):
            raise ValueError("设备有待核对的 BMC 地址应用，请先验证实际地址，再修改规划。")

    def invalidate(self):
        with self.store.db() as db:
            db.execute("DELETE FROM preflights")

    def network_services(self, network):
        path = self.directory / "network-services" / (network["id"] + ".json")
        if path.exists():
            row = json.loads(path.read_text())
            return row | {"source": "网络规划", "revision": digest(row)}
        configured = self.adapter.config.get("network_services", {}).get(
            network["id"],
            self.adapter.config.get("network_services", {}).get(network.get("name", ""), {}),
        )
        servers = configured.get("dns_servers", [])
        # Read the historical site network defaults, never per-profile DNS.
        if not servers:
            for item in self.adapter.config.get("network", {}).values():
                if (
                    isinstance(item, dict)
                    and item.get("网段") in [p["prefix"] for p in network["prefixes"]]
                    and item.get("DNS")
                ):
                    servers = [item["DNS"]]
        row = {"dns_servers": servers}
        return row | {"source": "站点网络默认" if servers else "尚未配置", "revision": digest(row)}

    def save_network_services(self, body):
        if set(body) != {"id", "revision", "dns_servers"}:
            raise ValueError("网络服务配置字段无效。")
        servers = body["dns_servers"]
        if not isinstance(servers, list) or not 1 <= len(servers) <= 4:
            raise ValueError("请配置1–4个DNS服务器地址。")
        try:
            servers = [str(ipaddress.ip_address(x)) for x in servers]
        except (ValueError, TypeError):
            raise ValueError("DNS服务器地址无效。") from None
        network = next((n for n in self.networks() if n["id"] == body["id"]), None)
        if not network or network["segment_type"] != "HOST_INBAND":
            raise ValueError("仅主机管理子网配置OS DNS。")
        if network["services"]["revision"] != body["revision"]:
            raise ValueError("DNS规划已变化，请刷新。")
        atomic_json(
            self.directory / "network-services" / (network["id"] + ".json"),
            {"dns_servers": servers},
        )
        return {
            "status": "saved",
            "detail": "DNS规划已保存；在下次OS安装生效，不修改当前DHCP或运行系统。",
        }

    def networks(self):
        ids = self.adapter.rpc("FindNetworkSegmentIds", {}).get("networkSegmentsIds", [])
        live = (
            self.adapter.rpc(
                "FindNetworkSegmentsByIds",
                {"network_segments_ids": ids, "include_num_free_ips": True},
            ).get("networkSegments", [])
            if ids
            else []
        )
        interfaces = self.adapter.rpc("FindInterfaces", {}).get("interfaces", [])
        records = []
        for n in live:
            if n.get("deleted"):
                continue
            cfg = n["config"]
            sid = value_id(n["id"])
            path = self.directory / "networks" / (sid + ".json")
            saved = json.loads(path.read_text()) if path.exists() else None
            row = {
                "id": sid,
                "name": n.get("metadata", {}).get("name", ""),
                "segment_type": cfg.get("segmentType", "TENANT"),
                "prefixes": cfg.get("prefixes", []),
                "mtu": cfg.get("mtu"),
                "subdomain_id": value_id(cfg.get("subdomainId")),
                "vpc_id": value_id(cfg.get("vpcId")),
                "allocation_strategy": self.adapter.config.get(
                    "network_allocation_strategies", {}
                ).get(
                    sid,
                    self.adapter.config.get("network_allocation_strategies", {}).get(
                        n.get("metadata", {}).get("name", ""),
                        "DYNAMIC" if saved and saved.get("created_by_console") else "UNKNOWN",
                    ),
                ),
                "allocation_strategy_source": "site-config"
                if sid in self.adapter.config.get("network_allocation_strategies", {})
                or n.get("metadata", {}).get("name", "")
                in self.adapter.config.get("network_allocation_strategies", {})
                else "console-created"
                if saved and saved.get("created_by_console")
                else "not-exposed-by-core",
                "state": n.get("status", {}).get("tenantState", "UNKNOWN"),
                "revision": segment_revision(n),
                "interface_count": sum(value_id(x.get("segmentId")) == sid for x in interfaces),
                "managed_by_console": bool(saved and saved.get("created_by_console")),
                "saved": saved,
            }
            # The current Core response omits policy. Deployment declarations and
            # creation defaults are hints, not a readback of the running allocator.
            row["observed_allocation_strategy"] = cfg.get("allocationStrategy", "UNKNOWN")
            row["services"] = self.network_services(row)
            records.append(row)
        return sorted(records, key=lambda row: (row["name"].casefold(), row["id"]))

    def save_network(self, body):
        if set(body) != {"id", "revision", "config"}:
            raise ValueError("子网编辑字段不完整。")
        config = copy.deepcopy(body["config"])
        allowed = {
            "name",
            "segment_type",
            "prefix",
            "gateway",
            "mtu",
            "reserve_first",
            "subdomain_id",
            "allocation_strategy",
        }
        if set(config) - allowed or not all(
            k in config for k in ["name", "segment_type", "prefix", "mtu", "reserve_first"]
        ):
            raise ValueError("子网配置字段无效。")
        if (
            not re.fullmatch("[A-Za-z0-9_.-]{1,128}", config["name"])
            or config["name"] == "static-assignments"
        ):
            raise ValueError("请输入有效的子网名；系统静态地址段不能编辑。")
        if config["segment_type"] not in ("HOST_INBAND", "ADMIN", "UNDERLAY"):
            raise ValueError("本期仅管理装机相关的站点子网。")
        if config.get("allocation_strategy", "DYNAMIC") not in ("DYNAMIC", "RESERVED"):
            raise ValueError("地址策略需为动态分配或仅预留。")
        try:
            net = ipaddress.ip_network(config["prefix"], strict=True)
            if net.version != 4:
                raise ValueError()
            if config.get("gateway") and (
                ipaddress.ip_address(config["gateway"]) not in net
                or config["gateway"] in (str(net.network_address), str(net.broadcast_address))
            ):
                raise ValueError()
        except ValueError:
            raise ValueError("子网 CIDR 或网关无效；本版编辑支持单 IPv4 前缀。") from None
        if (
            type(config["mtu"]) is not int
            or not 576 <= config["mtu"] <= 9216
            or type(config["reserve_first"]) is not int
            or not 0 <= config["reserve_first"] < net.num_addresses
        ):
            raise ValueError("MTU 或保留地址数超出范围。")
        if config["segment_type"] == "HOST_INBAND":
            try:
                uuid.UUID(config.get("subdomain_id", ""))
            except (ValueError, TypeError):
                raise ValueError("HostInband 需要 DNS 子域 UUID。") from None
        old = None
        if body["id"]:
            old = next((x for x in self.networks() if x["id"] == body["id"]), None)
            if old:
                raise ValueError(
                    "此子网已存在于 NICo。当前版本不支持原位修改；页面仅展示生效配置，不再保存无法应用的修改。"
                )
            try:
                uuid.UUID(body["id"])
            except (ValueError, TypeError):
                raise ValueError("子网 ID 无效。") from None
            draft_path = self.directory / "networks" / (body["id"] + ".json")
            deletion_path = self.directory / "network-deletions" / (body["id"] + ".json")
            if deletion_path.exists():
                raise ValueError("子网已有删除记录，请先核对删除结果。")
            if draft_path.exists() and json.loads(draft_path.read_text())["status"] in (
                "applying",
                "waiting_deletion",
            ):
                raise ValueError("子网正在应用，请等待完成后编辑。")
            if not old and body["revision"] is None and draft_path.exists():
                previous = json.loads(draft_path.read_text())
                if previous["status"] not in ("saved", "needs_attention"):
                    raise ValueError("请先核对上次子网应用结果。")
            elif not old or old["revision"] != body["revision"]:
                raise ValueError("NICo 子网已变化，请刷新后编辑。")
            if old and len(old["prefixes"]) != 1:
                raise ValueError("双栈或多个前缀须使用独立迁移，不能被单前缀表单覆盖。")
        if config.get("allocation_strategy", "DYNAMIC") != "DYNAMIC":
            raise ValueError("当前 NICo 创建接口不支持指定仅预留策略；请使用站点配置流程。")
        sid = body["id"] or str(uuid.uuid4())
        record = {
            "id": sid,
            "revision": body["revision"],
            "config": config,
            "status": "saved",
            "created_by_console": bool(not old or old["managed_by_console"]),
            "updated_at": time.time(),
            "before": {k: v for k, v in old.items() if k != "saved"} if old else None,
        }
        atomic_json(self.directory / "networks" / (sid + ".json"), record)
        self.write_network_file()
        return {"id": sid, "status": "saved", "file": "/data/config/network-segments.json"}

    def write_network_file(self):
        rows = [
            row
            for p in (self.directory / "networks").glob("*.json")
            if (row := json.loads(p.read_text())).get("status") != "deleted"
        ]
        atomic_json(self.directory / "network-segments.json", {"network_segments": rows})

    def apply_network(self, sid):
        try:
            uuid.UUID(sid)
        except (ValueError, TypeError):
            raise ValueError("子网 ID 无效。") from None
        if (self.directory / "network-deletions" / (sid + ".json")).exists():
            raise ValueError("子网已有删除记录，不能再次应用。")
        path = self.directory / "networks" / (sid + ".json")
        if not path.exists():
            raise ValueError("请先保存子网配置。")
        record = json.loads(path.read_text())
        if record["status"] != "saved":
            raise ValueError("配置已应用或需要核对，请刷新后重新保存。")
        live = self.networks()
        if any(x["id"] == sid for x in live):
            raise ValueError(
                "此子网已存在于 NICo。当前版本不支持原位修改；不会为应用历史规划而删除重建子网。"
            )
        if record["config"].get("allocation_strategy") == "RESERVED":
            record["status"] = "migration_required"
            atomic_json(path, record)
            self.write_network_file()
            raise ValueError(
                "当前 Core API 不支持写入仅预留策略；配置已保存，需通过站点配置或迁移应用。"
            )
        c = record["config"]
        for other in live:
            if other["id"] == sid:
                continue
            for p in other["prefixes"]:
                if ipaddress.ip_network(c["prefix"]).overlaps(ipaddress.ip_network(p["prefix"])):
                    raise ValueError("子网与现有 NICo 前缀重叠。")
        record["status"] = "applying"
        record["replacement_id"] = sid
        atomic_json(path, record)
        self.write_network_file()
        try:
            return self.create_network(record)
        except Exception:
            record["status"] = "needs_attention"
            atomic_json(path, record)
            self.write_network_file()
            raise

    def create_network(self, record):
        sid, c = record["id"], record["config"]
        path = self.directory / "networks" / (sid + ".json")
        record["status"] = "applying"
        record["stage"] = "create_requested"
        atomic_json(path, record)
        self.write_network_file()
        req = {
            "id": {"value": record["replacement_id"]},
            "name": c["name"],
            "segment_type": SEGMENT_TYPE.index(c["segment_type"]),
            "mtu": c["mtu"],
            "prefixes": [
                {
                    "prefix": c["prefix"],
                    "gateway": c.get("gateway") or None,
                    "reserve_first": c["reserve_first"],
                }
            ],
        }
        if c.get("subdomain_id"):
            req["subdomain_id"] = {"value": c["subdomain_id"]}
        n = self.adapter.rpc("CreateNetworkSegment", req)
        readback = self.adapter.rpc(
            "FindNetworkSegmentsByIds", {"network_segments_ids": [n["id"]]}
        )["networkSegments"][0]
        cfg, prefix = readback["config"], readback["config"]["prefixes"][0]
        if (
            value_id(n["id"]) != record["replacement_id"]
            or len(cfg["prefixes"]) != 1
            or readback.get("metadata", {}).get("name") != c["name"]
            or cfg.get("segmentType") != c["segment_type"]
            or cfg.get("mtu") != c["mtu"]
            or prefix["prefix"] != c["prefix"]
            or (prefix.get("gateway") or "") != (c.get("gateway") or "")
            or prefix.get("reserveFirst", 0) != c["reserve_first"]
            or c.get("subdomain_id")
            and value_id(cfg.get("subdomainId")) != c["subdomain_id"]
        ):
            raise RuntimeError("子网配置读回不匹配。")
        record["id"] = value_id(n["id"])
        record["status"] = "applied"
        record["applied_at"] = time.time()
        record["revision"] = segment_revision(readback)
        atomic_json(self.directory / "networks" / (record["id"] + ".json"), record)
        if record["id"] != sid:
            path.unlink()
        self.write_network_file()
        self.invalidate()
        return {
            "id": record["id"],
            "status": "applied",
            "replaced_id": sid if record["id"] != sid else None,
        }

    def finish_network_replacement(self, sid):
        path = self.directory / "networks" / (sid + ".json")
        record = json.loads(path.read_text())
        if record["status"] != "waiting_deletion":
            raise ValueError("没有可继续的子网回收操作。")
        try:
            while time.time() < record["deadline"]:
                rows = self.adapter.rpc(
                    "FindNetworkSegmentsByIds", {"network_segments_ids": [{"value": sid}]}
                ).get("networkSegments", [])
                if not rows:
                    return self.create_network(record)
                if not rows[0].get("deleted"):
                    raise RuntimeError("旧子网删除状态不匹配，请核对现场。")
                time.sleep(5)
            raise RuntimeError("等待旧子网回收超时，请核对 NICo 排空状态。")
        except Exception as error:
            record["status"] = "needs_attention"
            record["error"] = (
                str(error) if isinstance(error, RuntimeError) else "子网应用失败，请核对现场。"
            )
            atomic_json(path, record)
            self.write_network_file()
            raise

    def network_list(self):
        live = self.networks()
        ids = {x["id"] for x in live}
        drafts = [json.loads(p.read_text()) for p in (self.directory / "networks").glob("*.json")]
        deletions = [
            self.verify_network_deletion(p.stem)
            for p in (self.directory / "network-deletions").glob("*.json")
            if json.loads(p.read_text()).get("status") != "deleted"
        ]
        pending = {x["id"] for x in deletions}
        for row in live:
            row["deletion"] = next((x for x in deletions if x["id"] == row["id"]), None)
            row["delete_allowed"], row["delete_reason"] = self.network_delete_boundary(row)
        return {
            "networks": live,
            "drafts": sorted(
                [
                    x | {"delete_revision": digest(x)}
                    for x in drafts
                    if x["id"] not in ids
                    and x["id"] not in pending
                    and x.get("status") != "deleted"
                ],
                key=lambda x: (x["config"]["name"].casefold(), x["id"]),
            ),
            "deletions": sorted(
                [x for x in deletions if x["status"] != "deleted"],
                key=lambda x: (x["name"].casefold(), x["id"]),
            ),
            "file": "/data/config/network-segments.json",
        }

    @staticmethod
    def network_delete_boundary(row):
        if (
            row["name"] == "static-assignments"
            or row["segment_type"] not in ("HOST_INBAND", "UNDERLAY", "ADMIN")
            or row.get("vpc_id")
        ):
            return False, "系统或租户网络不能在此删除。"
        if not row.get("managed_by_console"):
            return False, "由站点配置管理；请通过站点配置移除，避免自动重建。"
        if row.get("interface_count"):
            return False, "仍有接口或地址占用。"
        if row.get("deletion") or (row.get("saved") or {}).get("status") in (
            "applying",
            "waiting_deletion",
            "needs_attention",
        ):
            return False, "已有操作待完成或待核对。"
        return True, ""

    def check_network_plan_references(self, row):
        from pxeye.services.device_config import DeviceConfig
        from pxeye.services.equipment import Equipment, interfaces_for, normal_native, KINDS

        config = DeviceConfig(self.adapter, self)
        prefixes = [ipaddress.ip_network(p["prefix"]) for p in row["prefixes"]]
        equipment = Equipment(self.adapter, self)
        native, errors = equipment.native()
        if errors:
            raise ValueError("类型声明读取失败，无法完整核对子网引用。")
        for plan in equipment.records("plans"):
            if row["id"] in plan.get("bindings", {}).values():
                raise ValueError("子网仍被交换机或供电框规划引用。")
        declarations = [(p["kind"], p["declaration"]) for p in equipment.records("plans")]
        declarations += [
            (kind, normal_native(kind, declaration))
            for kind in KINDS
            for declaration in native[kind + ":expected"]
        ]
        if any(
            ipaddress.ip_address(port["target_ip"]) in prefix
            for kind, declaration in declarations
            for port in interfaces_for(kind, declaration)
            if port.get("target_ip")
            for prefix in prefixes
        ):
            raise ValueError("子网内仍有交换机或供电框目标地址，请先调整对应配置。")
        # Both unsent plans and native declarations protect a network from deletion.
        for machine in self.planned_inventory() + self.inventory():
            intent = config.get(machine["chassis_serial_number"])
            if row["id"] in intent.get("network_bindings", {}).values():
                raise ValueError("子网仍被设备规划引用，请先调整设备规划。")
            addresses = [machine.get("bmc_ip_address")] + [
                nic.get("fixed_ip") for nic in machine.get("interfaces", [])
            ]
            if any(
                ipaddress.ip_address(address) in prefix
                for address in addresses
                if address
                for prefix in prefixes
            ):
                raise ValueError("子网内仍有设备规划或 NICo 声明地址，请先调整对应配置。")

    def delete_network(self, body):
        if set(body) != {"id", "revision", "confirm_delete"} or body["confirm_delete"] is not True:
            raise ValueError("请确认删除指定子网。")
        try:
            sid = str(uuid.UUID(body["id"]))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("子网 ID 无效。") from None
        operation = self.directory / "network-deletions" / (sid + ".json")
        if operation.exists():
            raise ValueError("删除已请求；请刷新核对结果，不重复发送。")
        row = next((r for r in self.networks() if r["id"] == sid), None)
        path = self.directory / "networks" / (sid + ".json")
        if row is None:
            draft = json.loads(path.read_text()) if path.exists() else None
            if (
                not draft
                or body["revision"] != digest(draft)
                or draft.get("status") not in ("saved", "migration_required")
                or draft.get("before")
                or draft.get("replacement_id")
            ):
                raise ValueError("草稿已变化或存在待核对的执行结果，请刷新。")
            # Discarding an unapplied draft cannot change native addresses or plans.
            # Reference checks apply only to deletion of the live NICo segment below.
            atomic_json(
                operation,
                {
                    "id": sid,
                    "name": draft["config"]["name"],
                    "status": "deleted",
                    "scope": "draft",
                    "before": draft,
                    "updated_at": time.time(),
                },
            )
            draft["status"] = "deleted"
            atomic_json(path, draft)
            self.write_network_file()
            return {"id": sid, "status": "deleted", "detail": "未应用草稿已删除；没有修改 NICo。"}
        if row["revision"] != body["revision"]:
            raise ValueError("NICo 子网已变化，请刷新后删除。")
        allowed, reason = self.network_delete_boundary(row)
        if not allowed:
            raise ValueError(reason)
        self.check_network_plan_references(row)
        record = {
            "id": sid,
            "name": row["name"],
            "status": "deleting",
            "scope": "nico",
            "before": row,
            "updated_at": time.time(),
            "deadline": time.time() + 660,
        }
        atomic_json(operation, record)
        try:
            self.adapter.rpc("DeleteNetworkSegment", {"id": {"value": sid}})
        except Exception:
            record["status"] = "delete_unknown"
            record["detail"] = "删除结果未确认；请刷新只读核对，不重复发送删除。"
            atomic_json(operation, record)
            raise
        self.invalidate()
        return {
            "id": sid,
            "status": "deleting",
            "detail": "NICo 已接受删除，等待子网回收；可刷新查看结果。",
        }

    def verify_network_deletion(self, sid):
        path = self.directory / "network-deletions" / (sid + ".json")
        record = json.loads(path.read_text())
        rows = self.adapter.rpc(
            "FindNetworkSegmentsByIds", {"network_segments_ids": [{"value": sid}]}
        ).get("networkSegments", [])
        if not rows:
            record["status"] = "deleted"
            draft_path = self.directory / "networks" / (sid + ".json")
            if draft_path.exists():
                draft = json.loads(draft_path.read_text())
                draft["status"] = "deleted"
                atomic_json(draft_path, draft)
            self.write_network_file()
        elif time.time() > record.get("deadline", 0):
            record["status"] = "delete_unknown"
            record["detail"] = "等待回收超时；请刷新核对 NICo 状态，不自动重发删除。"
        atomic_json(path, record)
        return record

    def logs(self, task_id):
        task = self.store.get(task_id)
        if task is None:
            raise ValueError("任务不存在。")
        raw = self.adapter.data / "tasks" / task_id / "console.raw"
        text = ""
        if raw.exists():
            with raw.open("rb") as f:
                f.seek(max(0, raw.stat().st_size - 65536))
                text = f.read().decode(errors="replace")
            text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text).replace("\r", "")
            # SOL can show echoed installation payloads. Never expose them to the browser.
            text = "\n".join(
                "[安装配置行已隐藏]"
                if any(
                    w in line.lower()
                    for w in [
                        "password",
                        "passwd",
                        "authorized-keys",
                        "bmc_username",
                        "token",
                        "private key",
                    ]
                )
                else line
                for line in text.splitlines()
            )
            for device in self.adapter.config.get("devices", []):
                cred = json.loads(
                    (self.adapter.secrets / device["bmc_credential_file"]).read_text()
                )
                if cred.get("password"):
                    text = text.replace(cred["password"], "[已隐藏]")
            if self.adapter.config.get("first_install_profiles"):
                for row in self.inventory():
                    if row.get("bmc_password"):
                        text = text.replace(row["bmc_password"], "[已隐藏]")
            if self.adapter.config.get("bmc_site_credential_file"):
                credential = json.loads(
                    (
                        self.adapter.secrets / self.adapter.config["bmc_site_credential_file"]
                    ).read_text()
                )
                if credential.get("password"):
                    text = text.replace(credential["password"], "[已隐藏]")
            execution = task.get("execution_device", {})
            if execution.get("login_ref"):
                credential = self.adapter.login_credential(execution)
                for field in ("password", "password_hash"):
                    text = text.replace(credential[field], "[已隐藏]")
        return {
            "task_id": task_id,
            "source": "authenticated-bmc-sol",
            "text": text,
            "bytes": raw.stat().st_size if raw.exists() else 0,
            "updated_at": raw.stat().st_mtime if raw.exists() else None,
            "status": task["status"],
            "limit": 65536,
        }
