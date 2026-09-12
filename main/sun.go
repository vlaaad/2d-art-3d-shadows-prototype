components {
  id: "cycle"
  component: "/scripts/day_cycle.script"
}
components {
  id: "shadow_setup"
  component: "/scripts/shadow_setup.script"
}
embedded_components {
  id: "shadow_camera"
  type: "camera"
  data: "aspect_ratio: 1.0\n"
  "fov: 0.7854\n"
  "near_z: 0.1\n"
  "far_z: 30.0\n"
  "orthographic_projection: 1\n"
  "orthographic_zoom: 68.0\n"
  "orthographic_mode: ORTHO_MODE_FIXED\n"
}
