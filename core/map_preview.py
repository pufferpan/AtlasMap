"""Run-scoped preview files and environment propagation to native workers."""
import io
import json
from pathlib import Path
import uuid
import numpy as np
from scripts.official.map_paths import io_path


def session(root,name,count):
    identity=uuid.uuid4().hex
    return dict(run_id=identity,name=name,count=count,folder=str(Path(root)/'preview'/identity))


def attach(steps,preview):
    def bind(step,index=0):
        step.env.update(ATLASMAP_PREVIEW_DIR=preview['folder'],ATLASMAP_PREVIEW_RUN_ID=preview['run_id'],
                        ATLASMAP_PREVIEW_INDEX=str(index))
        if step.parallel_factory:
            factory=step.parallel_factory
            def jobs():return [bind(job,i) for i,job in enumerate(factory())]
            step.parallel_factory=jobs
        return step
    return [bind(step) for step in steps]


def read_chunk(path,run_id,index):
    content=io_path(path).read_bytes()
    if len(content)>12*1024**2:raise ValueError('Preview exceeds its geometry budget')
    with np.load(io.BytesIO(content),allow_pickle=False) as data:
        metadata=json.loads(data['metadata'].tobytes())
        vertices=data['vertices']
    if metadata.get('schema')!=1 or metadata.get('run_id')!=run_id or metadata.get('worker')!=index:
        raise ValueError('Preview belongs to a different export')
    if (vertices.dtype!=np.float32 or vertices.ndim!=2 or vertices.shape[1]!=9
            or len(vertices)>360*192*3 or len(vertices)%3 or not np.isfinite(vertices).all()):
        raise ValueError('Invalid preview triangles')
    return vertices,metadata
