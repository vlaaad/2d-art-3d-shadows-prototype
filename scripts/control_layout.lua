local layout = require "scripts.vendor.layout"

local M = {}

-- Shared by rendering, sprite placement and input: all use the same HUD space.
function M.viewport(width, height, display_scale)
	-- Fixed display-scaled sizes: orientation changes placement, never size.
	local scale = display_scale or 1
	return width / scale, height / scale, scale
end

function M.apply(width, height, display_scale)
	local w, h, scale = M.viewport(width, height, display_scale)
	local tree = layout.with_layers({ "base", "thumb" }, layout.padding(24, layout.stack({
		layout.align(0, 0, layout.min_size(160, 160, layout.stack({
			layout.on_layer("base", layout.id("stick")),
			layout.align(0.5, 0.5, layout.min_size(64, 64, layout.on_layer("thumb", layout.id("thumb")))),
		}))),
		layout.align(1, 1, layout.min_size(80, 80, layout.on_layer("base", layout.id("cycle")))),
	})))
	return layout.apply(tree, 0, 0, w, h, 0, 0.8), scale
end

return M
