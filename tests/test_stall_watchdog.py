"""子进程长时间没有输出时，流水线应当终止它并说明原因。"""

from __future__ import annotations

import os
import sys
import time
import unittest

from core.ue_pipeline import Pipeline, Step


class StallWatchdogTest(unittest.TestCase):
    def test_silent_process_is_killed(self):
        script = "import time; print('start', flush=True); time.sleep(120)"
        step = Step(name="silent", cmd=[sys.executable, "-c", script], cwd=os.getcwd(), env={})
        lines = []
        pipeline = Pipeline([step], on_line=lines.append)
        old = os.environ.get("ATLASMAP_STALL_SECONDS")
        os.environ["ATLASMAP_STALL_SECONDS"] = "2"
        try:
            started = time.time()
            pipeline.start()
            pipeline._thread.join(30)
            elapsed = time.time() - started
        finally:
            if old is None:
                os.environ.pop("ATLASMAP_STALL_SECONDS", None)
            else:
                os.environ["ATLASMAP_STALL_SECONDS"] = old
        self.assertEqual(pipeline.code, -7, "\n".join(lines[-20:]))
        self.assertLess(elapsed, 30)
        self.assertTrue(any("进程卡住" in line for line in lines), lines[-10:])


if __name__ == "__main__":
    unittest.main()
