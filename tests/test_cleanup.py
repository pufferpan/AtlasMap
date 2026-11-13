"""导出后临时文件清理的行为。"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from core import cleanup, generic


def _write(path: Path, size: int = 8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class PlanAndCleanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Iris_Entry"
        self.app = Path(self._tmp.name) / "app"
        _write(self.root / "preview" / "abc" / "worker_0.npz", 16)
        _write(self.root / "source-render" / "raw" / "000.glb", 64)
        _write(self.root / "source-render" / "textures" / "a.png", 32)
        _write(self.root / "Iris_Entry_blender" / "run1" / "tasks" / "chunk_000.json", 8)
        _write(self.root / "split" / "000.glb", 128)
        _write(self.root / "scene.json", 256)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_plan_lists_only_intermediates(self):
        plan = cleanup.plan(str(self.root), app_dir=self.app / "none")
        kinds = sorted({item["kind"] for item in plan["items"]})
        self.assertEqual(kinds, ["preview", "raw", "tasks"])
        self.assertGreater(plan["size"], 0)

    def test_clean_keeps_deliverables(self):
        result = cleanup.clean(str(self.root), app_dir=self.app / "none")
        self.assertGreaterEqual(result["removed"], 3)
        self.assertFalse((self.root / "preview").exists())
        self.assertFalse((self.root / "source-render" / "raw").exists())
        self.assertEqual((self.root / "split" / "000.glb").read_bytes(), b"x" * 128)
        self.assertTrue((self.root / "scene.json").is_file())
        self.assertTrue((self.root / "source-render" / "textures" / "a.png").is_file())

    def test_keep_raw_leaves_chunks(self):
        cleanup.clean(str(self.root), include_raw=False, app_dir=self.app / "none")
        self.assertTrue((self.root / "source-render" / "raw" / "000.glb").is_file())
        self.assertFalse((self.root / "preview").exists())

    def test_old_job_configs_and_logs_are_pruned(self):
        jobs = self.app / "job-config"
        logs = self.app / "logs"
        jobs.mkdir(parents=True)
        logs.mkdir(parents=True)
        for index in range(cleanup.KEEP_JOB_CONFIGS + 5):
            path = jobs / f"{index}.json"
            _write(path)
            stamp = time.time() - (1000 - index)
            os.utime(path, (stamp, stamp))
        for index in range(cleanup.KEEP_LOGS + 4):
            path = logs / f"log-{index}.txt"
            _write(path)
            stamp = time.time() - (1000 - index)
            os.utime(path, (stamp, stamp))
        plan = cleanup.plan(str(self.root), include_raw=False, app_dir=self.app)
        kept = {Path(str(item["path"])).name for item in plan["items"]}
        self.assertNotIn(f"{cleanup.KEEP_JOB_CONFIGS + 4}.json", kept)
        self.assertIn("0.json", kept)
        self.assertNotIn(f"log-{cleanup.KEEP_LOGS + 3}.txt", kept)
        self.assertIn("log-0.txt", kept)

    def test_probe_leaves_no_temp_folder(self):
        before = set(Path(tempfile.gettempdir()).glob("atlasmap-probe-*"))
        code, data, _err = generic.probe(str(self.root / "missing.exe"), "x.json", timeout=5)
        self.assertEqual(code, 2)
        self.assertIsNone(data)
        after = set(Path(tempfile.gettempdir()).glob("atlasmap-probe-*"))
        self.assertEqual(after - before, set())


if __name__ == "__main__":
    unittest.main()
