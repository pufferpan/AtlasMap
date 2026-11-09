"""Publish bounded native scene geometry without decoding a single texture."""
import heapq
import io
import json
import os
from pathlib import Path
import time
import numpy as np
from map_preview_geometry import simplify,transform_triangles
from map_io import atomic_bytes


class LivePreview:
    def __init__(self):
        self.folder=os.environ.get('ATLASMAP_PREVIEW_DIR','')
        self.run_id=os.environ.get('ATLASMAP_PREVIEW_RUN_ID','')
        self.worker=int(os.environ.get('ATLASMAP_PREVIEW_INDEX','0'))
        self.limit=360
        self.objects={};self.last=0;self.cache={};self.disabled=False

    def add(self,objects,*,force=False,replace=False,complete=False):
        if not self.folder or self.disabled:return
        try:self._add(objects,force=force,replace=replace,complete=complete)
        except Exception as exc:
            self.disabled=True
            print('[preview] Cannot update map preview: '+str(exc),flush=True)

    def _add(self,objects,*,force,replace,complete):
        if replace:self.objects.clear()
        for obj in objects:
            if obj.type!='MESH' or obj.hide_render or obj.hide_get():continue
            source=str(obj.data.get('unrealAssetPath',''))+' '+obj.name
            if any(word in source.lower() for word in ('skysphere','sky_sphere','skydome','sky_dome')):continue
            matrix=np.asarray(obj.matrix_world,dtype=np.float64)
            corners=np.asarray(obj.bound_box)@matrix[:3,:3].T+matrix[:3,3]
            extent=np.ptp(corners,axis=0)
            if not np.isfinite(corners).all() or extent.max()>30000:continue
            score=float(extent[0]*extent[1]+extent.max()*extent[2])
            if score>.02:self.objects[obj.name]=(score,obj)
        best=heapq.nlargest(self.limit,self.objects.items(),key=lambda row:(row[1][0],row[0]))
        self.objects=dict(best)
        now=time.monotonic()
        if not force and now-self.last<3:return
        self.last=now
        batches=[];mesh_objects=0
        for name,(score,obj) in best:
            try:
                mesh=obj.data;key=mesh.as_pointer()
                if key not in self.cache:
                    mesh.calc_loop_triangles()
                    vertices=np.empty(len(mesh.vertices)*3,np.float32)
                    indices=np.empty(len(mesh.loop_triangles)*3,np.int32)
                    mesh.vertices.foreach_get('co',vertices)
                    mesh.loop_triangles.foreach_get('vertices',indices)
                    self.cache[key]=simplify(vertices.reshape(-1,3),indices.reshape(-1,3),192)
                points,normals=transform_triangles(self.cache[key],obj.matrix_world)
                if not len(points):continue
                color=np.array((.57,.65,.72),np.float32)
                if len(mesh.materials) and mesh.materials[0]:
                    value=np.asarray(mesh.materials[0].diffuse_color[:3])
                    if value.max()>.05:color=np.clip(value,.15,.9)
                data=np.concatenate((points,np.repeat(normals[:,None,:],3,axis=1),
                    np.broadcast_to(color,points.shape)),axis=2).reshape(-1,9)
                batches.append(data);mesh_objects+=1
            except ReferenceError:continue  # A deduplicated object may already be removed.
        vertices=np.concatenate(batches).astype(np.float32) if batches else np.empty((0,9),np.float32)
        meta=dict(schema=1,run_id=self.run_id,worker=self.worker,complete=complete,
                  sampled_objects=mesh_objects,triangles=len(vertices)//3)
        stream=io.BytesIO()
        np.savez_compressed(stream,vertices=vertices,metadata=np.frombuffer(json.dumps(meta).encode(),np.uint8))
        atomic_bytes(Path(self.folder)/f'worker_{self.worker}.npz',stream.getvalue())
        print('@ATLASMAP_PREVIEW '+json.dumps(meta),flush=True)
