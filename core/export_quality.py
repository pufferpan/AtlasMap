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


def _history_path():
    from core import exporter
    return Path(exporter.app_dir())/'export-size-history.json'


def _history():
    data=_read(_history_path())
    maps=data.get('maps') if isinstance(data,dict) else None
    return maps if isinstance(maps,dict) else {}


def _folder_bytes(folder,extensions=None):
    total=0;count=0
    try:
        iterator=Path(folder).rglob('*')
        for path in iterator:
            try:
                if not path.is_file():continue
                if extensions and path.suffix.lower() not in extensions:continue
                total+=path.stat().st_size;count+=1
            except OSError:continue
    except OSError:return total,count
    return total,count


def record_export(map_name,root,project='',max_tex=0):
    """Remember how big this map really came out; the next estimate is exact.

    Only byte counts are stored, so the file stays tiny and moving the export
    directory afterwards does not invalidate anything.
    """
    root=str(root or '')
    if not root or not Path(root).is_dir():return False
    from pathlib import Path as _P
    total,_=_folder_bytes(root)
    blend,_=_folder_bytes(root,{'.blend'})
    texture_bytes=0;pixels=0;images=0
    metadata=_read(_P(root)/'export-quality.json')
    folders=[_P(root),*(_P(p) for p in metadata.get('sources',[]) if Path(p).is_dir())]
    from scripts.official.map_image_header import image_dimensions
    seen=set()
    for folder in folders:
        for path in (folder/'textures').glob('*.png'):
            if str(path) in seen:continue
            seen.add(str(path))
            try:
                with path.open('rb') as source:header=source.read(24)
                width,height=image_dimensions(header,str(path))
            except (OSError,ValueError):continue
            texture_bytes+=path.stat().st_size;pixels+=width*height;images+=1
    reference=int(metadata.get('max_tex',max_tex) or max_tex or 0)
    if reference==0 and images:reference=max(1024,int(math.sqrt(pixels/images)))
    ue_bytes=0
    if project:
        parent=_P(project).parent
        content=parent/'Content'
        target=content if content.is_dir() else parent
        if target.is_dir() and target!=_P(root):ue_bytes,_=_folder_bytes(target)
    entry=dict(source_bytes=total,texture_bytes=texture_bytes,blend_bytes=blend,ue_bytes=ue_bytes,
               reference=reference,when=time.strftime('%Y-%m-%d %H:%M:%S'))
    maps=_history()
    maps[str(map_name).lower()]=entry
    path=_history_path();path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(dict(format='atlasmap-export-history',maps=maps),indent=2),encoding='utf-8')
    temporary.replace(path)
    return True


def evidence(map_name,root='',files=0,settings=None):
    """Read small headers/reports only: never load/decode game meshes or images."""
    from core import exporter
    settings=settings or exporter.load_settings()
    entry=_history().get(str(map_name).lower())
    if entry and int(entry.get('source_bytes',0))>0:
        return dict(entry,kind='history',
                    note='本图上次导出成功时记录的真实大小，只有贴图会随档位变化。')
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
    kind=data['kind']
    if kind=='history':
        # 本图上次成功导出时量到的真实字节数，只把贴图部分按档位折算
        tex=max(0,int(data.get('texture_bytes',0)))
        reference=int(data.get('reference',0) or 0)
        scale=(limit/reference)**2 if (limit and reference) else (1.0 if not limit else .8)
        scale=max(.05,min(1.0,scale))
        source_bytes=int(data.get('source_bytes',0) or 0)
        measured=int(data.get('ue_bytes' if target=='ue' else ('blend_bytes' if target=='blender' else 'source_bytes'),0) or 0)
        if target=='ue' and not data.get('ue_bytes'):measured=int(source_bytes*.55)
        if target=='blender' and not data.get('blend_bytes'):measured=int(source_bytes*.45)
        if source_bytes<=0:kind='inventory'
        else:
            share=min(tex,max(0,measured))
            value=max(0,measured-share)+share*scale
            exact=bool((not limit and not reference) or (limit and limit==reference))
            spread=.12 if exact else .30
            lower=int(value*(1-spread));upper=int(value*(1+spread))
            note=('按本图上次成功导出的实测大小' if exact else '按本图上次实测大小，贴图按当前档位折算')+'；其余资源按上次记录不变。'
            temporary=int(max(GB,upper*(2.5+.2*max(0,min(8,int(parallel))-1))))
            return dict(low=lower,high=upper,free_recommended=temporary,approximate=not exact,
                        original_unbounded=limit==0,basis='history',note=note)
    if kind=='source':
        fixed=int(data['geometry'])+int(data.get('instances',0))*1024
        tex=max(int(data.get('texture_bytes',0)),int(data.get('images',0))*16*1024,
                int(data['geometry']) if not data.get('images') else 0)
        reference=int(data['reference'])
        scale=(limit/reference)**2 if limit else max(1,(8192/reference)**2)
        scale=max(.02,min(1.0,scale))
        tex_low=tex*scale;tex_high=tex*scale
        geometry=int(data['geometry'])
        if target=='ue':
            # PNG 与 BC 压缩后的体积比在 0.5–1.35 之间摆动（取决于是否有 alpha、
            # 虚拟贴图和原图位深），实测 SafeHouse 1.09、ShootingArea 0.56。
            lower=tex_low*.50+geometry*.25;upper=tex_high*1.35+geometry*.60
        elif target=='blender':
            lower=tex_low*1.10+geometry*.9;upper=tex_high*1.70+geometry*1.3
        else:
            # 源目录 = 贴图 PNG + .blend + .glb/json；实测 .blend 占贴图的 0.8–1.0 倍
            lower=tex_low*1.75+geometry;upper=tex_high*2.45+geometry*1.6
        temporary=int(max(GB,upper*(2.5+.2*max(0,min(8,int(parallel))-1))))
        return dict(low=int(lower),high=max(int(lower),int(upper)),free_recommended=temporary,
                    approximate=True,original_unbounded=limit==0,basis='source',note=data['note'])
    # 没有实测量、也没有导出历史：只能按包体积给一个很宽的经验区间
    package=max(0,int(data.get('package_bytes',0)))
    levels=max(1,int(data.get('levels',1)))
    if package<=0:
        package=max(8*MB,levels*512*1024)
    ratio={'raw':(3.2,8.0),'blender':(2.8,6.5),'ue':(1.4,2.6)}[target]
    scale=(limit/1024)**2 if limit else 1.0
    scale=max(.04,min(1.0,scale))
    lower=package*ratio[0]*(.55+.45*scale)
    upper=package*ratio[1]*(.35+.65*scale)
    temporary=int(max(GB,upper*(2.5+.2*max(0,min(8,int(parallel))-1))))
    note=(' '.join(filter(None,(str(data.get('note') or ''),
                                '还没有这张图的导出记录，只能按地图包体积粗估，实际可能差到 2 倍。'))))
    return dict(low=int(lower),high=int(upper),free_recommended=temporary,approximate=True,
                original_unbounded=limit==0,basis='inventory',note=note)


def record_quality(root,key,maximum=None,sources=()):
    path=Path(root)/'export-quality.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(dict(quality=quality(key).key,max_tex=max_texture(dict(export_quality=key),maximum),
                                    sources=[str(p) for p in sources]),indent=2),encoding='utf-8')
