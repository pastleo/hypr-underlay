-- Runtime binding owner. Never remove/unbind native handles on Hyprland 0.56.
local M = {}
local key = "__hyprUnderlayShortcut"

local function live(binding)
  return binding and not tostring(binding):find("(expired)", 1, true)
end

function M.install(owner, shortcut, command)
  local retired = rawget(_G, "__hyprUnderlayRetired") or {}
  if retired[owner] then return false end
  local runtime = rawget(_G, key)
  if not runtime then
    runtime = { bindings = {} }
    rawset(_G, key, runtime)
    function runtime.deactivate()
      runtime.active = false
      for _, binding in pairs(runtime.bindings) do
        if live(binding) then binding:set_enabled(false) end
      end
    end
    function runtime.invoke()
      if runtime.active then hl.exec_cmd(runtime.command) end
    end
  end
  runtime.deactivate()
  runtime.owner, runtime.command, runtime.active = owner, command, true
  local binding = runtime.bindings[shortcut]
  if not live(binding) then
    binding = hl.bind(shortcut, runtime.invoke,
      { description = "Hypr Underlay: toggle focused window" })
    runtime.bindings[shortcut] = binding
  end
  binding:set_enabled(true)
  return true
end

return M
