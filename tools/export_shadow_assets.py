"""Export authored cards and proxies from the canonical Blender file.

This script deliberately contains no geometry construction. Edit the named
objects in ``assets/proxies/shadow_proxies.blend`` with Blender, validate their
silhouettes, then run:

    blender --background --python tools/export_shadow_assets.py
"""

from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
BLEND = ROOT / "assets" / "proxies" / "shadow_proxies.blend"
MESH_OUT = ROOT / "assets" / "meshes"

EXPORTS = {
    "tree_proxy": "tree_proxy.glb",
    "character_proxy": "character_proxy.glb",
    "grass_proxy": "grass_proxy.glb",
    "tree_card": "tree_card.glb",
    "character_card": "character_card.glb",
    "grass_card": "grass_card.glb",
}


def export_object(obj: bpy.types.Object, output: Path) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    # The Automation Bridge invokes Blender without an area/region context.
    # Supply the selection explicitly so this works in that persistent instance
    # as well as from ``blender --background``.
    window = bpy.context.window or bpy.context.window_manager.windows[0]
    area = next(candidate for candidate in window.screen.areas if candidate.type == "VIEW_3D")
    region = next(candidate for candidate in area.regions if candidate.type == "WINDOW")
    with bpy.context.temp_override(
        window=window,
        screen=window.screen,
        area=area,
        region=region,
        active_object=obj,
        object=obj,
        selected_objects=[obj],
        selected_editable_objects=[obj],
    ):
        bpy.ops.export_scene.gltf(
            filepath=str(output),
            export_format="GLB",
            use_selection=True,
            export_apply=True,
            export_yup=True,
        )


bpy.ops.wm.open_mainfile(filepath=str(BLEND))
MESH_OUT.mkdir(parents=True, exist_ok=True)
for object_name, filename in EXPORTS.items():
    export_object(bpy.data.objects[object_name], MESH_OUT / filename)
