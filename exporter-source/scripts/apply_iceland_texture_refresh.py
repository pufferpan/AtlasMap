"""Restore decoded texture inputs and material families in the active scene.

Geometry is retained. The ground uses the game's ten albedos and raw G16
layer pages; complex weather, height blends and advanced-rock overlays remain
documented approximations rather than invented replacement artwork.
"""
import bpy
import json
import re
import time
from pathlib import Path

import numpy as np
from mathutils import Vector

root=Path("D:/AtlasMap-tooling/out/Iceland/revised")
folder=root/"material_refresh"
document=json.loads((folder/"material_refresh.json").read_text(encoding="utf-8-sig"))
definitions=document["materials"]
ground_folder=root/"ground_material"
ground_source=json.loads((ground_folder/"ground_sources.json").read_text(encoding="utf-8-sig"))
backup=root/("Iceland_before_texture_refresh_"+str(int(time.time()))+".blend")
bpy.ops.wm.save_as_mainfile(filepath=str(backup),copy=True,compress=True)
images={}
materials={}
families={}


def load_image(path,non_color=False,packed=False):
    path=Path(path).resolve()
    key=str(path),non_color,packed
    if key not in images:
        image=bpy.data.images.load(str(path),check_existing=False)
        image.colorspace_settings.name="Non-Color" if non_color else "sRGB"
        image.alpha_mode="CHANNEL_PACKED" if packed else "STRAIGHT"
        images[key]=image
    return images[key]


class Builder:
    def __init__(self,name):
        self.material=bpy.data.materials.new(name)
        self.material.use_nodes=True
        self.nodes=self.material.node_tree.nodes
        self.links=self.material.node_tree.links
        self.nodes.clear()
        self.output=self.nodes.new("ShaderNodeOutputMaterial")
        self.shader=self.nodes.new("ShaderNodeBsdfPrincipled")
        self.links.new(self.shader.outputs[0],self.output.inputs["Surface"])
        self.shader.inputs["Metallic"].default_value=0
        self.shader.inputs["Roughness"].default_value=.7
        self.uv=None
        self.first_color=None

    def math(self,operation,a,b=None):
        node=self.nodes.new("ShaderNodeMath")
        node.operation=operation
        if hasattr(a,"node"):self.links.new(a,node.inputs[0])
        else:node.inputs[0].default_value=float(a)
        if b is not None:
            if hasattr(b,"node"):self.links.new(b,node.inputs[1])
            else:node.inputs[1].default_value=float(b)
        if operation=="COMPARE":node.inputs[2].default_value=.1
        return node.outputs[0]

    def coord(self,scale=(1,1),offset=(0,0),world=False,uv_index=0):
        if world:
            node=self.nodes.new("ShaderNodeNewGeometry")
            value=node.outputs["Position"]
        else:
            node=self.nodes.new("ShaderNodeUVMap")
            node.uv_map="UVMap" if uv_index==0 else f"UV{uv_index}"
            value=node.outputs["UV"]
        if tuple(scale)!=(1,1):
            node=self.nodes.new("ShaderNodeVectorMath")
            node.operation="MULTIPLY"
            node.inputs[1].default_value=(scale[0],scale[1],1)
            self.links.new(value,node.inputs[0]);value=node.outputs[0]
        if tuple(offset)!=(0,0):
            node=self.nodes.new("ShaderNodeVectorMath")
            node.operation="ADD"
            node.inputs[1].default_value=(offset[0],offset[1],0)
            self.links.new(value,node.inputs[0]);value=node.outputs[0]
        return value

    def texture(self,relative,non_color=False,packed=False,coordinate=None,base=folder):
        if not relative or not (base/relative).exists():return None
        node=self.nodes.new("ShaderNodeTexImage")
        node.image=load_image(base/relative,non_color,packed)
        if coordinate is not None:self.links.new(coordinate,node.inputs["Vector"])
        if not non_color and self.first_color is None:self.first_color=node
        return node

    def mix(self,a,b,factor,operation="MIX"):
        node=self.nodes.new("ShaderNodeMixRGB")
        node.blend_type=operation
        if hasattr(factor,"node"):self.links.new(factor,node.inputs[0])
        else:node.inputs[0].default_value=factor
        for socket,value in [(node.inputs[1],a),(node.inputs[2],b)]:
            if hasattr(value,"node"):self.links.new(value,socket)
            elif isinstance(value,(int,float)):socket.default_value=(value,value,value,1)
            else:socket.default_value=tuple(value[:3])+(1,)
        return node.outputs[0]

    def split(self,texture):
        node=self.nodes.new("ShaderNodeSeparateColor")
        self.links.new(texture.outputs["Color"],node.inputs["Color"])
        return node.outputs

    def normal(self,texture,packed_nar=False,strength=1):
        if texture is None:return
        color=texture.outputs["Color"]
        if packed_nar:
            split=self.split(texture)
            x=self.math("SUBTRACT",self.math("MULTIPLY",split["Red"],2),1)
            y=self.math("SUBTRACT",self.math("MULTIPLY",split["Green"],2),1)
            length=self.math("ADD",self.math("MULTIPLY",x,x),self.math("MULTIPLY",y,y))
            z=self.math("ADD",self.math("MULTIPLY",self.math("SQRT",self.math("MAXIMUM",self.math("SUBTRACT",1,length),0)),.5),.5)
            combine=self.nodes.new("ShaderNodeCombineColor")
            self.links.new(split["Red"],combine.inputs["Red"])
            self.links.new(split["Green"],combine.inputs["Green"])
            self.links.new(z,combine.inputs["Blue"])
            color=combine.outputs[0]
        node=self.nodes.new("ShaderNodeNormalMap")
        node.inputs["Strength"].default_value=strength
        self.links.new(color,node.inputs["Color"])
        self.links.new(node.outputs["Normal"],self.shader.inputs["Normal"])


