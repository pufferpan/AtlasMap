"""区域导出：分块筛选、glb 裁剪与报告。"""
from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from core import region


def _glb(positions: int = 3) -> bytes:
    """最小可解析的 glb：只有 POSITION accessor 的计数信息。"""
    document = {'asset': {'version': '2.0'}, 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
                'accessors': [{'componentType': 5126, 'count': positions, 'type': 'VEC3'}]}
    payload = json.dumps(document).encode('utf-8')
    payload += b' ' * ((4 - len(payload) % 4) % 4)
    binary = b'\x00' * 12
    header = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(payload) + 8 + len(binary))
    return (header + struct.pack('<II', len(payload), 0x4E4F534A) + payload
            + struct.pack('<II', len(binary), 0x004E4942) + binary)


def _level(name: str, low, high, instances: int = 1) -> dict:
    return {'file': name, 'level': f'{name}.umap', 'instances': instances,
            'ueBoundsMin': [low[0], low[1], 0.0], 'ueBoundsMax': [high[0], high[1], 0.0]}


class RegionTest(unittest.TestCase):
    def test_normalize_sorts_and_rejects_tiny(self):
        self.assertEqual(region.normalize([10, 20, -10, 0]), (-10, 0, 10, 20))
        self.assertIsNone(region.normalize([0, 0, 0.4, 10]))
        self.assertIsNone(region.normalize(['a', 0, 1, 1]))
        self.assertIsNone(region.normalize(None))

    def test_select_levels_keeps_intersecting_only(self):
        levels = [_level('BigMeshGroup_0_0', (0, 0), (1000, 1000)),
                  _level('BigMeshGroup_1_0', (2000, 0), (3000, 1000)),
                  _level('BigMeshGroup_5_5', (5000, 5000), (6000, 6000))]
        kept, dropped = region.select_levels(levels, region.normalize((900, 900, 2100, 2100)))
        names = [row['file'] for row in kept]
        self.assertIn('BigMeshGroup_0_0', names)
        self.assertIn('BigMeshGroup_1_0', names)
        self.assertEqual([row['file'] for row in dropped], ['BigMeshGroup_5_5'])

    def test_filter_map_deletes_outside_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            split = root / 'split'
            split.mkdir()
            levels = [_level('keep_me', (0, 0), (500, 500)), _level('drop_me', (5000, 5000), (5500, 5500))]
            for row in levels:
                (split / (row['file'] + '.glb')).write_bytes(_glb(6 if row['file'] == 'keep_me' else 2))
            manifest = {'note': '', 'levels': levels, 'totalVertices': 8}
            (split / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

            report = region.filter_map(root, region.normalize((-100, -100, 600, 600)))
            self.assertEqual((report['kept'], report['dropped']), (1, 1))
            self.assertFalse((split / 'drop_me.glb').exists())
            self.assertTrue((split / 'keep_me.glb').exists())
            saved = json.loads((split / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual([row['file'] for row in saved['levels']], ['keep_me'])
            self.assertEqual(saved['totalVertices'], 6)
            self.assertEqual(saved['regionFiltered']['dropped'], 1)
            written = json.loads((root / 'region-report.json').read_text(encoding='utf-8'))
            self.assertEqual(written['region'], [-100.0, -100.0, 600.0, 600.0])

    def test_filter_map_without_region_touches_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            split = root / 'split'
            split.mkdir()
            (split / 'a.glb').write_bytes(_glb())
            (split / 'manifest.json').write_text(
                json.dumps({'levels': [_level('a', (0, 0), (10, 10))]}), encoding='utf-8')
            report = region.filter_map(root, None)
            self.assertEqual(report['dropped'], 0)
            self.assertTrue((split / 'a.glb').exists())

    def test_plan_rect_marks_blender_bounds(self):
        row = _level('a', (-1000, -2000), (1000, 2000))
        rect = region.plan_rect(row)
        self.assertEqual(rect, (-1000.0, -2000.0, 1000.0, 2000.0))


if __name__ == '__main__':
    unittest.main()
