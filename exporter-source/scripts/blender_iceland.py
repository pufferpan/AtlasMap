"""Import exported Iceland blocks through Blender's glTF importer and render.

All positions retain the dfmap convention UE (x,-y,z)/100. Mesh data is
shared across levels by full source asset name, reducing memory consumption.
"""
import hashlib
import json
import math
import struct
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector, Matrix

ROOT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
WITH_MATERIALS = "--materials" in sys.argv
START = time.time()


def log(message):
    print(f"[{time.time() - START:.1f}s] {message}", flush=True)


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"
scene.unit_settings.scale_length = 1
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.display.shading.light = "STUDIO"
scene.display.shading.studiolight_rotate_z = 0.4
scene.display.shading.color_type = "TEXTURE" if WITH_MATERIALS else "OBJECT"
scene.display.shading.show_shadows = True
scene.display.shading.show_cavity = True
scene.display.shading.cavity_type = "BOTH"
scene.display.shading.curvature_ridge_factor = 1.25
scene.display.shading.curvature_valley_factor = 1.0
scene.display.shading.cavity_ridge_factor = 1.1
scene.display.shading.cavity_valley_factor = 1.0
scene.display.shading.show_specular_highlight = True
scene.display.shading.background_type = "WORLD"
scene.world = bpy.data.worlds.new("Iceland studio background")
scene.world.color = (0.12, 0.15, 0.19)
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "Medium High Contrast"
scene.display.render_aa = "16"

meshes = {}
materials = {}
images = {}
checks = []
temp = ROOT / "diagnostics" / "blender_import.glb"


