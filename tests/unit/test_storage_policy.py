"""System-disk rules must resolve to one disk, or refuse, before allocation."""

import unittest

from pxeye.installation.storage_policy import normalize_storage, select_disk


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
