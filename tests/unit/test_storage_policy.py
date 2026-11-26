"""System-disk rules must resolve to one disk, or refuse, before allocation."""

import unittest

from pxeye.installation.storage_policy import (
    apply_partition_layout,
    minimum_disk_bytes,
    normalize_storage,
    select_disk,
)


def disk(serial, model="SSD 480G", size=None):
    return {"serial": serial, "model": model, "size_bytes": size, "is_nvme": size is not None}


class IdenticalDiskTests(unittest.TestCase):
    def test_identical_disks_resolve_to_the_first_serial(self):
        disks = [disk("S2"), disk("S1")]
        for candidates in (disks, disks[::-1]):
            chosen = select_disk(candidates, {"selection": "identical"})
            self.assertEqual((chosen["serial"], chosen["source"]), ("S1", "方案规则"))

    def test_unique_rule_still_refuses_identical_disks(self):
        with self.assertRaisesRegex(ValueError, "匹配多块磁盘"):
            select_disk([disk("S1"), disk("S2")], {"selection": "unique"})

    def test_different_specifications_are_refused(self):
        rule = {"selection": "identical"}
        cases = (
            [disk("S1"), disk("S2", model="NVMe 1T")],
            [disk("S1", size=480 * 1024**3), disk("S2", size=960 * 1024**3)],
            [disk("S1", model="NO_MODEL"), disk("S2", model="NO_MODEL")],
        )
        for disks in cases:
            with self.assertRaisesRegex(ValueError, "规格不同"):
                select_disk(disks, rule)

    def test_model_pattern_narrows_mixed_disks_to_the_identical_pair(self):
        nvme = [disk(serial, "NVMe 1T", 1024**4) for serial in ("N1", "N2")]
        disks = [nvme[0], disk("S2"), disk("S1"), nvme[1]]
        rule = {"selection": "identical", "model_pattern": "SSD*"}
        self.assertEqual(select_disk(disks, rule)["serial"], "S1")

    def test_explicit_device_disk_takes_precedence(self):
        chosen = select_disk([disk("S1"), disk("S2")], {"selection": "identical"}, "S2")
        self.assertEqual((chosen["serial"], chosen["source"]), ("S2", "设备指定"))

    def test_no_candidate_and_unknown_rule_are_refused(self):
        with self.assertRaisesRegex(ValueError, "没有匹配磁盘"):
            select_disk([], {"selection": "identical"})
        with self.assertRaisesRegex(ValueError, "选择方式无效"):
            normalize_storage({"selection": "first"})


class LvmLayoutTests(unittest.TestCase):
    def template(self):
        from pxeye.installation.profile_template import generic_ubuntu
        import yaml

        return yaml.safe_load(generic_ubuntu({}, "nico", "", "UTC", "")["user_data"])["autoinstall"]

    def test_saved_profiles_without_a_layout_stay_direct(self):
        rule = normalize_storage({"selection": "unique", "efi_mib": 1024})
        self.assertEqual((rule["layout"], rule["vg_name"]), ("direct", "ubuntu-vg"))
        before = self.template()
        after = self.template()
        apply_partition_layout(after, {"efi_mib": 1024})
        before["storage"]["config"][1]["size"] = 1024**3
        self.assertEqual(after["storage"], before["storage"])

    def test_lvm_layout_puts_root_on_one_logical_volume(self):
        ai = self.template()
        apply_partition_layout(
            ai, {"layout": "lvm", "vg_name": "sysvg", "lv_name": "root", "root_gib": 100}
        )
        config = {x["id"]: x for x in ai["storage"]["config"]}
        self.assertEqual(
            [x["id"] for x in ai["storage"]["config"]],
            ["os-disk", "efi", "efi-format", "boot", "boot-format", "pv", "vg", "lv-root"]
            + ["root-format", "root-mount", "boot-mount", "efi-mount"],
        )
        self.assertEqual(config["boot"]["size"], 2048 * 1024**2)
        self.assertEqual((config["pv"]["size"], config["pv"]["number"]), (-1, 3))
        self.assertEqual((config["vg"]["name"], config["vg"]["devices"]), ("sysvg", ["pv"]))
        self.assertEqual(
            (config["lv-root"]["name"], config["lv-root"]["volgroup"], config["lv-root"]["size"]),
            ("root", "vg", 100 * 1024**3),
        )
        self.assertEqual(config["root-format"]["volume"], "lv-root")
        self.assertTrue(config["efi"]["grub_device"])

    def test_switching_back_restores_the_direct_structure(self):
        direct = self.template()
        apply_partition_layout(direct, {"root_fstype": "xfs"})
        ai = self.template()
        apply_partition_layout(ai, {"layout": "lvm"})
        apply_partition_layout(ai, {"layout": "lvm", "vg_name": "other"})
        self.assertEqual(
            next(x for x in ai["storage"]["config"] if x["type"] == "lvm_volgroup")["name"], "other"
        )
        apply_partition_layout(ai, {"root_fstype": "xfs"})
        self.assertEqual(ai["storage"], direct["storage"])

    def test_lvm_needs_room_for_boot_and_names_are_checked(self):
        self.assertEqual(
            minimum_disk_bytes({"layout": "lvm"}) - minimum_disk_bytes({}), (2048 + 16) * 1024**2
        )
        small = [disk("S1", size=22 * 1024**3)]
        self.assertEqual(select_disk(small, {})["serial"], "S1")
        with self.assertRaisesRegex(ValueError, "容量不足"):
            select_disk(small, {"layout": "lvm"})
        for bad in ({"vg_name": "-vg"}, {"lv_name": "snapshot1"}, {"vg_name": "a b"}):
            with self.assertRaisesRegex(ValueError, "名称"):
                normalize_storage({"layout": "lvm"} | bad)
        with self.assertRaisesRegex(ValueError, "分区布局"):
            normalize_storage({"layout": "raid"})
