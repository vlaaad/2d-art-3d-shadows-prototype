-- The native Automation Bridge Lua API exists only in debug builds.
-- Keep gameplay independent of it, without installing a fake global API.
if automation_bridge then
	return automation_bridge
end

local function noop() end

return {
	annotate = noop,
	command = noop,
	describe = noop,
	publish = noop,
}
