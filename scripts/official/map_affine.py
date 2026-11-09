"""Retain source glTF affine matrices without Blender TRS decomposition loss."""
import json
import numpy as np

BASIS=np.array(((1,0,0,0),(0,0,-1,0),(0,1,0,0),(0,0,0,1)),dtype=np.float64)


def gltf_bounds(document, binary):
    """Measure the exported positions in double precision, without Blender."""
    matrices = world_matrices(document)
    lower, upper = np.full(3, np.inf), np.full(3, -np.inf)
    for node in document['nodes']:
        if 'mesh' not in node:
            continue
        native = node.get('extras', {}).get('dfmap', {})
        if isinstance(native, str):
            native = json.loads(native)
        matrix = matrices.get(native.get('sourceId') or node.get('name'))
        if matrix is None:
            continue
        for primitive in document['meshes'][node['mesh']]['primitives']:
            accessor = document['accessors'][primitive['attributes']['POSITION']]
            if accessor['componentType'] != 5126 or accessor['type'] != 'VEC3':
                raise ValueError('Unsupported exported position accessor')
            view = document['bufferViews'][accessor['bufferView']]
            positions = np.ndarray((accessor['count'], 3), dtype='<f4', buffer=binary,
                offset=view.get('byteOffset', 0) + accessor.get('byteOffset', 0),
                strides=(view.get('byteStride', 12), 4))
            if not len(positions):
                continue
            positions = positions @ BASIS[:3, :3].T
            world = positions @ matrix[:3, :3].T + matrix[:3, 3]
            lower = np.minimum(lower, world.min(axis=0))
            upper = np.maximum(upper, world.max(axis=0))
    return lower, upper


def check_bounds(lower, upper, entry, document, binary):
    """Keep the 5 cm placement check, cross-checking huge float32 sky bounds."""
    native = np.array([entry['ueBoundsMin'], entry['ueBoundsMax']], dtype=np.float64)
    expected_lo, expected_hi = native / 100
    expected_lo[1], expected_hi[1] = -expected_hi[1], -expected_lo[1]
    errors = np.maximum(np.abs(lower - expected_lo), np.abs(upper - expected_hi))
    delta = float(errors.max())
    result = dict(bounds_delta_m=delta, bounds_reference='ue', bounds_valid=bool(delta <= .05))
    if result['bounds_valid']:
        return result
    # Source bounds were accumulated in float32 centimetres. At sky scales,
    # one representable step is already larger than the fixed 5 cm check.
    tolerance = np.maximum(.05, 2 * np.abs(np.spacing(native.astype(np.float32))).max(axis=0) / 100)
    if not np.all(errors <= tolerance):
        return result
    source_lo, source_hi = gltf_bounds(document, binary)
    source_delta = float(np.maximum(np.abs(lower - source_lo), np.abs(upper - source_hi)).max())
    result.update(bounds_valid=bool(source_delta <= .05), bounds_reference='gltf',
        source_glb_delta_m=source_delta, native_precision_tolerance_m=tolerance.tolist())
    return result


def world_matrices(document):
    result={}
    def walk(index,parent):
        node=document['nodes'][index]
        if 'matrix' in node:local=np.array(node['matrix'],dtype=np.float64).reshape(4,4).T
        else:
            x,y,z,w=node.get('rotation',(0,0,0,1))
            local=np.eye(4)
            local[:3,:3]=np.array(((1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)),
                (2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)),
                (2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y))))@np.diag(node.get('scale',(1,1,1)))
            local[:3,3]=node.get('translation',(0,0,0))
        world=parent@local
        if 'mesh' in node:
            native=node.get('extras',{}).get('dfmap',{})
            if isinstance(native,str):native=json.loads(native)
            result[native.get('sourceId') or node.get('name')]=BASIS@world@BASIS.T
        for child in node.get('children',[]):walk(child,world)
    for root in document.get('scenes',[{}])[document.get('scene',0)].get('nodes',[]):walk(root,np.eye(4))
    return result


def restore_affines(document,objects):
    import ast
    import bpy
    from mathutils import Matrix
    matrices=world_matrices(document)
    bpy.context.view_layer.update()
    for obj in objects:
        if obj.type!='MESH':continue
        native=obj.get('dfmap',{})
        if isinstance(native,str):
            try:native=json.loads(native)
            except json.JSONDecodeError:native=ast.literal_eval(native)
        target=matrices.get(native.get('sourceId') or obj.name)
        if target is None:continue
        if obj.parent is None:
            parent=bpy.data.objects.new('DF_SourceAffineFrame',None)
            bpy.context.scene.collection.objects.link(parent);obj.parent=parent
        # matrix_world assignment alone decomposes shear into TRS. The parent
        # inverse keeps the complete affine residual while sharing mesh data.
        obj.matrix_basis=Matrix.Identity(4)
        obj.matrix_parent_inverse=obj.parent.matrix_world.inverted_safe()@Matrix(target.tolist())
    bpy.context.view_layer.update()
