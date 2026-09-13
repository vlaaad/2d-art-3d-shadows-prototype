"""Validate and export one authored proxy/card pair from any Blender file.

This script deliberately contains no geometry construction or asset names.
After validating the live mesh, run:

    blender --background --python tools/export_shadow_assets.py -- \
      --blend <asset.blend> --proxy <object> --proxy-output <proxy.glb> \
      --expected-shells <count> --card <object> --card-output <card.glb>
"""

from pathlib import Path
import argparse
import json
import sys

import bpy
import bmesh


ROOT = Path(__file__).resolve().parents[1]


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def script_arguments():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blend", required=True)
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--proxy-output", required=True)
    parser.add_argument("--expected-shells", type=int, default=1)
    parser.add_argument("--card")
    parser.add_argument("--card-output")
    return parser.parse_args(values)


def validate_proxy(obj: bpy.types.Object, expected_components: int) -> None:
    if obj.type != "MESH":
        raise RuntimeError(f"{obj.name} must be a mesh")
    slots = [material.name if material else None for material in obj.data.materials]
    if slots != ["proxy"]:
        raise RuntimeError(f"{obj.name} must have exactly one material slot named 'proxy'; got {slots}")

    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    unseen = set(mesh.verts)
    component_count = 0
    while unseen:
        component_count += 1
        stack = [unseen.pop()]
        while stack:
            vertex = stack.pop()
            for edge in vertex.link_edges:
                neighbor = edge.other_vert(vertex)
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
    non_manifold_edges = sum(1 for edge in mesh.edges if not edge.is_manifold)
    mesh.free()

    if component_count != expected_components:
        raise RuntimeError(
            f"{obj.name} has {component_count} disconnected shells; expected {expected_components}. "
            "Unify accidental overlaps/pockets in Blender before export."
        )
    if non_manifold_edges:
        raise RuntimeError(f"{obj.name} has {non_manifold_edges} non-manifold edges")


def export_object(obj: bpy.types.Object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    old_hide_viewport = obj.hide_viewport
    old_hide_render = obj.hide_render
    old_hidden = obj.hide_get()
    obj.hide_viewport = False
    obj.hide_render = False
    obj.hide_set(False)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    # The Automation Bridge invokes Blender without an area/region context.
    # Supply the selection explicitly so this works in that persistent instance
    # as well as from ``blender --background``.
    window = bpy.context.window or bpy.context.window_manager.windows[0]
    area = next(candidate for candidate in window.screen.areas if candidate.type == "VIEW_3D")
    region = next(candidate for candidate in area.regions if candidate.type == "WINDOW")
    try:
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
                # Defold binds the source PNG separately in the .model resource.
                # Embedding a validation texture here silently duplicates it and
                # can make a four-vertex card larger than its actual artwork.
                export_image_format="NONE",
            )
    finally:
        obj.hide_viewport = old_hide_viewport
        obj.hide_render = old_hide_render
        obj.hide_set(old_hidden)


def export_asset(proxy: str, proxy_output: str, expected_shells: int = 1,
                 card: str | None = None, card_output: str | None = None):
    proxy_object = bpy.data.objects[proxy]
    validate_proxy(proxy_object, expected_shells)
    proxy_path = project_path(proxy_output)
    export_object(proxy_object, proxy_path)
    result = {"proxy": str(proxy_path), "expected_shells": expected_shells}
    if card or card_output:
        if not card or not card_output:
            raise RuntimeError("--card and --card-output must be provided together")
        card_path = project_path(card_output)
        export_object(bpy.data.objects[card], card_path)
        result["card"] = str(card_path)
    return result


if __name__ == "__main__":
    args = script_arguments()
    blend = project_path(args.blend)
    if Path(bpy.data.filepath) != blend:
        bpy.ops.wm.open_mainfile(filepath=str(blend))
    result = export_asset(
        proxy=args.proxy,
        proxy_output=args.proxy_output,
        expected_shells=args.expected_shells,
        card=args.card,
        card_output=args.card_output,
    )
    print("SHADOW_ASSET_EXPORT_RESULT=" + json.dumps(result, sort_keys=True))
