"""Validate, export, and bake an authored proxy/card pair together.

No geometry is constructed and the source blend/art are never saved or edited.
The CLI requires all three outputs so exporting cannot leave an old receiver map.
Use --quality fast for the edit loop; review also renders volume/side shadows.
See README.md for complete asset commands.
"""

from pathlib import Path
import argparse
import json
import sys
import tempfile
import shutil

import bpy
import bmesh

sys.path.insert(0, str(Path(__file__).resolve().parent))


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
    parser.add_argument("--card", required=True)
    parser.add_argument("--card-output", required=True)
    parser.add_argument("--surface-output", required=True, help="Validate, export, and bake together")
    parser.add_argument("--art", required=True, help="Source PNG for coverage validation")
    parser.add_argument("--pixels-x", type=int, required=True)
    parser.add_argument("--pixels-y", type=int, required=True)
    parser.add_argument("--quality", choices=("fast", "review"), default="review")
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


def export_and_bake(proxy, proxy_output, card, card_output, art, surface_output,
                    pixels_x, pixels_y, expected_shells=1, quality="review"):
    """Stage the full pipeline; publish outputs only when validation/baking pass.

    Coverage is checked on the live objects. The bake consumes the staged GLBs,
    so the receiver plane, pivot, normals, and proxy always match the export.
    """
    from render_proxy_validation import validate_asset
    from bake_proxy_surface_maps import bake_surface_map
    if not all((card, card_output, art, pixels_x, pixels_y)):
        raise ValueError("Baking requires --card, --card-output, --art, --pixels-x and --pixels-y")
    destinations = [project_path(p).resolve() for p in (proxy_output, card_output, surface_output)]
    sources = {Path(bpy.data.filepath).resolve(), project_path(art).resolve()}
    if len(set(destinations)) != 3 or sources.intersection(destinations):
        raise ValueError("Output files must be distinct and must not overwrite source art or blend files")
    if [p.suffix.lower() for p in destinations] != ['.glb', '.glb', '.png']:
        raise ValueError("Outputs must be proxy.glb, card.glb and surface.png")
    obj = bpy.data.objects[card]
    # Hidden source objects may not have evaluated world matrices yet.
    old_visibility = (obj.hide_viewport, obj.hide_get())
    try:
        obj.hide_viewport = False
        obj.hide_set(False)
        bpy.context.view_layer.update()
        points = [obj.matrix_world @ v.co for v in obj.data.vertices]
        width = max(p.x for p in points) - min(p.x for p in points)
        height = max(p.z for p in points) - min(p.z for p in points)
        validation = validate_asset(proxy, art, card, width, height,
                                    expected_shells=expected_shells, quality=quality)
    finally:
        obj.hide_viewport, hidden = old_visibility
        obj.hide_set(hidden)
    if not validation['passed']:
        raise ValueError("Asset validation failed: " + "; ".join(validation['failures'])
                         + ". Review: " + validation['output_directory'])
    with tempfile.TemporaryDirectory(prefix="shadow-asset-export-") as temporary:
        staging = Path(temporary)
        proxy_path, card_path, surface_path = [staging / name for name in ('proxy.glb', 'card.glb', 'surface.png')]
        export_asset(proxy, str(proxy_path), expected_shells, card, str(card_path))
        bake = bake_surface_map(proxy_path, card_path, surface_path, pixels_x, pixels_y)
        for source, destination in zip((proxy_path, card_path, surface_path), destinations):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    bake.update(proxy_glb=str(destinations[0]), card_glb=str(destinations[1]), output=str(destinations[2]))
    return dict(validation=validation, bake=bake)


if __name__ == "__main__":
    args = script_arguments()
    blend = project_path(args.blend)
    if Path(bpy.data.filepath) != blend:
        bpy.ops.wm.open_mainfile(filepath=str(blend))
    result = export_and_bake(
        args.proxy, args.proxy_output, args.card, args.card_output, args.art,
        args.surface_output, args.pixels_x, args.pixels_y, args.expected_shells, args.quality)
    print("SHADOW_ASSET_EXPORT_RESULT=" + json.dumps(result, sort_keys=True))
