"""Run every expensive export phase on isolated, source-level chunks.

Only the small catalogue barriers and the persistent streaming level have a
single writer. Native exporters, Blender and Unreal never share writable files.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from core.parallel_export import checked_file, copy_file, read, write
from core.ue_pipeline import Step, map_roots, validate_result
from scripts.official.map_io import io_path, metadata_path, share_file
from core.system_usage import ue_process_capacity,ue_import_capacity,ue_import_memory
from core.export_storage import disk_free, prefer_project_storage, source_budget, check_space


def plan_levels(text, roots, excluded, count, costs=None):
    files = {}
    for line in text.splitlines():
        match = re.match(r'^\s*([\d,]+)\s+(\S.*\.umap)\s*$', line, re.I)
        if not match:
            continue
        size, path = match.groups()
        path = path.replace('\\', '/')
        if (any(path.lower().startswith(root.lower()) for root in roots)
                and not any(word.lower() in path.lower() for word in excluded)):
            files[path] = costs[path] if costs is not None else int(size.replace(',', ''))
    if not files:
        raise ValueError('游戏包中没有找到所选地图的关卡')
    # Keep base/HD siblings together so their overlapping placements can be
    # removed before geometry conversion. Tie breaks never depend on input order.
    families = {}
    for path, size in sorted(files.items()):
        stem = re.sub(r'_HD$', '', Path(path).stem, flags=re.I).lower()
        families.setdefault(stem, []).append((path, size))
    chunks = [[] for _ in range(count)]
    weights = [0] * count
    for rows in sorted(families.values(), key=lambda r: (-sum(s for _, s in r), r[0][0])):
        index = min(range(count), key=lambda i: (weights[i], i))
        chunks[index].extend(path for path, _ in rows)
        weights[index] += sum(size for _, size in rows)
    return [sorted(chunk) for chunk in chunks]


def link_copy(source, target, pipeline=None):
    """Link immutable output from this run; fall back across volumes."""
    share_file(source,target,(lambda:pipeline._cancelled) if pipeline else None)


def _environment_content(row):
    # A shared cube may be referenced by different actors in each shard.
    # These fields describe provenance, not its pixels or rendering settings.
    # ``eligible`` is derived from the same per-shard actor label, so two shards
    # legitimately disagree when one sees the cube under a Sky actor and the
    # other under a ReflectionCapture; merge it with a logical OR instead of
    # aborting the whole export (a large map can reference one HDRI from dozens
    # of actors spread over many chunks).
    return {k:v for k,v in row.items()
            if k not in ('selection_basis','selection_bases','eligible')}


def _merge_environment_provenance(first, second):
    bases=set()
    for row in (first,second):
        bases.update(row.get('selection_bases') or [])
        if row.get('selection_basis'):bases.add(row['selection_basis'])
    if bases:
        first['selection_bases']=sorted(bases)
        first['selection_basis']=first['selection_bases'][0]


def merge_source_states(roots, destination, map_root, pipeline=None):
    output = io_path(destination) / 'source-render'
    packages, assets, levels = {}, {}, {}
    exporter = None
    for root in roots:
        if pipeline and pipeline._cancelled:raise InterruptedError('已终止源状态汇总')
        folder = io_path(root) / 'source-render'
        data = read(folder / 'state-index.json')
        if not data.get('complete'):
            raise ValueError('源渲染分块未完成')
        if exporter is not None and data['exporter'] != exporter:
            raise ValueError('源渲染分块使用了不同版本的导出器')
        exporter = data['exporter']
        for row in data['levels']:
            if row['level'] in levels:
                raise ValueError('源关卡被重复分配')
            levels[row['level']] = row
        for key, file in data['packages'].items():
            if pipeline and pipeline._cancelled:raise InterruptedError('已终止源状态汇总')
            source = checked_file(folder, file)
            if key in packages:
                if source.read_bytes() != checked_file(output, packages[key]).read_bytes():
                    raise ValueError('同一源包出现不一致的数据：' + key)
                continue
            packages[key] = file
            link_copy(source, output / file,pipeline)
        for row in data['preservedAssets']:
            if pipeline and pipeline._cancelled:raise InterruptedError('已终止烘焙载荷汇总')
            key = row['path']
            source = checked_file(folder, 'assets/' + key)
            if hashlib.sha256(source.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('烘焙载荷校验失败：' + key)
            if key in assets:
                if assets[key] != row:
                    raise ValueError('烘焙载荷不一致：' + key)
                continue
            assets[key] = row
            link_copy(source, output / 'assets' / key,pipeline)
    write(output / 'state-index.json', dict(complete=True, schema=1, mapRoot=map_root,
        exporter=exporter, levels=[levels[k] for k in sorted(levels)], packages=packages,
        preservedAssets=[assets[k] for k in sorted(assets)]))
    for filename,field in (('environment.json','skies'),('reflection-cubemaps.json','captures')):
        combined={};failures=[]
        for root in roots:
            folder=io_path(root)/'source-render';index=folder/filename
            if not index.is_file():continue
            document=read(index);failures.extend(document.get('failures',[]))
            for row in document.get(field,[]):
                if pipeline and pipeline._cancelled:raise InterruptedError('已终止环境资源汇总')
                key=(row['guid'],row.get('source','')) if row.get('guid') else (row.get('source_material',''),row.get('source_texture'))
                if key in combined and _environment_content(row)!=_environment_content(combined[key]):
                    raise ValueError('同一环境资源在分块间不一致：'+str(key))
                relative=row['texture'] if isinstance(row.get('texture'),str) else row['texture']['RelativePath']
                source=checked_file(folder,relative);target=io_path(output/relative)
                # checked_file validates both traversal and source existence.
                # Verify every duplicate's actual bytes too, before merging
                # provenance; matching JSON alone cannot prove integrity.
                if target.exists() and target.read_bytes()!=source.read_bytes():raise ValueError('环境贴图冲突：'+relative)
                if not target.exists():link_copy(source,target,pipeline)
                if key in combined:
                    # One shard may have seen this resource from a Sky actor and
                    # another from a reflection capture; either reference is
                    # enough to keep it eligible, the texture bytes are shared.
                    if row.get('eligible'):combined[key]['eligible']=True
                    _merge_environment_provenance(combined[key],row)
                else:
                    combined[key]=dict(row)
                    _merge_environment_provenance(combined[key],{})
        if combined or failures:write(output/filename,dict(schema=1,mapRoot=map_root,**{field:list(combined.values())},failures=failures))
    from core.scene_state import enrich
    return enrich(destination)


def full_parallel_steps(p, serial, run_id):
    count = max(2, min(8, int(p.get('parallel_processes', 2))))
    root, transfer = Path(p['root']), Path(p['transfer'])
    run = transfer / 'parallel' / run_id
    raw = [root / 'chunks' / run_id / f'Chunk_{i+1:03d}' for i in range(count)]
    outputs = [run / 'blender' / f'worker_{i}' for i in range(count)]
    imports = [run / 'ue' / f'worker_{i}' for i in range(count)]
    scripts = Path(p['scripts'])
    full_root = ' + '.join(map_roots(p['map']))
    inventory_log = run / 'inventory.log'
    ownership = []
    if (run/'source_plan.json').is_file():
        saved=read(run/'source_plan.json')
        if saved.get('run_id')==run_id and len(saved.get('chunks',[]))==count:
            ownership.extend(saved['chunks'])
    census=[run/'scan'/f'worker_{i}' for i in range(count)]
    project = Path(p['project'])
    native_root=project.parent/'.atlasmap-parallel'/run_id
    projects=[native_root/f'worker_{i}' for i in range(count)]
    # Compare available capacity before creating large intermediates, including
    # when the default Documents folder still has more than 4 GB free.
    spill=prefer_project_storage(root,project.parent)
    if spill:
        raw=[native_root/'source'/f'Chunk_{i+1:03d}' for i in range(count)]
        outputs=[native_root/'blender'/f'worker_{i}' for i in range(count)]
    # A saved run must keep using its original workspace even if the user
    # frees disk space between attempts.
    if (run/'workspace.json').is_file():
        workspace=read(run/'workspace.json')
        if workspace.get('run_id')!=run_id:raise ValueError('工作目录不属于本次任务')
        raw=[Path(path) for path in workspace['raw']]
        outputs=[Path(path) for path in workspace['outputs']]
    elif (transfer/'chunks/index.json').is_file():
        previous=read(transfer/'chunks/index.json')
        if previous.get('run_id')==run_id and len(previous.get('chunks',[]))==count:
            raw=[Path(chunk['blend']).parent for chunk in previous['chunks']]
            outputs=[Path(chunk['manifest']).parent for chunk in previous['chunks']]
    dest = p['dest'].rstrip('/')
    if not dest.startswith('/Game/') or '..' in dest.split('/'):
        raise ValueError('UE 目标必须位于 /Game 下')
    relative = Path(*dest.strip('/').split('/')[1:])
    threads = str(max(1, (os.cpu_count() or 4) // count))

    def task(pipe, **data):
        pipe._emit('@ATLASMAP_TASK ' + json.dumps(data, ensure_ascii=False))

    def preflight(pipe):
        if p.get('target')!='blender' and p.get('render_profile','game')=='game':
            from core.ue_render_config import ensure_game_renderer
            ensure_game_renderer(project)
        for path,minimum in ((root,128*1024**2),(raw[0].parent,4*1024**3),(project.parent,1024**3)):
            free=disk_free(path)
            if free<minimum:raise ValueError(f'磁盘空间不足：{path}，剩余 {free/1024**3:.2f} GB')
        pipe._emit(f'临时 UE 工程：{native_root}；该盘剩余 {disk_free(project.parent)/1024**3:.1f} GB')
        if spill:pipe._emit(f'工程盘可用空间更多，分块场景与资源缓存写入：{native_root}；所选导出目录保留索引')
        write(run/'workspace.json',dict(run_id=run_id,raw=[str(path) for path in raw],outputs=[str(path) for path in outputs]))

    def indexed(started):
        excluded = serial[0].cmd[serial[0].cmd.index('--exclude') + 1].split(',')
        ownership[:]=plan_levels(inventory_log.read_text(encoding='utf-8'),
            map_roots(p['map']), excluded, count)
        write(run / 'source_plan.json', dict(run_id=run_id, chunks=ownership))

    def scan_jobs():
        jobs=[]
        for i,folder in enumerate(census):
            write(folder/'levels.json',ownership[i])
            cmd=[serial[1].cmd[0],'--scan-chunk',str(Path(p['exe']).parent),p['config'],str(folder/'levels.json'),str(folder)]
            def validate(started,i=i,folder=folder):
                result=read(folder/'scan.json')
                if (not result.get('complete') or {r['level'] for r in result['levels']}!=set(ownership[i])
                        or (folder/'scan.json').stat().st_mtime<started-2):
                    raise ValueError('分块负载分析没有完整覆盖源关卡')
            jobs.append(Step(f'分块负载分析 {i+1}/{count}',cmd,validate=validate,
                work={'levels':len(ownership[i])},log_path=str(folder/'process.log')))
        return jobs

    def rebalance(pipe):
        rows={row['level']:row for folder in census for row in read(folder/'scan.json')['levels']}
        estimate=source_budget(list(rows.values()))
        check_space({str(raw[0].parent):estimate,str(root):max(256*1024**2,sum(row['instances'] for row in rows.values())*24*1024)})
        pipe._emit(f'按本图实际负载规划工作空间：约 {estimate/1024**3:.1f} GB；工作盘剩余 {disk_free(raw[0].parent)/1024**3:.1f} GB')
        costs={key:1+row['instances']+row['meshes']*6+row['actors']*.05 for key,row in rows.items()}
        excluded=serial[0].cmd[serial[0].cmd.index('--exclude')+1].split(',')
        ownership[:]=plan_levels(inventory_log.read_text(encoding='utf-8'),map_roots(p['map']),excluded,count,costs)
        write(run/'source_plan.json',dict(run_id=run_id,chunks=ownership,costs=costs))
        for i,levels in enumerate(ownership):
            task_data={'worker':i,'stage':'分块负载分配','event':'assigned',
                'work':{'levels':len(levels),'objects':sum(rows[l]['instances'] for l in levels)},
                'text':f'分块 {i+1}：{len(levels)} 关卡 / {sum(rows[l]["instances"] for l in levels)} 实例，按实际模型负载分配'}
            pipe._emit('@ATLASMAP_PARALLEL '+json.dumps(task_data,ensure_ascii=False))

    def export_jobs():
        jobs = []
        for i, folder in enumerate(raw):
            folder.mkdir(parents=True, exist_ok=True)
            if not ownership[i]:
                def empty(pipe, i=i, folder=folder):
                    write(folder / 'scene.json', dict(mapRoot=full_root, instances=[]))
                    write(folder / 'split/manifest.json', dict(levels=[]))
                    write(folder / 'lights.json', dict(lights=[]))
                    write(folder / 'merge_report.json', dict(MapRoot='__map_empty_chunk__/', Levels=[]))
                    task(pipe, event='assigned', work={'levels': 0}, text='本分块没有源关卡，保留空块')
                jobs.append(Step(f'源提取 {i+1}/{count}', [], action=empty))
                continue
            check_space({str(folder):512*1024**2})
            cmd = serial[0].cmd.copy()
            cmd[cmd.index('merge') + 2] = str(folder)
            cmd[cmd.index('--root') + 1] = ','.join(ownership[i])
            argument_file=folder/'export_arguments.json'
            write(argument_file,cmd[cmd.index('merge')+1:])
            cmd=[serial[1].cmd[0],'--export-chunk',str(Path(p['exe']).parent),p['config'],
                 str(argument_file),str(folder)]
            def validate(started, i=i, folder=folder):
                report = read(folder / 'merge_report.json')
                actual = {row['Level'] for row in report['Levels'] if row['Include']}
                if actual != set(ownership[i]) or (folder/'scene.json').stat().st_mtime < started-2:
                    raise ValueError('本次提取关卡与分块计划不一致')
                from core.export_filter import filter_export
                filter_export(folder)
                report=read(folder/'merge_report.json')
                # Worker 1 also owns preservation of unreferenced map bake files.
                if i == 0:
                    report['MapRoot'] = full_root
                    write(folder / 'merge_report.json', report)
            jobs.append(Step(f'源提取 {i+1}/{count}', cmd, validate=validate,
                storage_limits={str(folder):512*1024**2},log_path=str(folder/'extract.log'),work={'levels':len(ownership[i])}))
        return jobs

    def merge_geometry(pipe):
        scenes = [read(folder/'scene.json') for folder in raw]
        merged = dict(scenes[0], mapRoot=full_root)
        merged['instances'] = [row for scene in scenes for row in scene['instances']]
        if not merged['instances']:
            raise ValueError('所有源分块均没有可导出的几何体')
        write(root/'scene.json', merged)
        split = dict(read(raw[0]/'split/manifest.json'))
        split['levels'] = []
        decisions, lights = [], []
        # Filter repeated placements across chunks using stable native identity.
        seen = set()
        for folder in raw:
            if pipe._cancelled:raise InterruptedError('已终止源目录汇总')
            rejected = []
            for row in read(folder/'scene.json')['instances']:
                metadata=row.get('dfmap',{})
                key = (row['mesh'], tuple(round(v, 1 if 12 <= j < 15 else 5)
                    for j, v in enumerate(row.get('matrixUE') or [])),
                    json.dumps({k:metadata.get(k) for k in ('overrideMaterials','visibility','collision')}, sort_keys=True),
                    () if row.get('matrixUE') else json.dumps([row.get(k) for k in ('loc','rot','scale')]))
                if key in seen:
                    rejected.append(row['dfmap']['sourceId'])
                seen.add(key)
            write(folder/'drop_source_ids.json', rejected)
            for entry in read(folder/'split/manifest.json')['levels']:
                file=folder/'split'/entry['glb']
                entry = dict(entry, glb=str(file.relative_to(root) if file.is_relative_to(root) else file).replace('\\','/'))
                split['levels'].append(entry)
            decisions.extend(read(folder/'merge_report.json')['Levels'])
            lights.extend(read(folder/'lights.json')['lights'])
        split['levels'].sort(key=lambda e: e['level'])
        write(root/'split/manifest.json', split)
        write(root/'merge_report.json', dict(MapRoot=full_root, Levels=decisions,
            LevelsIncluded=len(decisions), Instances=len(merged['instances']), parallel_run_id=run_id,
            Vertices=sum(read(folder/'merge_report.json').get('Vertices',0) for folder in raw),
            Triangles=sum(read(folder/'merge_report.json').get('Triangles',0) for folder in raw)))
        from core.export_quality import record_quality
        record_quality(root,p.get('export_quality'),int(serial[0].cmd[serial[0].cmd.index('--max-tex')+1]),raw)
        write(root/'lights.json', dict(lights=lights))
        from core.export_filter import merge_filter_reports
        filtered=merge_filter_reports(raw,root)
        pipe._emit(f"爆破开局空气墙：各分块共移除 {filtered['removed_instances']} 个源实例")
        pipe._emit(f'源目录就绪：{len(decisions)} 关卡，{len(merged["instances"])} 实例；分块均已独立提取')

    def state_jobs():
        jobs=[]
        for i, folder in enumerate(raw):
            cmd=serial[1].cmd.copy();cmd[-2:]=[str(folder),str(folder/'source-render')]
            def validate(started, folder=folder):
                path=folder/'source-render/state-index.json'
                if path.stat().st_mtime < started-2 or not read(path).get('complete'):
                    raise ValueError('本次源渲染分块没有完成')
                from core.scene_state import enrich
                enrich(folder)
            jobs.append(Step(f'源光照与烘焙 {i+1}/{count}',cmd,validate=validate,
                env={'ATLASMAP_BAKE_CACHE':str(raw[0].parent/'bake-cache')},storage_limits={str(folder):512*1024**2},
                log_path=str(folder/'state.log'),work={'levels':len(ownership[i])}))
        return jobs

    def blender_jobs(stage):
        jobs=[]
        for i,(folder,out) in enumerate(zip(raw,outputs)):
            out.mkdir(parents=True,exist_ok=True)
            env=dict(ATLASMAP_UE_ROOT=str(out),ATLASMAP_CHUNK_NAMESPACE=f'C{i+1:03d}_',
                ATLASMAP_PARALLEL_RUN_ID=run_id,ATLASMAP_BLENDER_SHARD_COUNT='1',ATLASMAP_MAP_CHUNKS='0',
                ATLASMAP_MATERIAL_NAMESPACE=f'C{i+1:03d}_')
            env['ATLASMAP_IMAGE_CACHE']=str(outputs[0].parent/'image-cache')
            if stage==2:
                cmd=serial[2].cmd.copy();cmd[cmd.index('--')+1]=str(folder)
            elif stage==3:
                cmd=serial[3].cmd.copy();cmd[2]=str(folder/'scene_no_terrain.blend')
            else:
                cmd=serial[stage].cmd.copy()
            cmd[1:1]=['-t',threads]
            def validate(started,i=i,folder=folder,out=out,stage=stage):
                path=(folder/'scene_no_terrain.blend' if stage==2 else out/
                    {3:'manifest.json',4:'material_plan.json',5:'material_instance_plan.json'}[stage])
                if not path.is_file() or path.stat().st_mtime < started-2:
                    raise ValueError('Blender 没有生成本次分块结果：'+str(path))
                if stage==3:
                    data=read(path)
                    write(out/'chunk_result.json',dict(complete=True,run_id=run_id,index=i,
                        source_levels=ownership[i],counts=data['counts']))
            jobs.append(Step(f'{("场景创建","模型输出","材质编译","材质分组")[stage-2]} {i+1}/{count}',
                cmd,env=env,validate=validate,storage_limits={str(folder):512*1024**2,str(out):512*1024**2},log_path=str(out/f'phase_{stage}.log')))
        return jobs

    def catalogue(pipe):
        objects,meshes,materials,images={},{},{},{}
        rows=[]
        for i,(folder,out) in enumerate(zip(raw,outputs)):
            if pipe._cancelled:raise InterruptedError('已终止分块目录汇总')
            data=read(out/'manifest.json')
            receipt=read(out/'chunk_result.json')
            if receipt.get('run_id')!=run_id or not receipt.get('complete'):
                raise ValueError('分块模型目录不属于本次任务')
            for kind,table in (('objects',objects),('meshes',meshes),('materials',materials)):
                for item in data[kind]:
                    if pipe._cancelled:raise InterruptedError('已终止分块校验')
                    if item['id'] in table:raise ValueError('分块标识冲突：'+item['id'])
                    item=dict(item)
                    if kind=='meshes':
                        file=checked_file(out,item['fbx'])
                        if file.stat().st_size<160:raise ValueError('分块模型文件不完整：'+str(file))
                        with file.open('rb') as stream:
                            stream.seek(-16,2)
                            if stream.read()!=bytes.fromhex('f85a8c6adef5d97eece90ce3758f290b'):
                                raise ValueError('分块模型文件尾校验失败：'+str(file))
                        item['fbx']=metadata_path(file)
                    table[item['id']]=item
            for image in data['images']:
                if pipe._cancelled:raise InterruptedError('已终止贴图校验')
                file=checked_file(out,image['file'])
                if hashlib.sha256(file.read_bytes()).hexdigest()!=image['sha256']:
                    raise ValueError('分块贴图校验失败')
                if image['id'] in images and images[image['id']]['sha256']!=image['sha256']:
                    raise ValueError('分块贴图标识冲突')
                images[image['id']]=dict(image,file=metadata_path(file))
            rows.append(dict(index=i,count=count,run_id=run_id,name=f'Chunk_{i+1:03d}',
                source_levels=ownership[i],manifest=str(out/'manifest.json'),
                blend=str(folder/'scene_no_terrain.blend'),level=dest+f'/Chunks/LV_Chunk_{i+1:03d}',
                asset_destination=dest+f'/Chunks/Chunk_{i+1:03d}',counts=data['counts']))
        # No parent may escape its isolated chunk. Mesh/object slot references
        # are validated again by the native import and final saved-map audit.
        for obj in objects.values():
            if obj.get('parent') and obj['parent'] not in objects:raise ValueError('缺少父对象')
        merged=dict(read(outputs[0]/'manifest.json'),objects=list(objects.values()),
            meshes=list(meshes.values()),materials=list(materials.values()),images=list(images.values()),
            ue_root=dest,level=dest+'/LV_Map',streaming=True)
        merged['counts']=dict(objects=len(objects),mesh_objects=sum(o['type']=='MESH' for o in objects.values()),
            mesh_assets=len(meshes),materials=len(materials),images=len(images),
            hidden_render_meshes=sum(o['type']=='MESH' and o['hidden_render'] for o in objects.values()))
        write(transfer/'manifest.json',merged)
        write(transfer/'chunks/index.json',dict(complete=True,run_id=run_id,streaming=True,chunks=rows))
        pipe._emit(f'完整分块目录：{len(objects)} 对象 / {len(meshes)} 模型 / {len(images)} 贴图')

    import_costs=[]
    def ue_jobs():
        jobs=[]
        import_costs.clear()
        chunks=read(transfer/'chunks/index.json')['chunks']
        size=sum(file.stat().st_size for out in outputs for folder in ('meshes','textures')
                 for file in (out/folder).glob('*') if file.is_file())
        required=max(1024**3,size*4+count*64*1024**2)
        free=disk_free(project.parent)
        if free<required:
            raise ValueError(f'UE 工作盘空间不足：剩余 {free/1024**3:.1f} GB，本次分块建议至少 {required/1024**3:.1f} GB；源场景已保留')
        for i,(out,folder,state,chunk) in enumerate(zip(outputs,imports,raw,chunks)):
            isolated=projects[i];io_path(isolated).mkdir(parents=True,exist_ok=True)
            shutil.copy2(io_path(project),io_path(isolated/project.name))
            if io_path(project.parent/'Config').exists():
                shutil.copytree(io_path(project.parent/'Config'),io_path(isolated/'Config'),dirs_exist_ok=True)
            io_path(isolated/'Content').mkdir(exist_ok=True)
            cmd=serial[-1].cmd.copy();cmd[1]=str(isolated/project.name)
            cmd.append('-nosound')
            env=dict(serial[-1].env,ATLASMAP_UE_ROOT=str(out),ATLASMAP_SOURCE_ROOT=str(state),
                ATLASMAP_GLOBAL_SOURCE_ROOT=str(root),ATLASMAP_UE_DEST=chunk['asset_destination'],
                ATLASMAP_UE_LEVEL=chunk['level'],ATLASMAP_UE_FINISH='1',ATLASMAP_UE_SHARD=str(i+1),
                ATLASMAP_UE_PRIMARY_CHUNK='1' if i==0 else '0',
                ATLASMAP_UE_RUN_ID=run_id+f'_{i}',ATLASMAP_UE_SKIP='',ATLASMAP_UE_WORKERS=str(max(1,4//count)))
            def validate(started,i=i,out=out,state=state,chunk=chunk):
                validate_result(str(out/'ue_import_result.json'),chunk['level'],started,run_id+f'_{i}')
                for file in ('lighting_report.json','collision_report.json'):
                    validate_result(str(state/file),chunk['level'],started)
            local=read(out/'manifest.json')
            memory=ue_import_memory(local,sum(f.stat().st_size for f in (out/'meshes').glob('*') if f.is_file()))
            import_costs.append(memory)
            jobs.append(Step(f'UE 导入 / 灯光 / 碰撞 {i+1}/{count}',cmd,env=env,validate=validate,
                storage_limits={str(project.parent):1024**3},priority=memory,
                log_path=str(folder/'process.log')))
        return jobs

    def publish_jobs():
        jobs=[]
        chunks=read(transfer/'chunks/index.json')['chunks']
        for i,(folder,out,state,chunk) in enumerate(zip(imports,outputs,raw,chunks)):
            def publish(pipe,i=i,folder=folder,out=out,state=state,chunk=chunk):
                data=read(out/'manifest.json')
                content=io_path(projects[i]/'Content'/relative)
                expected=[content/'Chunks'/f'LV_Chunk_{i+1:03d}.umap']
                own=content/'Chunks'/f'Chunk_{i+1:03d}'
                expected += [own/'Meshes'/(r['id']+'.uasset') for r in data['meshes']]
                expected += [own/'Textures'/(r['id']+'.uasset') for r in data['images']]
                expected += [own/'Materials'/(r['id']+'.uasset') for r in read(out/'material_instance_plan.json')['instances']]
                for file in expected:
                    if not file.is_file():raise ValueError('分块保存缺少资源：'+str(file))
                files=[f for f in content.rglob('*') if f.suffix in ('.uasset','.umap','.uexp','.ubulk','.uptnl')]
                task(pipe,event='assigned',work={'objects':len(data['objects']),'levels':len(ownership[i])},
                    text=f'分块 {i+1}：独立校验并发布 {len(files)} 个资源文件')
                for n,file in enumerate(files):
                    if pipe._cancelled:raise RuntimeError('已终止导出')
                    share_file(file,project.parent/'Content'/relative/file.relative_to(content),lambda:pipe._cancelled)
                    if n%32==0 or n+1==len(files):
                        task(pipe,event='progress',done=n+1,total=len(files),unit='保存文件',current=file.name)
                write(folder/'publish_result.json',dict(complete=True,run_id=run_id,index=i,files=len(files)))
            jobs.append(Step(f'校验与保存 {i+1}/{count}',[],action=publish,
                log_path=str(folder/'publish.log')))
        return jobs

    def validate_master(started):
        validate_result(str(transfer/'ue_import_result.json'),dest+'/LV_Map',started,run_id)

    master=replace(serial[-1],name='汇总分块主关卡',
        cmd=[token.replace('ue_run_headless.py','ue_assemble_chunks.py') for token in serial[-1].cmd],
        env=dict(serial[-1].env,ATLASMAP_UE_RUN_ID=run_id),storage_limits={str(project.parent):1024**3,str(transfer):128*1024**2},validate=validate_master)

    def finish_jobs():
        jobs=[]
        for i,(folder,out,state) in enumerate(zip(imports,outputs,raw)):
            def finish(pipe,i=i,folder=folder,out=out,state=state):
                for report in (folder/'publish_result.json',out/'ue_import_result.json'):
                    if not read(report).get('complete'):raise ValueError('分块完成校验失败')
                for target in (projects[i],):
                    resolved=target.resolve()
                    if not resolved.is_relative_to(native_root.resolve()) or resolved==native_root.resolve():
                        raise ValueError('临时目录越界')
                    if pipe._cancelled:return
                    if io_path(resolved).exists():shutil.rmtree(io_path(resolved))
                task(pipe,event='progress',done=1,total=1,unit='最终校验',current=f'分块 {i+1}',
                    text=f'分块 {i+1} 已发布，灯光、碰撞与材质报告均通过')
            jobs.append(Step(f'最终校验 {i+1}/{count}',[],action=finish,log_path=str(folder/'finish.log')))
        return jobs

    steps=[Step('检查导出与工作盘空间',[],action=preflight),
        Step('源地图索引',[p['exe'],'--config',p['config'],'find',f'/{p["map"]}/','2147483647'],
               log_path=str(inventory_log),validate=indexed),
        Step('多进程分析实际模型负载',[],parallel_factory=scan_jobs,parallel_limit=lambda:ue_process_capacity(count)),
        Step('平衡分块任务量',[],action=rebalance),
        Step('多进程提取源地图',[],parallel_factory=export_jobs,parallel_limit=lambda:ue_process_capacity(count)),
        Step('汇总源目录',[],action=merge_geometry),
        Step('多进程读取源光照与烘焙',[],parallel_factory=state_jobs,parallel_limit=lambda:ue_process_capacity(count)),
        Step('汇总渲染状态',[],action=lambda pipe: (merge_source_states(raw,root,full_root,pipe) and None)),
        Step('多 Blender 创建分块场景',[],parallel_factory=lambda:blender_jobs(2),parallel_limit=lambda:ue_process_capacity(count)),
        Step('多 Blender 输出分块模型',[],parallel_factory=lambda:blender_jobs(3),parallel_limit=lambda:ue_process_capacity(count)),
        Step('多 Blender 编译材质',[],parallel_factory=lambda:blender_jobs(4)),
        Step('多 Blender 分组材质',[],parallel_factory=lambda:blender_jobs(5)),
        Step('汇总分块目录',[],action=catalogue),
        Step('多 UE 导入并还原灯光与碰撞',[],parallel_factory=ue_jobs,
             parallel_limit=lambda: ue_import_capacity(count,import_costs)),
        Step('多窗口校验与保存分块',[],parallel_factory=publish_jobs),master,
        Step('多窗口最终校验',[],parallel_factory=finish_jobs)]
    if p.get('target')=='blender':steps=steps[:9]
    return [replace(s,name=f'{i+1}/{len(steps)} {s.name}') for i,s in enumerate(steps)]
