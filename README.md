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

The character uses a force-driven dynamic 3D capsule, with height and rotation locked. The tree, barrel, boulder, and fence
use their complete authored shadow proxies as static collision meshes. Depth testing lets the character walk
in front of or behind the tree. The field contains 500 factory-spawned grass
cards and 500 matching shadow proxies; shared resources and local-space model
materials allow Defold to instance/batch both passes.

World geometry is authored in metres, so keep `physics.scale = 1.0`. Scaling
this scene down to `0.01` makes the player capsule smaller than Bullet's contact
tolerances: sustained movement can enter the prop meshes and become trapped.

Author the proxy and its final runtime art-card transform in the asset's `.blend`
file. Run validation, export, and receiver baking as one operation:

```sh
blender --background -noaudio --python-exit-code 1 --python tools/export_shadow_assets.py -- \
  --blend assets/proxies/shadow_proxies.blend --proxy tree_proxy --card tree_card \
  --art assets/textures/tree.png --expected-shells 2 \
  --proxy-output assets/meshes/tree_proxy.glb --card-output assets/meshes/tree_card.glb \
  --surface-output assets/textures/tree_surface.png --pixels-x 512 --pixels-y 512
```

For the boulder:

```sh
blender --background -noaudio --python-exit-code 1 --python tools/export_shadow_assets.py -- \
  --blend assets/proxies/boulder.blend --proxy boulder_proxy --card boulder_card \
  --art assets/textures/boulder.png \
  --proxy-output assets/meshes/boulder_proxy.glb --card-output assets/meshes/boulder_card.glb \
  --surface-output assets/textures/boulder_surface.png --pixels-x 256 --pixels-y 171
```

The command validates the authored proxy against the supplied PNG, requiring
90% overall / 95% contact coverage and the requested number of watertight shells.
It then exports into a temporary directory and bakes from those exact GLBs,
including their node transforms and UVs. Card dimensions, plane, and pivot are
automatic: never substitute an object's location for its world-space vertices.
Invalid UV layouts, missing receiver hits, or depths outside the shader's encoding
range fail before the output assets are replaced. Source artwork and `.blend`
files remain unchanged. All three output paths are required to avoid stale maps.

The default `review` quality produces volume and side-shadow images; inspect the
reported review directory. Use `--quality fast` for the coverage/contact edit loop.
Occasionally compare the result with Defold's F2 proxy overlay. The current shader
and baker assume upright cards and the fixed gameplay camera; camera or shader
depth-range changes must be coordinated with the baker.

To rebake already exported geometry without reauthoring it:

```sh
blender --background -noaudio --python-exit-code 1 --python tools/bake_proxy_surface_maps.py -- \
  --proxy-glb assets/meshes/tree_proxy.glb --card-glb assets/meshes/tree_card.glb \
  --output assets/textures/tree_surface.png --pixels-x 512 --pixels-y 512
```

Regression checks cover the verified tree/boulder maps, parent transforms, invalid
UVs, and preservation of an existing map when baking fails:

```sh
blender --background -noaudio --python-exit-code 1 --python tools/test_shadow_baking.py
```

Player collision regression checks (with the Defold editor open):

```sh
PYTHONPATH=automation-bridge-python python3 tools/test_player_collisions.py
```

These push into the barrel, trunk, boulder, and fence, check for entry into the
barrel/trunk interiors, and require movement away when the input reverses.
The game remains open with the player returned to the starting position.

Gameplay scripts access Automation Bridge through `scripts/diagnostics.lua`.
The native API is debug-only, so this adapter makes diagnostic hooks no-ops in
release builds. Keep new diagnostic calls behind the adapter so they cannot
interrupt gameplay when bundling HTML5 or native releases.