def build_material(path,definition):
    name=path.rsplit(".",1)[-1].rsplit("/",1)[-1]
    builder=Builder("TEXTURED_"+name)
    material=builder.material
    material["unrealMaterialPath"]=path
    material["texture_decoder_revision"]="DF_VT_chunk_u16_no_MAC_as_albedo"
    master=definition.get("MasterPath") or ""
    vectors=definition.get("VectorParameters",{})
    scalars=definition.get("ScalarParameters",{})
    parameters=definition.get("texture_parameters",{})
    def parameter(*names):
        for name in names:
            entry=parameters.get(name)
            if entry and entry.get("file"):return entry["file"]
        return None
    transform=vectors.get("UVScale_Offset",[1,1,0,0])
    uv=builder.coord(transform[:2],transform[2:4])
    advanced="AdvancedRock" in master
    base_file=definition.get("base_color") or parameter("BaseColorMap","BaseColorMap_SVT","ColorMap","AlbedoMap","CHMap","DecalTexture","BAMap")
    if advanced:base_file=parameter("BaseLayer_BaseColor_Height_SVT","BaseLayer_BaseColor_Height") or base_file
    base=builder.texture(base_file,packed=advanced,coordinate=uv)
    color=base.outputs["Color"] if base else vectors.get("BaseColor",vectors.get("Color",definition.get("Tint") or [1,1,1,1]))
    family="base_pbr"
    two_layer_factor=None
    if "TwoLayerDiffuse" in master and "SecondLayerBaseColor_Roughness" in vectors:
        mask=builder.texture(parameter("TwoLayerMaskMap","TwoLayerMaskMap_SVT"),True,True,uv)
        if mask:
            factor=builder.split(mask)["Red"]
            two_layer_factor=factor
            layer_color=vectors["SecondLayerBaseColor_Roughness"]
            if "WeatherCloth" in path:
                layer_color=builder.mix(color,layer_color,1,"MULTIPLY")
            color=builder.mix(color,layer_color,factor)
            builder.shader.inputs["Roughness"].default_value=vectors["SecondLayerBaseColor_Roughness"][3]
            family="two_layer_tint"
            material["second_layer_color"]=vectors["SecondLayerBaseColor_Roughness"]
    elif "MatBlend" in master:
        layer_files={}
        for key,entry in parameters.items():
            match=re.fullmatch(r"(\d{1,2})_([RGBA])_Base(?:_SVT)?",key,re.IGNORECASE)
            if match and entry.get("file"):
                layer_files[(int(match.group(1)),match.group(2).upper())]=entry["file"]
        layers=sorted((index,letter,file) for (index,letter),file in layer_files.items())
        ground_blend="MatBlend_Ground" in master
        skeletal_blend="MatBlend_Structures_SK" in master
        structure_blend="MatBlend_Structures" in master
        switches=definition.get("SwitchParameters",{})
        if structure_blend and not switches.get("Open ThreeLayer",False):
            layers=[layer for layer in layers if layer[0]<=2]
        separate_uv=ground_blend or structure_blend
        mask_index=0 if switches.get("use UV?",False) else (1 if structure_blend else 2)
        mask_uv=builder.coord(uv_index=mask_index) if separate_uv else None
        mask=builder.texture(parameter("BlendMask_SVT","BlendMask"),True,True,mask_uv)
        if structure_blend:material["blend_mask_uv"]=mask_index
        if layers:
            channel=builder.split(mask) if mask else None
            colors=[];weights=[]
            channel_names={"R":"Red","G":"Green","B":"Blue","A":None}
            for index,letter,relative in layers[:4]:
                layer_uv=builder.coord((scalars.get(f"Texcoord_{index:02d}_{letter}",1),)*2) if separate_uv else uv
                texture=builder.texture(relative,packed=True,coordinate=layer_uv)
                if texture is None:continue
                tint=vectors.get(f"Layer{index:02d}Tint",[1,1,1,0] if separate_uv else [1,1,1,1])
                sample=builder.mix(texture.outputs["Color"],vectors.get(f"BaseColorScaler_{index:02d}_{letter}",[1,1,1,1]),1,"MULTIPLY") if separate_uv else texture.outputs["Color"]
                colors.append(builder.mix(sample,tint,tint[3]) if separate_uv else builder.mix(sample,tint,1,"MULTIPLY"))
                weights.append((mask.outputs["Alpha"] if letter=="A" else channel[channel_names[letter]]) if channel else (1 if len(colors)==1 else 0))
            if colors:
                if separate_uv:
                    # Keep the base material in unpainted regions. A zero RGB
                    # mask must not synthesize a black surface through 0/epsilon.
                    painted=weights[0]
                    for weight in weights[1:]:painted=builder.math("ADD",painted,weight)
                    weights[0]=builder.math("ADD",weights[0],builder.math("LESS_THAN",painted,.0001))
                total=weights[0]
                for weight in weights[1:]:total=builder.math("ADD",total,weight)
                total=builder.math("MAXIMUM",total,.0001)
                color=(0,0,0,1)
                for sample,weight in zip(colors,weights):
                    term=builder.mix(sample,builder.math("DIVIDE",weight,total),1,"MULTIPLY")
                    color=builder.mix(color,term,1,"ADD")
                family="matblend_color_layers"
                material["unreconstructed_game_features"]="Height blending / custom UV data / weather effects"
                if structure_blend:
                    # Keep both layers' material response aligned with their
                    # colour weights, rather than using only layer one's maps.
                    roughness=metallic=0
                    normal_color=(0,0,0,1)
                    normal_samples=0
                    for (index,letter,_),weight in zip(layers[:4],weights):
                        layer_uv=builder.coord((scalars.get(f"Texcoord_{index:02d}_{letter}",1),)*2)
                        factor=builder.math("DIVIDE",weight,total)
                        response=builder.texture(parameter(f"{index:02d}_{letter}_MRA_SVT",f"{index:02d}_{letter}_MRA"),True,True,layer_uv)
                        if response:
                            values=builder.split(response)
                            rough=builder.math("MULTIPLY",values["Green"],scalars.get(f"Layer{index:02d}Roughness",1))
                            metal=builder.math("MULTIPLY",values["Red"],scalars.get(f"Layer{index:02d}Metal",0))
                        else:rough,metal=scalars.get(f"Layer{index:02d}Roughness",1),scalars.get(f"Layer{index:02d}Metal",0)
                        roughness=builder.math("ADD",roughness,builder.math("MULTIPLY",rough,factor))
                        metallic=builder.math("ADD",metallic,builder.math("MULTIPLY",metal,factor))
                        normal_sample=builder.texture(parameter(f"{index:02d}_{letter}_Normal_SVT",f"{index:02d}_{letter}_Normal"),True,True,layer_uv)
                        if normal_sample:
                            normal_color=builder.mix(normal_color,builder.mix(normal_sample.outputs["Color"],factor,1,"MULTIPLY"),1,"ADD")
                            normal_samples+=1
                    builder.links.new(roughness,builder.shader.inputs["Roughness"])
                    builder.links.new(metallic,builder.shader.inputs["Metallic"])
                    if normal_samples==len(weights):
                        normal_node=builder.nodes.new("ShaderNodeNormalMap")
                        builder.links.new(normal_color,normal_node.inputs["Color"])
                        builder.links.new(normal_node.outputs["Normal"],builder.shader.inputs["Normal"])
                    material["material_response_from_both_layers"]=True
                    family="structure_matblend_layers"
    elif advanced:
        family="advanced_rock_base"
        material["unreconstructed_game_features"]="Advanced R/G mask controls, curvature overlay, stains and RVT blend"
    tint=definition.get("Tint") or [1,1,1,1]
    if base and family=="base_pbr" and any(abs(x-1)>1e-6 for x in tint[:3]):color=builder.mix(color,tint,1,"MULTIPLY")
    if hasattr(color,"node"):builder.links.new(color,builder.shader.inputs["Base Color"])
    else:builder.shader.inputs["Base Color"].default_value=tuple(color[:3])+(1,)
    normal_file=parameter("BaseLayer_NAR_SVT","BaseLayer_NAR") if advanced else definition.get("normal") or parameter("NormalMap","NormalMap_SVT","01_R_Normal")
    normal=builder.texture(normal_file,True,True,None if advanced else uv) if family!="structure_matblend_layers" else None
    packed_nr=bool(parameter("NRMap"))
    builder.normal(normal,packed_nar=advanced or packed_nr)
    if packed_nr and normal:builder.links.new(builder.split(normal)["Blue"],builder.shader.inputs["Roughness"])
    if advanced and normal:builder.links.new(normal.outputs["Alpha"],builder.shader.inputs["Roughness"])
    packed_file=parameter("Metalic_Roughness_Alpha_Map","Metalic_Roughness_Alpha_Map_SVT") or definition.get("mra")
    packed=builder.texture(packed_file,True,True,uv) if family!="structure_matblend_layers" else None
    if packed and not advanced:
        channels=builder.split(packed)
        original=(definition.get("original_mra") or "").lower()
        if "orm" in original:metal,rough="Blue","Green"
        elif "rma" in original:metal,rough="Green","Red"
        else:metal,rough="Red","Green"
        builder.links.new(channels[metal],builder.shader.inputs["Metallic"])
        if family!="two_layer_tint":builder.links.new(channels[rough],builder.shader.inputs["Roughness"])
        elif two_layer_factor is not None:
            second_roughness=vectors["SecondLayerBaseColor_Roughness"][3]
            rough_mix=builder.math("ADD",builder.math("MULTIPLY",channels[rough],builder.math("SUBTRACT",1,two_layer_factor)),builder.math("MULTIPLY",second_roughness,two_layer_factor))
            builder.links.new(rough_mix,builder.shader.inputs["Roughness"])
        if parameter("Metalic_Roughness_Alpha_Map","Metalic_Roughness_Alpha_Map_SVT"):
            builder.links.new(channels["Blue"],builder.shader.inputs["Alpha"])
            material.surface_render_method="DITHERED"
            family="decal_pbr_alpha"
    if ("OpacityMask" in master or parameter("DecalTexture")) and base:
        opacity=builder.texture(parameter("OpacityMaskMap","OpacityMap","AlphaMap"),True,True,uv)
        alpha=builder.split(opacity)["Red"] if opacity else base.outputs["Alpha"]
        builder.links.new(alpha,builder.shader.inputs["Alpha"])
        material.surface_render_method="DITHERED"
    if "WeatherCloth" in path and definition.get("SwitchParameters",{}).get("UseDetailNormal",False):
        detail_uv=builder.coord((scalars.get("DetailNormalTiling",4),)*2)
        detail=builder.texture(parameter("DetailNormalMap"),True,True,detail_uv)
        if detail and builder.shader.inputs["Normal"].is_linked:
            original=builder.shader.inputs["Normal"].links[0].from_socket
            normal_node=builder.nodes.new("ShaderNodeNormalMap")
            normal_node.inputs["Strength"].default_value=scalars.get("DetailNormalScale",0)
            builder.links.new(detail.outputs["Color"],normal_node.inputs["Color"])
            add=builder.nodes.new("ShaderNodeVectorMath");add.operation="ADD"
            builder.links.new(original,add.inputs[0]);builder.links.new(normal_node.outputs["Normal"],add.inputs[1])
            geometry=builder.nodes.new("ShaderNodeNewGeometry")
            subtract=builder.nodes.new("ShaderNodeVectorMath");subtract.operation="SUBTRACT"
            builder.links.new(add.outputs[0],subtract.inputs[0]);builder.links.new(geometry.outputs["Normal"],subtract.inputs[1])
            normalize=builder.nodes.new("ShaderNodeVectorMath");normalize.operation="NORMALIZE"
            builder.links.new(subtract.outputs[0],normalize.inputs[0]);builder.links.new(normalize.outputs[0],builder.shader.inputs["Normal"])
            material["cloth_detail_normal_restored"]=True
            material["unreconstructed_game_features"]="Exact two-layer and detail-normal formulas are approximated; source opacity mode is opaque"
    if "M_Road_2layerDetail_HD" in master:
        response=builder.texture(parameter("HRAMap"),True,True,builder.coord((scalars.get("HRAMapTiling",1),)*2))
        if response:builder.links.new(builder.split(response)["Green"],builder.shader.inputs["Roughness"])
        attribute=builder.nodes.new("ShaderNodeVertexColor");attribute.layer_name="UEVertexColor"
        split=builder.nodes.new("ShaderNodeSeparateColor");builder.links.new(attribute.outputs["Color"],split.inputs["Color"])
        low=scalars.get("VerterxColorMin",0);high=scalars.get("VerterxColorMax",1)
        opacity=builder.math("DIVIDE",builder.math("SUBTRACT",split.outputs["Red"],low),max(high-low,.0001))
        opacity=builder.math("MINIMUM",builder.math("MAXIMUM",opacity,0),1)
        if base:opacity=builder.math("MULTIPLY",opacity,base.outputs["Alpha"])
        builder.links.new(opacity,builder.shader.inputs["Alpha"])
        material.surface_render_method="DITHERED"
        material["road_vertex_mask_restored"]=True
        material["unreconstructed_game_features"]="Vertex-red edge mask and HRA roughness restored; exact height/RVT/clipmap/weather composition remains approximate"
        family="road_vertex_mask_hra"
    if builder.first_color:builder.nodes.active=builder.first_color
    material["material_family_restored"]=family
    material["source_master"]=master
    material["has_decoded_base_color"]=bool(base)
    families[family]=families.get(family,0)+1
    return material


