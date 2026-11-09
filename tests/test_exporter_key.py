"""密钥文件定位：设置里的路径失效时要能自己找到随包/程序目录里的那一份。"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from core import exporter


class KeyfileLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.key = os.path.join(self.dir, "AESKey1.json")
        with open(self.key, "w", encoding="utf-8") as fh:
            fh.write('{"mainKey": "0x00", "keys": {}}')
        patcher = mock.patch.object(exporter, "app_dir", return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_prefers_explicit_setting(self) -> None:
        chosen = os.path.join(self.dir, "my-key.json")
        with open(chosen, "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.assertEqual(exporter.resolve_keyfile({"keyfile": chosen}), chosen)

    def test_stale_setting_falls_back_to_program_dir(self) -> None:
        stale = os.path.join(self.dir, "gone", "AESKey1.json")
        self.assertEqual(exporter.resolve_keyfile({"keyfile": stale}), self.key)

    def test_nothing_found_is_empty_string(self) -> None:
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        with mock.patch.object(exporter, "_src_root", return_value=empty.name), \
                mock.patch.object(exporter, "_meipass", return_value=None), \
                mock.patch.object(exporter, "app_dir", return_value=empty.name):
            self.assertEqual(exporter.resolve_keyfile({"keyfile": ""}), "")

    def test_config_writes_resolved_absolute_path(self) -> None:
        path = os.path.join(self.dir, "job.json")
        written = exporter.write_exporter_config(
            {"keyfile": os.path.join(self.dir, "nope.json"), "paks": "D:/Game/Paks"}, path=path)
        self.assertEqual(written, path)
        import json
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["KeyFile"], self.key.replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
