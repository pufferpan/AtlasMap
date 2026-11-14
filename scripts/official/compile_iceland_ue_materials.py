"""Translate the actual Blender material DAGs to UE custom math plus texture nodes."""
import hashlib
import json
from pathlib import Path

import sys as _sys, os as _os
ROOT=Path(_os.environ.get('ATLASMAP_UE_ROOT') or Path('.').resolve())
manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
source_materials={m['id']:m for m in manifest['materials']}
source_meshes={m['id']:m for m in manifest['meshes']}

def task_event(**data):
    print('@ATLASMAP_TASK '+json.dumps(data,ensure_ascii=False),flush=True)

task_event(event='assigned',work={'materials':len(source_materials),'meshes':len(source_meshes)},
           text=f'本块材质编译：{len(source_materials)} 材质 / {len(source_meshes)} 模型')

def number(value):
    value=float(value)
    if not (-1e30<value<1e30):raise ValueError('Non-finite shader value')
    result=format(value,'.9g')
    return result if '.' in result or 'e' in result else result+'.0'

class Ref:
    def __init__(self,kind,expression):self.kind,self.code=kind,expression
    def cast(self,kind):
        if self.kind==kind:return self.code
        if kind==1:
            if self.kind in (3,4):return f'dot(({self.code}).rgb,float3(0.2126,0.7152,0.0722))'
        if kind==3:
            if self.kind==1:return f'float3({self.code},{self.code},{self.code})'
            if self.kind==4:return f'({self.code}).rgb'
        if kind==4:
            if self.kind==1:return f'float4({self.code},{self.code},{self.code},1.0)'
            if self.kind==3:return f'float4({self.code},1.0)'
        raise ValueError((self.kind,kind))

