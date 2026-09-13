"""Render authored proxy alignment views from the editable Blender source.

Run against any authored asset with:

    blender --background --python tools/render_proxy_validation.py -- \
      --proxy <object> --art <png> --reference <art-object> \
      --width <world-width> --height <world-height>

The module's ``validate_asset()`` function can also be called in the persistent
Blender MCP session, validating an unsaved live mesh without export or Defold.
"""

from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import bpy
import bmesh
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLEND = ROOT / "assets" / "proxies" / "shadow_proxies.blend"
OUT = None
LAYOUT_RESOLUTION = 384
PREVIEW_RESOLUTION = 320
CACHE_VERSION = 2
CACHE = Path(tempfile.gettempdir()) / "defold-proxy-validation-cache"


def project_path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def script_arguments():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(
        description="Render source-art/proxy coverage, contact, volume, and side-shadow validation for one asset."
    )
    parser.add_argument("--blend", default=str(DEFAULT_BLEND), help="Blend file containing the authored proxy")
    parser.add_argument("--proxy", required=True, help="Export proxy object name")
    parser.add_argument("--art", required=True, help="Transparent source-art path, absolute or project-relative")
    parser.add_argument("--reference", required=True, help="Blender source-art reference object name")
    parser.add_argument("--width", required=True, type=float, help="Art card width in world units")
    parser.add_argument("--height", required=True, type=float, help="Art card height in world units")
    parser.add_argument("--stem", help="Output filename stem; defaults to the proxy name without _proxy")
    parser.add_argument("--light-span", type=float, help="Absolute X position for the two side lights")
    parser.add_argument("--output", help="Output directory; defaults to a new temporary directory")
    parser.add_argument("--quality", choices=("fast", "review"), default="fast")
    parser.add_argument("--expected-shells", type=int, default=1, help="Expected disconnected watertight shells")
    parser.add_argument("--min-art-coverage", type=float, default=0.90, help="Minimum opaque-art fraction covered by the proxy")
    parser.add_argument("--min-contact-coverage", type=float, default=0.95, help="Minimum contact-region opaque-art fraction covered by the proxy")
    parser.add_argument("--max-proxy-spill", type=float, default=0.20, help="Maximum proxy fraction outside opaque art")
    parser.add_argument("--max-contact-spill", type=float, default=0.13, help="Maximum contact-region proxy fraction outside art")
    return parser.parse_args(values)


def point_camera(camera, location, target):
    camera.location = location
    camera.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()


def hide_everything():
    for obj in bpy.context.scene.objects:
        obj.hide_render = True


def proxy_object(name):
    return bpy.data.objects[name]


def ensure_area_light():
    light_data = bpy.data.lights.get("VALIDATION_KEY") or bpy.data.lights.new("VALIDATION_KEY", "AREA")
    light = bpy.data.objects.get("VALIDATION_KEY") or bpy.data.objects.new("VALIDATION_KEY", light_data)
    if not light.users_collection:
        bpy.context.scene.collection.objects.link(light)
    light.data.energy = 900.0
    light.data.shape = "DISK"
    light.data.size = 5.0
    light.location = (-4.0, -6.0, 8.0)
    light.hide_render = False
    return light


