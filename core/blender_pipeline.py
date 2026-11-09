"""One-click Blender export; no Unreal installation or project is required."""
from dataclasses import replace
import json
import re
from pathlib import Path
import uuid
from core import ue_pipeline
from core.ue_pipeline import Step
from core.parallel_export import read,write
from core.full_parallel_export import full_parallel_steps
from core.system_usage import ue_process_capacity
from scripts.official.map_io import share_file


def project_path(root,name,run_id):
    return Path(str(root)+'_blender')/run_id[:12]/(name+'.blend')


def build_steps(p,run_id=None):
    run_id=run_id or uuid.uuid4().hex
    project=project_path(p['root'],p['map'],run_id)
    params=dict(p,target='blender',engine='',cmd='',project=str(project),parallel_export='0')
    serial=ue_pipeline.build_steps(params)
    parallel=p.get('parallel_export') in (True,'1')
    count=max(2,min(8,int(p.get('parallel_processes',2)))) if parallel else 1
    steps=full_parallel_steps(params,serial,run_id) if parallel else serial[:3]
    config=project.parent/'assemble.json'
    chunk_options=[]

    def save_jobs():
        chunk_options.clear()
        if parallel:
            workspace=read(Path(p['transfer'])/'parallel'/run_id/'workspace.json')
            if workspace.get('run_id')!=run_id:raise ValueError('Blender workspace belongs to another export')
            raw=[Path(path) for path in workspace['raw']]
        else:raw=[Path(p['root'])]
        jobs=[]
        for i,folder in enumerate(raw):
            output=project.parent/'assets'/f'Chunk_{i+1:03d}.blend'
            options=dict(output=str(output),run_id=run_id,index=i,source=p['root'],collection=f'AtlasMap_Chunk_{i+1:03d}')
            option_file=project.parent/'tasks'/f'chunk_{i+1:03d}.json';write(option_file,options)
            chunk_options.append(options)
            def validate(started,output=output):
                report=read(output.with_suffix('.json'))
                if (not report.get('complete') or report.get('run_id')!=run_id
                        or not output.is_file() or output.stat().st_mtime<started-2):
                    raise ValueError('Blender chunk was not saved and reopened successfully')
            jobs.append(Step(f'保存 Blender 分块 {i+1}/{count}',[p['blender'],'-b',str(folder/'scene_no_terrain.blend'),
                '--python-exit-code','1','-P',str(Path(p['scripts'])/'blender_save_project.py'),'--',str(option_file)],
                validate=validate,log_path=str(project.parent/'logs'/f'chunk_{i+1:03d}.log'),
                storage_limits={str(project.parent):512*1024**2}))
        return jobs

    def assemble_options(pipe):
        lighting=project.parent/'assets'/'source_lighting.json'
        source=Path(p['root'])/'render_state.json'
        if source.is_file():share_file(source,lighting)
        write(config,dict(project=str(project),map=p['map'],run_id=run_id,chunks=chunk_options,lighting=str(lighting)))

    def validate_master(started):
        report=read(project.parent/'blender_project.json')
        if (not report.get('complete') or report.get('run_id')!=run_id or report.get('map')!=p['map']
                or not report.get('mesh_objects') or report.get('chunks')!=count
                or project.stat().st_mtime<started-2):raise ValueError('Blender master project failed saved-data validation')

    steps.extend([Step('打包贴图并验证 Blender 分块',[],parallel_factory=save_jobs,
        parallel_limit=lambda:ue_process_capacity(count)),
        Step('准备 Blender 工程目录',[],action=assemble_options),
        Step('组装并重新打开 Blender 地图工程',[p['blender'],'-b','--python-exit-code','1','-P',
            str(Path(p['scripts'])/'blender_assemble_project.py'),'--',str(config)],validate=validate_master,
            log_path=str(project.parent/'logs'/'assemble.log'),storage_limits={str(project.parent):512*1024**2})])
    return [replace(step,name=f'{i+1}/{len(steps)} '+re.sub(r'^\d+/\d+\s+','',step.name)) for i,step in enumerate(steps)],str(project)