class Generator:
    def __init__(self,material,bindings,texture_inputs=None):
        self.material=material;self.nodes={n['id']:n for n in material['nodes']}
        self.bindings=bindings;self.texture_inputs=texture_inputs
        self.lines=[];self.cache={};self.globals=set()
    def temporary(self,kind,expression):
        name='v'+str(len(self.lines));self.lines.append(f'float{kind if kind>1 else ""} {name} = {expression};')
        return Ref(kind,name)
    def constant(self,socket):
        v=socket.get('default',0)
        if isinstance(v,list):return Ref(len(v),'float'+str(len(v))+'('+','.join(number(x) for x in v)+')')
        return Ref(1,number(v))
    def input(self,node,index):
        socket=node['inputs'][index]
        if 'link' in socket:
            link=socket['link'];return self.output(link['node'],link['output'])
        return self.constant(socket)
    def named(self,node,name):
        return self.input(node,next(i for i,s in enumerate(node['inputs']) if s['name']==name))
    def uv(self,name):
        index=self.bindings.get(name,-1)
        if index<0:return Ref(3,'float3(0,0,0)')
        key='UV'+str(index);self.globals.add(key)
        return Ref(3,f'float3({key}.x,1.0-{key}.y,0.0)')
    def output(self,identifier,output=0):
        key=(identifier,output)
        if key in self.cache:return self.cache[key]
        n=self.nodes[identifier];typ=n['type'];socket=n['outputs'][output]['name']
        if typ=='TEX_COORD':
            if socket!='UV':raise RuntimeError('Unsupported texture coordinate output '+socket)
            result=self.uv('__active__')
        elif typ=='UVMAP':result=self.uv(n.get('uv_map') or '__active__')
        elif typ=='NEW_GEOMETRY':
            if socket=='Position':
                self.globals.add('WP');result=Ref(3,'float3(WP.x,-WP.y,WP.z)*0.01')
            elif socket=='Normal':result=Ref(3,'float3(Parameters.TangentToWorld[2].x,-Parameters.TangentToWorld[2].y,Parameters.TangentToWorld[2].z)')
            else:raise RuntimeError('Unsupported geometry output '+socket)
        elif typ=='VERTEX_COLOR':
            self.globals.add('VC');result=Ref(4,'VC') if socket=='Color' else Ref(1,'VC.a')
        elif typ=='TEX_IMAGE':
            if self.texture_inputs is None:raise RuntimeError('Texture-dependent coordinate needs explicit support')
            base=self.texture_inputs[identifier]
            result=Ref(4,base) if socket=='Color' else Ref(1,base+'.a')
        elif typ=='MATH':
            a=self.input(n,0).cast(1);b=self.input(n,1).cast(1);op=n['operation']
            operators={'ADD':f'({a}+{b})','SUBTRACT':f'({a}-{b})','MULTIPLY':f'({a}*{b})',
                'DIVIDE':f'(abs({b})>1e-20 ? {a}/{b} : 0.0)','MAXIMUM':f'max({a},{b})','MINIMUM':f'min({a},{b})',
                'SQRT':f'sqrt(max({a},0.0))','LESS_THAN':f'(({a}<{b})?1.0:0.0)'}
            if op=='COMPARE':operators[op]=f'((abs({a}-{b})<=max({self.input(n,2).cast(1)},1e-5))?1.0:0.0)'
            if op not in operators:raise RuntimeError('Unsupported math '+op)
            expression=operators[op]
            if n.get('use_clamp'):expression='saturate('+expression+')'
            result=self.temporary(1,expression)
        elif typ=='VECT_MATH':
            a=self.input(n,0).cast(3);b=self.input(n,1).cast(3);op=n['operation']
            operators={'ADD':f'({a}+{b})','SUBTRACT':f'({a}-{b})','MULTIPLY':f'({a}*{b})',
                'NORMALIZE':f'(dot({a},{a})>1e-20 ? normalize({a}) : float3(0,0,0))'}
            if op not in operators:raise RuntimeError('Unsupported vector math '+op)
            result=self.temporary(3,operators[op])
        elif typ=='MIX_RGB':
            fac=self.input(n,0).cast(1);a=self.input(n,1).cast(4);b=self.input(n,2).cast(4)
            op=n['blend_type']
            colors={'MIX':f'lerp(({a}).rgb,({b}).rgb,saturate({fac}))',
                    'MULTIPLY':f'lerp(({a}).rgb,({a}).rgb*({b}).rgb,saturate({fac}))',
                    'ADD':f'(({a}).rgb+({b}).rgb*saturate({fac}))'}
            if op not in colors:raise RuntimeError('Unsupported colour blend '+op)
            rgb=colors[op]
            if n.get('use_clamp'):rgb='saturate('+rgb+')'
            result=self.temporary(4,f'float4({rgb},({a}).a)')
        elif typ=='MIX':
            # Blender 4/5 的 ShaderNodeMix：一堆重名 socket，必须按 identifier 取；
            # Ref.cast() 返回的是代码字符串（不是 Ref），所以这里全程用字符串拼。
            data_type=n.get('data_type','RGBA')
            blend=n.get('blend_type','MIX')
            kind={'RGBA':4,'VECTOR':3,'FLOAT':1}.get(data_type)
            if kind is None:raise RuntimeError('Unsupported Mix data_type '+str(data_type))
            suffix={4:'Color',3:'Vector',1:'Float'}[kind]
            ra=self.by_id(n,'A_'+suffix);rb=self.by_id(n,'B_'+suffix)
            if ra is None or rb is None:raise RuntimeError('Mix node missing A/B sockets')
            a=ra.cast(kind);b=rb.cast(kind)
            rf=self.by_id(n,'Factor_Float') or self.by_id(n,'Factor_Vector')
            factor=rf.cast(1) if rf is not None else '1.0'
            if blend=='MIX':
                code=f'lerp({a},{b},saturate({factor}))'
            elif blend=='MULTIPLY':
                code=f'({a}*{b})'
            elif blend=='ADD':
                code=f'({a}+{b})'
            elif blend=='SUBTRACT':
                code=f'({a}-{b})'
            elif blend=='SCREEN':
                code=f'(1.0-(1.0-{a})*(1.0-{b}))'
            else:
                raise RuntimeError('Unsupported Mix blend_type '+str(blend))
            result=self.temporary(kind,code)
        elif typ=='SEPARATE_COLOR':
            if n.get('mode','RGB')!='RGB':raise RuntimeError('Unsupported colour separation')
            a=self.input(n,0).cast(4);channel={'Red':'r','Green':'g','Blue':'b','Alpha':'a'}[socket]
            result=Ref(1,f'({a}).{channel}')
        elif typ=='COMBINE_COLOR':
            if n.get('mode','RGB')!='RGB':raise RuntimeError('Unsupported colour combination')
            channels=[self.input(n,i).cast(1) for i in range(min(4,len(n['inputs'])))]
            if len(channels)==3:channels.append('1.0')
            result=self.temporary(4,'float4('+','.join(channels)+')')
        elif typ=='NORMAL_MAP':
            if n.get('space')!='TANGENT':raise RuntimeError('Unsupported normal-map space')
            uv_index=self.bindings.get(n.get('uv_map') or '__active__',0)
            if uv_index!=0:raise RuntimeError('Normal map requires a non-default tangent basis')
            color=self.named(n,'Color').cast(3);strength=self.named(n,'Strength').cast(1)
            t=self.temporary(3,f'({color}*2.0-1.0)')
            shaped=self.temporary(3,f'float3({t.code}.x*{strength},-{t.code}.y*{strength},lerp(1.0,{t.code}.z,saturate({strength})))')
            world=self.temporary(3,f'normalize(mul({shaped.code},Parameters.TangentToWorld))')
            result=Ref(3,f'float3({world.code}.x,-{world.code}.y,{world.code}.z)')
        elif typ=='ATTRIBUTE':
            # ShaderNodeAttribute：读顶点色（Col / Vertex Color）或自定义属性。
            # 顶点色我们本来就导出成 VC，可以直连；其他属性没有数据来源，退化成 0，
            # 但绝不能让整块材质编译失败（Dam_Iris_Long3 就是死在这里）。
            scope=n.get('attribute_type','GEOMETRY')
            attribute=(n.get('attribute_name') or '').lower()
            if scope!='GEOMETRY':
                raise RuntimeError('Unsupported attribute scope '+str(scope))
            if attribute in ('','col','color','col0','vertexcolor','vertex_color','vc'):
                self.globals.add('VC')
                if socket=='Color':result=Ref(4,'VC')
                elif socket=='Vector':result=Ref(3,'float3(VC.r,VC.g,VC.b)')
                elif socket in ('Fac','Alpha'):result=Ref(1,'VC.a')
                else:raise RuntimeError('Unsupported attribute output '+socket)
            else:
                print('[atlas] WARN attribute '+repr(attribute)+' has no data source; using zero',
                      flush=True)
                if socket=='Color':result=Ref(4,'float4(0,0,0,0)')
                elif socket=='Vector':result=Ref(3,'float3(0,0,0)')
                else:result=Ref(1,'0.0')
        else:raise RuntimeError('Unsupported contributing node '+typ)
        self.cache[key]=result;return result
    def by_id(self,n,identifier):
        """按 socket identifier 取输入（Blender 4/5 的 Mix 节点有重名 socket，只能靠 identifier 认）。"""
        for index,socket in enumerate(n['inputs']):
            if socket.get('identifier')==identifier:
                return self.input(n,index)
        return None

    def texture_coordinates(self,texture):
        index=next(i for i,s in enumerate(texture['inputs']) if s['name']=='Vector')
        if 'link' in texture['inputs'][index]:ref=self.input(texture,index)
        else:ref=self.uv('__active__')
        vector=ref.cast(3)
        return '\n'.join(self.lines+[f'return float2(({vector}).x,1.0-({vector}).y);'])

