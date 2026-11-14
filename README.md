# Hypr Underlay

Turn an application window into a live desktop background—without floating the
terminal in front of it. Works with Firefox Picture-in-Picture and other apps.
Video stays in the original application; there is no capture or second player.

**Experimental. Currently targets Hyprland v0.56.2 only. Native plugin bugs can
terminate your whole desktop session. Save your work before trying it.**

## Two separate parts

| Component | Purpose |
| --- | --- |
| Native `hypr-underlay.so` + Python controller | Render and restore the selected window; works without Omarchy |
| Optional Omarchy service `pastleo.hypr-underlay` | Manage the keyboard shortcut and shell/config-reload lifecycle |

The default shortcut is **Super+Alt+B**: press once to background the focused
app, then again to restore it. The background fills its existing monitor and
follows that monitor's workspaces. Only one background is supported.

## Install

This is a local Arch package workflow for Omarchy—not an AUR publication.
The directory is still named `packaging/aur`, but no AUR account or helper is
needed. Requires `base-devel`, Git, Lua for build-time tests, and the supported
Hyprland version with matching headers. Run as your normal user, not root:

```sh
git clone https://github.com/pastleo/hypr-underlay.git
cd hypr-underlay/packaging/aur
makepkg -si
hypr-underlay companion-enable
```

`makepkg -si` builds and installs **both parts** as `hypr-underlay-git`, with
pacman tracking the system files. It may request sudo for dependency/package
installation. The recipe builds the latest upstream Git revision.

`companion-enable` registers the installed Omarchy service for your user and
enables **Super+Alt+B**, without editing `bindings.lua`. It refuses to overwrite
an existing registration or conflicting shortcut. Package installation itself
does not enable anything or load code into the running compositor.

Installed files:

- `/usr/bin/hypr-underlay`
- `/usr/lib/hypr-underlay/hypr-underlay.so`
- `/usr/share/hypr-underlay/omarchy-plugin/`

If migrating from an earlier manual installation, disable the old companion,
remove only its development symlink, and run `make uninstall` from that old
checkout first. Do not leave an old `$HOME/.local/bin/hypr-underlay` shadowing
the packaged command.

## Use

Focus an application and press **Super+Alt+B** to background it. Press again to
restore it, regardless of which window is now focused. The native library loads
only while a background is active; do not configure it to autoload separately.

```sh
hypr-underlay status
hypr-underlay off --if-active        # restore, safe even when inactive
hypr-underlay on                     # automatically select the only Firefox PiP
hypr-underlay on --window 0xADDRESS   # explicit address from hyprctl clients
```

Running `hypr-underlay toggle` from a terminal targets that terminal. Prefer the
shortcut when selecting another app. The companion manages shortcut and window
rules across shell/Hyprland-config reloads. There is no periodic polling,
network access, or automatic compilation at runtime.

### Change the shortcut

Create `${XDG_CONFIG_HOME:-$HOME/.config}/hypr-underlay/config.json`:

```json
{ "shortcut": "SUPER + ALT + U" }
```

Supported combinations use distinct `SUPER`, `ALT`, `CTRL`, and/or `SHIFT`
modifiers plus a single letter. Disable/re-enable the service to apply changes.
Conflicts are logged by the shell; another binding is never removed.

## Update

From the existing checkout's `packaging/aur` directory:

```sh
hypr-underlay off --if-active
git pull
makepkg -sif
```

The native plugin checks the exact ABI/build hash. The package deliberately
depends on `hyprland=0.56.2`; a newer Hyprland needs a tested code port, not just
a rebuild. **Remove Underlay rather than holding back system upgrades** if that
dependency blocks an upgrade. Local packages are not automatically rebuilt when
a dependency's ABI changes.

## Uninstall

Run in each desktop session that enabled the companion, before removing files:

```sh
hypr-underlay companion-disable
sudo pacman -R hypr-underlay-git
```

The first command disables the service, restores the background, and removes
only this installation's registration symlink. Settings and private restoration
data under `${XDG_STATE_HOME:-$HOME/.local/state}/hypr-underlay/` are preserved.
Do not delete that data before successful restoration. Root package hooks cannot
safely restore another user's compositor session.

## Behavior and limits

- The selected target temporarily becomes floating and non-focusable.
  Foreground terminals/unrelated apps retain their layout.
- Floating windows regain their geometry and pin/fullscreen state. Tiled apps
  return to their original workspace/tiling, not their exact old split position.
- Grouped, hidden and special-workspace windows are rejected.
- Closing the background app is safe; toggle/off cleans up the remaining state.
- Session locking, screen sharing, hotplug, blur optimizations and interactions
  with other native plugins still need broader testing. Do not treat this as a
  security/privacy feature or leave sensitive content in a background.
- This does not add Netflix support to another player or bypass DRM.

## Development

`RENDER_POST_WALLPAPER` inserts the target's normal render pass above wallpaper
and below bottom layers/tiled windows. One internal `renderWindow` hook skips
its later floating draw. No surface is converted to layer-shell; Hyprland still
manages client buffers, frame callbacks and damage.

```sh
make check
make validate                      # Omarchy manifest + Lua syntax
python3 tests/nested_smoke.py        # opt-in isolated compositor integration
python3 tests/aur_smoke.py           # Arch package build, no installation
```

Unit tests require Lua and Python. Integration also needs a Wayland parent,
Quickshell, `foot`, `grim`, and Python Pillow. It uses separate runtime/state,
denies the nested DRM seat backend, and loads no desktop configuration.
Synthetic screenshots and logs stay in ignored `build/`.
For Unix-socket path limits, use a short temporary directory; override it with
`HYPR_UNDERLAY_TEST_TMPDIR` if your system's default is too long.

Low-level debugging commands (prefer the controller for real use):

```sh
hyprctl plugin load "$PWD/build/hypr-underlay.so"
hyprctl underlay on address:0xADDRESS
hyprctl underlay-status
hyprctl underlay off
hyprctl plugin unload "$PWD/build/hypr-underlay.so"
```

Use `hyprctl -i INSTANCE` to select an isolated test compositor. Loading native
code into the wrong instance risks that entire session.

For unprivileged source experiments, `make && make install` installs both parts
under `$HOME/.local`; `make uninstall` removes them. Use
`python3 tools/hypr_underlay.py` directly to prefer the checkout's build.
`tests/aur_smoke.py` builds against a disposable local Git fixture, inspects the
combined package and relocated paths, and never installs it or contacts GitHub.

## License

[MIT](LICENSE).
