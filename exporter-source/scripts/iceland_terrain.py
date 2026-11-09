"""Decode Iceland CDLOD at a selected stored LOD; validate against node bounds.

Input files are unmodified BinaryAsset .uexp files extracted by dfmap raw.
The first 20 bytes are FByteBulkData and the last four are the package tag.
No geometry is synthesized for absent samples.
"""
import argparse
import json
import struct
from pathlib import Path

import numpy as np


def decode(folder, lod=3):
    folder = Path(folder)
    raw = (folder / "CDLODAsset_Header.uexp").read_bytes()
    bulk = raw[20:-4]
    tree_offset, tree_bytes = struct.unpack_from("<QQ", bulk, 16)
    assert tree_bytes % 96 == 0
    count = tree_bytes // 96
    assert tree_offset + tree_bytes <= len(bulk)
    scene = json.loads((folder / "landscape_cd_lod.json").read_text(encoding="utf-8-sig"))
    props = next(x["value"]["Properties"] for x in scene if x["type"] == "CDLODComponent")
    scale, bias = props["HeightScaleInLocalSpace"], props["HeightBiasInLocalSpace"]
    region = props["LandscapePositionAndSize"]
    step = float(2 ** lod)
    width = round(region["Z"] / 100 / step) + 1
    height = round(region["W"] / 100 / step) + 1
    x0, y0 = region["X"] / 100, region["Y"] / 100
    field = np.full((height, width), np.nan, dtype=np.float32)
    visible = np.ones((height - 1, width - 1, 2), dtype=np.bool_)
    visibility_offset, visibility_size = struct.unpack_from("<QQ", bulk, 32)
    visibility = bulk[visibility_offset:visibility_offset + visibility_size]
    coarse = (folder / "CDLODAsset_CoarseHeightmap.uexp").read_bytes()[20:-4]
    tiles = {}
    reports = []
    seam_error = 0.0
    for index in range(count):
        offset = tree_offset + index * 96
        node_lod = struct.unpack_from("<i", bulk, offset + 80)[0]
        if node_lod != lod:
            continue
        bounds = struct.unpack_from("<7f", bulk, offset + 20)
        rect = struct.unpack_from("<4f", bulk, offset + 48)
        data_offset, mask_bit_offset, tile_x, tile_y = struct.unpack_from("<4i", bulk, offset + 64)
        minimum, maximum = struct.unpack_from("<2f", bulk, offset + 84)
        if tile_x < 0:
            data = coarse
        else:
            key = (tile_x, tile_y)
            if key not in tiles:
                tiles[key] = (folder / f"CDLODAsset_Heightmap_x{tile_x}_y{tile_y}.uexp").read_bytes()[20:-4]
            data = tiles[key]
        rw, rh = round(rect[2]), round(rect[3])
        size = (rw + 2) * (rh + 2) * 4
        assert 0 <= data_offset <= len(data) - size
        rgba = np.frombuffer(data, np.uint8, count=size, offset=data_offset).reshape(rh + 2, rw + 2, 4)
        # One texel of stored border on all four sides. RG is UE's big-endian
        # packed height, normalized by the CDLOD component's scale and bias.
        rg = rgba[1:-1, 1:-1, :2].astype(np.float64)
        values = ((rg[:, :, 0] * 256 + rg[:, :, 1]) / 128 - 256) / scale + bias
        error = max(0.0, minimum - values.min(), values.max() - maximum)
        assert error < 0.02, (index, error, minimum, maximum, values.min(), values.max())
        px = bounds[0] - bounds[3] + rect[0] * step
        py = bounds[1] - bounds[4] + rect[1] * step
        ix, iy = round((px - x0) / step), round((py - y0) / step)
        assert abs(x0 + ix * step - px) < 0.001
        assert abs(y0 + iy * step - py) < 0.001
        assert 0 <= ix <= width - rw and 0 <= iy <= height - rh
        target = field[iy:iy + rh, ix:ix + rw]
        present = np.isfinite(target)
        if np.any(present):
            seam_error = max(seam_error, float(np.max(np.abs(target[present] - values[present]))))
        target[:] = values
        if mask_bit_offset >= 0:
            assert mask_bit_offset % 8 == 0
            mask_bytes = visibility[mask_bit_offset // 8:mask_bit_offset // 8 + 256]
            assert len(mask_bytes) == 256
            mask = np.unpackbits(np.frombuffer(mask_bytes, np.uint8), bitorder="little").reshape(32, 32, 2)
            rx, ry = round(rect[0]), round(rect[1])
            visible[iy:iy + rh - 1, ix:ix + rw - 1] = mask[ry:ry + rh - 1, rx:rx + rw - 1]
        reports.append({"node": index, "bounds_error_m": error, "minimum_m": float(values.min()), "maximum_m": float(values.max())})
    assert seam_error < 0.002, seam_error
    missing = int(np.isnan(field).sum())
    assert missing == 0, missing
    np.savez_compressed(folder.parent / "terrain.npz", height=field, visible=visible, x0=x0, y0=y0, step=step)
    result = {"source": "Iceland CDLOD stored height patches", "lod": lod, "spacing_m": step,
              "grid": [width, height], "patches": len(reports), "missing_samples": missing,
              "seam_error_m": seam_error, "minimum_m": float(field.min()), "maximum_m": float(field.max()),
              "height_scale": scale, "height_bias": bias, "nodes": reports}
    result["hidden_triangles_from_source_mask"] = int((~visible).sum())
    (folder / "terrain_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "nodes"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--lod", type=int, default=3)
    args = parser.parse_args()
    decode(args.folder, args.lod)
