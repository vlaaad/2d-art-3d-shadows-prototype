local M = {}

---@class ScreenRect
---@field x number
---@field y number
---@field w number
---@field h number
---@field z number?

---@alias Layout LayoutId|LayoutMinSize|LayoutAlign|LayoutPadding|LayoutHorizontal|LayoutVertical|LayoutStack|LayoutWithLayers|LayoutOnLayer

---@class LayoutId
---@field type "id"
---@field id string
---@field child Layout?

---@param id string
---@param child Layout?
---@return LayoutId
function M.id(id, child)
    return { type = "id", id = id, child = child }
end

---@class LayoutMinSize
---@field type "min_size"
---@field min_width number
---@field min_height number
---@field child Layout?

---@param min_width number
---@param min_height number
---@param child Layout?
---@return LayoutMinSize
function M.min_size(min_width, min_height, child)
    return { type = "min_size", min_width = min_width, min_height = min_height, child = child }
end

---@class LayoutAlign
---@field type "align"
---@field horizontal number
---@field vertical number
---@field child Layout

---@param horizontal number
---@param vertical number
---@param child Layout
---@return LayoutAlign
function M.align(horizontal, vertical, child)
    return { type = "align", horizontal = horizontal, vertical = vertical, child = child }
end

---@class LayoutPadding
---@field type "padding"
---@field padding number
---@field child Layout

---@param padding number
---@param child Layout
---@return LayoutPadding
function M.padding(padding, child)
    return { type = "padding", padding = padding, child = child }
end

---@class LayoutHorizontal
---@field type "horizontal"
---@field children Layout[]
---@field spacing number
---@field expanded_child_index integer?

---@param children Layout[]
---@param spacing number
---@param expanded_child_index integer?
---@return LayoutHorizontal
function M.horizontal(children, spacing, expanded_child_index)
    return { type = "horizontal", children = children, spacing = spacing, expanded_child_index = expanded_child_index }
end

---@class LayoutVertical
---@field type "vertical"
---@field children Layout[]
---@field spacing number
---@field expanded_child_index integer?

---@param children Layout[]
---@param spacing number
---@param expanded_child_index integer?
---@return LayoutVertical
function M.vertical(children, spacing, expanded_child_index)
    return { type = "vertical", children = children, spacing = spacing, expanded_child_index = expanded_child_index }
end

---@class LayoutStack
---@field type "stack"
---@field children Layout[]

---@param children Layout[]
---@return LayoutStack
function M.stack(children)
    return { type = "stack", children = children }
end

---@class LayoutWithLayers
---@field type "with_layers"
---@field layers string[]
---@field child Layout

---@param layers string[]
---@param child Layout
---@return LayoutWithLayers
function M.with_layers(layers, child)
    return { type = "with_layers", layers = layers, child = child }
end

---@class LayoutOnLayer
---@field type "on_layer"
---@field layer string
---@field child Layout

---@param layer string
---@param child Layout
---@return LayoutOnLayer
function M.on_layer(layer, child)
    return { type = "on_layer", layer = layer, child = child }
end

---@param layout LayoutHorizontal|LayoutVertical
---@param min_size_on_main_axis fun(layout: Layout): number
---@return number
local function min_list_size_on_main_axis(layout, min_size_on_main_axis)
    local children = layout.children
    local n = #children
    if n == 0 then
        return 0
    end

    local acc = 0
    for i = 1, n do
        acc = acc + min_size_on_main_axis(children[i])
    end
    return acc + (n - 1) * layout.spacing
end

---@param children Layout[]
---@param min_size_on_alt_axis fun(layout: Layout): number
---@return number
local function max_children_min_size(children, min_size_on_alt_axis)
    local max = 0
    for i = 1, #children do
        max = math.max(max, min_size_on_alt_axis(children[i]))
    end
    return max
end

---@param layout Layout
---@return number
local function min_width(layout)
    local t = layout.type
    if t == "id" then
        return layout.child and min_width(layout.child) or 0
    elseif t == "min_size" then
        return math.max(layout.min_width, layout.child and min_width(layout.child) or 0)
    elseif t == "align" then
        return min_width(layout.child)
    elseif t == "padding" then
        return min_width(layout.child) + layout.padding * 2
    elseif t == "horizontal" then
        ---@cast layout LayoutHorizontal
        return min_list_size_on_main_axis(layout, min_width)
    elseif t == "vertical" or t == "stack" then
        return max_children_min_size(layout.children, min_width)
    elseif t == "with_layers" or t == "on_layer" then
        return min_width(layout.child)
    end
    error("unknown layout type: " .. tostring(t))
end

---@param layout Layout
---@return number
local function min_height(layout)
    local t = layout.type
    if t == "id" then
        return layout.child and min_height(layout.child) or 0
    elseif t == "min_size" then
        return math.max(layout.min_height, layout.child and min_height(layout.child) or 0)
    elseif t == "align" then
        return min_height(layout.child)
    elseif t == "padding" then
        return min_height(layout.child) + layout.padding * 2
    elseif t == "horizontal" or t == "stack" then
        return max_children_min_size(layout.children, min_height)
    elseif t == "vertical" then
        ---@cast layout LayoutVertical
        return min_list_size_on_main_axis(layout, min_height)
    elseif t == "with_layers" or t == "on_layer" then
        return min_height(layout.child)
    end
    error("unknown layout type: " .. tostring(t))
end

---@param rects table<string, ScreenRect>
---@param id string
---@param x number
---@param y number
---@param w number
---@param h number
---@param z number?
local function set_rect(rects, id, x, y, w, h, z)
    rects[id] = { x = x, y = y, w = w, h = h, z = z }
