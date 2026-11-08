"""Read-only API routing and static assets."""

import mimetypes
import time
from urllib.parse import parse_qs, urlsplit
from pxeye import __version__


class QueryRoutes:
    def get_request(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self.respond(200, {"status": "ok", "mode": "live", "version": __version__})
        if path.startswith("/api/"):
            session = self.session()
            if session is None:
                return self.respond(401, {"error": "请先登录。"})
            if path == "/api/session":
                return self.respond(
                    200,
                    {
                        "operator": "站点操作员",
                        "csrf": session["csrf"],
                        "readiness": self.app.readiness(),
                    },
                )
            if path == "/api/readiness":
                return self.respond(200, self.app.readiness())
            if path == "/api/nico-deployment":
                refresh = parse_qs(urlsplit(self.path).query).get("refresh") == ["1"]
                return self.respond(200, self.app.nico_deployment.view(refresh=refresh))
            if path == "/api/site":
                return self.respond(200, self.app.site_information())
            if not self.app.readiness()["business_available"]:
                return self.respond(
                    503, {"error": self.app.readiness()["reason"], "code": "NICO_NOT_CONNECTED"}
                )
            if path == "/api/instances":
                return self.respond(200, self.app.instances.list())
            if path == "/api/equipment":
                snapshot = self.app.management_addresses.snapshot()
                data = self.app.equipment.view(snapshot)
                data["management_addresses"] = self.app.management_addresses.view(snapshot)
                return self.respond(200, data)
            if path == "/api/equipment-planning":
                from pxeye.services.equipment_planning import EquipmentPlanning

                return self.respond(
                    200, EquipmentPlanning(self.app.adapter, self.app.resources).list()
                )
            if path == "/api/equipment-planning/template":
                from pxeye.services.equipment_planning import EquipmentPlanning

                data = ("\ufeff" + EquipmentPlanning.template()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header(
                    "Content-Disposition", "attachment; filename=device-planning-template.csv"
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(data)
            if path == "/api/topology-layout":
                return self.respond(200, self.app.store.topology_layout())
            if path.startswith("/api/equipment/bmc-jobs/") and len(path.split("/")) == 5:
                return self.respond(
                    200, self.app.management_addresses.bmc_jobs().status(path.split("/")[4])
                )
            if path == "/api/equipment/template":
                kind = parse_qs(urlsplit(self.path).query).get("kind", [""])[0]
                data = ("\ufeff" + self.app.equipment.template(kind)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header(
                    "Content-Disposition", "attachment; filename=" + kind + "-template.csv"
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(data)
            if path.startswith("/api/equipment/") and len(path.split("/")) == 4:
                return self.respond(200, self.app.equipment.detail(path.split("/")[3]))
            if (
                path.startswith("/api/networks/")
                and path.endswith("/allocations")
                and len(path.split("/")) == 5
            ):
                return self.respond(200, self.app.equipment.allocations(path.split("/")[3]))
            if path.startswith("/api/instances/") and len(path.split("/")) == 4:
                return self.respond(200, self.app.instances.detail(path.split("/")[3]))
            if path == "/api/devices/template":
                data = (self.app.static / "machines-template.xlsx").read_bytes()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header("Content-Length", str(len(data)))
                self.send_header(
                    "Content-Disposition", "attachment; filename=machines-template.xlsx"
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(data)
            if path.startswith("/api/devices/") and path.endswith("/hardware"):
                from pxeye.services.hardware import Hardware
                from urllib.parse import unquote

                return self.respond(
                    200,
                    Hardware(self.app.adapter, self.app.resources).read(
                        unquote(path.split("/")[3])
                    ),
                )
            if path == "/api/networks":
                return self.respond(200, self.app.resources.network_list())
            if path == "/api/operating-systems":
                return self.respond(200, self.app.os_library.list())
            if path == "/api/operating-systems/sources":
                return self.respond(200, self.app.os_library.sources())
            if path == "/api/discovery/candidates":
                return self.respond(200, self.app.discovery.candidates())
            if path == "/api/devices/current-system":
                return self.respond(200, self.app.current_systems.view())
            if path == "/api/resources":
                devices = self.app.resources.devices()
                return self.respond(
                    200,
                    {
                        "site": self.app.config["site"],
                        "core_url": self.app.config["core_url"],
                        "site_readiness": {
                            "checked_at": time.time(),
                            "core_read": "本次资源API已返回",
                            "policy_source": "UI站点配置记录；非原生动态策略读回",
                            "cleanup": "首次接入可能清理本设备全部磁盘；系统盘授权不等于接入清理授权",
                            "boot_evidence": "未在本次资源读取中验证物理relay、PXE或Scout链路",
                            "max_batch": 50,
                            "concurrency": self.app.config.get("default_install_concurrency", 5),
                        },
                        "devices": devices,
                        "materials": self.app.config["materials"],
                        "network": self.app.config["network"],
                        "first_install_profiles": self.app.onboarding.profiles(),
                        "capabilities": [
                            "existing-instance-reinstall",
                            "first-install",
                            "batch-install",
                            "scout-admission",
                            "strict-ssh",
                            "persisted-tasks",
                            "csv-import",
                            "expected-machine-edit",
                            "network-segments",
                            "sol-logs",
                            "iso-upload",
                            "os-library",
                            "bmc-dhcp-candidates",
                            "device-installation-intent",
                        ],
                    },
                )
            if path == "/api/install-profiles":
                return self.respond(200, self.app.profiles.list())
            if path == "/api/tasks":
                return self.respond(
                    200, {"tasks": [self.app.task_view(task) for task in self.app.store.tasks()]}
                )
            if path == "/api/batches":
                return self.respond(200, {"batches": self.app.store.batches()})
            parts = path.split("/")
            if len(parts) == 4 and parts[2] == "batches":
                batch = self.app.store.batch(parts[3])
                return (
                    self.respond(200, batch)
                    if batch
                    else self.respond(404, {"error": "批次不存在。"})
                )
            if len(parts) == 5 and parts[2] == "devices" and parts[4] == "discovery":
                from urllib.parse import unquote

                return self.respond(200, self.app.onboarding.view(unquote(parts[3])))
            if len(parts) in (4, 5) and parts[2] == "tasks":
                task = self.app.store.get(parts[3])
                if task is None:
                    return self.respond(404, {"error": "任务不存在。"})
                if len(parts) == 5 and parts[4] == "receipt":
                    if not task.get("receipt"):
                        return self.respond(409, {"error": "尚无完整验收回执。"})
                    return self.respond(
                        200,
                        task["receipt"],
                        {
                            "Content-Disposition": "attachment; filename="
                            + task["id"]
                            + "-receipt.json"
                        },
                    )
                if len(parts) == 5 and parts[4] == "logs":
                    return self.respond(200, self.app.resources.logs(task["id"]))
                if len(parts) == 4:
                    return self.respond(200, self.app.task_view(task))
            return self.respond(404, {"error": "接口不存在。"})
        files = {
            "/" + str(file.relative_to(self.app.static)): str(file.relative_to(self.app.static))
            for file in self.app.static.rglob("*")
            if file.is_file() and file.suffix in (".html", ".js", ".css", ".svg")
        }
        files.update({"/": "live.html", "/index.html": "live.html"})
        # Existing asset URLs remain valid during an HTML/cache transition.
        files.update(
            {
                "/ui_runtime.js": "shared/ui_runtime.js",
                "/live.js": "shared/live.js",
                "/onboarding.js": "pages/onboarding.js",
                "/instances.js": "pages/instances.js",
                "/equipment.js": "pages/equipment.js",
                "/management_addresses.js": "pages/management_addresses.js",
                "/profiles.js": "pages/profiles.js",
                "/management.js": "pages/management.js",
                "/hardware.js": "pages/hardware.js",
                "/topology.js": "pages/topology.js",
            }
        )
        if path not in files:
            return self.respond(404, {"error": "页面不存在。"})
        target = self.app.static / files[path]
        data = target.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            (mimetypes.guess_type(str(target))[0] or "application/octet-stream")
            + "; charset=utf-8",
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)
