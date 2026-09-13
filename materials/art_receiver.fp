#version 140

in mediump vec2 var_texcoord0;
in mediump vec3 var_world_normal;
in highp vec4 var_shadow_coord;
in highp vec4 var_shadow_ray;
in mediump vec3 var_normal_x;
in mediump vec3 var_normal_y;
in mediump vec3 var_normal_z;

out vec4 out_fragColor;

uniform mediump sampler2D tex0;
uniform mediump sampler2D surface_map;
uniform highp sampler2D shadow_map;

uniform fs_uniforms
{
	mediump vec4 tint;
	highp vec4 shadow_texel_size;
	highp vec4 shadow_params;
	highp vec4 sun_direction;
	mediump vec4 day_tint;
	mediump vec4 lighting;
};

#include "/render/shadows.glsl"

void main()
{
	vec4 tint_pm = vec4(tint.rgb * tint.a, tint.a);
	vec4 color = texture(tex0, var_texcoord0) * tint_pm;
	if (color.a < 0.025)
	{
		discard;
	}

	// Every surface-map texel describes a valid receiver. Proxy hits contain the
	// baked surface normal/depth; misses explicitly contain the card-plane normal
	// and zero depth. Linear filtering can therefore make a continuous transition
	// without ever mixing receiver data with a transparent-black sentinel.
	vec4 surface_data = texture(surface_map, var_texcoord0);
	highp vec4 receiver_shadow_coord = var_shadow_coord;
	float encoded_depth = clamp((surface_data.a - (1.0 / 255.0)) / (254.0 / 255.0), 0.0, 1.0);
	float surface_depth = mix(-1.0, 2.5, encoded_depth);
	receiver_shadow_coord += var_shadow_ray * surface_depth;
	vec3 local_normal = surface_data.rgb * 2.0 - 1.0;
	vec3 receiver_normal = normalize(
		local_normal.x * var_normal_x +
		local_normal.y * var_normal_y +
		local_normal.z * var_normal_z);

	vec3 direction_to_light = -normalize(sun_direction.xyz);
	float n_dot_l = max(dot(receiver_normal, direction_to_light), 0.0);
	float wrapped_diffuse = 0.72 + 0.28 * n_dot_l;
	float illumination = 1.0;
	// Explicit card-plane texels still use the same world-space shadow lookup,
	// preserving shadows that cross between different objects.
	float visibility = directional_shadow_visibility(
		shadow_map,
		receiver_shadow_coord,
		shadow_texel_size.xy,
		shadow_params,
		receiver_normal,
		direction_to_light
	);
	// Painted assets already contain local form shading. Keep dynamic shadows
	// readable without letting dense proxy lobes blacken the crown. This applies
	// identically to tree, character, and grass, including cross-object shadows.
	visibility = mix(1.0, visibility, 0.72);
	float shadow = 1.0 - lighting.z * (1.0 - visibility);

	out_fragColor = vec4(color.rgb * day_tint.rgb * illumination * shadow, color.a);
}
