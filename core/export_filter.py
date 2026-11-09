"""Remove confirmed BombDefusal start barriers from exported static scenes.

Identity comes from the source actor class, never a Plane mesh, white material,
name substring such as BlockWall, or inferred visibility. Geometry buffers stay
byte-for-byte intact; unused mesh data may remain after its nodes are removed.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

from scripts.official.map_io import io_path

RULE='bombdefusal_start_barrier_v1'
ACTOR_CLASS=re.compile(r"(?:^|/)BP_BlockWall_BombDefusal_C'",re.I)
MAP_PATH=re.compile(r'(?:^|/)Maps/(?:BuildMaps_HD/)?BombDefusal_[^/]+/',re.I)
JSON_CHUNK=0x4e4f534a
BIN_CHUNK=0x004e4942


def is_start_barrier(instance):
    metadata=instance.get('dfmap') or {}
    if isinstance(metadata,str):metadata=json.loads(metadata)
    source=str(metadata.get('sourceLevel') or instance.get('name') or '')
    return bool(MAP_PATH.search(source) and ACTOR_CLASS.search(str(instance.get('name',''))))


def _source_id(node):
    data=node.get('extras',{}).get('dfmap',{})
    if isinstance(data,str):data=json.loads(data)
    return data.get('sourceId') or node.get('name','')


def _json_bytes(data):
    return json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')


def _glb_parts(raw):
    if len(raw)<20 or struct.unpack_from('<III',raw)!=(0x46546c67,2,len(raw)):
        raise ValueError('Invalid GLB header')
    chunks=[];offset=12
    while offset<len(raw):
        if offset+8>len(raw):raise ValueError('Truncated GLB chunk header')
        size,kind=struct.unpack_from('<II',raw,offset);offset+=8
        if size%4 or offset+size>len(raw):raise ValueError('Invalid GLB chunk length')
        chunks.append((kind,raw[offset:offset+size]));offset+=size
    if not chunks or chunks[0][0]!=JSON_CHUNK:raise ValueError('Missing GLB JSON')
    return chunks


def remove_glb_nodes(raw,rejected):
    chunks=_glb_parts(raw);document=json.loads(chunks[0][1])
    original=document.get('nodes',[])
    removed={i for i,node in enumerate(original) if _source_id(node) in rejected}
    if not removed:return raw,None,0
    if document.get('skins') or document.get('animations'):
        raise ValueError('Start-barrier filtering requires a static GLB (no skins/animations)')
    # The exporter emits flat source placements. Keep the invariant explicit
    # instead of accidentally deleting a foreign source object's child tree.
    pending=list(removed)
    while pending:
        for child in original[pending.pop()].get('children',[]):
            identity=_source_id(original[child])
            if identity and identity not in rejected:
                raise ValueError('Barrier contains a separate source child; refusing ambiguous removal')
            if child not in removed:removed.add(child);pending.append(child)
    keep=[i for i in range(len(original)) if i not in removed]
    remap={old:new for new,old in enumerate(keep)}
    document['nodes']=[original[i] for i in keep]
    for node in document['nodes']:
        if 'children' in node:node['children']=[remap[i] for i in node['children'] if i in remap]
    for scene in document.get('scenes',[]):
        scene['nodes']=[remap[i] for i in scene.get('nodes',[]) if i in remap]
    encoded=json.dumps(document,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    encoded+=b' '*((-len(encoded))%4)
    output_chunks=[(JSON_CHUNK,encoded),*chunks[1:]]
    body=b''.join(struct.pack('<II',len(data),kind)+data for kind,data in output_chunks)
    result=struct.pack('<III',0x46546c67,2,12+len(body))+body
    return result,(document,next((data for kind,data in chunks if kind==BIN_CHUNK),b'')),len(removed)


def _level_file(root,entry):
    relative=entry.get('glb')
    if not relative:raise ValueError('Split manifest has no GLB path')
    p=Path(relative)
    candidates=[io_path(p)] if p.is_absolute() else [io_path(root/'split'/p),io_path(root/p)]
    matches={p.resolve() for p in candidates if p.is_file()}
    if len(matches)!=1:raise ValueError('Missing or ambiguous split GLB: '+relative)
    return next(iter(matches))


def _bounds(entry,document,binary):
    import numpy as np
    from scripts.official.map_affine import gltf_bounds
    lower,upper=gltf_bounds(document,binary)
    if not np.all(np.isfinite([lower,upper])):raise ValueError('Retained GLB has no finite geometry bounds')
    native_lower=np.array([lower[0],-upper[1],lower[2]])*100
    native_upper=np.array([upper[0],-lower[1],upper[2]])*100
    entry.update(ueBoundsMin=native_lower.tolist(),ueBoundsMax=native_upper.tolist(),
        ueSizeM=((native_upper-native_lower)/100).tolist(),
        ueCentreM=((native_upper+native_lower)/200).tolist(),
        blenderBoundsMinM=lower.tolist(),blenderBoundsMaxM=upper.tolist())


def _atomic(path,data):
    temporary=path.with_name(path.name+'.barrier-filter.tmp')
    temporary.write_bytes(data);temporary.replace(path)


def filter_export(root):
    """Filter one complete native export or a merged export, before Blender.

    Returns a report; repeated calls do not rewrite already-filtered geometry.
    A malformed matching source ID/GLB fails the export instead of silently
    claiming the barriers were removed. No source-render assets are changed.
    """
    root=io_path(root);scene_path=root/'scene.json'
    scene_bytes=scene_path.read_bytes();scene=json.loads(scene_bytes.decode('utf-8-sig'))
    digest=hashlib.sha256(scene_bytes).hexdigest();report_path=root/'filter_report.json'
    if report_path.is_file():
        previous=json.loads(report_path.read_text(encoding='utf-8-sig'))
        if previous.get('rule')==RULE and previous.get('scene_after_sha256')==digest:
            return previous
    instances=scene.get('instances',[])
    matches=[row for row in instances if is_start_barrier(row)]
    rejected=set()
    for row in matches:
        data=row.get('dfmap') or {}
        if isinstance(data,str):data=json.loads(data)
        identity=data.get('sourceId')
        if not identity:raise ValueError('Confirmed start barrier lacks stable source ID')
        rejected.add(identity)
    report=dict(complete=False,rule=RULE,source_class='BP_BlockWall_BombDefusal_C',
        reason='User-requested omission of BombDefusal start barriers from static map exports',
        removed_instances=len(matches),removed_source_ids=sorted(rejected),
        instances_before=len(instances),instances_after=len(instances)-len(matches),
        scene_before_sha256=digest,files=[],binary_payloads_preserved=True)
    if not matches:
        report.update(complete=True,scene_after_sha256=digest)
        _atomic(report_path,_json_bytes(report));return report
    if len(rejected)!=len(matches):raise ValueError('Barrier source IDs are not unique')
    manifest_path=root/'split/manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    by_level=Counter(row['dfmap']['sourceLevel'] for row in matches)
    retained=[row for row in instances if row not in matches]
    remaining_by_level=Counter(row.get('dfmap',{}).get('sourceLevel') for row in retained)
    pending={};processed={};levels=[];found=set()
    for original in manifest.get('levels',[]):
        entry=dict(original);level=entry.get('sourceLevel') or entry.get('level')
        if not by_level.get(level):levels.append(entry);continue
        path=_level_file(root,entry)
        raw=path.read_bytes()
        filtered,geometry,node_count=remove_glb_nodes(raw,rejected)
        if geometry is None:raise ValueError('Matching scene barriers absent from their GLB: '+level)
        document,binary=geometry
        old_ids={_source_id(n) for n in json.loads(_glb_parts(raw)[0][1]).get('nodes',[])}
        found.update(rejected&old_ids)
        pending[path]=filtered;processed[path]=True
        entry['instances']=remaining_by_level.get(level,0)
        entry['startBarriersRemoved']=by_level[level]
        report['files'].append({'file':str(path),'removed_nodes':node_count,
            'before_sha256':hashlib.sha256(raw).hexdigest(),'after_sha256':hashlib.sha256(filtered).hexdigest()})
        if entry['instances']:
            _bounds(entry,document,binary);levels.append(entry)
    if found!=rejected:raise ValueError('Not all matching barrier IDs were removed from split GLBs: '+repr(sorted(rejected-found)))
    scene_glb=root/'scene.glb'
    if scene_glb.is_file() and scene_glb.resolve() not in processed:
        original=scene_glb.read_bytes();filtered,_,count=remove_glb_nodes(original,rejected)
        pending[scene_glb]=filtered
        report['files'].append({'file':str(scene_glb),'removed_nodes':count,
            'before_sha256':hashlib.sha256(original).hexdigest(),'after_sha256':hashlib.sha256(filtered).hexdigest()})
    scene['instances']=retained
    for key in ('instanceCount','instancesCount'):
        if key in scene:scene[key]=len(retained)
    scene['exportFilters']={'rule':RULE,'removedInstances':len(matches),'report':'filter_report.json'}
    manifest['levels']=levels
    manifest['exportFilters']={'rule':RULE,'removedInstances':len(matches)}
    pending[scene_path]=_json_bytes(scene);pending[manifest_path]=_json_bytes(manifest)
    merge_path=root/'merge_report.json'
    if merge_path.is_file():
        merge=json.loads(merge_path.read_text(encoding='utf-8-sig'))
        for level in merge.get('Levels',[]):
            key=level.get('Level')
            if key in by_level:
                level['Instances']=remaining_by_level.get(key,0)
                level['StartBarriersRemoved']=by_level[key]
        if 'Instances' in merge:merge['Instances']=len(retained)
        merge['ExportFilters']={'Rule':RULE,'RemovedInstances':len(matches),'Report':'filter_report.json'}
        pending[merge_path]=_json_bytes(merge)
    report.update(complete=True,scene_after_sha256=hashlib.sha256(pending[scene_path]).hexdigest())
    # All reads, source-ID coverage and bounds checks have succeeded before
    # replacing any file. Atomic per-file replacements retain binary payloads.
    for path,data in pending.items():_atomic(path,data)
    _atomic(report_path,_json_bytes(report))
    return report


def merge_filter_reports(roots,destination):
    """Keep chunk omissions visible in the merged export's audit report."""
    roots=[io_path(root) for root in roots];destination=io_path(destination)
    reports=[json.loads((root/'filter_report.json').read_text(encoding='utf-8-sig'))
             for root in roots if (root/'filter_report.json').is_file()]
    if any(not report.get('complete') or report.get('rule')!=RULE for report in reports):
        raise ValueError('Incomplete barrier filter in source chunks')
    scene=(destination/'scene.json').read_bytes();data=json.loads(scene.decode('utf-8-sig'))
    removed_ids=sorted({identity for report in reports for identity in report['removed_source_ids']})
    removed=sum(report['removed_instances'] for report in reports)
    if removed!=len(removed_ids):raise ValueError('Barrier identity duplicated across source chunks')
    report={'complete':True,'rule':RULE,'source_class':'BP_BlockWall_BombDefusal_C',
        'removed_instances':removed,'removed_source_ids':removed_ids,
        'instances_before':len(data['instances'])+removed,'instances_after':len(data['instances']),
        'scene_after_sha256':hashlib.sha256(scene).hexdigest(),'binary_payloads_preserved':True,
        'chunk_reports':[str(root/'filter_report.json') for root in roots if (root/'filter_report.json').is_file()],
        'files':[row for report in reports for row in report.get('files',[])]}
    _atomic(destination/'filter_report.json',_json_bytes(report))
    return report
