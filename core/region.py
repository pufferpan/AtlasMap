"""区域导出：只保留框选范围内的分块。

导出器按网格把地图切成 `BigMeshGroup_<x>_<y>` 分块，每一块在
`split/manifest.json` 里都有 UE 世界坐标的包围盒。框选就是拿这个包围盒做二维
相交判断：相交的留下，不相交的连 glb 一起删掉。粒度是分块而不是三角形，
所以选中边缘会多带一点几何——这是刻意的，避免把建筑切开。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCHEMA = 1


def normalize(bounds) -> Optional[Tuple[float, float, float, float]]:
    """(minX, minY, maxX, maxY)，单位 UE 厘米；无效时返回 None。"""
    if not bounds:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in bounds)
    except (TypeError, ValueError):
        return None
    low_x, high_x = sorted((x0, x1))
    low_y, high_y = sorted((y0, y1))
    if high_x - low_x < 1.0 or high_y - low_y < 1.0:
        return None
    return low_x, low_y, high_x, high_y


def intersection(level: dict, region: Tuple[float, float, float, float]) -> float:
    """分块与选区在 XY 平面上的相交面积（平方厘米）；0 表示不相交。"""
    low = level.get('ueBoundsMin') or []
    high = level.get('ueBoundsMax') or []
    if len(low) < 2 or len(high) < 2:
        return 0.0
    width = min(float(high[0]), region[2]) - max(float(low[0]), region[0])
    height = min(float(high[1]), region[3]) - max(float(low[1]), region[1])
    if width <= 0 or height <= 0:
        return 0.0
    return width * height


def _manifest(root: os.PathLike) -> Tuple[Path, dict]:
    path = Path(root) / 'split' / 'manifest.json'
    if not path.is_file():
        raise ValueError('还没有 split/manifest.json，无法按区域过滤：' + str(path))
    return path, json.loads(path.read_text(encoding='utf-8-sig'))


def select_levels(levels: List[dict], region) -> Tuple[List[dict], List[dict]]:
    bounds = normalize(region)
    if bounds is None:
        return list(levels), []
    kept, dropped = [], []
    for level in levels:
        (kept if intersection(level, bounds) > 0 else dropped).append(level)
    return kept, dropped


def _positions(glb: Path) -> int:
    """从 glb 的 accessor 里数顶点，用来重算 totalVertices。"""
    try:
        raw = glb.read_bytes()
        import struct
        json_length = struct.unpack_from('<I', raw, 12)[0]
        document = json.loads(raw[20:20 + json_length].decode('utf-8').rstrip())
    except Exception:                                   # noqa: BLE001 - 坏文件按 0 计
        return 0
    total = 0
    for mesh in document.get('meshes') or []:
        for primitive in mesh.get('primitives') or []:
            index = (primitive.get('attributes') or {}).get('POSITION')
            accessors = document.get('accessors') or []
            if index is not None and index < len(accessors):
                total += int(accessors[index].get('count') or 0)
    return total


def filter_map(root: os.PathLike, region, *, delete: bool = True) -> Dict[str, object]:
    """按区域裁掉分块，返回统计；区域为空时原样返回。"""
    path, manifest = _manifest(root)
    levels = manifest.get('levels') or []
    kept, dropped = select_levels(levels, region)
    if region is None or not dropped:
        return {'schema': SCHEMA, 'region': normalize(region), 'kept': len(kept),
                'dropped': 0, 'removed_bytes': 0, 'levels': len(levels)}
    removed = 0
    folder = path.parent
    for level in dropped:
        for suffix in ('.glb', '.gltf'):
            candidate = folder / (str(level.get('file')) + suffix)
            if candidate.is_file():
                removed += candidate.stat().st_size
                if delete:
                    candidate.unlink()
    manifest['levels'] = kept
    manifest['totalVertices'] = sum(_positions(folder / (str(level.get('file')) + '.glb')) for level in kept)
    manifest.setdefault('note', '')
    manifest['regionFiltered'] = {'schema': SCHEMA, 'bounds': list(normalize(region)),
                                  'kept': len(kept), 'dropped': len(dropped)}
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(temporary, path)
    report = {'schema': SCHEMA, 'region': normalize(region), 'kept': len(kept),
              'dropped': len(dropped), 'removed_bytes': removed, 'levels': len(levels)}
    (Path(root) / 'region-report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    return report


def plan_rect(level: dict) -> Optional[Tuple[float, float, float, float]]:
    low = level.get('ueBoundsMin') or []
    high = level.get('ueBoundsMax') or []
    if len(low) < 2 or len(high) < 2:
        return None
    return float(low[0]), float(low[1]), float(high[0]), float(high[1])
