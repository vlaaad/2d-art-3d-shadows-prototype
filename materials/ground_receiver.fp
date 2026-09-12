#version 140

in mediump vec2 var_texcoord0;
in mediump vec3 var_world_normal;
in highp vec4 var_shadow_coord;

out vec4 out_fragColor;

uniform mediump sampler2D tex0;
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
	vec3 direction_to_light = -normalize(sun_direction.xyz);
	float n_dot_l = max(dot(normalize(var_world_normal), direction_to_light), 0.0);
	float wrapped_diffuse = 0.72 + 0.28 * n_dot_l;
	float illumination = lighting.x + lighting.y * wrapped_diffuse;
	float visibility = directional_shadow_visibility(
		shadow_map, var_shadow_coord, shadow_texel_size.xy, shadow_params,
		var_world_normal, direction_to_light);
	float shadow = 1.0 - lighting.z * (1.0 - visibility);
	out_fragColor = vec4(color.rgb * day_tint.rgb * illumination * shadow, color.a);
}
