"""通用游戏支持：包目录探测、密钥归一、probe 结果解析、find 输出解析。"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import generic as g
from core import generic


class GenericSupportTests(unittest.TestCase):
    def test_hex_key_accepts_common_shapes(self):
        plain = "0123456789abcdef" * 4
        spaced = "0x" + " ".join(["0123456789abcdef"] * 4)
        self.assertEqual(g.hex_key(plain), plain)
        self.assertEqual(g.hex_key(spaced), plain)
        self.assertEqual(g.hex_key("01234567-89ab-cdef-" * 4), plain)
        with self.assertRaises(ValueError):
            g.hex_key("abc")
        with self.assertRaises(ValueError):
            g.hex_key("zz" * 32)

    def test_pending_only_lists_locked_archives(self):
        data = {"archives": [
            {"file": "a.pak", "encrypted": True, "guid": "00000000", "mounted": False},
            {"file": "b.utoc", "encrypted": True, "guid": "ABCDEF01", "mounted": False},
            {"file": "c.pak", "encrypted": False, "guid": "", "mounted": False},
            {"file": "d.pak", "encrypted": True, "guid": "00000000", "mounted": True},
        ]}
        rows = g.pending(data)
        self.assertEqual([r["file"] for r in rows], ["a.pak", "b.utoc"])
        self.assertEqual(rows[0]["guid"], "")
        self.assertEqual(rows[1]["guid"], "abcdef01")
        self.assertEqual(g.pending(None), [])

    def test_parse_find_dedupes_and_keeps_order(self):
        text = (
            "   1,234  Game/Content/Maps/A.umap\n"
            "      12  Game/Content/Maps/B.umap\n"
            "   1,234  game/content/maps/a.umap\n"
            "  999  something.uexp\n"
        )
        self.assertEqual(g.parse_find(text), ["Game/Content/Maps/A.umap",
                                              "Game/Content/Maps/B.umap"])

    def test_write_config_and_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = g.write_config(Path(tmp) / "c.json", "D:/G/Content/Paks",
                                 "GAME_UE5_4", keyfile="D:/k.json", oodle="D:/o.dll")
            data = json.loads(Path(cfg).read_text(encoding="utf-8"))
            self.assertEqual(data["Game"], "GAME_UE5_4")
            self.assertEqual(data["PaksDirectory"], "D:/G/Content/Paks")
            self.assertTrue(data["Recursive"])

            keys = g.write_keys(Path(tmp) / "k.json", "ab" * 32,
                                {"00112233445566778899AABBCCDDEEFF": "cd" * 32,
                                 "0000000000000000": "ee" * 32})
            value = json.loads(Path(keys).read_text(encoding="utf-8"))
            self.assertEqual(value["MainKey"], "ab" * 32)
            self.assertEqual(len(value["Keys"]), 1)
            self.assertEqual(value["Keys"][0]["guid"],
                             "00112233445566778899aabbccddeeff")

    def test_paks_dirs_finds_nested_content_paks(self):
        with tempfile.TemporaryDirectory() as tmp:
            paks = Path(tmp) / "WuRen" / "Content" / "Paks"
            paks.mkdir(parents=True)
            (paks / "a.pak").write_bytes(b"x")
            other = Path(tmp) / "Windows"
            other.mkdir(parents=True)
            found = g.paks_dirs(tmp)
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].endswith(os.path.join("WuRen", "Content", "Paks")))
            self.assertEqual(g.paks_dirs(str(Path(tmp) / "missing")), [])


if __name__ == "__main__":
    unittest.main()


class ExportFallbackTest(unittest.TestCase):
    """只给一个 .umap 时，若没有实例就退回上级目录重导。"""

    def _manifest(self, folder, levels, instances):
        Path(folder, "split").mkdir(parents=True, exist_ok=True)
        rows = [{"file": f"{i:03d}_L{i}", "level": f"L{i}", "instances": instances}
                for i in range(levels)]
        Path(folder, "split", "manifest.json").write_text(
            json.dumps({"levels": rows}), encoding="utf-8")

    def test_instances_reads_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(generic._instances(tmp), (0, 0))
            self._manifest(tmp, 3, 4)
            self.assertEqual(generic._instances(tmp), (3, 12))

    def test_empty_single_file_falls_back_to_folder(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "merge" in cmd:                             # 只有退回目录才有实例
                self._manifest(cmd[-1], 2, 5)
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(generic.subprocess, "run", side_effect=fake_run):
            run = generic.export_map("exe", "cfg", "Game/Content/ZP/L_HE.uasset", tmp)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("merge", calls[1])
        self.assertIn("Game/Content/ZP/", calls[1])
        self.assertIn("改用上级目录", run.stdout)

    def test_single_file_with_instances_is_kept(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            self._manifest(cmd[-1], 1, 7)
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(generic.subprocess, "run", side_effect=fake_run):
            generic.export_map("exe", "cfg", "Game/A/B.umap", tmp)
        self.assertEqual(len(calls), 1)
