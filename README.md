# 2D art / 3D shadows prototype

A Defold 2.5D lighting experiment: transparent hand-painted model cards share a
single receiver material, while matching shallow low-poly models render only to
a directional shadow map. The sun orbits through a ten-second day/night cycle.
This branch requires Defold 1.13.2 beta or newer because prop collision objects
use the new glTF-backed `TYPE_MESH` shape.

Controls:

- WASD or arrow keys: move
- Space: pause/resume the day/night cycle
- R: reset time of day
- F2: show/hide translucent shadow proxies
- F3: show/hide Defold 3D physics colliders
- Backquote/tilde: toggle the profiler

The character uses a kinematic 3D capsule. The tree, barrel, boulder, and fence
use their complete authored shadow proxies as static collision meshes. Depth testing lets the character walk
in front of or behind the tree. The field contains 500 factory-spawned grass
cards and 500 matching shadow proxies; shared resources and local-space model
materials allow Defold to instance/batch both passes.

`assets/proxies/shadow_proxies.blend` is the canonical authored source for the
art-card pivots and the editable 3D proxies. The PNG artwork remains unchanged.
Edit the named solids in Blender against their reference cards, validate them,
then export with `blender --background --python tools/export_shadow_assets.py`.
The export script contains no geometry construction.

To rebake the tree receiver map after validating its proxy, use the card's
world-space plane and bottom edge (its object origin has a separate Y offset):

```sh
blender --background --python tools/bake_proxy_surface_maps.py -- \
  --blend assets/proxies/shadow_proxies.blend --proxy tree_proxy \
  --output assets/textures/tree_surface.png --pixels-x 512 --pixels-y 512 \
  --card-width 3.7 --card-height 4.2 --card-y 0.0 --pivot-z -0.065625
```

The boulder likewise uses the exported card plane at world Y = 0.0:

```sh
blender --background --python tools/bake_proxy_surface_maps.py -- \
  --blend assets/proxies/boulder.blend --proxy boulder_proxy \
  --output assets/textures/boulder_surface.png --pixels-x 256 --pixels-y 171 \
  --card-width 2.6 --card-height 1.73671875 --card-y 0.0 --pivot-z -0.17265625
```

---
