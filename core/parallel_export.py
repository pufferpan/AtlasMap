"""Isolated Blender/UE processes; only the coordinator publishes shared output."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil

from core.ue_pipeline import Step, validate_result
from scripts.official.map_io import io_path, metadata_path


def read(path):
    return json.loads(io_path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def owns(asset_id, index, count):
    return int(hashlib.sha256(asset_id.encode()).hexdigest()[:8], 16) % count == index


def checked_file(root, relative):
    root = io_path(root).resolve()
    path = io_path(root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'文件路径越界：{relative}')
    if not path.is_file():
        raise ValueError(f'缺少文件：{relative}')
    return path


def copy_file(source, target, pipeline):
    if pipeline._cancelled:
        raise RuntimeError('已终止导出')
    source, target = io_path(source), io_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.partial')
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


def merge_blender(roots, destination, run_id, pipeline):
    """Require all shards, complete ownership, identical scene and intact textures."""
    manifests = [read(Path(root) / 'manifest.json') for root in roots]
    reference = manifests[0]
    if 'chunk' in reference:
        return merge_map_chunks(roots, manifests, destination, run_id, pipeline)
    expected_materials = reference['parallel']['all_material_ids']
    expected_meshes = [m['id'] for m in reference['meshes']]
    materials, images, owners = {}, {}, {}
    count = len(roots)
    for index, (root, data) in enumerate(zip(roots, manifests)):
        report = read(Path(root) / 'parallel_result.json')
        metadata = data['parallel']
        if (not report.get('complete') or report.get('run_id') != run_id
                or metadata['run_id'] != run_id or metadata['index'] != index
                or metadata['count'] != count
                or metadata['all_material_ids'] != expected_materials
                or data['source_blend'] != reference['source_blend']
                or data['objects'] != reference['objects'] or data['meshes'] != reference['meshes']):
            raise ValueError(f'Blender 分片 {index + 1} 不完整或场景不一致')
        want_materials = {a for a in expected_materials if owns(a, index, count)}
        want_meshes = {a for a in expected_meshes if owns(a, index, count)}
        if (set(report['materials']) != want_materials or set(report['meshes']) != want_meshes
                or len(data['materials']) != len(want_materials)
                or {m['id'] for m in data['materials']} != want_materials):
            raise ValueError('Blender 分片缺少资源或重复分配')
        materials.update({m['id']: m for m in data['materials']})
        for mesh in data['meshes']:
            if mesh['id'] in want_meshes:
                source = checked_file(root, mesh['fbx'])
                if source.stat().st_size < 160:
                    raise ValueError('FBX 输出不完整：' + str(source))
                with source.open('rb') as stream:
                    stream.seek(-16, 2)
                    if stream.read() != bytes.fromhex('f85a8c6adef5d97eece90ce3758f290b'):
                        raise ValueError('FBX 文件尾校验失败：' + str(source))
                owners[mesh['id']] = (root, mesh)
        for item in data['images']:
            source = checked_file(root, item['file'])
            if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('贴图校验失败：' + str(source))
            if item['id'] in images:
                previous = images[item['id']][1]
                if any(item[k] != previous[k] for k in ('sha256', 'srgb', 'size', 'file')):
                    raise ValueError('贴图 ID 冲突：' + item['id'])
            else:
                images[item['id']] = (root, item)
    if len(materials) != len(expected_materials) or len(owners) != len(expected_meshes):
        raise ValueError('并行结果未覆盖完整场景')
    for material in materials.values():
        for node in material['nodes']:
            if node.get('image') and node['image'] not in images:
                raise ValueError('材质引用了缺失贴图')
    destination = Path(destination)
    for folder in ('meshes', 'textures', 'material_graphs', 'validation'):
        (destination / folder).mkdir(parents=True, exist_ok=True)
    for root, mesh in owners.values():
        source = checked_file(root, mesh['fbx'])
        copy_file(source, destination / mesh['fbx'], pipeline)
        revision = source.with_suffix('.revision')
        if revision.exists():
            copy_file(revision, (destination / mesh['fbx']).with_suffix('.revision'), pipeline)
        validation = Path(root) / 'validation' / (mesh.get('source_mesh', mesh['id']) + '.json')
        if validation.exists():
            copy_file(validation, destination / 'validation' / validation.name, pipeline)
    for root, item in images.values():
        copy_file(checked_file(root, item['file']), destination / item['file'], pipeline)
    merged = dict(reference)
    merged.pop('parallel')
    merged['materials'] = [materials[key] for key in expected_materials]
    merged['images'] = [images[key][1] for key in sorted(images)]
    merged['counts'] = dict(reference['counts'], materials=len(materials), images=len(images))
    write(destination / 'manifest.json', merged)
    pipeline._emit(f'Blender 并行合并：{len(owners)} 模型 / {len(materials)} 材质 / {len(images)} 贴图')


def merge_map_chunks(roots, manifests, destination, run_id, pipeline):
    catalog=manifests[0]['catalog']
    expected_objects={o['id']:o for o in catalog['objects']}
    expected_meshes={m['id']:m for m in catalog['meshes']}
    objects,meshes,materials,images={},{},{},{}
    levels=set()
    for index,(root,data) in enumerate(zip(roots,manifests)):
        chunk=data['chunk'];receipt=read(Path(root)/'parallel_result.json')
        if (not receipt.get('complete') or receipt.get('run_id')!=run_id
                or chunk['run_id']!=run_id or chunk['index']!=index
                or chunk['count']!=len(roots) or data['catalog']!=catalog):
            raise ValueError('地图分块不完整或来源不一致')
        ids={o['id'] for o in data['objects']}
        if ids!=set(chunk['object_ids']) or ids&objects.keys() or levels.intersection(chunk['source_levels']):
            raise ValueError('地图分块对象或源关卡重复')
        for obj in data['objects']:
            if obj!=expected_objects.get(obj['id']) or (obj.get('parent') and obj['parent'] not in ids):
                raise ValueError('分块坐标或父子关系不完整')
        if set(receipt['meshes'])!={m['id'] for m in data['meshes']}:
            raise ValueError('地图块模型没有全部导出')
        if set(receipt['materials'])!={m['id'] for m in data['materials']}:
            raise ValueError('地图块材质没有全部导出')
        objects.update({o['id']:o for o in data['objects']});levels.update(chunk['source_levels'])
        for mesh in data['meshes']:
            if mesh!=expected_meshes.get(mesh['id']):raise ValueError('共享模型定义不一致')
            source=checked_file(root,mesh['fbx'])
            with source.open('rb') as stream:
                if source.stat().st_size<160:raise ValueError('分块 FBX 不完整')
                stream.seek(-16,2)
                if stream.read()!=bytes.fromhex('f85a8c6adef5d97eece90ce3758f290b'):raise ValueError('分块 FBX 校验失败')
            meshes.setdefault(mesh['id'],(root,mesh))
        for material in data['materials']:
            if material['id'] in materials and material!=materials[material['id']]:raise ValueError('共享材质定义冲突')
            materials[material['id']]=material
        for image in data['images']:
            source=checked_file(root,image['file'])
            if hashlib.sha256(source.read_bytes()).hexdigest()!=image['sha256']:raise ValueError('分块贴图损坏')
            if image['id'] in images and any(image[k]!=images[image['id']][1][k] for k in ('sha256','srgb','file')):
                raise ValueError('共享贴图冲突')
            images.setdefault(image['id'],(root,image))
    if set(objects)!=set(expected_objects) or set(meshes)!=set(expected_meshes) or set(materials)!=set(catalog['material_ids']):
        raise ValueError('地图分块未覆盖完整地图')
    destination=Path(destination)
    for folder in ('meshes','textures','material_graphs','validation','chunks'):
        (destination/folder).mkdir(parents=True,exist_ok=True)
    for root,mesh in meshes.values():
        source=checked_file(root,mesh['fbx']);copy_file(source,destination/mesh['fbx'],pipeline)
        if source.with_suffix('.revision').exists():
            copy_file(source.with_suffix('.revision'),(destination/mesh['fbx']).with_suffix('.revision'),pipeline)
    for root,item in images.values():copy_file(checked_file(root,item['file']),destination/item['file'],pipeline)
    index_rows=[]
    for index,(root,data) in enumerate(zip(roots,manifests)):
        relative=f'chunks/Chunk_{index+1:03d}'
        local=dict(data);local.pop('catalog')
        write(destination/relative/'manifest.json',local)
        copy_file(checked_file(root,'chunk.blend'),destination/relative/'scene.blend',pipeline)
        index_rows.append(dict(data['chunk'],name=f'Chunk_{index+1:03d}',manifest=relative+'/manifest.json',
                               blend=relative+'/scene.blend',counts=local['counts']))
    merged=dict(manifests[0]);merged.pop('chunk');merged.pop('catalog')
    merged['objects']=catalog['objects'];merged['meshes']=catalog['meshes']
    merged['materials']=[materials[key] for key in catalog['material_ids']]
    merged['images']=[images[key][1] for key in sorted(images)]
    merged['counts']=dict(objects=len(objects),mesh_objects=sum(o['type']=='MESH' for o in objects.values()),
        mesh_assets=len(meshes),materials=len(materials),images=len(images),
        hidden_render_meshes=sum(o['type']=='MESH' and o['hidden_render'] for o in objects.values()))
    write(destination/'chunks/index.json',dict(complete=True,run_id=run_id,chunks=index_rows))
    write(destination/'manifest.json',merged)
    pipeline._emit(f'地图分块合并：{len(index_rows)} 场景块 / {len(objects)} 对象 / {len(levels)} 源地图块')


def parallel_steps(p, serial, run_id):
    count = max(2, min(8, int(p.get('parallel_processes', 2))))
    transfer = Path(p['transfer'])
    run = transfer / 'parallel' / run_id
    blender_roots = [run / 'blender' / f'worker_{i}' for i in range(count)]
    ue_jobs = []

    def blender_factory():
        jobs = []
        for index, root in enumerate(blender_roots):
            root.mkdir(parents=True, exist_ok=True)
            env = dict(serial[3].env, ATLASMAP_UE_ROOT=str(root), ATLASMAP_BLENDER_SHARD_INDEX=str(index),
                       ATLASMAP_BLENDER_SHARD_COUNT=str(count), ATLASMAP_PARALLEL_RUN_ID=run_id,ATLASMAP_MAP_CHUNKS='1')
            cmd = serial[3].cmd.copy()
            cmd[1:1] = ['-t', str(max(1, (os.cpu_count() or 4) // count))]
            def validate(started, root=root):
                report = read(root / 'parallel_result.json')
                if (not report.get('complete') or report.get('run_id') != run_id
                        or (root / 'parallel_result.json').stat().st_mtime < started - 2):
                    raise ValueError('Blender 并行任务没有生成本次完成报告')
            jobs.append(Step(f'Blender {index + 1}/{count}', cmd, env=env,
                             validate=validate, log_path=str(root / 'process.log')))
        return jobs

    def ue_factory():
        from scripts.official.map_chunks import material_subset
        manifest = read(transfer / 'manifest.json')
        chunks=read(transfer/'chunks/index.json')['chunks']
        plan=read(transfer/'material_plan.json');instances=read(transfer/'material_instance_plan.json')
        all_images={row['id']:row for row in manifest['images']}
        project = Path(p['project'])
        dest = p['dest'].rstrip('/')
        if not dest.startswith('/Game/') or '..' in dest.split('/'):
            raise ValueError('UE 目标必须位于 /Game 下')
        jobs = []
        for index in range(count):
            root = run / 'ue' / f'worker_{index}'
            isolated = root / 'project'
            isolated.mkdir(parents=True, exist_ok=True)
            (isolated / 'Content').mkdir(exist_ok=True)
            isolated_project = isolated / project.name
            shutil.copy2(project, isolated_project)
            if (project.parent / 'Config').exists():
                shutil.copytree(project.parent / 'Config', isolated / 'Config', dirs_exist_ok=True)
            data=read(transfer/chunks[index]['manifest'])
            local_plan,local_instances,image_ids=material_subset(plan,instances,data['objects'],data['meshes'])
            image_ids.update(row['id'] for row in data['images'])
            data['images']=[all_images[key] for key in sorted(image_ids)]
            for kind, key in (('images', 'file'), ('meshes', 'fbx')):
                data[kind]=[dict(item,**{key:metadata_path(checked_file(transfer,item[key]))}) for item in data[kind]]
            data['counts']=dict(data['counts'],images=len(data['images']))
            write(root / 'manifest.json', data)
            write(root/'material_plan.json',local_plan);write(root/'material_instance_plan.json',local_instances)
            level=dest+f'/Chunks/LV_Chunk_{index+1:03d}'
            env = dict(serial[-1].env, ATLASMAP_UE_ROOT=str(root), ATLASMAP_UE_FINISH='0',
                       ATLASMAP_UE_SHARD=str(index + 1),
                       ATLASMAP_UE_SKIP='',ATLASMAP_UE_LEVEL=level,
                       ATLASMAP_UE_WORKERS=str(max(1, min(4, int(p.get('workers', 8)) // count))),
                       ATLASMAP_UE_RUN_ID=run_id + f'_{index}')
            cmd = serial[-1].cmd.copy()
            cmd[1] = str(isolated_project)
            def validate(started, root=root, index=index,level=level):
                validate_result(str(root / 'ue_import_result.json'), level, started, run_id + f'_{index}')
                result = read(root / 'ue_import_result.json')
                if result.get('stages') != ['textures','meshes','masters','instances','bindings','actors','parents']:
                    raise ValueError('UE 并行阶段不匹配')
            jobs.append(Step(f'UE {index + 1}/{count}', cmd, env=env, validate=validate,
                             log_path=str(root / 'process.log')))
            ue_jobs.append((root, isolated, data))
        return jobs

    def merge_ue(pipeline):
        relative = Path(*p['dest'].strip('/').split('/')[1:])
        pending, packages = [], set()
        for index, (root, project, data) in enumerate(ue_jobs):
            report = read(root / 'ue_import_result.json')
            if not report.get('complete') or report.get('run_id') != run_id + f'_{index}':
                raise ValueError('UE 分片结果不完整')
            content=project/'Content'/relative
            chunk_map=content/'Chunks'/f'LV_Chunk_{index+1:03d}.umap'
            if not chunk_map.is_file():raise ValueError('UE 分块关卡未保存')
            expected=[content/'Textures'/row['id'] for row in data['images']]
            expected +=[content/'Meshes'/row['id'] for row in data['meshes']]
            expected +=[content/'Materials'/row['id'] for row in read(root/'material_instance_plan.json')['instances']]
            for asset in expected:
                if not asset.with_suffix('.uasset').is_file():raise ValueError('UE 分块缺少资源：'+str(asset))
            for source in sorted(content.rglob('*')):
                if not source.is_file() or source.suffix not in ('.uasset','.umap','.uexp','.ubulk','.uptnl'):continue
                key=source.relative_to(content)
                # Shared dependency packages have identical global definitions; one coordinator publishes them.
                if key in packages:continue
                packages.add(key)
                pending.append((source,Path(p['project']).parent/'Content'/relative/key))
        for source, target in pending:
            copy_file(source, target, pipeline)
        write(run / 'asset_merge_result.json', {'complete': True, 'run_id': run_id,
                                               'packages': len(packages), 'processes': count})
        pipeline._emit(f'UE 并行合并：{len(packages)} 个资源包；开始组装最终关卡与灯光')

    final = replace(serial[-1], env=dict(serial[-1].env, ATLASMAP_UE_SKIP='textures,meshes,masters,instances,bindings',
                                       ATLASMAP_UE_PARALLEL_MERGED='1'))
    def cleanup(pipeline):
        # Remove only this successful run's private intermediates. Keep receipts/logs.
        targets = [root / folder for root in blender_roots
                   for folder in ('meshes', 'textures', 'validation', 'material_graphs')]
        targets += [project for _, project, _ in ue_jobs]
        for target in targets:
            resolved = target.resolve()
            if not resolved.is_relative_to(run.resolve()) or resolved == run.resolve():
                raise ValueError('临时目录超出本次导出范围')
            if pipeline._cancelled:
                return
            if resolved.exists():
                try:
                    shutil.rmtree(resolved)
                except OSError as exc:
                    pipeline._emit(f'[临时文件保留] {exc}')
        pipeline._emit('并行导出临时资源已清理，任务报告和日志已保留')
    result = serial[:3] + [Step('Blender 并行导出', [], parallel_factory=blender_factory),
        Step('校验并合并 Blender 分片', [], action=lambda pipe: merge_blender(blender_roots, transfer, run_id, pipe)),
        serial[4], serial[5], Step('UE 并行导入', [], parallel_factory=ue_factory),
        Step('合并 UE 资源', [], action=merge_ue), final, Step('清理本次并行临时资源', [], action=cleanup)]
    return [replace(step, name=f'{i + 1}/{len(result)} ' + step.name.split(' ', 1)[-1]
                    if step.name[:1].isdigit() else f'{i + 1}/{len(result)} {step.name}')
            for i, step in enumerate(result)]
