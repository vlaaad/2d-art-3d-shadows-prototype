"""Generate the textured cards used by the 2.5D prototype.

Run with: blender --background --python tools/generate_proxy_meshes.py

Art cards and shadow proxies are authored in Blender and exported by
``export_shadow_assets.py``. This script only builds the generic ground quad.
"""

from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "meshes"


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def material(name):
    value = bpy.data.materials.get(name)
    if value is None:
        value = bpy.data.materials.new(name)
    return value


def export_selected(filename):
    OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(OUT / filename),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
    )


def make_quad(filename, width=1.0, height=1.0, horizontal=False, uv_tiles=(1.0, 1.0)):
    reset_scene()
    half_width = width * 0.5
    if horizontal:
        half_height = height * 0.5
        vertices = [
            (-half_width, -half_height, 0),
            (half_width, -half_height, 0),
            (half_width, half_height, 0),
            (-half_width, half_height, 0),
        ]
    else:
        vertices = [
            (-half_width, 0, 0),
            (half_width, 0, 0),
            (half_width, 0, height),
            (-half_width, 0, height),
        ]
    mesh = bpy.data.meshes.new(filename)
    mesh.from_pydata(vertices, [], [(0, 1, 2, 3)])
    mesh.materials.append(material("art"))
    uv_layer = mesh.uv_layers.new(name="UVMap")
    u_tiles, v_tiles = uv_tiles
    uv_by_vertex = ((0, 0), (u_tiles, 0), (u_tiles, v_tiles), (0, v_tiles))
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uv_by_vertex[loop.vertex_index]
    obj = bpy.data.objects.new(filename, mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    export_selected(filename)


make_quad("art_quad.glb")
make_quad("ground_quad.glb", width=20.0, height=20.0, horizontal=True, uv_tiles=(5.0, 5.0))
