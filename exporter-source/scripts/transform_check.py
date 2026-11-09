"""Compare dfmap's extracted instance transforms against the raw level data.

Reads a `dfmap dump` JSON of a .umap and pairs every StaticMeshComponent with the instance
dfmap produced for the same mesh, then reports translation/rotation/scale mismatches. This
separates "extraction is wrong" from "axis mapping is wrong".
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

dump_path = sys.argv[1]
scene_path = sys.argv[2]
level_key = sys.argv[3]          # substring that identifies this level inside scene.json names

d = json.load(open(dump_path, encoding='utf-8'))
scene = json.load(open(scene_path, encoding='utf-8'))
inst = [i for i in scene['instances'] if level_key in i['name']]
print(f'{dump_path}')
print(f'  components in dump : {sum(1 for e in d if e.get("type") == "StaticMeshComponent")}')
print(f'  instances in scene : {len(inst)}')

# raw component table
comps = []
for e in d:
    if e.get('type') != 'StaticMeshComponent':
        continue
    p = (e.get('value') or {}).get('Properties') or {}
    L = p.get('RelativeLocation') or {}
    R = p.get('RelativeRotation') or {}
    S = p.get('RelativeScale3D') or {}
    mesh = (p.get('StaticMesh') or {}).get('ObjectName', '')
    m = re.search(r"'([^']+)'", mesh)
    comps.append({
        'name': e.get('name'),
        'mesh': m.group(1) if m else '',
        'loc': (L.get('X', 0.0), L.get('Y', 0.0), L.get('Z', 0.0)),
        'rot': (R.get('Roll', 0.0), R.get('Pitch', 0.0), R.get('Yaw', 0.0)),
        'scale': (S.get('X', 1.0), S.get('Y', 1.0), S.get('Z', 1.0)),
        'attach': (p.get('AttachParent') or {}).get('ObjectName', ''),
    })
print(f'  components with AttachParent: {sum(1 for c in comps if c["attach"])}')

# greedy match scene instances to components by (mesh, rounded location)
used = set()
exact = miss = 0
worst = []
for c in comps:
    best = None
    bestd = 1e30
    for k, i in enumerate(inst):
        if k in used:
            continue
        if i['mesh'].split('.')[-1] != c['mesh']:
            continue
        d2 = sum((a - b) ** 2 for a, b in zip(c['loc'], i['loc']))
        if d2 < bestd:
            bestd, best = d2, k
    if best is None:
        miss += 1
        continue
    used.add(best)
    i = inst[best]
    delta = [round(a - b, 3) for a, b in zip(c['loc'], i['loc'])]
    rdelta = [round(a - b, 3) for a, b in zip(c['rot'], i.get('rot') or (0, 0, 0))]
    sdelta = [round(a - b, 4) for a, b in zip(c['scale'], i.get('scale') or (1, 1, 1))]
    good_loc = max(abs(v) for v in delta) < 0.01
    good_rot = max(abs(v) for v in rdelta) < 0.01
    good_scale = max(abs(v) for v in sdelta) < 0.001
    if good_loc and good_rot and good_scale:
        exact += 1
    else:
        worst.append((max(abs(v) for v in delta), c['mesh'], list(c['loc']), list(i['loc']), delta,
                      c['attach'], 'loc' if not good_loc else ('rot' if not good_rot else 'scale'),
                      list(c['rot']), list(i.get('rot') or ()), rdelta,
                      list(c['scale']), list(i.get('scale') or ()), sdelta))

print(f'\n  matched exactly (loc+rot+scale): {exact}/{len(comps)}')
print(f'  no scene counterpart           : {miss}')
print(f'  matched but differ             : {len(worst)}')
worst.sort(reverse=True)
for w in worst[:12]:
    print(f'    [{w[6]}] maxdelta={w[0]:10.3f}  {w[1]}')
    print(f'        level loc={w[2]} rot={w[7]} scale={w[10]}')
    print(f'        dfmap loc={w[3]} rot={w[8]} scale={w[11]}')
    print(f'        d_loc={w[4]} d_rot={w[9]} d_scale={w[12]}  attach={w[5] or "-"}')
