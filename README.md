# 2D art / 3D shadows prototype

A Defold 2.5D lighting experiment: transparent hand-painted model cards share a
single receiver material, while matching shallow low-poly models render only to
a directional shadow map. The sun orbits through a ten-second day/night cycle.

Controls:

- WASD or arrow keys: move
- Space: pause/resume the day/night cycle
- R: reset time of day

The trunk has a circular movement blocker. Depth testing lets the character walk
in front of or behind the tree. The field contains 500 factory-spawned grass
cards and 500 matching shadow proxies; shared resources and local-space model
materials allow Defold to instance/batch both passes.

`assets/proxies/shadow_proxies.blend` is the canonical authored source for the
art-card pivots and the editable 3D proxies. The PNG artwork remains unchanged.
Edit the named solids in Blender against their reference cards, validate them,
then export with `blender --background --python tools/export_shadow_assets.py`.
The export script contains no geometry construction.

---
