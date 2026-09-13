"""Bake a fixed-view depth/normal receiver map from any authored proxy.

Every texel is valid receiver data. Proxy hits store their baked normal/depth;
misses store the card-plane normal and zero depth so hardware filtering blends
continuously across the shared proxy-to-card transition. The PNG art remains
immutable and the proxy remains Blender-authored. Run:

    blender --background --python tools/bake_proxy_surface_maps.py -- \
      --blend <asset.blend> --proxy <object> --output <surface.png> \
      --pixels-x 256 --pixels-y 256 --card-width 1.0 --card-height 1.0 \
      --card-y 0.0 --pivot-z 0.0

Card dimensions, ``--card-y``, and ``--pivot-z`` describe the world-space
mesh vertices, not the card object's origin. For example, ``tree_card`` has
an object Y offset of -0.64 but its vertices lie on world Y = 0.0. Using the
object offset shifts receiver hits away from the artwork and creates a seam.

``bake_surface_map()`` can also be called directly against a live object in the
persistent Blender instance, avoiding an export/reload cycle while iterating.
"""

from pathlib import Path
import argparse
import json
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPTH_MIN = -1.0
DEFAULT_DEPTH_MAX = 2.5

# Surface-to-camera direction in Blender coordinates. Defold's camera at
# (0, 7.8, 10.5), looking at (0, 1.25, 0), maps to Blender (x, -z, y).
RAY = Vector((0.0, -10.5, 6.55)).normalized()


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def script_arguments():
    values = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blend", required=True)
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pixels-x", type=int, required=True)
    parser.add_argument("--pixels-y", type=int, required=True)
    parser.add_argument("--card-width", type=float, required=True)
    parser.add_argument("--card-height", type=float, required=True)
    parser.add_argument("--card-y", type=float, required=True)
    parser.add_argument("--pivot-z", type=float, required=True)
    parser.add_argument("--depth-min", type=float, default=DEFAULT_DEPTH_MIN)
    parser.add_argument("--depth-max", type=float, default=DEFAULT_DEPTH_MAX)
    return parser.parse_args(values)


def _barycentric_weights(point, a, b, c):
    edge0 = b - a
    edge1 = c - a
    relative = point - a
    dot00 = edge0.dot(edge0)
    dot01 = edge0.dot(edge1)
    dot11 = edge1.dot(edge1)
    dot20 = relative.dot(edge0)
    dot21 = relative.dot(edge1)
    denominator = dot00 * dot11 - dot01 * dot01
    if abs(denominator) < 1e-12:
        return None
    weight_b = (dot11 * dot20 - dot01 * dot21) / denominator
    weight_c = (dot00 * dot21 - dot01 * dot20) / denominator
    return 1.0 - weight_b - weight_c, weight_b, weight_c


def _smooth_normal_data(proxy):
    """Return evaluated mesh data used to interpolate authored smooth normals."""
    evaluated = proxy.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    triangles_by_polygon = {}
    for triangle in mesh.loop_triangles:
        triangles_by_polygon.setdefault(triangle.polygon_index, []).append(tuple(triangle.vertices))
    return evaluated, mesh, triangles_by_polygon


def _hit_normal(mesh, triangles_by_polygon, polygon_index, location, fallback):
    polygon = mesh.polygons[polygon_index]
    if not polygon.use_smooth:
        return fallback
    best = None
    for indices in triangles_by_polygon.get(polygon_index, ()):
        a, b, c = (mesh.vertices[index].co for index in indices)
        weights = _barycentric_weights(location, a, b, c)
        if weights is None:
            continue
        score = min(weights)
        if best is None or score > best[0]:
            best = (score, indices, weights)
    if best is None:
        return fallback
    _score, indices, weights = best
    normal = sum(
        (mesh.vertices[index].normal * weight for index, weight in zip(indices, weights)),
        Vector((0.0, 0.0, 0.0)),
    )
    return normal.normalized() if normal.length_squared > 1e-12 else fallback


