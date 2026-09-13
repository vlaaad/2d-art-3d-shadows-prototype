"""Bake receiver data from the exact static GLBs loaded by the game.

    blender --background --python tools/bake_proxy_surface_maps.py -- \
      --proxy-glb assets/meshes/tree_proxy.glb \
      --card-glb assets/meshes/tree_card.glb \
      --output assets/textures/tree_surface.png --pixels-x 512 --pixels-y 512

No card offsets or dimensions are accepted: node transforms and UVs in the
exported card determine each receiver position. Prefer export_shadow_assets.py
with --surface-output to validate, export, and bake together.
"""

from pathlib import Path
import argparse
import json
import sys
import hashlib
import tempfile

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shadow_geometry import read_mesh, card_frame


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
    parser.add_argument("--proxy-glb", required=True)
    parser.add_argument("--card-glb", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pixels-x", type=int, required=True)
    parser.add_argument("--pixels-y", type=int, required=True)
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


def bake_surface_map(proxy_glb, card_glb, output, pixels_x, pixels_y):
    """Bake and atomically replace a map only after geometry/depth checks pass."""
    if pixels_x <= 0 or pixels_y <= 0:
        raise ValueError("pixel dimensions must be positive")
    proxy_path = project_path(str(proxy_glb))
    card_path = project_path(str(card_glb))
    proxy = read_mesh(proxy_path)
    frame = card_frame(read_mesh(card_path))
    if proxy['material'] != 'proxy':
        raise ValueError("Exported proxy must have exactly one slot named 'proxy'")
    depth_min, depth_max = DEFAULT_DEPTH_MIN, DEFAULT_DEPTH_MAX
    tree = BVHTree.FromPolygons(proxy['positions'], proxy['triangles'], all_triangles=True)
    # Cover the entire exported proxy, even if its origin is far from the card.
    distances = [(p - frame['origin']).dot(RAY) for p in proxy['positions']]
    ray_start = max(distances) + 1.0
    ray_length = ray_start - min(distances) + 1.0
    output_path = project_path(str(output))
    if output_path.suffix.lower() != '.png' or output_path in (proxy_path, card_path):
        raise ValueError("Output must be a separate PNG file")
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
        for px in range(pixels_x):
            u = (px + 0.5) / pixels_x
            point_on_card = frame["origin"] + frame["right"] * u + frame["up"] * v
            # RAY points from the card toward the gameplay camera. Trace from
            # that camera side back into the asset so the first hit is the
            # visible surface; tracing the opposite way bakes the rear shell
            # and creates fixed depth-transition bands in the 2D receiver.
            card_distance = (point_on_card - frame['origin']).dot(RAY)
            origin = point_on_card + RAY * (ray_start - card_distance)
            location, normal, face, _distance = tree.ray_cast(origin, -RAY, ray_length)
            if location is None:
                continue

            indices = proxy['triangles'][face]
            weights = _barycentric_weights(location, *(proxy['positions'][i] for i in indices))
            if weights is not None:
                normal = sum((proxy['normals'][i] * w for i, w in zip(indices, weights)), Vector()).normalized()

            depth = (location - point_on_card).dot(RAY)
            if not depth_min <= depth <= depth_max:
                raise ValueError(f"Receiver depth {depth:.5f} lies outside shader range [{depth_min}, {depth_max}]; refusing to clip")
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

    if not hit_count:
        raise ValueError("Proxy does not intersect the receiver card's camera rays")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = bpy.data.images.new("receiver_bake", width=pixels_x, height=pixels_y, alpha=True)
    try:
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "STRAIGHT"
        image.pixels.foreach_set(pixels)
        image.file_format = "PNG"
        with tempfile.TemporaryDirectory(prefix="receiver-bake-", dir=output_path.parent) as staging:
            temporary = Path(staging) / output_path.name
            image.filepath_raw = str(temporary)
            image.save()
            temporary.replace(output_path)
    finally:
        bpy.data.images.remove(image)

    return {
        "proxy_glb": str(proxy_path),
        "card_glb": str(card_path),
        "proxy_sha256": hashlib.sha256(proxy_path.read_bytes()).hexdigest(),
        "card_sha256": hashlib.sha256(card_path.read_bytes()).hexdigest(),
        "card_frame": {key: list(value) for key, value in frame.items()},
        "output": str(output_path),
        "hit_texels": hit_count,
        "total_texels": pixels_x * pixels_y,
        "depth_min": depth_low,
        "depth_max": depth_high,
    }


if __name__ == "__main__":
    args = script_arguments()
    result = bake_surface_map(args.proxy_glb, args.card_glb, args.output, args.pixels_x, args.pixels_y)
    print("SURFACE_BAKE_RESULT=" + json.dumps(result, sort_keys=True))
