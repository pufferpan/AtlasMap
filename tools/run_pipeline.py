"""命令行驱动整条流水线（和界面「一键全自动」走同一套代码），用来验证自动化。

用法：
    python tools/run_pipeline.py <地图名> [--dest /Game/AtlasMaps/Xxx] [--skip-textures]

导出目录默认 work/ue_test/Pipe_<地图名>，transfer 是它的 `_ue` 兄弟目录。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import exporter, ue_pipeline                                # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    name = sys.argv[1]
    dest = f"/Game/AtlasMaps/{name}54"
    skip = "--skip-textures" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--dest" and i + 1 < len(sys.argv):
            dest = sys.argv[i + 1]

    settings = exporter.load_settings()
    root = os.path.join(HERE, "work", "ue_test", "Pipe_" + name)
    p = {
        "exe": exporter.find_exe() or "",
        "config": exporter.exporter_config_path(),
        "blender": settings.get("blender") or r"G:\SteamLibrary\steamapps\common\Blender\blender.exe",
        "scripts": os.path.join(HERE, "scripts", "official"),
        "root": root,
        "transfer": root + "_ue",
        "map": name,
        "dest": dest,
        "engine": r"E:\UE_5.4\Engine\Binaries\Win64\UnrealEditor.exe",
        "cmd": r"E:\UE_5.4\Engine\Binaries\Win64\UnrealEditor-Cmd.exe",
        "project": os.path.join(HERE, "work", "ue_test", "AtlasMapTest54", "AtlasMapTest54.uproject"),
    }
    for note in ue_pipeline.prepare_dirs(root):
        print("[dirs]", note)

    steps = ue_pipeline.build_steps(p, max_tex=512, skip_textures=skip)
    t0 = time.time()

    def on_line(line: str) -> None:
        print(f"[{int(time.time() - t0):5d}s] {line}", flush=True)

    pipe = ue_pipeline.Pipeline(steps, on_line=on_line)
    pipe.start()
    while pipe.running:
        time.sleep(0.3)
    print("EXIT", pipe.code, f"{int(time.time()-t0)}s")
    return int(pipe.code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
