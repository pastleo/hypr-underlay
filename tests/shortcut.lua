local created, commands = {}, {}
hl = {
  bind = function(shortcut, callback, options)
    local binding = { shortcut = shortcut, callback = callback, enabled = true }
    function binding:set_enabled(value)
      assert(not self.expired, "touched expired native handle")
      self.enabled = value
    end
    setmetatable(binding, { __tostring = function(self)
      return self.expired and "HL.Keybind(expired)" or "HL.Keybind(test)"
    end })
    created[#created + 1] = binding
    return binding
  end,
  exec_cmd = function(command) commands[#commands + 1] = command end,
  unbind = function() error("must never broadly unbind") end,
}
local shortcut = dofile("hypr/shortcut.lua")
assert(shortcut.install("a", "SUPER + ALT + B", "first"))
created[1].callback()
assert(commands[1] == "first")
assert(shortcut.install("b", "SUPER + ALT + B", "second"))
assert(#created == 1, "must reuse binding")
created[1].callback()
assert(commands[2] == "second")
_G.__hyprUnderlayShortcut.deactivate()
assert(not created[1].enabled)
created[1].callback()
assert(#commands == 2)
created[1].expired = true
assert(shortcut.install("c", "SUPER + ALT + B", "third"))
assert(#created == 2, "must replace expired handle without touching it")
assert(shortcut.install("d", "SUPER + ALT + U", "fourth"))
assert(not created[2].enabled and created[3].enabled)
_G.__hyprUnderlayRetired = { late = true }
assert(not shortcut.install("late", "SUPER + ALT + B", "bad"))
assert(_G.__hyprUnderlayShortcut.owner == "d")
print("PASS: shortcut reuse, safe expiry, disable, owner handover and cancellation")
