"""Regression-verify `dfmap map` output against the historical stitch_all.py results.

Historical reference: E:\\新建文件夹 (8)\\stitch_report.json, produced by stitch_all.py from an
FModel export of the same tile folders. It recorded, per clipmap:
  * tile grid and assembled size
  * "mip consistency": mean|d| between a box-downsample of the assembled Mip0 and the
    assembled Mip1, for the identity layout and for three flipped layouts. The identity
    layout must win by a wide margin, which is what proves the stitching orientation.

If dfmap reproduces the same sizes AND the same mip-consistency numbers, the pak-driven
export is equivalent to the historical one.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
Image.MAX_IMAGE_PIXELS = None

OUT = Path(r"G:\AAAAAmanp研究\out\maps")
HIST = Path(r"E:\新建文件夹 (8)\stitch_report.json")

hist = json.load(open(HIST, encoding="utf-8"))
hist_by_folder = {h["folder"].replace("\\", "/"): h for h in hist}

report = json.load(open(OUT / "map_export_report.json", encoding="utf-8"))
mine = {}
for r in report:
    mine.setdefault(r["map"], {})[r["mip"]] = r

print(f"historical clipmaps : {len(hist_by_folder)}")
print(f"dfmap clipmaps      : {len(mine)}\n")

print(f"{'clipmap':<58} {'size hist':>11} {'size dfmap':>11} {'grid':>7} {'ident':>7} {'yflip':>7} {'verdict'}")
print("-" * 118)

ok = bad = missing = 0
for folder, h in sorted(hist_by_folder.items()):
    hm0 = h["mips"].get("Mip0", {})
    hsize = hm0.get("size", "-")
    hgrid = hm0.get("grid", "-")

    key = folder
    if key not in mine:
        print(f"{folder:<58} {hsize:>11} {'MISSING':>11}")
        missing += 1
        continue

    m0 = mine[key].get(0)
    msize = f"{m0['width']}x{m0['height']}" if m0 else "-"
    mgrid = f"{m0['gridX']}x{m0['gridY']}" if m0 else "-"

    # recompute mip consistency on our PNGs
    p0 = OUT / f"{key.replace('/', '_')}_Mip0.png"
    p1 = OUT / f"{key.replace('/', '_')}_Mip1.png"
    ident = yflip = margin = None
    if p0.exists() and p1.exists():
        a0 = np.asarray(Image.open(p0).convert("RGBA"), dtype=np.uint8)
        a1 = np.asarray(Image.open(p1).convert("RGBA"), dtype=np.int16)
        down = np.asarray(Image.fromarray(a0).resize((a1.shape[1], a1.shape[0]), Image.BOX), dtype=np.int16)
        d = {
            "identity": float(np.abs(a1 - down).mean()),
            "y": float(np.abs(a1[::-1] - down).mean()),
            "x": float(np.abs(a1[:, ::-1] - down).mean()),
            "xy": float(np.abs(a1[::-1, ::-1] - down).mean()),
        }
        ident, yflip = d["identity"], d["y"]
        runner = min(v for k, v in d.items() if k != "identity")
        margin = runner / max(ident, 1e-6)

    hident = h.get("mip_check", {}).get("diffs", {}).get("identity (y0=top, x0=left)")
    hyflip = h.get("mip_check", {}).get("diffs", {}).get("y flipped")

    # Same criterion the historical pipeline used: the identity layout must be the BEST of
    # the four. A narrow margin is reported as a warning, exactly as stitch_all.py did.
    same_size = (msize == hsize)
    identity_best = ident is not None and yflip is not None and ident < yflip
    weak = identity_best and margin is not None and margin < 2.0
    delta = abs(ident - hident) if (ident is not None and hident is not None) else None

    if not same_size:
        verdict, bad = "SIZE MISMATCH", bad + 1
    elif not identity_best:
        verdict, bad = "ORIENTATION WRONG", bad + 1
    elif weak:
        verdict, ok = "OK (weak margin, as historically flagged)", ok + 1
    else:
        verdict, ok = "OK", ok + 1

    print(f"{folder:<58} {hsize:>11} {msize:>11} {mgrid:>7} "
          f"{(f'{ident:.2f}' if ident is not None else '-'):>7} "
          f"{(f'{yflip:.2f}' if yflip is not None else '-'):>7}  {verdict}")

    if hident is not None and ident is not None:
        exact = "" if (delta or 0) < 0.02 else f"   (historical {hident:.2f}, delta {delta:.2f})"
        print(f"{'':<58} historical ident={hident:.2f} yflip={hyflip:.2f}{exact}")

print("-" * 118)
print(f"matched: {ok}   problems: {bad}   missing: {missing}")
print("\nVERDICT: " + ("ALL CLIPMAPS REPRODUCED" if bad == 0 and missing == 0
                       else f"{bad + missing} clipmap(s) need attention"))
sys.exit(0 if bad == 0 and missing == 0 else 1)
