"""并发上限是否按内存余量收紧要能被开关控制。"""

from __future__ import annotations

import unittest
from unittest import mock

from core import exporter, system_usage


GB = 1024 ** 3


def _tight():
    return {"memory_available": 1 * GB, "commit_available": 1 * GB, "memory_total": 16 * GB}


def _loose():
    return {"memory_available": 48 * GB, "commit_available": 96 * GB, "memory_total": 64 * GB}


class MemoryLimitTest(unittest.TestCase):
    def test_switch_off_uses_requested_count(self):
        self.assertEqual(system_usage.ue_process_capacity(8, snapshot=_tight(), limit_by_memory=False), 8)
        self.assertEqual(system_usage.ue_import_capacity(8, [6 * GB], snapshot=_tight(),
                                                         limit_by_memory=False), 8)

    def test_switch_on_respects_available_memory(self):
        self.assertEqual(system_usage.ue_process_capacity(8, snapshot=_tight(), limit_by_memory=True), 1)
        self.assertGreater(system_usage.ue_process_capacity(8, snapshot=_loose(), limit_by_memory=True), 1)

    def test_import_budget_is_ignored_when_off(self):
        costs = [40 * GB, 40 * GB]
        self.assertEqual(system_usage.ue_import_capacity(2, costs, snapshot=_loose(),
                                                         limit_by_memory=False), 2)
        self.assertLessEqual(system_usage.ue_import_capacity(2, costs, snapshot=_loose(),
                                                             limit_by_memory=True), 1)

    def test_default_reads_setting(self):
        with mock.patch.object(exporter, "load_settings", return_value={"mem_limit": False}):
            self.assertEqual(system_usage.ue_process_capacity(6, snapshot=_tight()), 6)
        with mock.patch.object(exporter, "load_settings", return_value={}):
            self.assertTrue(system_usage.memory_aware())
        with mock.patch.object(exporter, "load_settings", return_value={"mem_limit": False}):
            self.assertFalse(system_usage.memory_aware())


if __name__ == "__main__":
    unittest.main()