def ensure_game_camera(target_width, target_height):
    """Match the direction of main/camera.go, reframed around one asset."""
    camera_data = bpy.data.cameras.get("VALIDATION_GAME_CAMERA") or bpy.data.cameras.new("VALIDATION_GAME_CAMERA")
    camera = bpy.data.objects.get("VALIDATION_GAME_CAMERA") or bpy.data.objects.new("VALIDATION_GAME_CAMERA", camera_data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    # Render previews are square; frame by the larger world dimension so wide
    # assets such as fences are never clipped or validated with fake heights.
    camera.data.ortho_scale = max(target_width, target_height) * 1.28
    # Defold (x, y-up, z-ground) maps to Blender (x, -z, y-up).
    # Keep the exact vector from camera (0, 7.8, 10.5) to target
    # (0, 1.25, 0), while only translating the framing target.
    target = Vector((0.0, 0.0, target_height * 0.47))
    camera_offset = Vector((0.0, -10.5, 6.55))
    point_camera(camera, target + camera_offset, target)
    camera.hide_render = False
    return camera


def overlay_material():
    value = bpy.data.materials.get("VALIDATION_PROXY_BLUE") or bpy.data.materials.new("VALIDATION_PROXY_BLUE")
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (0.025, 0.32, 1.0, 1.0)
    shader.inputs["Roughness"].default_value = 0.68
    shader.inputs["Metallic"].default_value = 0.0
    return value


def marker_material():
    value = bpy.data.materials.get("VALIDATION_PIVOT_RED") or bpy.data.materials.new("VALIDATION_PIVOT_RED")
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (1.0, 0.01, 0.01, 1.0)
    shader.inputs["Emission Color"].default_value = (1.0, 0.0, 0.0, 1.0)
    shader.inputs["Emission Strength"].default_value = 1.5
    return value


def make_pivot_marker(width):
    material = marker_material()
    result = []
    for name, location, scale in (
        ("VALIDATION_GROUND_CONTACT_X", (0.0, 0.0, 0.012), (width * 0.56, 0.018, 0.012)),
        ("VALIDATION_GROUND_CONTACT_Z", (0.0, 0.0, 0.10), (0.014, 0.018, 0.10)),
    ):
        bpy.ops.mesh.primitive_cube_add(location=location)
        obj = bpy.context.view_layer.objects.active
        obj.name = name
        obj.scale = scale
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        obj.data.materials.append(material)
        result.append(obj)
    return result


def render_mismatch(art_path, proxy_path, marker_path, output_path, width, height):
    """Produce an unambiguous alpha-coverage diagnostic.

    Magenta = proxy outside art; yellow = art without proxy; green = overlap.
    Geometry still comes only from the manually authored Blender source.
    """
    stem = output_path.with_suffix("")
    art_mask = Path(str(stem) + "-art-mask.png")
    proxy_mask = Path(str(stem) + "-proxy-mask.png")
    inverse_art = Path(str(stem) + "-inverse-art.png")
    inverse_proxy = Path(str(stem) + "-inverse-proxy.png")
    overlap_mask = Path(str(stem) + "-overlap-mask.png")
    mesh_only_mask = Path(str(stem) + "-mesh-only-mask.png")
    art_only_mask = Path(str(stem) + "-art-only-mask.png")
    base = Path(str(stem) + "-base.png")
    overlap = Path(str(stem) + "-overlap.png")
    mesh_only = Path(str(stem) + "-mesh-only.png")
    art_only = Path(str(stem) + "-art-only.png")
    composite = Path(str(stem) + "-composite.png")

    subprocess.run(["magick", str(art_path), "-alpha", "extract", str(art_mask)], check=True)
    subprocess.run(["magick", str(proxy_path), "-alpha", "extract", str(proxy_mask)], check=True)
    subprocess.run(["magick", str(art_mask), "-negate", str(inverse_art)], check=True)
    subprocess.run(["magick", str(proxy_mask), "-negate", str(inverse_proxy)], check=True)
    subprocess.run(["magick", str(art_mask), str(proxy_mask), "-compose", "multiply", "-composite", str(overlap_mask)], check=True)
    subprocess.run(["magick", str(proxy_mask), str(inverse_art), "-compose", "multiply", "-composite", str(mesh_only_mask)], check=True)
    subprocess.run(["magick", str(art_mask), str(inverse_proxy), "-compose", "multiply", "-composite", str(art_only_mask)], check=True)
    subprocess.run(["magick", str(art_path), "-channel", "A", "-evaluate", "multiply", "0.22", "+channel", str(base)], check=True)
    for color, mask, destination in (
        ("#20e070", overlap_mask, overlap),
        ("#ff00a8", mesh_only_mask, mesh_only),
        ("#ffe600", art_only_mask, art_only),
    ):
        subprocess.run(
            ["magick", "-size", f"{width}x{height}", f"xc:{color}", str(mask), "-alpha", "off", "-compose", "CopyOpacity", "-composite", str(destination)],
            check=True,
        )
    subprocess.run(["magick", str(base), str(overlap), "-compose", "over", "-composite", str(composite)], check=True)
    subprocess.run(["magick", str(composite), str(art_only), "-compose", "over", "-composite", str(composite)], check=True)
    subprocess.run(["magick", str(composite), str(mesh_only), "-compose", "over", "-composite", str(composite)], check=True)
    def mask_mean(path, crop=None):
        command = ["magick", str(path)]
        if crop:
            command.extend(["-crop", crop, "+repage"])
        command.extend(["-format", "%[fx:mean]", "info:"])
        return float(subprocess.run(command, check=True, capture_output=True, text=True).stdout)

    bounds_text = subprocess.run(
        ["magick", str(art_mask), "-trim", "-format", "%@", "info:"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    bounds_match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", bounds_text)
    if bounds_match:
        _bounds_width, bounds_height, _bounds_x, bounds_y = map(int, bounds_match.groups())
        contact_y = max(0, min(height - 1, bounds_y + round(bounds_height * 0.65)))
    else:
        contact_y = round(height * 0.65)
    contact_crop = f"{width}x{height - contact_y}+0+{contact_y}"
    proxy_mean = mask_mean(proxy_mask)
    outside_mean = mask_mean(mesh_only_mask)
    art_mean = mask_mean(art_mask)
    art_only_mean = mask_mean(art_only_mask)
    contact_proxy_mean = mask_mean(proxy_mask, contact_crop)
    contact_outside_mean = mask_mean(mesh_only_mask, contact_crop)
    contact_art_mean = mask_mean(art_mask, contact_crop)
    contact_art_only_mean = mask_mean(art_only_mask, contact_crop)
    metrics = {
        "proxy_outside_art_fraction": outside_mean / max(proxy_mean, 1e-8),
        "contact_proxy_outside_art_fraction": contact_outside_mean / max(contact_proxy_mean, 1e-8),
        "art_covered_by_proxy_fraction": 1.0 - art_only_mean / max(art_mean, 1e-8),
        "contact_art_covered_by_proxy_fraction": 1.0 - contact_art_only_mean / max(contact_art_mean, 1e-8),
    }

    if marker_path:
        subprocess.run(["magick", str(composite), str(marker_path), "-compose", "over", "-composite", str(output_path)], check=True)
    else:
        composite.replace(output_path)
    for temporary in (
        art_mask, proxy_mask, inverse_art, inverse_proxy, overlap_mask,
        mesh_only_mask, art_only_mask, base, overlap, mesh_only, art_only,
    ):
        temporary.unlink(missing_ok=True)
    composite.unlink(missing_ok=True)
    return metrics


def authored_reference(reference_name):
    return bpy.data.objects[reference_name]


def render_game_layout(proxy_name, reference_name, width, height, stem):
    """Render art and proxy at the same origin using the gameplay camera."""
    camera = ensure_game_camera(width, height)
    bpy.context.scene.camera = camera
    ensure_area_light()
    render = bpy.context.scene.render
    render.engine = "BLENDER_EEVEE"
    render.film_transparent = True
    render.resolution_x = LAYOUT_RESOLUTION
    render.resolution_y = LAYOUT_RESOLUTION
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"

    proxy = proxy_object(proxy_name)
    reference = authored_reference(reference_name)
    CACHE.mkdir(parents=True, exist_ok=True)
    image_sources = []
    for material in reference.data.materials:
        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    path = Path(bpy.path.abspath(node.image.filepath))
                    image_sources.append((str(path), path.stat().st_mtime_ns if path.exists() else None))
    cache_data = json.dumps({
        "version": CACHE_VERSION,
        "reference": reference_name,
        "reference_matrix": [round(value, 8) for row in reference.matrix_world for value in row],
        "reference_vertices": [tuple(round(value, 8) for value in vertex.co) for vertex in reference.data.vertices],
        "reference_uvs": [
            tuple(round(value, 8) for value in loop.uv)
            for layer in reference.data.uv_layers
            for loop in layer.data
        ],
        "image_sources": image_sources,
        "width": width,
        "height": height,
        "resolution": render.resolution_x,
    }, sort_keys=True).encode()
    cache_key = hashlib.sha256(cache_data).hexdigest()[:20]
    cached_art = CACHE / f"{cache_key}-art.png"
    cached_marker = CACHE / f"{cache_key}-pivot.png"
    markers = []

    hide_everything()
    proxy.hide_render = False
    camera.hide_render = False
    ensure_area_light()
    old_materials = list(proxy.data.materials)
    proxy.data.materials.clear()
    proxy.data.materials.append(overlay_material())
    proxy_path = OUT / f"{stem}-game-proxy.png"
    render.filepath = str(proxy_path)
    bpy.ops.render.render(write_still=True)
    proxy.data.materials.clear()
    for material in old_materials:
        proxy.data.materials.append(material)

    art_path = OUT / f"{stem}-game-art.png"
    if cached_art.exists():
        shutil.copyfile(cached_art, art_path)
    else:
        hide_everything()
        camera.hide_render = False
        ensure_area_light()
        reference.hide_render = False
        # Validate the actual authored transform that will be exported. Moving
        # the reference here would hide card/bake alignment mistakes.
        render.filepath = str(art_path)
        bpy.ops.render.render(write_still=True)
        shutil.copyfile(art_path, cached_art)

    marker_path = OUT / f"{stem}-game-pivot.png"
    if cached_marker.exists():
        shutil.copyfile(cached_marker, marker_path)
    else:
        markers = make_pivot_marker(width)
        hide_everything()
        camera.hide_render = False
        for marker in markers:
            marker.hide_render = False
        render.filepath = str(marker_path)
        bpy.ops.render.render(write_still=True)
        shutil.copyfile(marker_path, cached_marker)

    translucent_path = OUT / f"{stem}-game-proxy-translucent.png"
    overlay_path = OUT / f"{stem}-game-layout-overlay.png"
    subprocess.run(
        ["magick", str(proxy_path), "-channel", "A", "-evaluate", "multiply", "0.42", "+channel", str(translucent_path)],
        check=True,
    )
    unmarked_path = OUT / f"{stem}-game-layout-unmarked.png"
    subprocess.run(["magick", str(art_path), str(translucent_path), "-compose", "over", "-composite", str(unmarked_path)], check=True)
    subprocess.run(["magick", str(unmarked_path), str(marker_path), "-compose", "over", "-composite", str(overlay_path)], check=True)
    mismatch_path = OUT / f"{stem}-game-layout-mismatch.png"
    metrics = render_mismatch(
        art_path,
        proxy_path,
        marker_path,
        mismatch_path,
        render.resolution_x,
        render.resolution_y,
    )

    # The bottom/contact region is more perceptually important than the crown.
    # Keep a magnified crop as a first-class review artifact and a numeric gate.
    contact_path = OUT / f"{stem}-contact-mismatch.png"
    crop_width = round(render.resolution_x * 0.55)
    crop_height = round(render.resolution_y * 0.30)
    crop_x = round((render.resolution_x - crop_width) * 0.5)
    crop_y = round(render.resolution_y * 0.65)
    subprocess.run(
        [
            "magick", str(mismatch_path),
            "-crop", f"{crop_width}x{crop_height}+{crop_x}+{crop_y}", "+repage",
            "-resize", f"{crop_width * 2}x{crop_height * 2}",
            str(contact_path),
        ],
        check=True,
    )
    metrics_path = OUT / f"{stem}-validation.json"
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n")
    print(f"{stem}: {json.dumps(metrics, sort_keys=True)}")

    translucent_path.unlink()
    unmarked_path.unlink()
    for temporary in (art_path, proxy_path, marker_path, overlay_path):
        temporary.unlink(missing_ok=True)
    for marker in markers:
        data = marker.data
        bpy.data.objects.remove(marker, do_unlink=True)
        if data.users == 0:
            bpy.data.meshes.remove(data)

    return metrics


def render_front(proxy_name, art_path, width, height, stem):
    hide_everything()
    proxy = proxy_object(proxy_name)
    proxy.hide_render = False

    camera_data = bpy.data.cameras.get("VALIDATION_FRONT_CAMERA") or bpy.data.cameras.new("VALIDATION_FRONT_CAMERA")
    camera = bpy.data.objects.get("VALIDATION_FRONT_CAMERA") or bpy.data.objects.new("VALIDATION_FRONT_CAMERA", camera_data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = height
    point_camera(camera, (0.0, -10.0, height * 0.5), (0.0, 0.0, height * 0.5))
    camera.hide_render = False
    ensure_area_light()
    bpy.context.scene.camera = camera

    render = bpy.context.scene.render
    render.engine = "BLENDER_EEVEE"
    render.film_transparent = True
    render.resolution_x = round(width * 200)
    render.resolution_y = round(height * 200)
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    proxy_path = OUT / f"{stem}-proxy-front.png"
    render.filepath = str(proxy_path)
    bpy.ops.render.render(write_still=True)

    overlay_path = OUT / f"{stem}-alignment-overlay.png"
    translucent_path = OUT / f"{stem}-proxy-translucent.png"
    subprocess.run(
        ["magick", str(proxy_path), "-channel", "A", "-evaluate", "multiply", "0.36", "+channel", str(translucent_path)],
        check=True,
    )
    subprocess.run(
        [
            "magick",
            str(ROOT / art_path),
            "-resize",
            f"{render.resolution_x}x{render.resolution_y}!",
            str(translucent_path),
            "-compose",
            "over",
            "-composite",
            str(overlay_path),
        ],
        check=True,
    )
    translucent_path.unlink()


def render_three_quarter(proxy_name, stem, target_width, target_height):
    hide_everything()
    proxy = proxy_object(proxy_name)
    proxy.hide_render = False
    ensure_area_light()
    camera_data = bpy.data.cameras.get("VALIDATION_VOLUME_CAMERA") or bpy.data.cameras.new("VALIDATION_VOLUME_CAMERA")
    camera = bpy.data.objects.get("VALIDATION_VOLUME_CAMERA") or bpy.data.objects.new("VALIDATION_VOLUME_CAMERA", camera_data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(target_width, target_height) * 1.18
    point_camera(camera, (5.8, -7.4, 4.8), (0.0, 0.0, target_height * 0.47))
    camera.hide_render = False
    bpy.context.scene.camera = camera
    render = bpy.context.scene.render
    render.engine = "BLENDER_EEVEE"
    render.film_transparent = False
    bpy.context.scene.world.color = (0.025, 0.035, 0.055)
    render.resolution_x = PREVIEW_RESOLUTION
    render.resolution_y = PREVIEW_RESOLUTION
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    render.filepath = str(OUT / f"{stem}-proxy-volume.png")
    bpy.ops.render.render(write_still=True)


def render_shadow_preview(proxy_name, reference_name, stem, target_width, target_height, light_x):
    """Render the 2D source with a proxy-only side shadow, without Defold."""
    for obj in list(bpy.data.objects):
        if obj.name.startswith("VALIDATION_SHADOW_"):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)

    camera = ensure_game_camera(target_width, target_height)
    bpy.context.scene.camera = camera
    bpy.ops.mesh.primitive_plane_add(size=18, location=(0.0, 0.0, -0.012))
    ground = bpy.context.view_layer.objects.active
    ground.name = "VALIDATION_SHADOW_GROUND"
    ground_material = bpy.data.materials.get("VALIDATION_SHADOW_GROUND_MATERIAL") or bpy.data.materials.new(
        "VALIDATION_SHADOW_GROUND_MATERIAL"
    )
    ground_material.diffuse_color = (0.25, 0.34, 0.16, 1.0)
    ground.data.materials.append(ground_material)

    light_data = bpy.data.lights.new("VALIDATION_SHADOW_SUN", "SUN")
    light_data.energy = 3.0
    light_data.angle = 0.10
    light = bpy.data.objects.new("VALIDATION_SHADOW_SUN", light_data)
    bpy.context.scene.collection.objects.link(light)
    point_camera(light, (light_x, -5.0, 8.0), (0.0, 0.0, 1.4))

    hide_everything()
    camera.hide_render = False
    ground.hide_render = False
    light.hide_render = False
    proxy = proxy_object(proxy_name)
    proxy.hide_render = False
    reference = authored_reference(reference_name)
    reference.hide_render = False
    old_proxy_camera = proxy.visible_camera
    old_reference_shadow = reference.visible_shadow
    proxy.visible_camera = False
    reference.visible_shadow = False

    scene = bpy.context.scene
    render = scene.render
    render.engine = "BLENDER_EEVEE"
    render.film_transparent = False
    render.resolution_x = PREVIEW_RESOLUTION
    render.resolution_y = PREVIEW_RESOLUTION
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    scene.world.color = (0.09, 0.12, 0.07)
    side = "left" if light_x < 0 else "right"
    render.filepath = str(OUT / f"{stem}-shadow-preview-{side}.png")
    bpy.ops.render.render(write_still=True)

    proxy.visible_camera = old_proxy_camera
    reference.visible_shadow = old_reference_shadow
    for obj in (ground, light):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)


def topology(proxy):
    obj = proxy_object(proxy)
    if obj.type != "MESH":
        raise RuntimeError(f"{proxy} must be a mesh")
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
    result = {
        "components": component_count,
        "non_manifold_edges": sum(1 for edge in mesh.edges if not edge.is_manifold),
        "vertices": len(mesh.verts),
        "faces": len(mesh.faces),
        "material_slots": [material.name if material else None for material in obj.data.materials],
    }
    mesh.free()
    return result


def validate_asset(proxy, art, reference, width, height, stem=None, light_span=None, output=None,
                   quality="fast", expected_shells=1, min_art_coverage=0.90,
                   min_contact_coverage=0.95,
                   max_proxy_spill=0.20, max_contact_spill=0.13):
    """Validate one live Blender proxy and return paths/metrics without exporting it."""
    global OUT, LAYOUT_RESOLUTION, PREVIEW_RESOLUTION
    LAYOUT_RESOLUTION, PREVIEW_RESOLUTION = (640, 480) if quality == "review" else (384, 320)
    OUT = Path(output) if output else Path(tempfile.mkdtemp(prefix="defold-proxy-validation-"))
    OUT.mkdir(parents=True, exist_ok=True)
    stem = stem or proxy.removesuffix("_proxy")
    light_span = light_span or max(width * 1.6, 2.0)
    art_path = project_path(art)

    scene = bpy.context.scene
    topology_data = topology(proxy)
    failures = []
    if topology_data["components"] != expected_shells:
        failures.append(
            f"{proxy} has {topology_data['components']} disconnected shells; expected {expected_shells}"
        )
    if topology_data["non_manifold_edges"]:
        failures.append(f"{proxy} has {topology_data['non_manifold_edges']} non-manifold edges")
    if topology_data["material_slots"] != ["proxy"]:
        failures.append(f"{proxy} material slots must be exactly ['proxy']; got {topology_data['material_slots']}")

    old_camera = scene.camera
    old_world_color = tuple(scene.world.color)
    old_render_samples = scene.eevee.taa_render_samples
    scene.eevee.taa_render_samples = 1 if quality == "fast" else 4
    old_hidden = {obj.name: obj.hide_render for obj in scene.objects}
    reference_object = authored_reference(reference)
    # Export cards may intentionally have an untextured material slot. Bind the
    # supplied source art for validation instead of measuring an opaque quad.
    old_materials = list(reference_object.data.materials)
    material = bpy.data.materials.new("VALIDATION_SOURCE_ART")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(art_path), check_existing=True)
    shader = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    material.node_tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    reference_object.data.materials.clear()
    reference_object.data.materials.append(material)
    visibility = [(obj, obj.hide_viewport, obj.hide_get()) for obj in
                  (reference_object, proxy_object(proxy))]
    for obj, _disabled, _hidden in visibility:
        obj.hide_viewport = False
        obj.hide_set(False)
    bpy.context.view_layer.update()
    try:
        metrics = render_game_layout(proxy, reference, width, height, stem)
        checks = ["game_layout_coverage", "ground_contact"]
        if quality == "review":
            render_three_quarter(proxy, stem, width, height)
            render_shadow_preview(proxy, reference, stem, width, height, -light_span)
            render_shadow_preview(proxy, reference, stem, width, height, light_span)
            checks.extend(("volume", "left_shadow", "right_shadow"))
    finally:
        reference_object.data.materials.clear()
        for old_material in old_materials:
            reference_object.data.materials.append(old_material)
        bpy.data.materials.remove(material)
        for obj, disabled, hidden in visibility:
            obj.hide_viewport = disabled
            obj.hide_set(hidden)
        scene.camera = old_camera
        scene.world.color = old_world_color
        scene.eevee.taa_render_samples = old_render_samples
        for name, hidden in old_hidden.items():
            obj = bpy.data.objects.get(name)
            if obj:
                obj.hide_render = hidden

    summary = {
        "asset": stem,
        "proxy": proxy,
        "source_art": str(art_path),
        "output_directory": str(OUT),
        "quality": quality,
        "checks": checks,
        "metrics": metrics,
        "topology": topology_data,
    }
    if metrics["art_covered_by_proxy_fraction"] < min_art_coverage:
        failures.append(
            f"{proxy} covers {metrics['art_covered_by_proxy_fraction']:.1%} of opaque art; "
            f"required {min_art_coverage:.1%}"
        )
    if metrics["contact_art_covered_by_proxy_fraction"] < min_contact_coverage:
        failures.append(
            f"{proxy} covers {metrics['contact_art_covered_by_proxy_fraction']:.1%} of contact art; "
            f"required {min_contact_coverage:.1%}"
        )
    if metrics["proxy_outside_art_fraction"] > max_proxy_spill:
        failures.append(
            f"{proxy} spills {metrics['proxy_outside_art_fraction']:.1%} outside opaque art; "
            f"maximum {max_proxy_spill:.1%}"
        )
    if metrics["contact_proxy_outside_art_fraction"] > max_contact_spill:
        failures.append(
            f"{proxy} contact spill is {metrics['contact_proxy_outside_art_fraction']:.1%}; "
            f"maximum {max_contact_spill:.1%}"
        )
    summary["passed"] = not failures
    summary["failures"] = failures
    (OUT / "validation-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    args = script_arguments()
    blend = project_path(args.blend)
    if Path(bpy.data.filepath) != blend:
        bpy.ops.wm.open_mainfile(filepath=str(blend))
    output = args.output or os.environ.get("PROXY_VALIDATION_OUT")
    summary = validate_asset(
        proxy=args.proxy,
        art=args.art,
        reference=args.reference,
        width=args.width,
        height=args.height,
        stem=args.stem,
        light_span=args.light_span,
        output=output,
        quality=args.quality,
        expected_shells=args.expected_shells,
        min_art_coverage=args.min_art_coverage,
        min_contact_coverage=args.min_contact_coverage,
        max_proxy_spill=args.max_proxy_spill,
        max_contact_spill=args.max_contact_spill,
    )
    print("PROXY_VALIDATION_RESULT=" + json.dumps(summary, sort_keys=True))
    if not summary["passed"]:
        raise SystemExit(2)
