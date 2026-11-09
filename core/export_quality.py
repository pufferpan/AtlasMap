"""Shared texture quality and explicitly approximate export/storage forecasts."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import time
import uuid

MB=1024**2
GB=1024**3


@dataclass(frozen=True)
class Quality:
    key:str
    title:str
    max_tex:int
    note:str


QUALITIES=(
    Quality('draft','轻量 · 512',512,'适合快速查看，贴图最高 512 像素。'),
    Quality('standard','标准 · 1K（推荐）',1024,'兼顾清晰度、导出时间和磁盘占用。'),
    Quality('high','高清 · 2K',2048,'适合近距离查看，贴图最高 2048 像素。'),
    Quality('ultra','超清 · 4K',4096,'保留更多贴图细节，占用空间和内存更高。'),
    Quality('original','原始 · 不限制',0,'使用资源中可用的原始 mip，体积可能明显增加。'),
)


def quality(key=None):
    return next((q for q in QUALITIES if q.key==key),QUALITIES[1])


def max_texture(parameters,override=None):
    value=override if override is not None else parameters.get('max_tex',quality(parameters.get('export_quality')).max_tex)
    value=int(value)
    if value<0 or value>32768:raise ValueError('贴图上限必须在 0–32768 之间')
    return value


def size_text(value):
    return f'{value/GB:.1f} GB' if value>=GB else f'{max(1,math.ceil(value/MB))} MB'


def _read(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def _cache_path():
    from core import exporter
    return Path(exporter.app_dir())/'export-size-inventory.json'


def cache_inventory(text,settings):
    """Keep byte counts from the same mounted-game listing used by map scanning."""
    pattern=re.compile(r'^\s*([\d,]+)\s+(DeltaForce/Content/Maps/(?:(?:BuildMaps_HD|BuildMaps)/)?([^/\s]+)/.+)\s*$',re.I)
    maps={};seen=set()
    for line in text.splitlines():
        match=pattern.match(line)
        if not match:continue
        size,path,name=match.groups();path=path.strip().lower()
        if path in seen or name.lower().startswith('physxshared'):continue
        seen.add(path)
        row=maps.setdefault(name.lower(),dict(files=0,package_bytes=0,levels=0))
        row['files']+=1;row['package_bytes']+=int(size.replace(',',''))
        row['levels']+=int(path.endswith('.umap'))
    value=dict(paks=str(settings.get('paks','')),game=settings.get('game','GAME_DeltaForce'),scanned=time.time(),maps=maps)
    path=_cache_path();temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temporary.replace(path)


def evidence(map_name,root='',files=0,settings=None):
    """Read small headers/reports only: never load/decode game meshes or images."""
    from core import exporter
    settings=settings or exporter.load_settings()
    report=_read(Path(root)/'merge_report.json') if root else {}
    declared=str(report.get('MapRoot','')).replace('\\','/').lower()
    roots=[f'deltaforce/content/maps/{prefix}{map_name}/'.lower() for prefix in ('','BuildMaps_HD/','BuildMaps/')]
    if int(report.get('Instances',0))>0 and any(r in declared.split(' + ') for r in roots):
        texture_bytes=0;pixels=0;images=0
        metadata=_read(Path(root)/'export-quality.json')
        folders=[Path(root),*(Path(p) for p in metadata.get('sources',[]))]
        paths={path for folder in folders for path in (folder/'textures').glob('*.png')}
        for path in paths:
            try:
                with path.open('rb') as source:header=source.read(24)
                from scripts.official.map_image_header import image_dimensions
                width,height=image_dimensions(header,str(path))
                texture_bytes+=path.stat().st_size;pixels+=width*height;images+=1
            except (OSError,ValueError):continue
        # Old releases always used 1024 in the one-click pipelines.
        reference=int(metadata.get('max_tex',1024))
        if reference==0 and images:reference=max(1024,int(math.sqrt(pixels/images)))
        geometry=max(4*MB,int(report.get('Vertices',0))*48+int(report.get('Triangles',0))*12)
        return dict(kind='source',geometry=geometry,instances=int(report['Instances']),
                    texture_bytes=texture_bytes,reference=max(1,reference),images=images,
                    note='基于该地图已有的源导出统计；切换到更高质量时仍是推算。')
    cache=_read(_cache_path())
    if cache.get('paks')==str(settings.get('paks','')) and cache.get('game')==settings.get('game','GAME_DeltaForce'):
        row=cache.get('maps',{}).get(map_name.lower())
        if row and row.get('levels',0)>0:return dict(row,kind='inventory',note='按扫描到的地图包体积初估；外部引用、资源复用和压缩率会造成较大偏差。')
    if files>0:return dict(kind='count',files=files,package_bytes=0,levels=max(1,files//4),
                           note='仅按地图文件数量初估；重新扫描地图可补充包体积依据。')
    return None


def forecast(data,key='standard',target='ue',parallel=1):
    """A planning range, not a promised upper bound or the total project size."""
    if not data:return None
    limit=int(quality(key).max_tex)
    if data['kind']=='source':
        fixed=int(data['geometry'])+int(data.get('instances',0))*1024
        tex=max(int(data.get('texture_bytes',0)),int(data.get('images',0))*16*1024,
                int(data['geometry']) if not data.get('images') else 0)
        reference=data['reference']
        scale=(limit/reference)**2 if limit else max(1,(8192/reference)**2)
        tex_low=tex*min(1,scale)*.65;tex_high=tex*scale*1.6
        lower=fixed*.7+tex_low;upper=fixed*2+max(tex_low,tex_high)
    else:
        # Missing mesh/texture metadata makes the first estimate intentionally
        # broad. Package bytes include only assets under this map's own roots.
        package=max(0,int(data.get('package_bytes',0)))
        levels=max(1,int(data.get('levels',1)))
        fixed=max(4*MB,package*2+levels*256*1024)
        texture_base=max(8*MB,package*3+levels*MB)
        scale=(limit/1024)**2 if limit else 64
        lower=fixed*.5+texture_base*min(1,scale)*.25
        upper=fixed*4+texture_base*scale*2
    factor={'raw':1,'blender':1.2,'ue':1.7}[target]
    lower=int(lower*factor);upper=max(lower,int(upper*factor))
    # Source files, transfer textures, native imports and shader/cache files
    # coexist; parallel workers may duplicate some intermediate resources.
    temporary=int(max(GB,upper*(2.5+.2*max(0,min(8,int(parallel))-1))))
    return dict(low=lower,high=upper,free_recommended=temporary,approximate=True,
                original_unbounded=limit==0,basis=data['kind'],note=data['note'])


def record_quality(root,key,maximum=None,sources=()):
    path=Path(root)/'export-quality.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(dict(quality=quality(key).key,max_tex=max_texture(dict(export_quality=key),maximum),
                                    sources=[str(p) for p in sources]),indent=2),encoding='utf-8')
