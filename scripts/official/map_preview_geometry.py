"""Bounded, texture-free triangle previews. Export geometry is never modified."""
import numpy as np


def simplify(vertices,triangles,limit=192):
    vertices=np.asarray(vertices,dtype=np.float32).reshape(-1,3)
    triangles=np.asarray(triangles,dtype=np.int32).reshape(-1,3)
    if not len(triangles):return np.empty((0,3,3),np.float32)
    if not np.isfinite(vertices).all():raise ValueError('Non-finite preview vertices')
    lo=vertices.min(axis=0);extent=np.maximum(vertices.max(axis=0)-lo,1e-6)
    faces=vertices[triangles]
    for cells in (24,16,12,8,6,4,3,2):
        if len(faces)<=limit:break
        keys=np.rint((vertices-lo)/extent*cells).astype(np.int32)
        _,inverse=np.unique(keys,axis=0,return_inverse=True)
        count=int(inverse.max())+1
        means=np.column_stack([np.bincount(inverse,weights=vertices[:,axis],minlength=count) for axis in range(3)])
        means/=np.bincount(inverse,minlength=count)[:,None]
        remapped=inverse[triangles]
        valid=(remapped[:,0]!=remapped[:,1])&(remapped[:,0]!=remapped[:,2])&(remapped[:,1]!=remapped[:,2])
        remapped=remapped[valid]
        if not len(remapped):continue
        _,unique=np.unique(np.sort(remapped,axis=1),axis=0,return_index=True)
        candidate=means[remapped[np.sort(unique)]]
        if len(candidate):faces=candidate
    area=np.linalg.norm(np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]),axis=1)
    faces=faces[area>1e-10]
    if len(faces)>limit:
        area=np.linalg.norm(np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]),axis=1)
        faces=faces[np.sort(np.argsort(area,kind='stable')[-limit:])]
    return np.asarray(faces,np.float32)


def transform_triangles(faces,matrix):
    matrix=np.asarray(matrix,dtype=np.float64).reshape(4,4)
    points=np.asarray(faces,dtype=np.float64)@matrix[:3,:3].T+matrix[:3,3]
    normals=np.cross(points[:,1]-points[:,0],points[:,2]-points[:,0])
    length=np.linalg.norm(normals,axis=1)
    valid=(length>1e-10)&np.isfinite(points).all(axis=(1,2))
    return points[valid].astype(np.float32),(normals[valid]/length[valid,None]).astype(np.float32)
