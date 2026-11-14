#!/usr/bin/env python3
"""Explicit, reversible controller. Never edits a Hyprland config file."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import shutil
import shlex
import time

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "hypr-underlay.so"
def installation_prefix(root):
    if root.name == "omarchy-plugin" and root.parent.name == "hypr-underlay":
        return root.parents[2]  # PREFIX/share/hypr-underlay/omarchy-plugin
    return root


PREFIX = installation_prefix(ROOT)


def find_plugin():
    if os.environ.get("HYPR_UNDERLAY_PLUGIN"):
        return Path(os.environ["HYPR_UNDERLAY_PLUGIN"]).expanduser()
    return next((path for path in (
        ROOT / "build" / PLUGIN_NAME,
        PREFIX / "lib/hypr-underlay" / PLUGIN_NAME,
        Path("/usr/lib/hypr-underlay") / PLUGIN_NAME,
        Path.home() / ".local/lib/hypr-underlay" / PLUGIN_NAME,
    ) if path.is_file()), ROOT / "build" / PLUGIN_NAME)


PLUGIN = find_plugin()
COMPANION = next((path for path in (
    PREFIX / "share/hypr-underlay/omarchy-plugin",
    ROOT,
    Path("/usr/share/hypr-underlay/omarchy-plugin"),
    Path.home() / ".local/share/hypr-underlay/omarchy-plugin",
) if (path / "manifest.json").is_file()), ROOT)
COMPANION_ID = "pastleo.hypr-underlay"
TAG = "hypr-underlay"
RULE = "hyprUnderlayWindowRule"
REGISTRY = "__hyprUnderlayShortcut"
DESCRIPTION = "Hypr Underlay: toggle focused window"


def select_pip(clients, address=None):
    candidates = [
        w for w in clients
        if w["class"] == "firefox" and w["title"] == "Picture-in-Picture"
        and w["mapped"] and w["floating"] and w["workspace"]["id"] > 0
        and (address is None or w["address"] == address)
    ]
    if len(candidates) != 1:
        raise ValueError("Open one Firefox PiP first, or select one with --window 0xADDRESS.")
    return candidates[0]


def select_window(clients, address):
    window = next((w for w in clients if w["address"] == address), None)
    if not window or not window["mapped"] or window.get("hidden") or window["workspace"]["id"] <= 0:
        raise ValueError("Focus a normal application window first (not a hidden or scratchpad window).")
    if window.get("grouped"):
        raise ValueError("Ungroup this window before using it as a background.")
    return window


def monitor_geometry(monitor):
    width, height = monitor["width"], monitor["height"]
    if monitor["transform"] % 2:
        width, height = height, width
    scale = monitor["scale"]
    return monitor["x"], monitor["y"], round(width / scale), round(height / scale)


def same_window(saved, current):
    return all(saved.get(key) == current.get(key) for key in ("address", "pid", "stableId"))


def lua_string(value):
    return '"' + "".join(
        "\\" + f"{ord(c):03d}" if c in '\\"' or ord(c) < 32 else c for c in str(value)
    ) + '"'


def shortcut_spec(text):
    parts = [part.strip().upper() for part in text.split("+")]
    modifiers = {"SUPER": 64, "ALT": 8, "CTRL": 4, "SHIFT": 1}
    if len(parts) < 2 or not re.fullmatch("[A-Z]", parts[-1]):
        raise ValueError("Shortcut must use modifiers and one letter, e.g. SUPER + ALT + B.")
    if any(part not in modifiers for part in parts[:-1]) or len(set(parts[:-1])) != len(parts[:-1]):
        raise ValueError("Use distinct SUPER, ALT, CTRL and/or SHIFT modifiers.")
    return " + ".join(parts), sum(modifiers[part] for part in parts[:-1]), parts[-1]


def shortcut_conflict(bindings, mask, key):
    # Include physical-key bindings too (evdev letter codes + the XKB offset).
    physical = {"A": 38, "B": 56, "C": 54, "D": 40, "E": 26, "F": 41, "G": 42,
                "H": 43, "I": 31, "J": 44, "K": 45, "L": 46, "M": 58, "N": 57,
                "O": 32, "P": 33, "Q": 24, "R": 27, "S": 39, "T": 28, "U": 30,
                "V": 55, "W": 25, "X": 53, "Y": 29, "Z": 52}
    return next((binding for binding in bindings
                 if binding.get("modmask") == mask
                 and (binding.get("key", "").upper() == key or binding.get("keycode") == physical[key])
                 and binding.get("description") != DESCRIPTION), None)


def companion_link():
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "omarchy/plugins" / COMPANION_ID


def register_companion(target):
    link = companion_link()
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return link
        raise ValueError("A different Hypr Underlay companion is registered. Disable/remove that registration before switching installations.")
    if link.exists():
        raise ValueError("Companion path already exists; refusing to overwrite it.")
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target.resolve(), target_is_directory=True)
    return link


def omarchy(*args):
    if os.geteuid() == 0:
        raise ValueError("Run companion commands as your desktop user, not root.")
    process = subprocess.run(["omarchy", *args], capture_output=True, text=True, timeout=10)
    if process.returncode:
        raise RuntimeError(process.stdout.strip() + "\n" + process.stderr.strip())
    return process.stdout.strip()


def companion_enable():
    if os.geteuid() == 0:
        raise ValueError("Run companion-enable as your desktop user, not root.")
    if not (COMPANION / "omarchy/Underlay.qml").is_file():
        raise ValueError("Companion payload is not installed.")
    if not shutil.which("omarchy"):
        raise ValueError("Omarchy is required for the optional companion.")
    register_companion(COMPANION)
    omarchy("shell", "shell", "rescanPlugins")
    # Registry scans are asynchronous. Wait for discovery, not repeated enables.
    for _ in range(30):
        plugins = json.loads(omarchy("plugin", "list", "--json"))
        if any(plugin["id"] == COMPANION_ID for plugin in plugins):
            print(omarchy("plugin", "enable", COMPANION_ID))
            return
        time.sleep(0.1)
    raise RuntimeError("Companion registered but discovery is still pending; run omarchy plugin enable " + COMPANION_ID)


def companion_disable(instance):
    link = companion_link()
    if not link.is_symlink() or link.resolve() != COMPANION.resolve():
        raise ValueError("No registration owned by this installation; use the matching checkout/installation to disable it.")
    omarchy("plugin", "disable", COMPANION_ID)
    controller = Controller(instance)
    with (controller.directory / "controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # QML destruction launches cleanup asynchronously through the plugin
        # symlink. Stop the current owner before unlinking that path, otherwise
        # the detached helper may never start and leave its shortcut enabled.
        owner = controller.ctl(
            "repl", f"local r=rawget(_G,{lua_string(REGISTRY)}); return r and r.active and r.owner or ''"
        )
        if owner:
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", owner):
                raise ValueError("Invalid active companion owner; registration was preserved.")
            controller.service_stop(owner)
        controller.disable(if_active=True)
        link.unlink()
    omarchy("shell", "shell", "rescanPlugins")
    print("Omarchy companion disabled and this installation's registration removed.")


class Controller:
    def __init__(self, instance):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", instance):
            raise ValueError("Missing or invalid Hyprland instance; set HYPRLAND_INSTANCE_SIGNATURE or --instance.")
        self.instance = instance
        state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        self.directory = state_home / "hypr-underlay" / instance
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_file = self.directory / "trial.json"

    def ctl(self, *args):
        process = subprocess.run(
            ["hyprctl", "-i", self.instance, *args],
            capture_output=True, text=True, timeout=10,
        )
        output = process.stdout.strip()
        if process.returncode or output.startswith("error:"):
            raise RuntimeError(f"hyprctl {' '.join(args)}: {output} {process.stderr.strip()}")
        return output

    def ok(self, *args):
        output = self.ctl(*args)
        if output != "ok":
            raise RuntimeError(output)

    def dispatch(self, function, **args):
        # All values here are numbers, strings or booleans, which JSON encodes
        # compatibly with Lua literals. Keys come only from this source file.
        fields = ", ".join(f"{key}={json.dumps(value)}" for key, value in args.items())
        self.ok("dispatch", f"hl.dsp.{function}({{{fields}}})")

    def plugin_loaded(self):
        return any(p["name"] == "hypr-underlay" for p in json.loads(self.ctl("plugin", "list", "-j")))

    def enable(self, address=None, active=False, owner=None):
        if self.state_file.exists():
            raise ValueError("A saved trial exists. Run off first; refusing to overwrite restoration data.")
        clients = json.loads(self.ctl("clients", "-j"))
        if active or address:
            address = address or json.loads(self.ctl("activewindow", "-j")).get("address")
            window = select_window(clients, address)
        else:
            window = select_pip(clients)
        # An explicit target and the active-window toggle are generic. Preserve
        # the old no-argument `on` behavior for Firefox PiP users.
        generic = active or address is not None
        monitor = next(m for m in json.loads(self.ctl("monitors", "-j")) if m["id"] == window["monitor"])
        if not PLUGIN.is_file():
            raise ValueError("Plugin not built. Run make first.")
        if self.plugin_loaded():
            raise ValueError("Plugin already loaded outside this controller. Turn it off/unload it first.")
        state = {"window": window, "plugin": str(PLUGIN), "instance": self.instance, "owner": owner}
        # Exclusive creation before any change, including plugin load.
        with self.state_file.open("x") as file:
            os.chmod(self.state_file, 0o600)
            json.dump(state, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        try:
            self.ok("plugin", "load", str(PLUGIN))
            selector = "address:" + window["address"]
            if window.get("fullscreen", 0) or window.get("fullscreenClient", 0):
                self.dispatch("window.fullscreen_state", window=selector, action="set", internal=0, client=0)
            if not window["floating"]:
                self.dispatch("window.float", window=selector, action="on")
            self.install_rule(selector)
            x, y, width, height = monitor_geometry(monitor)
            self.dispatch("window.resize", window=selector, x=width, y=height)
            self.dispatch("window.move", window=selector, x=x, y=y)
            if generic:
                self.dispatch("window.pin", window=selector, action="on")
            self.ok("underlay", "on", selector)
            remaining = [
                w for w in clients if w["address"] != window["address"] and w["mapped"]
                and not w.get("hidden") and w["monitor"] == window["monitor"]
                and (w["workspace"]["id"] == window["workspace"]["id"] or w["pinned"])
            ]
            if remaining:
                foreground = min(remaining, key=lambda w: w.get("focusHistoryID", 999))
                self.dispatch("focus", window="address:" + foreground["address"])
        except Exception:
            try:
                self.disable()
            except Exception as rollback:
                print(f"Rollback incomplete; restoration data retained: {rollback}", file=sys.stderr)
            raise
        print("Window background enabled. Toggle again or run off to restore.")

    def install_rule(self, selector):
        self.dispatch("window.tag", window=selector, tag="+" + TAG)
        self.ok("eval", f"""
            if {RULE} then {RULE}:set_enabled(false) end
            {RULE} = hl.window_rule({{
                name="hypr-underlay", match={{tag="{TAG}"}},
                no_focus=true, no_follow_mouse=true, no_dim=true,
                decorate=false, border_size=0, rounding=0, no_shadow=true,
                no_blur=true, no_anim=true,
                opacity="1 override 1 override 1 override"
            }})
        """)

    def disable(self, if_active=False):
        if not self.state_file.exists():
            if if_active:
                return
            raise ValueError("No controller-managed trial to restore.")
        state = json.loads(self.state_file.read_text())
        saved = state["window"]
        clients = json.loads(self.ctl("clients", "-j"))
        current = next((w for w in clients if same_window(saved, w)), None)
        if current:
            selector = "address:" + saved["address"]
            # Keep no-focus and background rendering while restoring geometry.
            self.dispatch("window.resize", window=selector, x=saved["size"][0], y=saved["size"][1])
            self.dispatch("window.move", window=selector, x=saved["at"][0], y=saved["at"][1])
            self.dispatch("window.pin", window=selector, action="on" if saved["pinned"] else "off")
        loaded = self.plugin_loaded()
        if loaded:
            self.ok("underlay", "off")
        self.ok("eval", f"if {RULE} then {RULE}:set_enabled(false); {RULE}=nil end")
        if current:
            self.dispatch("window.tag", window="address:" + saved["address"], tag="-" + TAG)
            if saved["floating"] and not saved["pinned"] and current["workspace"]["id"] != saved["workspace"]["id"]:
                self.dispatch("window.move", window=selector, workspace=str(saved["workspace"]["id"]))
            if not saved["floating"]:
                # Reinsert into the original workspace's tiling algorithm.
                # Its previous split/tree position is not reconstructable.
                self.dispatch("window.pin", window=selector, action="off")
                self.dispatch("window.move", window=selector, workspace=str(saved["workspace"]["id"]))
                self.dispatch("window.float", window=selector, action="off")
            if saved.get("fullscreen", 0) or saved.get("fullscreenClient", 0):
                self.dispatch("window.fullscreen_state", window=selector, action="set",
                              internal=saved.get("fullscreen", 0), client=saved.get("fullscreenClient", 0))
        if loaded:
            self.ok("plugin", "unload", state["plugin"])
        self.state_file.unlink()
        print("Window restored; experimental plugin unloaded.")

    def toggle(self, address=None, owner=None):
        if self.state_file.exists():
            self.disable()
        else:
            self.enable(address, active=True, owner=owner)

    def assert_owner(self, owner):
        self.ok("eval", f"local r=rawget(_G,{lua_string(REGISTRY)}); "
                f"assert(r and r.active and r.owner=={lua_string(owner)}, 'Hypr Underlay companion is no longer active')")

    def service_start(self, owner, shortcut=None):
        if not owner:
            raise ValueError("service-start requires --owner.")
        if not PLUGIN.is_file():
            raise ValueError("Native plugin not found. Build/install hypr-underlay first.")
        if shortcut is None:
            config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hypr-underlay/config.json"
            shortcut = json.loads(config.read_text()).get("shortcut") if config.is_file() else None
        shortcut, mask, key = shortcut_spec(shortcut or "SUPER + ALT + B")
        conflict = shortcut_conflict(json.loads(self.ctl("binds", "-j")), mask, key)
        if conflict:
            raise ValueError(f"Shortcut {shortcut} is already bound; choose another shortcut in hypr-underlay/config.json.")
        helper = ROOT / "hypr/shortcut.lua"
        if not helper.is_file():
            raise ValueError("Companion runtime missing. Start the service from its plugin checkout.")
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), "toggle", "--notify", "--owner", owner])
        self.ok("eval", f"assert(dofile({lua_string(helper)}).install("
                f"{lua_string(owner)},{lua_string(shortcut)},{lua_string(command)}), 'Hypr Underlay owner already retired')")
        if self.state_file.exists():
            state = json.loads(self.state_file.read_text())
            current = next((w for w in json.loads(self.ctl("clients", "-j")) if same_window(state["window"], w)), None)
            if current:
                # Recover temporary Lua rules after a compositor config reload.
                selector = "address:" + current["address"]
                self.install_rule(selector)
                if not self.plugin_loaded():
                    self.ok("plugin", "load", state["plugin"])
                self.ok("underlay", "on", selector)
                state["owner"] = owner
                temporary = self.state_file.with_suffix(".new")
                with temporary.open("w") as file:
                    os.chmod(temporary, 0o600)
                    json.dump(state, file)
                temporary.replace(self.state_file)
            else:
                self.disable()
        print("Hypr Underlay shortcut active:", shortcut)

    def service_stop(self, owner):
        if not owner:
            raise ValueError("service-stop requires --owner.")
        # Tombstones handle a stop arriving before a delayed async installation.
        self.ok("eval", f"""
            local cancelled=rawget(_G,"__hyprUnderlayRetired") or {{}}
            rawset(_G,"__hyprUnderlayRetired",cancelled)
            cancelled[{lua_string(owner)}]=true
            local r=rawget(_G,{lua_string(REGISTRY)})
            if r and r.owner=={lua_string(owner)} then r.deactivate() end
        """)
        if self.state_file.exists() and json.loads(self.state_file.read_text()).get("owner") == owner:
            self.disable()

    def status(self):
        if self.plugin_loaded():
            print(self.ctl("underlay-status"))
        else:
            print("Native plugin not loaded (loaded only while a background is active).")
        active = self.ctl("repl", f"local r=rawget(_G,{lua_string(REGISTRY)}); return r and r.active or false")
        print("Omarchy shortcut:", "active" if active == "true" else "inactive")
        if self.state_file.exists():
            print("Restoration data is available; toggle again or run off to restore the window.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("on", "off", "status", "toggle", "service-start", "service-stop",
                                          "companion-enable", "companion-disable"))
    parser.add_argument("--window", help="Specific application address, e.g. 0x1234")
    parser.add_argument("--notify", action="store_true", help="Show errors as desktop notifications (for keybindings)")
    parser.add_argument("--instance", default=os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
    parser.add_argument("--if-active", action="store_true", help="Make off a no-op when no background is active")
    parser.add_argument("--owner", help=argparse.SUPPRESS)
    parser.add_argument("--shortcut", help="Companion shortcut override (modifiers + letter)")
    args = parser.parse_args()
    try:
        if args.action == "companion-enable":
            companion_enable()
            return 0
        if args.action == "companion-disable":
            companion_disable(args.instance or "")
            return 0
        controller = Controller(args.instance or "")
        if args.owner and not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", args.owner):
            raise ValueError("Invalid companion owner token.")
        with (controller.directory / "controller.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if args.owner and args.action in ("on", "off", "toggle"):
                controller.assert_owner(args.owner)
            if args.action == "on":
                controller.enable(args.window, owner=args.owner)
            elif args.action == "off":
                controller.disable(args.if_active)
            elif args.action == "toggle":
                controller.toggle(args.window, owner=args.owner)
            elif args.action == "service-start":
                controller.service_start(args.owner, args.shortcut)
            elif args.action == "service-stop":
                controller.service_stop(args.owner)
            else:
                controller.status()
    except (ValueError, RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(error, file=sys.stderr)
        if args.notify and shutil.which("notify-send"):
            subprocess.run(["notify-send", "-u", "critical", "Window background", str(error)], timeout=5)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
