"""Authenticated command routing; operation services own execution policy."""

import uuid
from pxeye.services.device_plans import DevicePlans
from pxeye.domain.topology import normalize_topology_layout


class CommandRoutes:
    def dispatch_command(self, path, body, session):
        deployment_actions = {
            "/api/nico-deployment/preflight": self.app.nico_deployment.preflight,
            "/api/nico-deployment/start": self.app.nico_deployment.start,
            "/api/nico-deployment/connect": self.app.nico_deployment.connect,
        }
        if path in deployment_actions:
            return self.respond(202, deployment_actions[path](body))
        if (
            path not in ("/api/site", "/api/logout")
            and not self.app.readiness()["business_available"]
        ):
            return self.respond(
                503, {"error": self.app.readiness()["reason"], "code": "NICO_NOT_CONNECTED"}
            )
        if path == "/api/resources/refresh":
            return self.respond(200, self.app.plan(self.app.resources.refresh_inventory))
        if path == "/api/topology-layout":
            layout = normalize_topology_layout(self.app, body)
            return self.respond(200, self.app.store.save_topology_layout(layout))
        if path.startswith("/api/equipment-planning/"):
            from pxeye.services.equipment_planning import EquipmentPlanning
            from pxeye.services.interface_planning import InterfacePlanning

            planning = EquipmentPlanning(self.app.adapter, self.app.resources)
            action = path.removeprefix("/api/equipment-planning/")
            if action == "preview":
                from pxeye.domain.workbook import workbook_csv

                if set(body) == {"xlsx"}:
                    text = workbook_csv(body["xlsx"])
                elif set(body) == {"csv"}:
                    text = body["csv"]
                else:
                    raise ValueError("请提交设备规划 Excel 或 CSV。")
                return self.respond(200, planning.preview(text, session["token"]))
            handlers = {
                "export-interfaces": lambda: InterfacePlanning(planning).export(
                    body, session["token"]
                ),
                "save": lambda: planning.save(body),
                "import": lambda: planning.import_csv(body, session["token"]),
                "match": lambda: planning.match(body),
            }
            if action not in handlers:
                return self.respond(404, {"error": "设备规划操作不存在。"})
            return self.respond(200, self.app.plan(handlers[action]))
        if path.startswith("/api/equipment/"):
            action = path.removeprefix("/api/equipment/")
            equipment, owner = self.app.equipment, session["token"]
            actor = "operator@" + self.client_address[0]
            handlers = {
                "save": lambda: equipment.save(body),
                "import-preview": lambda: equipment.import_preview(body, owner),
                "import-apply": lambda: equipment.import_apply(body, owner),
                "identify": lambda: equipment.identify(body, owner),
                "identify-many": lambda: equipment.identify_many(body, owner),
                "enroll": lambda: equipment.enroll(body, owner, self.app.discovery, actor),
                "sync-preview": lambda: equipment.sync_preview(body, owner),
                "sync-apply": lambda: equipment.sync_apply(body, owner, actor),
                "pin-preview": lambda: equipment.pin_preview(body, owner),
                "pin-apply": lambda: equipment.pin_apply(body, owner, actor),
                "reconcile": lambda: equipment.reconcile(body, actor),
                "address-save": lambda: self.app.management_addresses.save(body),
                "address-identify": lambda: self.app.management_addresses.identify_many(body),
                "address-preview": lambda: self.app.management_addresses.preview(body, owner),
                "address-apply": lambda: self.app.management_addresses.start(body, owner, actor),
                "address-verify": lambda: self.app.management_addresses.verify(body, actor),
                "batch-refresh": lambda: self.app.management_addresses.batch_refresh(body),
                "bmc-restart-unsent": lambda: self.app.management_addresses.bmc_jobs().restart_unsent(
                    body
                ),
                "bmc-finish-sync": lambda: self.app.management_addresses.bmc_jobs().finish_sync(
                    body
                ),
                "batch-redfish-preview": lambda: self.app.management_addresses.batch_redfish_preview(
                    body, owner
                ),
                "batch-redfish-apply": lambda: self.app.management_addresses.batch_redfish_apply(
                    body, owner, actor
                ),
            }
            if action not in handlers:
                return self.respond(404, {"error": "设备操作不存在。"})
            if action in (
                "sync-apply",
                "pin-apply",
                "enroll",
                "batch-redfish-apply",
                "bmc-finish-sync",
                "bmc-restart-unsent",
            ):
                return self.respond(200, self.app.configure(handlers[action]))
            with self.app.os_lock():
                return self.respond(200, handlers[action]())
        if (
            path.startswith("/api/instances/")
            and path.endswith("/release")
            and len(path.split("/")) == 5
        ):
            iid = path.split("/")[3]
            return self.respond(
                202,
                self.app.configure(
                    lambda: self.app.instances.release(
                        iid, body, "operator@" + self.client_address[0]
                    )
                ),
            )
        if path.startswith("/api/install-profiles/"):
            action = path.rsplit("/", 1)[-1]
            if action == "save":
                return self.respond(200, self.app.configure(lambda: self.app.profiles.save(body)))
            if action == "new-version":
                return self.respond(
                    200, self.app.configure(lambda: self.app.profiles.new_version(body))
                )
            if action == "check" and set(body) == {"id"}:
                result = self.app.configure(lambda: self.app.profiles.check(body["id"]))
                return self.respond(200, {k: v for k, v in result.items() if k != "os_record"})
            if action in ("publish", "active", "delete"):
                return self.respond(
                    200, self.app.configure(lambda: self.app.profiles.action(body, action))
                )
            raise ValueError("方案操作无效。")
        if path == "/api/operating-systems/upload":
            return self.respond(201, self.app.os_library.begin(body, "operator"))
        if path == "/api/operating-systems/import":
            return self.respond(202, self.app.os_library.operate("import", body, "operator"))
        if path == "/api/operating-systems/prepare":
            if set(body) != {"id"}:
                raise ValueError("请选择已上传 ISO。")
            return self.respond(202, self.app.os_library.prepare(body["id"], "operator"))
        if path == "/api/operating-systems/recover":
            return self.respond(200, self.app.os_library.operate("recover", body, "operator"))
        if path == "/api/operating-systems/cancel":
            return self.respond(200, self.app.os_library.operate("cancel", body, "operator"))
        if path == "/api/operating-systems/register":
            return self.respond(200, self.app.os_library.operate("register", body, "operator"))
        if path == "/api/operating-systems/activate":
            return self.respond(200, self.app.os_library.operate("activate", body, "operator"))
        if path == "/api/discovery/authenticate":
            return self.respond(
                200,
                self.app.configure(lambda: self.app.discovery.authenticate(body, session["token"])),
            )
        if path == "/api/devices/current-system/query":
            return self.respond(202, self.app.current_systems.start(body))
        if path == "/api/discovery/enroll":
            return self.respond(
                200,
                self.app.configure(
                    lambda: self.app.discovery.enroll(
                        body, session["token"], "operator@" + self.client_address[0]
                    )
                ),
            )
        if path == "/api/devices/bmc-address/preview":
            return self.respond(
                200,
                self.app.configure(lambda: self.app.bmc_addresses.preview(body, session["token"])),
            )
        if path == "/api/devices/bmc-address/apply":
            return self.respond(
                200,
                self.app.configure(
                    lambda: self.app.bmc_addresses.apply(
                        body, session["token"], "operator@" + self.client_address[0]
                    )
                ),
            )
        if path == "/api/devices/bmc-address/verify":
            return self.respond(
                200,
                self.app.configure(
                    lambda: self.app.bmc_addresses.verify(
                        body, "operator@" + self.client_address[0]
                    )
                ),
            )
        if path == "/api/device-plans/installation-selection":
            if set(body) != {"serial", "revision", "hostname", "profile_id", "disk_serial"}:
                raise ValueError("安装准备规划字段无效。")
            self.app.configure(
                lambda: DevicePlans(self.app.adapter, self.app.resources).installation_selection(
                    body["serial"],
                    body["hostname"],
                    body["profile_id"],
                    body["disk_serial"],
                    body["revision"],
                )
            )
            return self.respond(200, {"status": "saved"})
        if path == "/api/device-plans/bulk-preview":
            return self.respond(
                200,
                DevicePlans(self.app.adapter, self.app.resources).bulk_preview(
                    body, session["token"]
                ),
            )
        if path == "/api/device-plans/bulk-apply":
            return self.respond(
                200,
                self.app.plan(
                    lambda: DevicePlans(self.app.adapter, self.app.resources).bulk_apply(
                        body, session["token"]
                    )
                ),
            )
        if path == "/api/device-plans/save":
            return self.respond(
                200,
                self.app.plan(lambda: DevicePlans(self.app.adapter, self.app.resources).save(body)),
            )
        if path == "/api/device-plans/preview":
            raise ValueError(
                "请在设备规划 TAB 下载新的 CSV 模板并导入，旧版设备声明不能作为规划导入。"
            )
        if path == "/api/device-plans/import":
            raise ValueError("旧版导入预览已失效，请在设备规划 TAB 重新导入。")
        if path == "/api/devices/installation-config/validate":
            proposed = body.pop("machine", None)
            return self.respond(
                200, self.app.device_config.save(body, proposed=proposed, validate_only=True)
            )
        if path == "/api/devices/installation-config":
            return self.respond(200, self.app.configure(lambda: self.app.device_config.save(body)))
        if path == "/api/devices/preview":
            if set(body) != {"csv"}:
                raise ValueError("请选择官方格式 CSV。")
            return self.respond(200, self.app.resources.preview(body["csv"], session["token"]))
        if path == "/api/devices/import":
            if set(body) != {"preview_id"}:
                raise ValueError("请先预览导入内容。")
            return self.respond(
                200,
                self.app.configure(
                    lambda: self.app.resources.apply_import(body["preview_id"], session["token"])
                ),
            )
        if path == "/api/devices/edit":
            return self.respond(
                200, self.app.configure(lambda: self.app.resources.edit(body, session["token"]))
            )
        if path == "/api/devices/admit":
            return self.respond(
                200,
                self.app.configure(
                    lambda: self.app.onboarding.admit(body, "operator@" + self.client_address[0])
                ),
            )
        if path == "/api/devices/admission-preview":
            return self.respond(
                200,
                self.app.configure(
                    lambda: self.app.onboarding.admission_preview(body, session["token"])
                ),
            )
        if path == "/api/devices/admit-batch":
            return self.respond(
                200,
                self.app.configure(
                    lambda: self.app.onboarding.admit_batch(
                        body, session["token"], "operator@" + self.client_address[0]
                    )
                ),
            )
        if path == "/api/batches/preflight":
            return self.respond(200, self.app.batch_preflight(body, session["token"]))
        if path == "/api/batches":
            return self.respond(
                202,
                self.app.submit_batch(body, session["token"], "operator@" + self.client_address[0]),
            )
        if path == "/api/networks/services":
            return self.respond(
                200, self.app.configure(lambda: self.app.resources.save_network_services(body))
            )
        if path == "/api/site":
            return self.respond(200, self.app.save_site(body))
        if path == "/api/networks/save":
            return self.respond(
                200, self.app.configure(lambda: self.app.resources.save_network(body))
            )
        if path == "/api/networks/apply":
            if set(body) != {"id"}:
                raise ValueError("请选择已保存的子网。")
            result = self.app.apply_network(body["id"])
            return self.respond(202 if result["status"] == "waiting_deletion" else 200, result)
        if path == "/api/networks/delete":
            result = self.app.configure(lambda: self.app.resources.delete_network(body))
            return self.respond(202 if result["status"] == "deleting" else 200, result)
        if path == "/api/preflight":
            if set(body) != {"device", "hostname"}:
                raise ValueError("预检只接受设备和 hostname。")
            if self.app.store.active(body["device"]):
                raise ValueError("设备已有活动任务或待处理现场。")
            check = self.app.configure(
                lambda: self.app.adapter.preflight(body["device"], body["hostname"])
            )
            check["id"] = uuid.uuid4().hex
            self.app.store.preflight(check["id"], check)
            return self.respond(200, check)
        if path == "/api/tasks":
            actor = "operator@" + self.client_address[0]
            return self.respond(202, self.app.submit(body, actor))
        parts = path.split("/")
        if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "restart-preflight":
            if body:
                raise ValueError("重新检查不接受额外字段。")
            return self.respond(200, self.app.restart_preflight(parts[3], session["token"]))
        if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "restart-install":
            return self.respond(
                202,
                self.app.restart_install(
                    parts[3], body, session["token"], "operator@" + self.client_address[0]
                ),
            )
        if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "retry-preflight":
            if body:
                raise ValueError("重试核对不接受额外字段。")
            return self.respond(200, self.app.retry_install_preflight(parts[3], session["token"]))
        if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "retry-install":
            return self.respond(
                202,
                self.app.retry_install(
                    parts[3], body, session["token"], "operator@" + self.client_address[0]
                ),
            )
        if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "prepare-preflight":
            if body:
                raise ValueError("规划核对不接受额外字段。")
            return self.respond(200, self.app.preparation_preflight(parts[3], session["token"]))
        if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "continue-prepare":
            return self.respond(
                202,
                self.app.continue_preparation(
                    parts[3], body, session["token"], "operator@" + self.client_address[0]
                ),
            )
        if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "resume":
            return self.respond(
                202, self.app.resume(parts[3], body, "operator@" + self.client_address[0])
            )
        if len(parts) == 5 and parts[2] == "tasks" and parts[4] == "close":
            return self.respond(
                200, self.app.close_task(parts[3], body, "operator@" + self.client_address[0])
            )
        return self.respond(404, {"error": "接口不存在。"})
