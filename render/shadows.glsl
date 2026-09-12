#ifndef PROTOTYPE_SHADOWS_GLSL
#define PROTOTYPE_SHADOWS_GLSL

highp float shadow_compare(sampler2D shadow_texture, highp vec2 uv, highp float receiver_depth)
{
	if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0))))
	{
		return 1.0;
	}
	return receiver_depth <= texture(shadow_texture, uv).r ? 1.0 : 0.0;
}

highp float directional_shadow_visibility(
	sampler2D shadow_texture,
	highp vec4 shadow_coord,
	highp vec2 texel_size,
	highp vec4 shadow_params,
	highp vec3 normal,
	highp vec3 direction_to_light)
{
	if (shadow_coord.w <= 0.0)
	{
		return 1.0;
	}

	highp vec3 projected = shadow_coord.xyz / shadow_coord.w;
	if (any(lessThan(projected, vec3(0.0))) || any(greaterThan(projected, vec3(1.0))))
	{
		return 1.0;
	}

	highp float facing = max(dot(normalize(normal), normalize(direction_to_light)), 0.0);
	highp float bias = max(shadow_params.z, shadow_params.w * (1.0 - facing));
	highp float receiver_depth = projected.z - bias;
	highp vec2 step_size = texel_size * shadow_params.y;

	if (shadow_params.x < 2.0)
	{
		return shadow_compare(shadow_texture, projected.xy, receiver_depth);
	}

	highp float visibility = 0.0;
	if (shadow_params.x < 4.0)
	{
		for (int y = -1; y <= 1; ++y)
		{
			for (int x = -1; x <= 1; ++x)
			{
				visibility += shadow_compare(
					shadow_texture,
					projected.xy + vec2(float(x), float(y)) * step_size,
					receiver_depth
				);
			}
		}
		return visibility / 9.0;
	}

	for (int y = -2; y <= 2; ++y)
	{
		for (int x = -2; x <= 2; ++x)
		{
			visibility += shadow_compare(
				shadow_texture,
				projected.xy + vec2(float(x), float(y)) * step_size,
				receiver_depth
			);
		}
	}
	return visibility / 25.0;
}

#endif
