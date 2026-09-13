#version 140

out vec4 out_fragColor;

void main()
{
	// Intentionally loud: overlap and pivot errors must be obvious over the art.
	out_fragColor = vec4(0.0, 0.9, 1.0, 0.32);
}