for path,definition in definitions.items():materials[path]=build_material(path,definition)
changed_slots=0
for obj in bpy.context.scene.objects:
    if obj.type!="MESH":continue
    for slot_index,slot in enumerate(obj.material_slots):
        old=slot.material
        if old and old.get("unrealMaterialPath") in materials:
            replacement=materials[old["unrealMaterialPath"]]
            if old==replacement:continue
            if slot.link=="OBJECT":slot.material=replacement
            else:obj.data.materials[slot_index]=replacement
            changed_slots+=1

# Source-driven terrain: two 5-bit layer indices plus a 3-bit blend weight.
terrain=next((o for o in bpy.context.scene.objects if o.type=="MESH" and o.get("source")=="BuildMaps_HD/Iceland/Runtime/LandscapeCDLOD"),None)
if terrain is None:raise RuntimeError("Source CDLOD terrain object is missing")
builder=Builder("Iceland ground - source DTA albedos and G16 weights")
width=height=4034
weight_uv=builder.coord((1/width,1/height),(.5/width,1.5/height),world=True)
weights=builder.texture("terrain_layer_ids_weights.png",True,True,weight_uv,base=ground_folder)
weights.interpolation="Closest"
weights.extension="EXTEND"
channels=builder.split(weights)
index_a=builder.math("MULTIPLY",channels["Red"],255)
index_b=builder.math("MULTIPLY",channels["Green"],255)
weight_b=builder.math("MULTIPLY",channels["Blue"],255/7)
weight_a=builder.math("SUBTRACT",1,weight_b)
color=(0,0,0,1)
for layer in ground_source["layers"]:
    coordinate=builder.coord((layer["tiling"],layer["tiling"]),world=True)
    sample=builder.texture(layer["file"],False,True,coordinate,base=ground_folder)
    a=builder.math("MULTIPLY",builder.math("COMPARE",index_a,layer["index"]),weight_a)
    b=builder.math("MULTIPLY",builder.math("COMPARE",index_b,layer["index"]),weight_b)
    contribution=builder.mix(sample.outputs["Color"],builder.math("ADD",a,b),1,"MULTIPLY")
    color=builder.mix(color,contribution,1,"ADD")