def import_direct(document, binary, source):
    """Read the same GLB accessors, sharing source meshes before creating objects.

    This avoids constructing and then deleting thousands of duplicate meshes.
    All resulting level bounds are independently checked below.
    """
    def read_accessor(index):
        attr = document["accessors"][index]
        view = document["bufferViews"][attr["bufferView"]]
        dtype = {5126: "<f4", 5125: "<u4", 5123: "<u2"}[attr["componentType"]]
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[attr["type"]]
        assert "byteStride" not in view
        return np.frombuffer(binary, dtype=dtype, count=attr["count"] * width,
                             offset=view.get("byteOffset", 0) + attr.get("byteOffset", 0)).reshape(-1, width)

    def texture_image(index, non_color=False):
        image_info = document["images"][document["textures"][index]["source"]]
        if "uri" in image_info:
            from urllib.parse import unquote
            filename = (source.parent / unquote(image_info["uri"])).resolve()
        else:
            view = document["bufferViews"][image_info["bufferView"]]
            start, size = view.get("byteOffset",0), view["byteLength"]
            blob = binary[start:start+size]
            filename = ROOT / "textures" / (hashlib.sha256(blob).hexdigest()[:20] + ".png")
            filename.parent.mkdir(exist_ok=True)
            if not filename.exists():
                filename.write_bytes(blob)
        if not filename.exists():
            return None
        key = str(filename), non_color
        if key not in images:
            image = bpy.data.images.load(str(filename), check_existing=False)
            image.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
            images[key] = image
        return images[key]

    local_materials = []
    if WITH_MATERIALS:
        for definition in document.get("materials", []):
            key = definition.get("extras", {}).get("unrealMaterialPath") or definition.get("name", "material")
            if key in materials:
                local_materials.append(materials[key])
                continue
            material = bpy.data.materials.new(definition.get("name", "Iceland material"))
            material["unrealMaterialPath"] = key
            material.use_nodes = True
            nodes, links = material.node_tree.nodes, material.node_tree.links
            shader = nodes.get("Principled BSDF")
            pbr = definition.get("pbrMetallicRoughness", {})
            color = pbr.get("baseColorFactor", [0.65,0.65,0.65,1])
            shader.inputs["Base Color"].default_value = color
            material.diffuse_color = color
            shader.inputs["Metallic"].default_value = pbr.get("metallicFactor",0)
            shader.inputs["Roughness"].default_value = pbr.get("roughnessFactor",0.65)
            if "baseColorTexture" in pbr:
                image = texture_image(pbr["baseColorTexture"]["index"])
                if image:
                    node = nodes.new("ShaderNodeTexImage")
                    node.image = image
                    node.location = (-500,160)
                    links.new(node.outputs["Color"], shader.inputs["Base Color"])
                    nodes.active = node
            if "normalTexture" in definition:
                image = texture_image(definition["normalTexture"]["index"],True)
                if image:
                    node = nodes.new("ShaderNodeTexImage")
                    node.image = image
                    node.location = (-700,-100)
                    normal = nodes.new("ShaderNodeNormalMap")
                    normal.location = (-350,-100)
                    links.new(node.outputs["Color"],normal.inputs["Color"])
                    links.new(normal.outputs["Normal"],shader.inputs["Normal"])
            if "metallicRoughnessTexture" in pbr:
                image = texture_image(pbr["metallicRoughnessTexture"]["index"],True)
                if image:
                    node = nodes.new("ShaderNodeTexImage")
                    node.image = image
                    separate = nodes.new("ShaderNodeSeparateColor")
                    links.new(node.outputs["Color"],separate.inputs["Color"])
                    links.new(separate.outputs["Green"],shader.inputs["Roughness"])
                    links.new(separate.outputs["Blue"],shader.inputs["Metallic"])
            materials[key] = material
            local_materials.append(material)

    local_meshes = []
    for source_mesh in document["meshes"]:
        key = source_mesh["extras"]["unrealAssetPath"]
        if key in meshes:
            local_meshes.append(meshes[key])
            continue
        primitive = source_mesh["primitives"][0]
        positions = read_accessor(primitive["attributes"]["POSITION"])
        coords = positions[:, [0, 2, 1]].copy()
        coords[:, 1] *= -1
        indices = np.concatenate([read_accessor(p["indices"]).ravel() for p in source_mesh["primitives"]]).astype(np.int32)
        chosen_vertices = None
        if key.endswith("SM_WaterPlan_50cm.SM_WaterPlan_50cm") and np.ptp(coords[:,2]) < 0.0001:
            # This shader tessellation grid is exactly planar. A four-corner
            # representation preserves both its surface and affine UVs, while
            # avoiding 19 million redundant vertices across the ocean tiles.
            uv_source = read_accessor(primitive["attributes"]["TEXCOORD_0"])
            design = np.column_stack((coords[:,:2],np.ones(len(coords))))
            fitted = design @ np.linalg.lstsq(design,uv_source,rcond=None)[0]
            lo,hi = coords.min(axis=0),coords.max(axis=0)
            corners = np.array([[lo[0],lo[1]],[hi[0],lo[1]],[hi[0],hi[1]],[lo[0],hi[1]]])
            selected = np.array([np.argmin(np.sum((coords[:,:2]-point)**2,axis=1)) for point in corners])
            if np.max(np.abs(fitted-uv_source)) < 0.0003 and np.max(np.abs(coords[selected,:2]-corners)) < 0.0001:
                triangle = coords[indices[:3]]
                sign = np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])[2]
                chosen_vertices = selected
                coords = coords[selected]
                indices = np.array([0,1,2,0,2,3] if sign>0 else [0,2,1,0,3,2],dtype=np.int32)
        data = bpy.data.meshes.new(source_mesh["name"])
        data["unrealAssetPath"] = key
        if chosen_vertices is not None:
            data["planar_water_original_vertices"] = len(positions)
            data["planar_water_uv_error_max"] = float(np.max(np.abs(fitted-uv_source)))
        data.vertices.add(len(coords))
        data.vertices.foreach_set("co", coords.ravel())
        data.loops.add(len(indices))
        data.loops.foreach_set("vertex_index", indices)
        triangles = len(indices) // 3
        data.polygons.add(triangles)
        data.polygons.foreach_set("loop_start", np.arange(triangles, dtype=np.int32) * 3)
        data.polygons.foreach_set("loop_total", np.full(triangles, 3, dtype=np.int32))
        data.polygons.foreach_set("use_smooth", np.ones(triangles, dtype=np.bool_))
        data.update()
        if WITH_MATERIALS:
            if "COLOR_0" in primitive["attributes"]:
                colors=read_accessor(primitive["attributes"]["COLOR_0"])
                if chosen_vertices is not None:colors=colors[chosen_vertices]
                layer=data.color_attributes.new(name="UEVertexColor",type="FLOAT_COLOR",domain="CORNER")
                layer.data.foreach_set("color",colors[indices].ravel())
            elif source_mesh.get("extras",{}).get("unrealVertexColorState")=="default_white":
                layer=data.color_attributes.new(name="UEVertexColor",type="FLOAT_COLOR",domain="CORNER")
                layer.data.foreach_set("color",np.ones(len(indices)*4,dtype=np.float32))
            for uv_key in sorted(k for k in primitive["attributes"] if k.startswith("TEXCOORD_")):
                channel=int(uv_key.rsplit("_",1)[-1])
                uv = read_accessor(primitive["attributes"][uv_key]).copy()
                if chosen_vertices is not None:
                    uv = uv[chosen_vertices]
                uv[:,1] = 1 - uv[:,1]
                layer = data.uv_layers.new(name="UVMap" if channel==0 else f"UV{channel}")
                layer.data.foreach_set("uv", uv[indices].ravel())
            face_slots = []
            for item in source_mesh["primitives"]:
                material_index = item.get("material")
                if material_index is None or material_index >= len(local_materials):
                    material_index = 0
                if local_materials:
                    slot = len(data.materials)
                    data.materials.append(local_materials[material_index])
                    face_slots.extend([slot] * (len(indices)//3 if chosen_vertices is not None else len(read_accessor(item["indices"])) // 3))
            if face_slots:
                data.polygons.foreach_set("material_index", np.array(face_slots,dtype=np.int32))
        if "NORMAL" in primitive["attributes"]:
            normals = read_accessor(primitive["attributes"]["NORMAL"])[:, [0, 2, 1]].copy()
            if chosen_vertices is not None:
                normals = normals[chosen_vertices]
            normals[:, 1] *= -1
            data.normals_split_custom_set_from_vertices(normals)
        local_meshes.append(data)
        meshes[key] = data
    objects = []
    water_batches = {}
    basis = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))

    def walk(index, parent):
        node = document["nodes"][index]
        if "matrix" in node:
            local = Matrix(np.array(node["matrix"]).reshape(4, 4).T.tolist())
        else:
            assert not any(k in node for k in ("translation", "rotation", "scale"))
            local = Matrix.Identity(4)
        world = parent @ local
        if "mesh" in node:
            source_mesh = local_meshes[node["mesh"]]
            if source_mesh.get("unrealAssetPath","").endswith("SM_WaterPlan_50cm.SM_WaterPlan_50cm") and len(source_mesh.vertices)==4:
                water_batches.setdefault(node["mesh"],[]).append(np.array(basis @ world @ basis.inverted(),dtype=np.float64))
                return
            obj = bpy.data.objects.new(node.get("name", "Iceland mesh"), source_mesh)
            scene.collection.objects.link(obj)
            obj.matrix_world = basis @ world @ basis.inverted()
            objects.append(obj)
        for child in node.get("children", []):
            walk(child, world)

    for index in document["scenes"][document.get("scene", 0)]["nodes"]:
        walk(index, Matrix.Identity(4))
    for mesh_index, transforms in water_batches.items():
        template = local_meshes[mesh_index]
        matrices = np.array(transforms)
        vertices = np.empty(len(template.vertices)*3,dtype=np.float32)
        template.vertices.foreach_get("co",vertices)
        vertices = vertices.reshape(-1,3)
        coordinates = np.einsum("nij,kj->nki",matrices[:,:3,:3],vertices)+matrices[:,None,:3,3]
        base_indices = np.empty(len(template.loops),dtype=np.int32)
        template.loops.foreach_get("vertex_index",base_indices)
        all_indices = (base_indices[None,:]+np.arange(len(matrices))[:,None]*len(vertices)).astype(np.int32).ravel()
        data = bpy.data.meshes.new("Iceland planar ocean tiles")
        data["unrealAssetPath"] = template["unrealAssetPath"]+"#baked_planar_water"
        data["original_source_asset"] = template["unrealAssetPath"]
        data["source_instances"] = len(matrices)
        data.vertices.add(coordinates.size//3)
        data.vertices.foreach_set("co",coordinates.astype(np.float32).ravel())
        data.loops.add(len(all_indices))
        data.loops.foreach_set("vertex_index",all_indices)
        triangles = len(all_indices)//3
        data.polygons.add(triangles)
        data.polygons.foreach_set("loop_start",np.arange(triangles,dtype=np.int32)*3)
        data.polygons.foreach_set("loop_total",np.full(triangles,3,dtype=np.int32))
        for material in template.materials:
            data.materials.append(material)
        if template.uv_layers:
            uv = np.empty(len(template.loops)*2,dtype=np.float32)
            template.uv_layers.active.data.foreach_get("uv",uv)
            data.uv_layers.new(name="UVMap").data.foreach_set("uv",np.tile(uv,len(matrices)))
        data.update()
        obj = bpy.data.objects.new("Iceland ocean tiles (equivalent planar surface)",data)
        scene.collection.objects.link(obj)
        objects.append(obj)
        log(f"Merged {len(matrices)} coplanar ocean tiles with identical surface/UV boundaries")
    return objects


palette = {"geometry": (0.60, 0.66, 0.69, 1), "interiors": (0.64, 0.69, 0.72, 1),
           "decorations": (0.56, 0.61, 0.64, 1), "supplement": (0.65, 0.69, 0.72, 1), "structures": (0.60,0.66,0.69,1), "radar_supports":(0.6,0.66,0.69,1), "common_towers":(0.6,0.66,0.69,1), "common_static":(0.6,0.66,0.69,1)}
for group in ("geometry", "interiors", "decorations", "supplement", "structures", "common_towers", "common_static"):
    split = ROOT / group / "split"
    if not (split / "manifest.json").exists():
        continue
    manifest = json.loads((split / "manifest.json").read_text(encoding="utf-8-sig"))
    collection = bpy.data.collections.new(group)
    scene.collection.children.link(collection)
    for li, entry in enumerate(manifest["levels"]):
        source = split / entry["glb"]
        raw = source.read_bytes()
        jl = struct.unpack_from("<I", raw, 12)[0]
        document = json.loads(raw[20:20 + jl])
        for mesh in document.get("meshes", []):
            asset = mesh["name"]
            mesh["name"] = "DFM_" + hashlib.sha256(asset.encode()).hexdigest()[:20]
            mesh.setdefault("extras", {})["unrealAssetPath"] = asset
            if not WITH_MATERIALS:
                for primitive in mesh["primitives"]:
                    primitive.pop("material", None)
        if not WITH_MATERIALS:
            document.pop("materials", None)
        encoded = json.dumps(document, separators=(",", ":")).encode()
        encoded += b" " * (-len(encoded) % 4)
        binary_chunk = raw[20 + jl:]
        temp.write_bytes(struct.pack("<III", 0x46546C67, 2, 20 + len(encoded) + len(binary_chunk))
                         + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded + binary_chunk)
        if "--direct" in sys.argv:
            imported = import_direct(document, raw[28 + jl:], source)
        else:
            before = set(bpy.data.objects)
            bpy.ops.import_scene.gltf(filepath=str(temp), import_pack_images=False)
            imported = [o for o in bpy.data.objects if o not in before]
        lower, upper = np.full(3, np.inf), np.full(3, -np.inf)
        for obj in imported:
            for existing in list(obj.users_collection):
                existing.objects.unlink(obj)
            collection.objects.link(obj)
            if obj.type != "MESH":
                continue
            key = obj.data.get("unrealAssetPath")
            if key in meshes and meshes[key] != obj.data:
                duplicate = obj.data
                obj.data = meshes[key]
                if duplicate.users == 0:
                    bpy.data.meshes.remove(duplicate)
            else:
                meshes[key] = obj.data
            obj.color = palette[group]
            obj["source_level"] = entry["level"]
            vertices = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
            obj.data.vertices.foreach_get("co", vertices)
            matrix = np.array(obj.matrix_world, dtype=np.float64)
            world = vertices.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
            if len(world):
                lower = np.minimum(lower, world.min(axis=0))
                upper = np.maximum(upper, world.max(axis=0))
        expected_lo = np.array(entry["ueBoundsMin"]) / 100
        expected_hi = np.array(entry["ueBoundsMax"]) / 100
        expected_lo[1], expected_hi[1] = -expected_hi[1], -expected_lo[1]
        delta = float(max(np.max(np.abs(lower - expected_lo)), np.max(np.abs(upper - expected_hi))))
        checks.append({"group": group, "level": entry["level"], "objects": sum(o.type == "MESH" for o in imported), "bounds_delta_m": delta})
        if delta > 0.05:
            raise RuntimeError(f"Misplaced level {entry['level']}: {delta} m")
        if li % 20 == 0:
            log(f"Imported {group} {li + 1}/{len(manifest['levels'])}; unique meshes {len(meshes)}")
    log(f"Finished {group}")

# Additive base/HD layers can repeat the very same placement. The per-level
# bounds above are checked before removing repeated objects across roots.
placements = {}
duplicate_count = 0
duplicates_to_remove = []
for obj in list(scene.objects):
    if obj.type != "MESH":
        continue
    key = (obj.data.get("unrealAssetPath"), tuple(round(float(v),4 if column<3 else 3)
           for row in obj.matrix_world for column,v in enumerate(row)))
    if key in placements:
        duplicates_to_remove.append(obj)
        duplicate_count += 1
    else:
        placements[key] = obj
if duplicates_to_remove:
    bpy.data.batch_remove(ids=duplicates_to_remove)
log(f"Removed {duplicate_count} repeated placements across source layers")

# The CDLOD mesh comes entirely from stored height samples and visibility bits.
terrain = np.load(ROOT / "terrain.npz")
heights = terrain["height"]
rows, cols = heights.shape
x0, y0, step = float(terrain["x0"]), float(terrain["y0"]), float(terrain["step"])
xx, yy = np.meshgrid(x0 + np.arange(cols) * step, -(y0 + np.arange(rows) * step))
coords = np.column_stack((xx.ravel(), yy.ravel(), heights.ravel())).astype(np.float32)
grid = np.arange(rows * cols, dtype=np.int32).reshape(rows, cols)
a, b, c, d = grid[:-1, :-1], grid[1:, :-1], grid[:-1, 1:], grid[1:, 1:]
faces = np.stack((np.stack((a, b, c), axis=-1), np.stack((c, b, d), axis=-1)), axis=-2)
faces = faces[terrain["visible"]].reshape(-1, 3)
mesh = bpy.data.meshes.new("Iceland CDLOD heightfield 4m")
mesh.vertices.add(len(coords))
mesh.vertices.foreach_set("co", coords.ravel())
mesh.loops.add(faces.size)
mesh.loops.foreach_set("vertex_index", faces.ravel())
mesh.polygons.add(len(faces))
mesh.polygons.foreach_set("loop_start", np.arange(len(faces), dtype=np.int32) * 3)
mesh.polygons.foreach_set("loop_total", np.full(len(faces), 3, dtype=np.int32))
mesh.polygons.foreach_set("use_smooth", np.ones(len(faces), dtype=np.bool_))
mesh.update()
obj = bpy.data.objects.new("Iceland — source CDLOD terrain", mesh)
obj["source"] = "BuildMaps_HD/Iceland/Runtime/LandscapeCDLOD"
obj["sample_spacing_m"] = step
obj.color = (0.30, 0.36, 0.39, 1)
scene.collection.objects.link(obj)
log(f"Terrain: {len(coords)} vertices; {len(faces)} triangles")
del coords, faces, grid, xx, yy

camera_data = bpy.data.cameras.new("Iceland inspection camera")
camera = bpy.data.objects.new("Iceland inspection camera", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
camera_data.type = "ORTHO"
camera_data.clip_start = 1
camera_data.clip_end = 100000


def aim(position, target, scale):
    camera.location = position
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.ortho_scale = scale


summary = {"blender_version": bpy.app.version_string,
           "axis": "UE(x,-y,z)/100, metres, Z-up",
           "levels": len(checks), "mesh_objects": sum(o.type == "MESH" for o in scene.objects),
           "unique_source_meshes": len(meshes), "terrain_vertices": len(mesh.vertices),
           "terrain_triangles": len(mesh.polygons),
           "maximum_bounds_delta_m": max(x["bounds_delta_m"] for x in checks),
           "material_mode": "decoded game base-color and normal textures" if WITH_MATERIALS else "geometry inspection colours",
           "materials":len(materials), "images":len(images), "duplicates_removed":duplicate_count,
           "checks": checks}
(ROOT / "diagnostics" / "blender_validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
aim((5000, -1700, 3900), (2016, 2100, -70), 4800)
scene.render.resolution_x = 1800
scene.render.resolution_y = 1400
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.clip_end = 100000
            area.spaces.active.region_3d.view_distance = 3500
            area.spaces.active.region_3d.view_location = (2016, 2100, -50)
            area.spaces.active.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
            area.spaces.active.shading.type = "SOLID"
            area.spaces.active.shading.color_type = "TEXTURE" if WITH_MATERIALS else "OBJECT"
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT / "Iceland.blend"), compress=True)
if "--no-render" in sys.argv:
    raise SystemExit(0)
for name, position, target, scale, resolution in [
    ("Iceland_overview", (5000, -1700, 3900), (2016, 2100, -70), 4800, (1800, 1400)),
    ("Iceland_top", (2016, 2016, 6000), (2016, 2016, 0), 4250, (1800, 1800)),
    ("Iceland_detail", (3100, 1400, 1100), (2110, 2200, -30), 1650, (1800, 1200)),
]:
    aim(position, target, scale)
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.filepath = str(ROOT / (name + ".png"))
    log(f"Rendering {name}")
    bpy.ops.render.render(write_still=True)
log("Saved Blender project and three inspection images")
