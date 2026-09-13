"""Regression checks: blender -b -noaudio --python-exit-code 1 --python tools/test_shadow_baking.py"""
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_proxy_surface_maps import bake_surface_map, RAY
from shadow_geometry import card_frame, read_mesh

ROOT = Path(__file__).resolve().parents[1]


def edited_glb(source, output, edit):
    data = Path(source).read_bytes()
    length = struct.unpack_from('<I', data, 12)[0]
    document = json.loads(data[20:20 + length])
    edit(document)
    encoded = json.dumps(document).encode()
    encoded += b' ' * (-len(encoded) % 4)
    tail = data[20 + length:]
    Path(output).write_bytes(struct.pack('<4sII', b'glTF', 2, 20 + len(encoded) + len(tail))
                            + struct.pack('<II', len(encoded), 0x4E4F534A) + encoded + tail)


def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        image.colorspace_settings.name = 'Non-Color'
        image.alpha_mode = 'STRAIGHT'
        values = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(values)
        return np.rint(values * 255).astype(np.int16)
    finally:
        bpy.data.images.remove(image)


class ReceiverBakingTests(unittest.TestCase):
    def test_fixed_tree_and_boulder_maps(self):
        # Golden images are the maps visually verified after fixing both seams.
        # Exported vertex normals may quantize one step differently from Blender.
        for name, size, bottom in [('tree', (512, 512), -.065625), ('boulder', (256, 171), -.17265625)]:
            with self.subTest(asset=name), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'surface.png'
                result = bake_surface_map(ROOT / f'assets/meshes/{name}_proxy.glb',
                                          ROOT / f'assets/meshes/{name}_card.glb', output, *size)
                self.assertAlmostEqual(result['card_frame']['origin'][1], 0.0, places=5)
                self.assertAlmostEqual(result['card_frame']['origin'][2], bottom, places=5)
                delta = np.abs(pixels(output) - pixels(ROOT / f'assets/textures/{name}_surface.png'))
                self.assertLessEqual(int(delta.max()), 1)

    def test_parent_transform_is_included(self):
        source = ROOT / 'assets/meshes/tree_card.glb'
        original = card_frame(read_mesh(source))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'parent.glb'
            def add_parent(doc):
                roots = doc['scenes'][doc.get('scene', 0)]['nodes']
                doc['nodes'].append({'translation': [2, 3, 4], 'children': roots})
                doc['scenes'][doc.get('scene', 0)]['nodes'] = [len(doc['nodes']) - 1]
            edited_glb(source, path, add_parent)
            actual = card_frame(read_mesh(path))
            self.assertLess((actual['origin'] - original['origin'] - Vector((2, -4, 3))).length, 1e-5)

    def test_mirrored_tiled_and_overlapping_uvs_are_rejected(self):
        mesh = read_mesh(ROOT / 'assets/meshes/tree_card.glb')
        for uv in [[(1-u, v) for u, v in mesh['uvs']], [(u*2, v) for u, v in mesh['uvs']]]:
            broken = copy.deepcopy(mesh)
            broken['uvs'] = uv
            with self.assertRaises(ValueError):
                card_frame(broken)
        broken = copy.deepcopy(mesh)
        broken['triangles'][1] = broken['triangles'][0]
        with self.assertRaises(ValueError):
            card_frame(broken)

    def test_bad_depth_and_misses_preserve_existing_output(self):
        for shift, message in [(RAY * 5, 'outside shader range'), (Vector((100, 0, 0)), 'does not intersect')]:
            with self.subTest(shift=shift), tempfile.TemporaryDirectory() as temporary:
                proxy = Path(temporary) / 'proxy.glb'
                output = Path(temporary) / 'surface.png'
                output.write_bytes(b'existing map must survive')
                def translate(doc):
                    node = doc['nodes'][0]
                    node['translation'] = [shift.x, shift.z, -shift.y]
                edited_glb(ROOT / 'assets/meshes/boulder_proxy.glb', proxy, translate)
                with self.assertRaisesRegex(ValueError, message):
                    bake_surface_map(proxy, ROOT / 'assets/meshes/boulder_card.glb', output, 32, 24)
                self.assertEqual(output.read_bytes(), b'existing map must survive')


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReceiverBakingTests))
    if not result.wasSuccessful():
        raise RuntimeError('Receiver baking regression checks failed')
