"""Deterministic source-level partitioning with intact parent hierarchies."""
def partition_objects(objects, count):
    if count < 1:
        raise ValueError('Chunk count must be positive')
    by_id = {row['id']: row for row in objects}
    if len(by_id) != len(objects):
        raise ValueError('Duplicate scene object ID')
    parent = {key: key for key in by_id}
    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    def join(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a,b)] = min(a,b)
    levels = {}
    for row in objects:
        if row.get('parent'):
            if row['parent'] not in by_id:
                raise ValueError('Missing object parent: '+row['id'])
            join(row['id'], row['parent'])
        level = row.get('properties', {}).get('source_level')
        if level:
            if level in levels:
                join(row['id'], levels[level])
            else:
                levels[level] = row['id']
    groups = {}
    for row in objects:
        groups.setdefault(find(row['id']), []).append(row)
    chunks = [dict(index=i, object_ids=[], source_levels=[], weight=0) for i in range(count)]
    units = sorted(groups.items(), key=lambda item:(
        -sum(max(1,int(row.get('triangles',1))) for row in item[1]), item[0]))
    for _, rows in units:
        target = min(chunks, key=lambda c:(c['weight'],len(c['object_ids']),c['index']))
        target['object_ids'].extend(row['id'] for row in rows)
        target['source_levels'].extend(row.get('properties',{}).get('source_level') for row in rows
                                       if row.get('properties',{}).get('source_level'))
        target['weight'] += sum(max(1,int(row.get('triangles',1))) for row in rows)
    for chunk in chunks:
        chunk['object_ids'].sort()
        chunk['source_levels'] = sorted(set(chunk['source_levels']))
    return chunks


def material_subset(plan, instances, objects, meshes):
    """Include each chunk's bound material variants and parent texture dependencies."""
    object_ids={row['id'] for row in objects}
    mesh_ids={row['id'] for row in meshes}
    needed={mid for key,values in plan['object_materials'].items() if key in object_ids for mid in values if mid}
    needed.update(mid for key,values in plan['mesh_materials'].items() if key in mesh_ids for mid in values if mid)
    local_plan=dict(plan,materials=[row for row in plan['materials'] if row['id'] in needed],
        mesh_materials={key:value for key,value in plan['mesh_materials'].items() if key in mesh_ids},
        object_materials={key:value for key,value in plan['object_materials'].items() if key in object_ids})
    selected=[row for row in instances['instances'] if row['id'] in needed]
    if {row['id'] for row in selected} != needed:
        raise ValueError('Chunk has unresolved material instances')
    parents={row['parent'] for row in selected}
    selected_parents=[row for row in instances['parents'] if row['id'] in parents]
    images=set()
    for row in local_plan['materials']+selected+selected_parents:
        textures=row.get('textures',[])
        if isinstance(textures,dict):
            images.update(textures.values())
        else:
            images.update(t['image'] for t in textures if t.get('image'))
    return local_plan,dict(instances,instances=selected,parents=selected_parents),images