variants={};assignments={};mesh_defaults={}
def compile_material(material_id,mesh):
    m=source_materials[material_id]
    needed={'__active__'}
    needed.update(n.get('uv_map') or '__active__' for n in m['nodes'] if n['type'] in ['UVMAP','NORMAL_MAP'])
    bindings={name:(mesh['active_render_uv'] if name=='__active__' else mesh['uv_layers'].index(name) if name in mesh['uv_layers'] else -1) for name in sorted(needed)}
    key=material_id+'_'+hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()[:8]
    if key in variants:return key
    textures=[];g=Generator(m,bindings,{})
    if m['use_nodes']:
        shader=next(n for n in m['nodes'] if n['type']=='BSDF_PRINCIPLED')
        roots=['Base Color','Metallic','Roughness','Alpha','Normal','IOR','Transmission Weight']
        roots=[name for name in roots if any(s['name']==name for s in shader['inputs'])]
        # Reachability is computed before replacing image nodes with sampled inputs.
        seen=set()
        def visit(node):
            if node in seen:return
            seen.add(node)
            for socket in m['nodes'][node]['inputs']:
                if 'link' in socket:visit(socket['link']['node'])
        for name in roots:
            socket=next(s for s in shader['inputs'] if s['name']==name)
            if 'link' in socket:visit(socket['link']['node'])
        for node in m['nodes']:
            if node['id'] not in seen or node['type']!='TEX_IMAGE':continue
            input_name='Img_'+str(node['id'])
            cg=Generator(m,bindings)
            code=cg.texture_coordinates(node)
            if (m.get('surface') or {}).get('kind')=='water':
                speed=(m.get('surface') or {}).get('normal_speed',0)
                scale=(m.get('surface') or {}).get('normal_scale',1)
                if speed:
                    cg.globals.add('TIME')
                    # Advect the sampled source wave normal, without moving mesh vertices.
                    code=code.replace('return ',f'return float2(TIME*{number(speed)},TIME*{number(speed*.37)}) + {number(scale)}*',1)
            textures.append({'node':node['id'],'input':input_name,'image':node['image'],'coordinate_code':code,
                'coordinate_inputs':sorted(cg.globals),'extension':node.get('extension','REPEAT'),'interpolation':node.get('interpolation','Linear')})
            g.texture_inputs[node['id']]=input_name
        base=g.named(shader,'Base Color').cast(3);metal=g.named(shader,'Metallic').cast(1);rough=g.named(shader,'Roughness').cast(1);alpha=g.named(shader,'Alpha').cast(1)
        normal_socket=next(s for s in shader['inputs'] if s['name']=='Normal')
        normal=g.named(shader,'Normal').cast(3) if 'link' in normal_socket else 'float3(Parameters.TangentToWorld[2].x,-Parameters.TangentToWorld[2].y,Parameters.TangentToWorld[2].z)'
        alpha_socket=next(s for s in shader['inputs'] if s['name']=='Alpha')
        masked='link' in alpha_socket or alpha_socket.get('default',1)<.999
    else:
        base='float3('+','.join(number(x) for x in m['diffuse_color'][:3])+')';metal=number(m['metallic']);rough=number(m['roughness']);alpha=number(m['diffuse_color'][3]);normal='float3(Parameters.TangentToWorld[2].x,-Parameters.TangentToWorld[2].y,Parameters.TangentToWorld[2].z)';masked=m['diffuse_color'][3]<.999
    surface=m.get('surface') or {}
    # An alpha texture alone does not distinguish glass from foliage. Preserve
    # the native blend/shading family collected before the glTF conversion.
    kind=surface.get('kind')
    if not kind:
        transmission=next((s for s in shader['inputs'] if s['name'] in ('Transmission Weight','Transmission')),{}) if m['use_nodes'] else {}
        kind='translucent' if m.get('surface_render_method')=='BLENDED' or transmission.get('default',0)>0 else 'masked' if masked else 'opaque'
    ior=g.named(shader,'IOR').cast(1) if m['use_nodes'] and any(s['name']=='IOR' for s in shader['inputs']) else '1.45'
    specular='0.5'
    if surface:
        if kind in ('translucent','water'):
            alpha=number(surface['opacity']);rough=number(surface['roughness']);metal='0.0'
            ior=number(surface['ior']);specular=number(surface['specular'])
        elif kind=='opaque':alpha='1.0'
    elif kind=='translucent' and m['use_nodes'] and transmission.get('default',0)>0:
        alpha=f'({alpha}*(1.0-{g.named(shader,transmission["name"]).cast(1)}))'
    masked=kind=='masked'
    final=g.lines+[f'OutNormal=normalize(float3(({normal}).x,-({normal}).y,({normal}).z));',
        f'OutMetallic=saturate({metal});',f'OutRoughness=saturate({rough});',f'OutAlpha=saturate({alpha});',f'OutIOR=clamp({ior},1.0,2.5);',f'OutSpecular=saturate({specular});',f'return {base};']
    code='\n'.join(final)
    record={'id':key,'source_material':material_id,'source_name':m['source_name'],'source_path':m['source_path'],
            'surface_kind':kind,'surface':surface,'bindings':bindings,'masked':masked,'two_sided':not m['backface_culling'],
            'textures':textures,'code':code,'inputs':sorted(g.globals),'sha256':hashlib.sha256((code+json.dumps({'kind':kind,'surface':surface},sort_keys=True)).encode()).hexdigest()}
    variants[key]=record
    (ROOT/'material_graphs'/f'{key}.hlsl').write_text(code)
    return key

for index,mesh in enumerate(manifest['meshes']):
    mesh_defaults[mesh['id']]=[compile_material(mid,mesh) if mid else None for mid in mesh['materials']]
    if index%8==0 or index+1==len(manifest['meshes']):
        task_event(event='progress',done=index+1,total=len(manifest['meshes'])+len(manifest['objects']),unit='材质绑定',current=mesh['id'])
for index,obj in enumerate(manifest['objects']):
    if obj['type']=='MESH':assignments[obj['id']]=[compile_material(mid,source_meshes[obj['mesh']]) if mid else None for mid in obj['materials']]
    if index%32==0 or index+1==len(manifest['objects']):
        task_event(event='progress',done=len(manifest['meshes'])+index+1,total=len(manifest['meshes'])+len(manifest['objects']),unit='材质绑定',current=obj['id'])
plan={'materials':list(variants.values()),'mesh_materials':mesh_defaults,'object_materials':assignments,
      'counts':{'source_materials':len(source_materials),'material_variants':len(variants),'mesh_assignments':len(mesh_defaults),'object_assignments':len(assignments)},
      'unsupported_contributing_nodes':[]}
(ROOT/'material_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(plan['counts'],indent=2))
