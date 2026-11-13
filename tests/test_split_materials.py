"""贴图透明通道修复：贴花 / 树叶 / 纱网不能当实心材质导出。"""
import io
import json
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from core import split_materials as materials


def png(size=(16, 16), alpha=None, mode='RGBA'):
    image = Image.new('RGBA', size, (200, 120, 60, 255))
    if alpha:
        pixels = image.load()
        for y in range(size[1]):
            for x in range(size[0]):
                if alpha(x, y):
                    pixels[x, y] = (200, 120, 60, 0)
    if mode == 'RGB':
        return _encode(image.convert('RGB'))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def _encode(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def glb(materials_spec, images, *, alpha_modes=None):
    """最小的合法 GLB：一个场景、一块 buffer 装 PNG。"""
    document = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': []}],
                'nodes': [], 'meshes': [], 'accessors': [], 'bufferViews': [],
                'images': [], 'textures': [], 'materials': [], 'buffers': [{}]}
    binary = b''
    for data in images:
        while len(binary) % 4:
            binary += b'\0'
        document['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary),
                                        'byteLength': len(data)})
        document['images'].append({'bufferView': len(document['bufferViews']) - 1,
                                   'mimeType': 'image/png'})
        binary += data
    document['buffers'][0] = {'byteLength': len(binary)}
    for index, entry in enumerate(materials_spec):
        document['textures'].append({'source': entry['image'], 'sampler': 0})
        material = {'name': entry.get('name', 'M%d' % index),
                    'pbrMetallicRoughness': {'baseColorTexture': {'index': index}}}
        if alpha_modes and entry.get('declared'):
            material['alphaMode'] = entry['declared']
        document['materials'].append(material)
    return document, binary


def write(path, document, binary):
    text = json.dumps(document, separators=(',', ':')).encode('utf-8')
    text += b' ' * (-len(text) % 4)
    binary = binary + b'\0' * (-len(binary) % 4)
    body = struct.pack('<II', len(text), materials.CHUNK_JSON) + text
    body += struct.pack('<II', len(binary), materials.CHUNK_BIN) + binary
    Path(path).write_bytes(struct.pack('<III', materials.GLB_MAGIC, 2, 12 + len(body)) + body)


class SplitMaterialTests(unittest.TestCase):

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / 'split').mkdir()

    def tearDown(self):
        self.folder.cleanup()

    def _write(self, name, materials_spec, images, alpha_modes=None):
        document, binary = glb(materials_spec, images, alpha_modes=alpha_modes)
        path = self.root / 'split' / name
        write(path, document, binary)
        return path

    def test_opaque_texture_stays_opaque(self):
        path = self._write('000_a.glb', [{'image': 0}], [png(mode='RGB')])
        result = materials.repair_glb(path)
        self.assertEqual(result['modes']['OPAQUE'], 1)
        document, _ = materials.read_glb(path)
        self.assertNotIn('alphaMode', document['materials'][0])

    def test_cutout_texture_becomes_mask(self):
        # 四分之一像素全透明 —— 树叶卡片、贴花都属于这一档
        path = self._write('000_b.glb', [{'image': 0}],
                           [png(alpha=lambda x, y: x < 8 and y < 8)])
        result = materials.repair_glb(path)
        self.assertEqual(result['modes']['MASK'], 1)
        document, _ = materials.read_glb(path)
        material = document['materials'][0]
        self.assertEqual(material['alphaMode'], 'MASK')
        self.assertEqual(material['alphaCutoff'], materials.CUTOFF)
        self.assertTrue(material['doubleSided'])

    def test_soft_alpha_becomes_blend(self):
        # 一半像素半透明、几乎没有镂空 —— 玻璃、纱网
        def semi(x, y):
            return (x + y) % 2 == 0

        image = Image.new('RGBA', (16, 16), (10, 10, 10, 128))
        pixels = image.load()
        for y in range(16):
            for x in range(16):
                if semi(x, y):
                    pixels[x, y] = (10, 10, 10, 255)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        path = self._write('000_c.glb', [{'image': 0}], [buffer.getvalue()])
        result = materials.repair_glb(path)
        self.assertEqual(result['modes']['BLEND'], 1)
        document, _ = materials.read_glb(path)
        self.assertEqual(document['materials'][0]['alphaMode'], 'BLEND')
        self.assertNotIn('alphaCutoff', document['materials'][0])

    def test_repair_is_idempotent_and_keeps_binary(self):
        path = self._write('000_d.glb', [{'image': 0}],
                           [png(alpha=lambda x, y: y < 6)])
        first, binary_first = materials.read_glb(path)
        materials.repair_glb(path)
        second, binary_second = materials.read_glb(path)
        self.assertEqual(binary_first, binary_second)
        materials.repair_glb(path)
        third, binary_third = materials.read_glb(path)
        self.assertEqual(second['materials'], third['materials'])
        self.assertEqual(binary_second, binary_third)
        self.assertEqual(first['materials'][0].get('alphaMode'), None)

    def test_missing_texture_falls_back_to_opaque(self):
        document, binary = glb([{'image': -1}], [png()])
        document['materials'][0]['pbrMetallicRoughness'].pop('baseColorTexture')
        path = self.root / 'split' / '000_e.glb'
        write(path, document, binary)
        result = materials.repair_glb(path)
        self.assertEqual(result['modes']['OPAQUE'], 1)

    def test_split_summary_lists_every_file(self):
        self._write('000_f.glb', [{'image': 0}], [png(alpha=lambda x, y: y < 4)])
        self._write('001_g.glb', [{'image': 0}], [png(mode='RGB')])
        summary = materials.repair_split(self.root)
        self.assertEqual(summary['files'], 2)
        self.assertGreaterEqual(summary['changed'], 1)
        stored = json.loads((self.root / 'split' / 'material-alpha.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['files'], 2)
        self.assertEqual(stored['modes']['MASK'], 1)
        self.assertEqual(stored['modes']['OPAQUE'], 1)

    def test_corrupt_file_is_reported_not_raised(self):
        (self.root / 'split' / '000_bad.glb').write_bytes(b'not a glb at all')
        summary = materials.repair_split(self.root)
        self.assertEqual(summary['files'], 0)
        self.assertEqual(len(summary['skipped']), 1)


if __name__ == '__main__':
    unittest.main()