end

---@class LayoutLayerBand
---@field start_z number
---@field end_z number

---@param layers string[]
---@param start_z number
---@param end_z number
---@param reserve_start boolean
---@return table<string, LayoutLayerBand>
local function create_layer_scope(layers, start_z, end_z, reserve_start)
    local step = (end_z - start_z) / (#layers + (reserve_start and 1 or 0))
    local first_index = reserve_start and 1 or 0
    local scope = {}
    for i = 1, #layers do
        local band_start = start_z + step * (i - 1 + first_index)
        scope[layers[i]] = {
            start_z = band_start,
            end_z = band_start + step,
        }
    end
    return scope
end

---@param layout Layout
---@param x number
---@param y number
---@param w number
---@param h number
---@param min_z number
---@param max_z number
---@return table<string, ScreenRect>
function M.apply(layout, x, y, w, h, min_z, max_z)
    local rects = {}

    ---@param node Layout
    ---@param nx number
    ---@param ny number
    ---@param nw number
    ---@param nh number
    ---@param z number?
    ---@param band_start_z number?
    ---@param band_end_z number?
    ---@param scope table<string, LayoutLayerBand>?
    local function visit(node, nx, ny, nw, nh, z, band_start_z, band_end_z, scope)
        local t = node.type
        if t == "id" then
            set_rect(rects, node.id, nx, ny, nw, nh, z)
            if node.child then
                visit(node.child, nx, ny, nw, nh, z, band_start_z, band_end_z, scope)
            end
        elseif t == "min_size" then
            if node.child then
                visit(node.child, nx, ny, nw, nh, z, band_start_z, band_end_z, scope)
            end
        elseif t == "align" then
            ---@cast node LayoutAlign
            local child = node.child
            local cw = min_width(child)
            local ch = min_height(child)
            visit(child, nx + (nw - cw) * node.horizontal, ny + (nh - ch) * node.vertical, cw, ch, z, band_start_z, band_end_z, scope)
        elseif t == "padding" then
            local p2 = node.padding * 2
            visit(node.child, nx + node.padding, ny + node.padding, math.max(0, nw - p2), math.max(0, nh - p2), z, band_start_z, band_end_z, scope)
        elseif t == "horizontal" then
            local children = node.children
            local spacing = node.spacing
            local expanded_child_index = node.expanded_child_index
            if expanded_child_index then
                local left_w = 0
                for i = 1, expanded_child_index - 1 do
                    local child = children[i]
                    local cw = min_width(child)
                    visit(child, nx + left_w, ny, cw, nh, z, band_start_z, band_end_z, scope)
                    left_w = left_w + cw + spacing
                end

                local right_w = 0
                local right_edge = nx + nw
                for i = #children, expanded_child_index + 1, -1 do
                    local child = children[i]
                    local cw = min_width(child)
                    right_w = right_w + cw
                    visit(child, right_edge - right_w, ny, cw, nh, z, band_start_z, band_end_z, scope)
                    right_w = right_w + spacing
                end

                visit(children[expanded_child_index], nx + left_w, ny, math.max(0, nw - left_w - right_w), nh, z, band_start_z, band_end_z, scope)
            else
                local dx = 0
                for i = 1, #children do
                    local child = children[i]
                    local cw = min_width(child)
                    visit(child, nx + dx, ny, cw, nh, z, band_start_z, band_end_z, scope)
                    dx = dx + cw + spacing
                end
            end
        elseif t == "vertical" then
            local children = node.children
            local spacing = node.spacing
            local expanded_child_index = node.expanded_child_index
            if expanded_child_index then
                local bottom_h = 0
                for i = 1, expanded_child_index - 1 do
                    local child = children[i]
                    local ch = min_height(child)
                    visit(child, nx, ny + bottom_h, nw, ch, z, band_start_z, band_end_z, scope)
                    bottom_h = bottom_h + ch + spacing
                end

                local top_h = 0
                local top_edge = ny + nh
                for i = #children, expanded_child_index + 1, -1 do
                    local child = children[i]
                    local ch = min_height(child)
                    top_h = top_h + ch
                    visit(child, nx, top_edge - top_h, nw, ch, z, band_start_z, band_end_z, scope)
                    top_h = top_h + spacing
                end

                visit(children[expanded_child_index], nx, ny + bottom_h, nw, math.max(0, nh - bottom_h - top_h), z, band_start_z, band_end_z, scope)
            else
                local dy = 0
                for i = 1, #children do
                    local child = children[i]
                    local ch = min_height(child)
                    visit(child, nx, ny + dy, nw, ch, z, band_start_z, band_end_z, scope)
                    dy = dy + ch + spacing
                end
            end
        elseif t == "stack" then
            for i = 1, #node.children do
                visit(node.children[i], nx, ny, nw, nh, z, band_start_z, band_end_z, scope)
            end
        elseif t == "with_layers" then
            local start_z = band_start_z or min_z
            local end_z = band_end_z or max_z
            local layer_scope = create_layer_scope(node.layers, start_z, end_z, band_start_z ~= nil)
            visit(node.child, nx, ny, nw, nh, nil, nil, nil, layer_scope)
        elseif t == "on_layer" then
            assert(scope, "layout on_layer requires a layer scope")
            local band = scope[node.layer]
            visit(node.child, nx, ny, nw, nh, band.start_z, band.start_z, band.end_z, scope)
        else
            error("unknown layout type: " .. tostring(t))
        end
    end

    visit(layout, x, y, w, h)
    return rects
end

M.min_width = min_width
M.min_height = min_height

return M