def bake_surface_map(
    proxy: bpy.types.Object,
    output: str | Path,
    pixels_x: int,
    pixels_y: int,
    card_width: float,
    card_height: float,
    card_y: float,
    pivot_z: float,
    depth_min: float = DEFAULT_DEPTH_MIN,
    depth_max: float = DEFAULT_DEPTH_MAX,
):
    if proxy.type != "MESH":
        raise RuntimeError(f"{proxy.name} must be a mesh")
    if pixels_x <= 0 or pixels_y <= 0 or card_width <= 0 or card_height <= 0:
        raise RuntimeError("pixel dimensions and card dimensions must be positive")
    if depth_max <= depth_min:
        raise RuntimeError("depth-max must be greater than depth-min")

    output_path = project_path(str(output))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = BVHTree.FromObject(proxy, bpy.context.evaluated_depsgraph_get())
    evaluated, evaluated_mesh, triangles_by_polygon = _smooth_normal_data(proxy)
    # A miss is not an absent sample: it is the card-plane receiver. Encoding
    # that state explicitly prevents linear filtering from mixing proxy data
    # with transparent black and creating a lighting seam at proxy silhouettes.
    fallback_depth = 1.0 / 255.0 + ((0.0 - depth_min) / (depth_max - depth_min)) * (254.0 / 255.0)
    fallback_texel = (0.5, 0.5, 1.0, fallback_depth)
    pixels = list(fallback_texel) * (pixels_x * pixels_y)
    hit_count = 0
    depth_low = depth_max
    depth_high = depth_min

    for py in range(pixels_y):
        v = (py + 0.5) / pixels_y
        z = pivot_z + v * card_height
        for px in range(pixels_x):
            u = (px + 0.5) / pixels_x
            point_on_card = Vector(((u - 0.5) * card_width, card_y, z))
            # RAY points from the card toward the gameplay camera. Trace from
            # that camera side back into the asset so the first hit is the
            # visible surface; tracing the opposite way bakes the rear shell
            # and creates fixed depth-transition bands in the 2D receiver.
            origin = point_on_card + RAY * 4.0
            location, normal, face, _distance = tree.ray_cast(origin, -RAY, 8.0)
            if location is None:
                continue

            normal = _hit_normal(evaluated_mesh, triangles_by_polygon, face, location, normal)

            depth = max(depth_min, min(depth_max, (location - point_on_card).dot(RAY)))
            # glTF/Defold coordinates: Blender (x, y, z) -> (x, z, -y).
            normal_defold = Vector((normal.x, normal.z, -normal.y)).normalized()
            encoded_depth = 1.0 / 255.0 + ((depth - depth_min) / (depth_max - depth_min)) * (254.0 / 255.0)
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

    try:
        old = bpy.data.images.get(output_path.name)
        if old:
            bpy.data.images.remove(old)
        image = bpy.data.images.new(output_path.name, width=pixels_x, height=pixels_y, alpha=True)
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "STRAIGHT"
        image.pixels.foreach_set(pixels)
        image.file_format = "PNG"
        image.filepath_raw = str(output_path)
        image.save()
    finally:
        evaluated.to_mesh_clear()

    return {
        "proxy": proxy.name,
        "output": str(output_path),
        "hit_texels": hit_count,
        "total_texels": pixels_x * pixels_y,
        "depth_min": depth_low if hit_count else None,
        "depth_max": depth_high if hit_count else None,
    }


if __name__ == "__main__":
    args = script_arguments()
    blend = project_path(args.blend)
    if Path(bpy.data.filepath) != blend:
        bpy.ops.wm.open_mainfile(filepath=str(blend))
    result = bake_surface_map(
        proxy=bpy.data.objects[args.proxy],
        output=args.output,
        pixels_x=args.pixels_x,
        pixels_y=args.pixels_y,
        card_width=args.card_width,
        card_height=args.card_height,
        card_y=args.card_y,
        pivot_z=args.pivot_z,
        depth_min=args.depth_min,
        depth_max=args.depth_max,
    )
    print("SURFACE_BAKE_RESULT=" + json.dumps(result, sort_keys=True))
