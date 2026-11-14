-- Standalone test configuration. Never source into a desktop configuration.
hl.monitor({ output = "", mode = "960x540@60", position = "auto", scale = 1 })
hl.config({
    general = { gaps_in = 0, gaps_out = 0, border_size = 0, layout = "dwindle" },
    decoration = { rounding = 0, blur = { enabled = false }, shadow = { enabled = false } },
    animations = { enabled = false },
    input = { follow_mouse = 0 },
    misc = { disable_hyprland_logo = true, disable_splash_rendering = true,
             disable_watchdog_warning = true, disable_xdg_env_checks = true },
    ecosystem = { no_donation_nag = true, no_update_news = true, enforce_permissions = false },
    xwayland = { enabled = false },
})
hl.window_rule({
    match = { class = "firefox", title = "^Picture-in-Picture$" },
    float = true, size = { 960, 540 }, move = { 0, 0 },
    no_focus = true, no_follow_mouse = true, no_anim = true,
    decorate = false, no_blur = true, no_shadow = true,
    opacity = "1 override 1 override 1 override",
})
