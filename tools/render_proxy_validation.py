"""Render authored proxy alignment views from the editable Blender source.

Run with:

    blender --background --python tools/render_proxy_validation.py

The front overlay uses the exact card framing (bottom-centre pivot and world
aspect), making root/limb drift visible before testing shadows in Defold.
"""

from pathlib import Path
import json
import os
import subprocess

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
BLEND = ROOT / "assets" / "proxies" / "shadow_proxies.blend"
OUT = Path(os.environ.get("PROXY_VALIDATION_OUT", "/tmp/2d-art-3d-shadows-prototype/proxy-validation"))


def point_camera(camera, location, target):
    camera.location = location
    camera.rotation_euler = (Vector(target) - Vector(location)).to_track_quat("-Z", "Y").to_euler()


def hide_everything():
    for obj in bpy.context.scene.objects:
        obj.hide_render = True


def proxy_object(name):
    collection = bpy.data.collections["EXPORT_PROXIES"]
    return next(obj for obj in collection.objects if obj.name == name)


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


def ensure_game_camera(target_height):
    """Match the direction of main/camera.go, reframed around one asset."""
    camera_data = bpy.data.cameras.get("VALIDATION_GAME_CAMERA") or bpy.data.cameras.new("VALIDATION_GAME_CAMERA")
    camera = bpy.data.objects.get("VALIDATION_GAME_CAMERA") or bpy.data.objects.new("VALIDATION_GAME_CAMERA", camera_data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = target_height * 1.28
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

    contact_y = round(height * 0.65)
    contact_crop = f"{width}x{height - contact_y}+0+{contact_y}"
    proxy_mean = mask_mean(proxy_mask)
    outside_mean = mask_mean(mesh_only_mask)
    contact_proxy_mean = mask_mean(proxy_mask, contact_crop)
    contact_outside_mean = mask_mean(mesh_only_mask, contact_crop)
    metrics = {
        "proxy_outside_art_fraction": outside_mean / max(proxy_mean, 1e-8),
        "contact_proxy_outside_art_fraction": contact_outside_mean / max(contact_proxy_mean, 1e-8),
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


def authored_reference(collection_name):
    collection = bpy.data.collections[collection_name]
    return next(obj for obj in collection.objects if obj.name.endswith("REFERENCE_DO_NOT_EXPORT"))


def render_game_layout(proxy_name, collection_name, width, height, stem):
    """Render art and proxy at the same origin using the gameplay camera."""
    camera = ensure_game_camera(height)
    bpy.context.scene.camera = camera
    ensure_area_light()
    render = bpy.context.scene.render
    render.engine = "BLENDER_EEVEE"
    render.film_transparent = True
    render.resolution_x = 800
    render.resolution_y = 800
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"

    proxy = proxy_object(proxy_name)
    reference = authored_reference(collection_name)
    markers = make_pivot_marker(width)

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

    hide_everything()
    camera.hide_render = False
    ensure_area_light()
    reference.hide_render = False
    # Authored reference geometry is parked 0.64 units behind the edit mesh;
    # this temporary object translation puts its card plane at runtime depth 0.
    reference.location.y = -0.64
    art_path = OUT / f"{stem}-game-art.png"
    render.filepath = str(art_path)
    bpy.ops.render.render(write_still=True)

    hide_everything()
    camera.hide_render = False
    for marker in markers:
        marker.hide_render = False
    marker_path = OUT / f"{stem}-game-pivot.png"
    render.filepath = str(marker_path)
    bpy.ops.render.render(write_still=True)

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

    # A proxy spilling outside the painted contact patch creates the most
    # obvious floating/double-root shadow. Fail before launching Defold.
    if metrics["contact_proxy_outside_art_fraction"] > 0.13:
        raise RuntimeError(
            f"{stem} contact mismatch is {metrics['contact_proxy_outside_art_fraction']:.1%}; "
            "adjust the authored Blender proxy before runtime validation"
        )


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


def render_three_quarter(proxy_name, stem, target_height):
    hide_everything()
    proxy = proxy_object(proxy_name)
    proxy.hide_render = False
    ensure_area_light()
    camera_data = bpy.data.cameras.get("VALIDATION_VOLUME_CAMERA") or bpy.data.cameras.new("VALIDATION_VOLUME_CAMERA")
    camera = bpy.data.objects.get("VALIDATION_VOLUME_CAMERA") or bpy.data.objects.new("VALIDATION_VOLUME_CAMERA", camera_data)
    if not camera.users_collection:
        bpy.context.scene.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = target_height * 1.18
    point_camera(camera, (5.8, -7.4, 4.8), (0.0, 0.0, target_height * 0.47))
    camera.hide_render = False
    bpy.context.scene.camera = camera
    render = bpy.context.scene.render
    render.engine = "BLENDER_EEVEE"
    render.film_transparent = False
    bpy.context.scene.world.color = (0.025, 0.035, 0.055)
    render.resolution_x = 800
    render.resolution_y = 800
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    render.filepath = str(OUT / f"{stem}-proxy-volume.png")
    bpy.ops.render.render(write_still=True)


def render_shadow_preview(proxy_name, collection_name, stem, target_height, light_x):
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

    camera = ensure_game_camera(target_height)
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
    reference = authored_reference(collection_name)
    reference.hide_render = False
    old_proxy_camera = proxy.visible_camera
    old_reference_shadow = reference.visible_shadow
    proxy.visible_camera = False
    reference.visible_shadow = False

    scene = bpy.context.scene
    render = scene.render
    render.engine = "BLENDER_EEVEE"
    render.film_transparent = False
    render.resolution_x = 800
    render.resolution_y = 800
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


if __name__ == "__main__":
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    OUT.mkdir(parents=True, exist_ok=True)
    render_front("tree_proxy", "assets/textures/tree.png", 3.7, 4.2, "tree")
    render_front("character_proxy", "assets/textures/character.png", 1.15, 1.72, "character")
    render_three_quarter("tree_proxy", "tree", 4.2)
    render_three_quarter("character_proxy", "character", 1.72)
    render_game_layout("tree_proxy", "TREE_PROXY_AUTHORED", 3.7, 4.2, "tree")
    render_game_layout("character_proxy", "CHARACTER_PROXY_AUTHORED", 1.15, 1.72, "character")
    render_game_layout("grass_proxy", "GRASS_PROXY_AUTHORED", 1.45, 0.72, "grass")
    render_shadow_preview("tree_proxy", "TREE_PROXY_AUTHORED", "tree", 4.2, -6.0)
    render_shadow_preview("tree_proxy", "TREE_PROXY_AUTHORED", "tree", 4.2, 6.0)
