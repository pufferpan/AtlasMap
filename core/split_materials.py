"""Repair split GLB materials that lost their transparency.

`map-export merge` writes every material as glTF OPAQUE, even when the base-color
texture carries an alpha channel (decals, foliage cards, window decals, tape
marks). Blender then imports them solid, and the UE material compiler -- which
decides masked/translucent from the Blender alpha wiring -- copies that verdict.

The fix is mechanical: read the base-color texture of every material straight out
of the GLB, look at its alpha histogram, and write back the alphaMode the texture
actually needs. Nothing else in the file changes.
"""
from __future__ import annotations

import base64
import io
import json
import os
import struct
from pathlib import Path
from urllib.parse import unquote
from typing import Dict, Optional, Tuple

from PIL import Image

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

CLEAR = 0.02          # >=2% 全透明像素：贴图带通道，至少按裁剪处理
SEMI = 0.08           # >=8% 半透明像素：也是带通道
BLEND_SEMI = 0.30     # 半透明占三成以上、镂空很少：玻璃 / 纱网
BLEND_CLEAR_MAX = 0.30
CUTOFF = 0.5
SAMPLE = 384


def read_glb(path: os.PathLike) -> Tuple[dict, bytes]:
    raw = Path(path).read_bytes()
    magic, version, length = struct.unpack_from('<III', raw, 0)
    if magic != GLB_MAGIC or version != 2:
        raise ValueError('不是 GLB 2 文件：' + str(path))
    if length != len(raw):
        raise ValueError('GLB 长度字段与文件大小不一致：' + str(path))
    document = None
    binary = b''
    offset = 12
    while offset + 8 <= len(raw):
        size, kind = struct.unpack_from('<II', raw, offset)
        body = offset + 8
        if body + size > len(raw):
            raise ValueError('GLB 数据块被截断：' + str(path))
        if kind == CHUNK_JSON and document is None:
            document = json.loads(raw[body:body + size].decode('utf-8').rstrip())
        elif kind == CHUNK_BIN and not binary:
            binary = raw[body:body + size]
        offset = body + size
    if document is None:
        raise ValueError('GLB 没有 JSON 块：' + str(path))
    return document, binary


def write_glb(path: os.PathLike, document: dict, binary: bytes) -> None:
    text = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    text += b' ' * (-len(text) % 4)
    payload = binary + b'\0' * (-len(binary) % 4)
    body = struct.pack('<II', len(text), CHUNK_JSON) + text
    if payload:
        body += struct.pack('<II', len(payload), CHUNK_BIN) + payload
    header = struct.pack('<III', GLB_MAGIC, 2, 12 + len(body))
    temporary = Path(str(path) + '.alpha-tmp')
    temporary.write_bytes(header + body)
    os.replace(temporary, path)


def alpha_stats(data: Optional[bytes], limit: int = SAMPLE) -> Optional[Tuple[float, float]]:
    """(全透明比例, 半透明比例)；图像读不出来时返回 None。"""
    if not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            if 'A' not in image.getbands() and image.mode not in ('P', 'PA'):
                return 0.0, 0.0
            rgba = image.convert('RGBA')
            rgba.thumbnail((limit, limit))
            histogram = rgba.getchannel('A').histogram()
    except Exception:                                   # noqa: BLE001 - 坏图按不支持处理
        return None
    total = sum(histogram) or 1
    clear = sum(histogram[:128]) / total
    semi = sum(histogram[128:250]) / total
    return clear, semi


def choose_alpha_mode(clear: float, semi: float) -> str:
    if semi >= BLEND_SEMI and clear < BLEND_CLEAR_MAX:
        return 'BLEND'
    if clear >= CLEAR or semi >= SEMI:
        return 'MASK'
    return 'OPAQUE'


def _image_payload(document: dict, binary: bytes, index: int, folder: Path) -> Optional[bytes]:
    images = document.get('images') or []
    if 0 <= index < len(images):
        image = images[index]
        if 'bufferView' in image:
            view = (document.get('bufferViews') or [])[image['bufferView']]
            start = view.get('byteOffset', 0)
            return binary[start:start + view['byteLength']]
        uri = image.get('uri') or ''
        if uri.startswith('data:') and ',' in uri:
            return base64.b64decode(uri.split(',', 1)[1])
        if uri:
            # 导出器把贴图放在 ../textures/ 下，路径相对 glb，且可能带转义
            name = unquote(uri.replace('\\', '/'))
            candidate = (folder / name).resolve()
            if candidate.is_file():
                return candidate.read_bytes()
    return None


def _base_color_image(document: dict, material: dict) -> Optional[int]:
    texture = (material.get('pbrMetallicRoughness') or {}).get('baseColorTexture') or {}
    index = texture.get('index')
    if index is None:
        return None
    textures = document.get('textures') or []
    if index >= len(textures):
        return None
    return (textures[index] or {}).get('source')


def repair_glb(path: os.PathLike) -> Dict[str, object]:
    document, binary = read_glb(path)
    folder = Path(path).resolve().parent
    cache: Dict[int, Optional[Tuple[float, float]]] = {}
    changed = 0
    modes: Dict[str, int] = {'OPAQUE': 0, 'MASK': 0, 'BLEND': 0}
    materials = document.get('materials') or []
    for material in materials:
        image_index = _base_color_image(document, material)
        stats = None
        if image_index is not None:
            if image_index not in cache:
                cache[image_index] = alpha_stats(_image_payload(document, binary, image_index, folder))
            stats = cache[image_index]
        mode = choose_alpha_mode(*stats) if stats else 'OPAQUE'
        modes[mode] += 1
        if mode == 'OPAQUE':
            if 'alphaMode' in material or 'alphaCutoff' in material:
                changed += 1
            material.pop('alphaMode', None)
            material.pop('alphaCutoff', None)
            continue
        if material.get('alphaMode') != mode:
            changed += 1
        material['alphaMode'] = mode
        if mode == 'MASK':
            material['alphaCutoff'] = CUTOFF
        else:
            material.pop('alphaCutoff', None)
        if not material.get('doubleSided'):
            material['doubleSided'] = True
        material.setdefault('extras', {})['atlasmapAlpha'] = (
            'clear={:.3f} semi={:.3f}'.format(stats[0], stats[1]))
    if changed:
        write_glb(path, document, binary)
    return {'materials': len(materials), 'changed': changed, 'modes': modes}


def split_files(root: os.PathLike) -> list:
    folder = Path(root) / 'split'
    return sorted(folder.glob('*.glb')) if folder.is_dir() else []


def repair_split(root: os.PathLike, *, log=None) -> dict:
    summary = {'format': 'atlasmap-split-alpha', 'files': 0, 'changed': 0,
               'modes': {'OPAQUE': 0, 'MASK': 0, 'BLEND': 0}, 'skipped': []}
    for path in split_files(root):
        try:
            result = repair_glb(path)
        except Exception as error:                      # noqa: BLE001 - 单个文件坏不影响整张图
            summary['skipped'].append({'file': path.name, 'reason': str(error)[:200]})
            continue
        summary['files'] += 1
        summary['changed'] += int(result['changed'])
        for mode, count in result['modes'].items():
            summary['modes'][mode] += count
    if summary['files']:
        target = Path(root) / 'split' / 'material-alpha.json'
        temporary = target.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, target)
    if log:
        log('修正贴图透明通道：{} 个 GLB / {} 个材质改档（{}）'.format(
            summary['files'], summary['changed'], summary['modes']))
    return summary
