local M = {}

local MSG_SET_SHADOW = hash("set_directional_shadow")
local MSG_SET_LIGHTING = hash("set_day_lighting")
local SHADOW_SAMPLER = "shadow_map"

local function clip_to_texture_matrix()
	local matrix = vmath.matrix4()
	matrix.c0 = vmath.vector4(0.5, 0.0, 0.0, 0.0)
	matrix.c1 = vmath.vector4(0.0, 0.5, 0.0, 0.0)
	matrix.c2 = vmath.vector4(0.0, 0.0, 0.5, 0.0)
	matrix.c3 = vmath.vector4(0.5, 0.5, 0.5, 1.0)
	return matrix
end

local function create_target(name, resolution)
	local depth = {
		format = graphics.TEXTURE_FORMAT_DEPTH,
		width = resolution,
		height = resolution,
		min_filter = graphics.TEXTURE_FILTER_NEAREST,
		mag_filter = graphics.TEXTURE_FILTER_NEAREST,
		u_wrap = graphics.TEXTURE_WRAP_CLAMP_TO_EDGE,
		v_wrap = graphics.TEXTURE_WRAP_CLAMP_TO_EDGE,
		flags = render.TEXTURE_BIT,
	}
	return render.render_target(name, {
		[graphics.BUFFER_TYPE_DEPTH_BIT] = depth,
	})
end

function M.init(target_name)
	local context = {
		target_name = target_name,
		camera = nil,
		target = nil,
		resolution = 0,
		clip_to_texture = clip_to_texture_matrix(),
		constants = render.constant_buffer(),
		polygon_offset_factor = 2.0,
		polygon_offset_units = 4.0,
	}
	context.constants.shadow_params = vmath.vector4(3.0, 1.0, 0.0008, 0.002)
	context.constants.sun_direction = vmath.vector4(-0.5, -0.8, -0.3, 0.0)
	context.constants.day_tint = vmath.vector4(1.0, 1.0, 1.0, 1.0)
	context.constants.lighting = vmath.vector4(0.35, 0.75, 0.58, 1.0)
	return context
end

function M.final(context)
	if context and context.target then
		render.delete_render_target(context.target)
		context.target = nil
	end
end

function M.on_message(context, message_id, message)
	if message_id == MSG_SET_SHADOW then
		context.camera = message.camera
		local resolution = math.max(1, math.floor(message.resolution or 1024))
		if not context.target or context.resolution ~= resolution then
			if context.target then
				render.delete_render_target(context.target)
			end
			context.target = create_target(context.target_name, resolution)
			context.resolution = resolution
			context.constants.shadow_texel_size = vmath.vector4(1.0 / resolution, 1.0 / resolution, 0.0, 0.0)
		end
		context.polygon_offset_factor = message.polygon_offset_factor or 2.0
		context.polygon_offset_units = message.polygon_offset_units or 4.0
		context.constants.shadow_params = vmath.vector4(
			message.pcf_kernel_size or 3.0,
			message.pcf_sample_spacing or 1.0,
			message.receiver_min_bias or 0.0008,
			message.receiver_slope_bias or 0.002
		)
		return true
	elseif message_id == MSG_SET_LIGHTING then
		context.constants.sun_direction = message.sun_direction
		context.constants.day_tint = message.day_tint
		context.constants.lighting = message.lighting
		return true
	end
	return false
end

function M.render_depth(context, caster_predicate)
	if not context.target or not context.camera then
		return
	end

	local view = camera.get_view(context.camera)
	local projection = camera.get_projection(context.camera)
	local frustum = projection * view
	context.constants.mtx_shadow = context.clip_to_texture * frustum

	render.set_render_target(context.target)
	render.set_viewport(0, 0, context.resolution, context.resolution)
	render.set_camera()
	render.set_view(view)
	render.set_projection(projection)
	render.set_color_mask(false, false, false, false)
	render.set_depth_mask(true)
	render.set_depth_func(graphics.COMPARE_FUNC_LEQUAL)
	render.enable_state(graphics.STATE_DEPTH_TEST)
	render.enable_state(graphics.STATE_CULL_FACE)
	render.set_cull_face(graphics.FACE_TYPE_BACK)
	render.disable_state(graphics.STATE_BLEND)
	render.enable_state(graphics.STATE_POLYGON_OFFSET_FILL)
	render.set_polygon_offset(context.polygon_offset_factor, context.polygon_offset_units)
	render.clear({ [graphics.BUFFER_TYPE_DEPTH_BIT] = 1.0 })
	render.draw(caster_predicate, {
		frustum = frustum,
		frustum_planes = render.FRUSTUM_PLANES_ALL,
	})
	render.set_polygon_offset(0.0, 0.0)
	render.disable_state(graphics.STATE_POLYGON_OFFSET_FILL)
	render.set_color_mask(true, true, true, true)
	render.set_render_target(render.RENDER_TARGET_DEFAULT)
end

function M.render_receivers(context, receiver_predicate)
	if not context.target then
		render.draw(receiver_predicate)
		return
	end
	render.enable_texture(SHADOW_SAMPLER, context.target, graphics.BUFFER_TYPE_DEPTH_BIT)
	render.draw(receiver_predicate, { constants = context.constants })
	render.disable_texture(SHADOW_SAMPLER)
end

return M
