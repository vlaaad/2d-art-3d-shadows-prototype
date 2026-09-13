"""Read the static GLB geometry used by Defold, including node transforms.

Coordinates and normals are converted from glTF (Y up) to Blender (Z up).
Only the unskinned triangle meshes used by this prototype are accepted.
"""
import json
import math
from pathlib import Path
import struct

from mathutils import Matrix, Quaternion, Vector


GLTF_TO_BLENDER = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def read_mesh(path):
    data = Path(path).read_bytes()
    if len(data) < 20 or struct.unpack_from('<4sII', data) != (b'glTF', 2, len(data)):
        raise ValueError(f'{path}: expected a GLB 2.0 file')
    chunks = {}
    offset = 12
    while offset < len(data):
        length, kind = struct.unpack_from('<II', data, offset)
        chunks[kind] = data[offset + 8:offset + 8 + length]
        offset += 8 + length
    doc = json.loads(chunks[0x4E4F534A])
    binary = chunks[0x004E4942]
    if len(doc.get('buffers', [])) != 1 or 'uri' in doc['buffers'][0] or doc.get('animations'):
        raise ValueError(f'{path}: only static, embedded GLB buffers are supported')

    def accessor(index):
        spec = doc['accessors'][index]
        if 'sparse' in spec or spec.get('normalized'):
            raise ValueError('Sparse/normalized accessors are unsupported')
        fmt = {5121: 'B', 5123: 'H', 5125: 'I', 5126: 'f'}[spec['componentType']]
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}[spec['type']]
        view = doc['bufferViews'][spec['bufferView']]
        if view.get('buffer', 0) != 0:
            raise ValueError('External buffers are unsupported')
        start = view.get('byteOffset', 0) + spec.get('byteOffset', 0)
        packed = struct.Struct('<' + fmt * width)
        stride = view.get('byteStride', packed.size)
        return [packed.unpack_from(binary, start + i * stride) for i in range(spec['count'])]

    instances = []

    def visit(index, parent):
        node = doc['nodes'][index]
        if 'skin' in node:
            raise ValueError('Skinned meshes cannot be baked with a static receiver map')
        if 'matrix' in node:
            m = node['matrix']
            local = Matrix([m[i:i + 4] for i in range(0, 16, 4)]).transposed()
        else:
            q = node.get('rotation', (0, 0, 0, 1))
            local = Matrix.LocRotScale(Vector(node.get('translation', (0, 0, 0))),
                                       Quaternion((q[3], *q[:3])), Vector(node.get('scale', (1, 1, 1))))
        world = parent @ local
        if 'mesh' in node:
            instances.append((doc['meshes'][node['mesh']], GLTF_TO_BLENDER @ world))
        for child in node.get('children', []):
            visit(child, world)

    for node in doc['scenes'][doc.get('scene', 0)]['nodes']:
        visit(node, Matrix.Identity(4))
    if len(instances) != 1:
        raise ValueError(f'{path}: expected exactly one mesh instance; found {len(instances)}')
    mesh, world = instances[0]
    if len(mesh['primitives']) != 1:
        raise ValueError(f'{path}: expected one material slot/primitive')
    primitive = mesh['primitives'][0]
    if primitive.get('mode', 4) != 4 or primitive.get('targets'):
        raise ValueError('Only static triangle primitives are supported')
    normal_matrix = world.to_3x3().inverted().transposed()
    attributes = primitive['attributes']
    positions = [world @ Vector(p) for p in accessor(attributes['POSITION'])]
    if any(not all(math.isfinite(v) for v in p) for p in positions):
        raise ValueError('Mesh contains non-finite positions')
    normals = [(normal_matrix @ Vector(n)).normalized() for n in accessor(attributes['NORMAL'])]
    if len(normals) != len(positions) or any(n.length < 0.5 or not all(math.isfinite(v) for v in n) for n in normals):
        raise ValueError('Mesh needs a finite, nonzero normal for every vertex')
    indices = [i[0] for i in accessor(primitive['indices'])] if 'indices' in primitive else list(range(len(positions)))
    if len(indices) % 3 or any(i >= len(positions) for i in indices):
        raise ValueError('Invalid triangle indices')
    triangles = [tuple(indices[i:i + 3]) for i in range(0, len(indices), 3)]
    if world.to_3x3().determinant() < 0:
        triangles = [(a, c, b) for a, b, c in triangles]
    # glTF UVs have a top-left origin; the baker writes Blender bottom-up pixels.
    uvs = [(u, 1.0 - v) for u, v in accessor(attributes['TEXCOORD_0'])] if 'TEXCOORD_0' in attributes else None
    return dict(positions=positions, normals=normals, triangles=triangles, uvs=uvs,
                material=doc['materials'][primitive['material']]['name'])


def card_frame(mesh):
    """Validate a full, upright UV rectangle and return its real world plane."""
    if mesh['uvs'] is None or len(mesh['triangles']) != 2:
        raise ValueError('Receiver card must be a rectangle with two UV-mapped triangles')
    if len(mesh['uvs']) != len(mesh['positions']):
        raise ValueError('Receiver card needs a UV for every vertex')
    corners = {}
    for p, uv in zip(mesh['positions'], mesh['uvs']):
        key = tuple(round(v) for v in uv)
        if any(abs(v - k) > 1e-5 or k not in (0, 1) for v, k in zip(uv, key)):
            raise ValueError('Receiver UVs must cover exactly [0, 1] without tiling')
        if key in corners and (corners[key] - p).length > 1e-5:
            raise ValueError('Receiver UVs map to multiple positions')
        corners[key] = p
    if set(corners) != {(0, 0), (1, 0), (0, 1), (1, 1)}:
        raise ValueError('Receiver card needs all four UV corners')
    triangles = [{tuple(round(v) for v in mesh['uvs'][i]) for i in triangle} for triangle in mesh['triangles']]
    shared = triangles[0] & triangles[1]
    if any(len(t) != 3 for t in triangles) or len(shared) != 2 or len(triangles[0] | triangles[1]) != 4:
        raise ValueError('Receiver triangles must share a single diagonal')
    a, b = shared
    if a[0] == b[0] or a[1] == b[1]:
        raise ValueError('Receiver triangles overlap instead of sharing a diagonal')
    origin = corners[0, 0]
    right = corners[1, 0] - origin
    up = corners[0, 1] - origin
    if (corners[1, 1] - origin - right - up).length > 1e-5:
        raise ValueError('Receiver card is not a planar rectangle')
    if right.x <= 0 or up.z <= 0 or max(abs(right.y), abs(right.z), abs(up.x), abs(up.y)) > 1e-5:
        raise ValueError('Receiver card must be upright with U along +X and V along +Z; rotated/mirrored cards are unsupported')
    area = sum((mesh['positions'][b] - mesh['positions'][a]).cross(mesh['positions'][c] - mesh['positions'][a]).length / 2
               for a, b, c in mesh['triangles'])
    if abs(area - right.x * up.z) > 1e-5:
        raise ValueError('Receiver triangles do not cover the UV rectangle')
    return dict(origin=origin, right=right, up=up)
