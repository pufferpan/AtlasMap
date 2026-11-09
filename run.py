"""开发期入口：`python run.py`（打包后走 AtlasMap.exe）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    try:
        from app.__main__ import main
        raise SystemExit(main())
    except Exception:
        import tempfile
        import traceback
        with open(os.path.join(tempfile.gettempdir(), "atlasmap_crash.txt"),
                  "w", encoding="utf-8") as fh:
            fh.write(traceback.format_exc())
        raise