color=builder.mix((.25,.27,.25,1),color,weights.outputs["Alpha"])
builder.links.new(color,builder.shader.inputs["Base Color"])
builder.shader.inputs["Roughness"].default_value=.85
builder.material["source"]="Iceland CDLOD DTA: 10 original albedos, 840 G16 pages"
builder.material["approximation"]="Static colour layers; near tiling in local metres. Dynamic wetness, height blend, far-UV transition and micro-normal layers not rebuilt."
terrain.data.materials.clear()
terrain.data.materials.append(builder.material)
terrain.data.polygons.foreach_set("material_index",np.zeros(len(terrain.data.polygons),dtype=np.int32))

scene=bpy.context.scene
scene.render.engine="BLENDER_EEVEE"
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=="VIEW_3D":
            space=area.spaces.active
            space.shading.type="MATERIAL"
            space.shading.use_scene_world=False
            space.shading.use_scene_lights=False
            space.overlay.show_relationship_lines=False
            area.tag_redraw()
bpy.ops.file.pack_all()
output=root/"Iceland_textures_restored.blend"
if output.exists():output=root/("Iceland_textures_restored_"+str(int(time.time()))+".blend")
bpy.ops.wm.save_as_mainfile(filepath=str(output),compress=True)
report={"file":str(output),"backup":str(backup),"material_sources":len(materials),"image_datablocks":len(images),
        "material_families":families,"material_slots_updated":changed_slots,"ground_layers":len(ground_source["layers"]),
        "ground_weight_pages":len(ground_source["pages"]),"decoder_misses":document["misses"],
        "notes":"Advanced-rock overlays and dynamic landscape effects remain approximations; no MAC mask is used as albedo."}
(folder/"blender_application.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
result=report
