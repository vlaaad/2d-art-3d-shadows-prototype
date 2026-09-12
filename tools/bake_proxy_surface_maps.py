"""Bake fixed-view proxy depth and normals for the shared art-card shader.

The PNG art remains immutable and the proxy meshes remain Blender-authored.
This tool only samples each existing proxy along the gameplay camera ray. RGB
stores a Defold-local normal and alpha stores signed distance from the art-card
plane. Alpha zero means the proxy does not cover that texel.
"""

from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parents[1]
BLEND = ROOT / "assets" / "proxies" / "shadow_proxies.blend"
DEPTH_MIN = -1.0
DEPTH_MAX = 2.5

# Blender coordinates corresponding to the fixed Defold gameplay camera ray.
RAY = Vector((0.0, 10.5, -6.55)).normalized()

SPECS = (
    ("tree_proxy", "tree_surface.png", 512, 512, 3.7, 4.2, -0.64, -0.065625),
    ("character_proxy", "character_surface.png", 256, 384, 1.15, 1.72, -0.64, -(16 / 384) * 1.72),
    ("grass_proxy", "grass_surface.png", 256, 128, 1.45, 0.72, -0.64, -(6 / 128) * 0.72),
)


def bake(
    name: str,
    filename: str,
    pixels_x: int,
    pixels_y: int,
    width: float,
    height: float,
    card_y: float,
    pivot_z: float,
) -> None:
    proxy = bpy.data.objects[name]
    tree = BVHTree.FromObject(proxy, bpy.context.evaluated_depsgraph_get())
    pixels = [0.0] * (pixels_x * pixels_y * 4)
    hit_count = 0
    depth_low = DEPTH_MAX
    depth_high = DEPTH_MIN

    for py in range(pixels_y):
        v = (py + 0.5) / pixels_y
        z = pivot_z + v * height
        for px in range(pixels_x):
            u = (px + 0.5) / pixels_x
            # Start on the actual authored card plane.  Using y=0 here while
            # the card is at y=-0.64 bakes a consistent screen-space/pivot
            # offset into every receiver and is especially visible at feet
            # and roots.
            point_on_card = Vector(((u - 0.5) * width, card_y, z))
            origin = point_on_card - RAY * 4.0
            location, normal, _face, _distance = tree.ray_cast(origin, RAY, 8.0)
            if location is None:
                continue

            depth = max(DEPTH_MIN, min(DEPTH_MAX, (location - point_on_card).dot(RAY)))
            # glTF/Defold coordinates: Blender (x, y, z) -> (x, z, -y).
            normal_defold = Vector((normal.x, normal.z, -normal.y)).normalized()
            encoded_depth = 1.0 / 255.0 + ((depth - DEPTH_MIN) / (DEPTH_MAX - DEPTH_MIN)) * (254.0 / 255.0)
            index = (py * pixels_x + px) * 4
            pixels[index:index + 4] = (
                normal_defold.x * 0.5 + 0.5,
                normal_defold.y * 0.5 + 0.5,
                normal_defold.z * 0.5 + 0.5,
                encoded_depth,
            )
            hit_count += 1
            depth_low = min(depth_low, depth)
            depth_high = max(depth_high, depth)

    old = bpy.data.images.get(filename)
    if old:
        bpy.data.images.remove(old)
    image = bpy.data.images.new(filename, width=pixels_x, height=pixels_y, alpha=True)
    image.colorspace_settings.name = "Non-Color"
    image.alpha_mode = "STRAIGHT"
    image.pixels.foreach_set(pixels)
    image.file_format = "PNG"
    image.filepath_raw = str(ROOT / "assets" / "textures" / filename)
    image.save()
    print(
        f"{name}: {hit_count}/{pixels_x * pixels_y} texels, "
        f"depth {depth_low:.4f}..{depth_high:.4f}"
    )


if __name__ == "__main__":
    bpy.ops.wm.open_mainfile(filepath=str(BLEND))
    for spec in SPECS:
        bake(*spec)
