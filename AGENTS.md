# Development

- Hypr Underlay has an experimental native Hyprland plugin, an independent
  Python controller, and an optional Omarchy shell service.
- Compile against installed headers matching the running compositor. Review the
  exact upstream renderer before changing hook signatures or render ordering.
- Test in an isolated/headless compositor before loading into a user's desktop.
- Never autoload the plugin, change unrelated windows' layouts, or modify
  packaged Omarchy files as part of an experiment. The explicit target may
  temporarily become floating and must be restored afterward.
- Keep local diagnostics and session details in ignored `AGENTS.local.md`.
- `make` builds the plugin; `make check` runs controller tests.
- Builds must atomically replace the shared object; never truncate a binary
  that may currently be mapped into a compositor.
- Never broadly unbind/remove runtime binding handles on Hyprland v0.56.2.
  Use safe expiry checks and disable/reuse handles. Preserve owner tokens and
  cancellation tombstones so delayed teardown cannot disable a new service.
- The companion must detect shortcut conflicts and recover after compositor
  reload. It must not compile code or load native code merely by being enabled.
- Run `make validate` for the manifest/Lua, and `python3 tests/nested_smoke.py`
  for native rendering, installation/uninstallation, and real Quickshell
  lifecycle tests. These require a disposable runtime, never the live desktop.
- Keep examples portable and private handoff notes ignored. Do not publish,
  configure remotes, commit, or push unless explicitly requested.
- `packaging/aur/` contains a local Arch native/controller/companion VCS recipe,
  not an AUR publication plan. Keep `.SRCINFO` synchronized and installation
  guidance in the root README. Package hooks must never modify user homes or
  interact with user compositor sessions as root.
- `python3 tests/aur_smoke.py` exercises makepkg against a disposable local Git
  fixture, without package installation or remote publication. Packaged Omarchy
  payloads are registered explicitly through the normal user's controller.
