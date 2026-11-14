"""Opt-in integration test. Starts/stops only its own nested compositor."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
PLUGIN = BUILD / "hypr-underlay.so"


def wait_for(fn, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {description}")


def main():
    BUILD.mkdir(exist_ok=True)
    # Isolate sockets and state. Deny the DRM/seat backend so only a window on
    # the parent Wayland compositor is used, never a physical display.
    parent_display = Path(os.environ["WAYLAND_DISPLAY"])
    if not parent_display.is_absolute():
        parent_display = Path(os.environ["XDG_RUNTIME_DIR"]) / parent_display
    children = []
    with tempfile.TemporaryDirectory(
        prefix="n", dir=os.environ.get("HYPR_UNDERLAY_TEST_TMPDIR", tempfile.gettempdir())
    ) as directory:
        runtime = Path(directory)
        runtime.chmod(0o700)
        env = os.environ.copy()
        env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        env.pop("DISPLAY", None)
        env.update(
            XDG_RUNTIME_DIR=str(runtime),
            XDG_STATE_HOME=str(runtime / "state"),
            XDG_CONFIG_HOME=str(runtime / "config"),
            WAYLAND_DISPLAY=str(parent_display),
            AQ_DRM_DEVICES="/dev/null",
            LIBSEAT_BACKEND="none",
            HYPRLAND_NO_SD_VARS="1",
            HYPRLAND_NO_SD_NOTIFY="1",
            HYPRLAND_NO_RT="1",
        )
        with (BUILD / "nested.log").open("w") as log:
            compositor = subprocess.Popen(
                ["Hyprland", "--config", str(ROOT / "tests/nested.lua")],
                env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                def instance():
                    if compositor.poll() is not None:
                        raise RuntimeError("Nested compositor exited; see build/nested.log")
                    result = subprocess.run(
                        ["hyprctl", "instances", "-j"], env=env,
                        capture_output=True, text=True, timeout=3,
                    )
                    if result.returncode:
                        return None
                    try:
                        instances = json.loads(result.stdout)
                    except json.JSONDecodeError:
                        return None
                    return next((i for i in instances if i["pid"] == compositor.pid), None)

                instance_data = wait_for(instance, "nested IPC")
                env["HYPRLAND_INSTANCE_SIGNATURE"] = instance_data["instance"]
                env["WAYLAND_DISPLAY"] = str(runtime / instance_data["wl_socket"])

                def ctl(*args):
                    result = subprocess.run(
                        ["hyprctl", *args], env=env, capture_output=True, text=True, timeout=10,
                    )
                    if result.returncode:
                        raise RuntimeError(f"hyprctl {args}: {result.stdout} {result.stderr}")
                    return result.stdout.strip()

                def dispatch(code):
                    result = ctl("dispatch", code)
                    if result != "ok":
                        raise RuntimeError(f"Dispatcher failed: {code}: {result}")

                wait_for(lambda: json.loads(ctl("monitors", "-j")), "nested output")
                errors = ctl("configerrors")
                if errors:
                    raise RuntimeError(errors)
                print("Nested compositor ready; no desktop config loaded.", flush=True)

                def foot(app_id, title, color, alpha):
                    children.append(subprocess.Popen([
                        "foot", "--config=/dev/null", f"--app-id={app_id}", f"--title={title}",
                        "-o", f"colors-dark.background={color}", "-o", f"colors-dark.alpha={alpha}",
                        "-o", "colors-light.background=00ff00", "-o", "colors-light.alpha=1.0",
                        "-o", "cursor.blink=no",
                        "python3", "-c", "import signal; signal.pause()",
                    ], env=env, stdout=log, stderr=subprocess.STDOUT))

                foot("firefox", "Picture-in-Picture", "ff0000", "1.0")
                pip = wait_for(
                    lambda: next((w for w in json.loads(ctl("clients", "-j")) if w["class"] == "firefox"), None),
                    "red test PiP",
                )
                foot("pip-test-terminal", "Tiled test terminal", "0000ff", "0.5")
                terminal = wait_for(
                    lambda: next((w for w in json.loads(ctl("clients", "-j")) if w["class"] == "pip-test-terminal"), None),
                    "transparent tiled test terminal",
                )
                assert not terminal["floating"], "Test terminal must remain tiled"
                dispatch('hl.dsp.focus({window=' + json.dumps("address:" + terminal["address"]) + '})')
                selector = json.dumps("address:" + pip["address"])
                dispatch(f'hl.dsp.window.alter_zorder({{window={selector}, mode="top"}})')

                def screenshot(name):
                    path = BUILD / f"nested-{name}.png"
                    subprocess.run(["grim", str(path)], env=env, check=True, timeout=10,
                                   stdout=subprocess.DEVNULL, stderr=log)
                    with Image.open(path) as image:
                        return image.convert("RGB").getpixel((image.width // 2, image.height // 2))

                def red(pixel):
                    return pixel[0] > 220 and pixel[1] < 20 and pixel[2] < 20

                def purple(pixel):
                    return 80 < pixel[0] < 200 and pixel[1] < 20 and 80 < pixel[2] < 200

                wait_for(lambda: red(screenshot("before")), "baseline red foreground")
                print("Baseline: red PiP covers tiled terminal.", flush=True)
                assert ctl("plugin", "load", str(PLUGIN)) == "ok"
                assert ctl("underlay", "on", "address:" + pip["address"]) == "ok"
                wait_for(lambda: purple(screenshot("enabled")), "red PiP below blue tiled terminal")
                status = json.loads(ctl("underlay-status"))
                assert status["background_frames"] > 0 and status["suppressed_draws"] > 0, status
                clients = json.loads(ctl("clients", "-j"))
                assert not next(w for w in clients if w["address"] == terminal["address"])["floating"]
                print("PASS: purple blend proves PiP behind terminal; terminal remains tiled.", status, flush=True)
                # A new client buffer must damage/repaint the background too,
                # rather than leaving the first injected frame frozen.
                os.kill(children[0].pid, signal.SIGUSR2)
                wait_for(
                    lambda: (lambda p: p[0] < 20 and 80 < p[1] < 200 and 80 < p[2] < 200)(
                        screenshot("updated")
                    ),
                    "updated green PiP below blue terminal",
                )
                os.kill(children[0].pid, signal.SIGUSR1)
                wait_for(lambda: purple(screenshot("enabled")), "restored red test buffer")
                print("PASS: client buffer updates repaint behind tiled terminal.", flush=True)
                assert ctl("underlay", "off") == "ok"
                wait_for(lambda: red(screenshot("disabled")), "restored foreground PiP")
                assert ctl("plugin", "unload", str(PLUGIN)) == "ok"
                print("PASS: disable and plugin unload restore ordinary rendering.", flush=True)
                for pinned in (False, True):
                    dispatch(f'hl.dsp.window.pin({{window={selector}, action="{ "on" if pinned else "off" }"}})')
                    for action in ("on", "status"):
                        subprocess.run(
                            ["python3", str(ROOT / "tools/hypr_underlay.py"), action],
                            env=env, check=True, timeout=20,
                        )
                    wait_for(lambda: purple(screenshot("controller-enabled")), "controller background")
                    assert not next(
                        w for w in json.loads(ctl("clients", "-j")) if w["address"] == terminal["address"]
                    )["floating"]
                    subprocess.run(
                        ["python3", str(ROOT / "tools/hypr_underlay.py"), "off"],
                        env=env, check=True, timeout=20,
                    )
                    wait_for(lambda: red(screenshot("controller-disabled")), "controller restoration")
                    restored = next(w for w in json.loads(ctl("clients", "-j")) if w["address"] == pip["address"])
                    assert restored["pinned"] == pinned
                    assert restored["size"] == pip["size"] and restored["at"] == pip["at"]
                print("PASS: controller on/off restores geometry and both pin states; terminal stays tiled.", flush=True)
                dispatch(f'hl.dsp.window.close({{window={selector}}})')
                wait_for(
                    lambda: all(w["address"] != pip["address"] for w in json.loads(ctl("clients", "-j"))),
                    "fake PiP closure",
                )
                foot("generic-background-test", "Generic app", "ff0000", "1.0")
                generic = wait_for(
                    lambda: next((w for w in json.loads(ctl("clients", "-j")) if w["class"] == "generic-background-test"), None),
                    "generic tiled application",
                )
                assert not generic["floating"]
                target = json.dumps("address:" + generic["address"])

                def toggle():
                    subprocess.run(
                        ["python3", str(ROOT / "tools/hypr_underlay.py"), "toggle"],
                        env=env, check=True, timeout=20,
                    )

                for floating, fullscreen in ((False, False), (True, False), (False, True)):
                    dispatch(f'hl.dsp.window.float({{window={target}, action="{ "on" if floating else "off" }"}})')
                    if fullscreen:
                        dispatch(f'hl.dsp.window.fullscreen_state({{window={target}, action="set", internal=2, client=2}})')
                    dispatch(f'hl.dsp.focus({{window={target}}})')
                    original = next(w for w in json.loads(ctl("clients", "-j")) if w["address"] == generic["address"])
                    toggle()
                    wait_for(lambda: purple(screenshot("generic-enabled")), "generic app behind tiled terminal")
                    windows = json.loads(ctl("clients", "-j"))
                    active_target = next(w for w in windows if w["address"] == generic["address"])
                    assert active_target["floating"] and active_target["pinned"]
                    assert active_target["fullscreen"] == 0
                    assert not next(w for w in windows if w["address"] == terminal["address"])["floating"]
                    assert json.loads(ctl("activewindow", "-j"))["address"] == terminal["address"]
                    if floating:
                        dispatch('hl.dsp.focus({workspace="2"})')
                    toggle()
                    restored = next(w for w in json.loads(ctl("clients", "-j")) if w["address"] == generic["address"])
                    assert restored["floating"] == original["floating"]
                    assert restored["pinned"] == original["pinned"]
                    assert restored["workspace"] == original["workspace"]
                    assert restored["fullscreen"] == original["fullscreen"]
                    assert restored["fullscreenClient"] == original["fullscreenClient"]
                    if floating:
                        assert restored["at"] == original["at"] and restored["size"] == original["size"]
                        dispatch('hl.dsp.focus({workspace="1"})')
                    if fullscreen:
                        dispatch(f'hl.dsp.window.fullscreen_state({{window={target}, action="set", internal=0, client=0}})')
                print("PASS: active-window toggle supports generic tiled, floating and fullscreen apps.", flush=True)
                prefix = runtime / "install-prefix"
                subprocess.run(["make", "install", "PREFIX=" + str(prefix)],
                               env=env, check=True, stdout=log, stderr=log, timeout=30)
                subprocess.run([str(prefix / "bin/hypr-underlay"), "on", "--window", generic["address"]],
                               env=env, check=True, stdout=log, stderr=log, timeout=20)
                wait_for(lambda: purple(screenshot("installed")), "installed controller/native library")
                subprocess.run(["make", "uninstall", "PREFIX=" + str(prefix)],
                               env=env, check=True, stdout=log, stderr=log, timeout=30)
                assert not (prefix / "bin/hypr-underlay").exists()
                assert not (prefix / "lib/hypr-underlay/hypr-underlay.so").exists()
                assert not any(p["name"] == "hypr-underlay" for p in json.loads(ctl("plugin", "list", "-j")))
                print("PASS: native install, installed controller, active uninstall and file removal.", flush=True)
                controller = ["python3", str(ROOT / "tools/hypr_underlay.py")]
                # A real conflict must be rejected without replacing the other
                # user's binding; reload only this disposable compositor to
                # clear the test sentinel afterward.
                assert ctl("eval", '_G.underlaySentinel=hl.bind("SUPER + ALT + B", function()end, {description="Conflict sentinel"})') == "ok"
                conflict = subprocess.run(
                    controller + ["service-start", "--owner", "conflict-test"],
                    env=env, capture_output=True, text=True, timeout=20,
                )
                assert conflict.returncode != 0 and "already bound" in conflict.stderr
                assert ctl("repl", "return _G.underlaySentinel:is_enabled()") == "true"
                assert ctl("reload") == "ok"
                print("PASS: shortcut conflict refuses activation and preserves the original binding.", flush=True)

                # Exercise the system-package layout rather than the checkout.
                subprocess.run(["make", "install", "PREFIX=" + str(prefix)],
                               env=env, check=True, stdout=log, stderr=log, timeout=30)
                installed_companion = prefix / "share/hypr-underlay/omarchy-plugin"
                assert (installed_companion / "manifest.json").is_file()
                service_env = env | {
                    "QS_DISABLE_FILE_WATCHER": "1", "QS_NO_RELOAD_POPUP": "1",
                    "UNDERLAY_SERVICE_SOURCE": (installed_companion / "omarchy/Underlay.qml").as_uri(),
                }
                service = subprocess.Popen(
                    ["quickshell", "-p", str(ROOT / "tests/service_shell.qml")],
                    env=service_env, stdout=log, stderr=subprocess.STDOUT,
                )
                children.append(service)

                def service_call(method):
                    result = subprocess.run(
                        ["quickshell", "ipc", "--pid", str(service.pid), "call", "underlay-test", method],
                        env=service_env, capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode:
                        log.write("Quickshell IPC: " + result.stderr + result.stdout + "\n")
                        log.flush()
                        return None
                    return result.stdout.strip()

                def service_ready():
                    result = service_call("status")
                    if result:
                        log.write("Service status: " + result + "\n")
                        log.flush()
                    return result and json.loads(result)["installed"]

                def inactive():
                    return ctl("repl", 'local r=rawget(_G,"__hyprUnderlayShortcut"); return not r or not r.active') == "true"

                wait_for(service_ready, "real Quickshell companion installation")
                for _ in range(3):
                    old_owner = json.loads(service_call("status"))["owner"]
                    service_call("disable")
                    wait_for(inactive, "companion deactivation")
                    service_call("enable")
                    wait_for(service_ready, "companion reactivation")
                    # Late cleanup from the old component cannot disable the new.
                    subprocess.run(controller + ["service-stop", "--owner", old_owner],
                                   env=env, check=True, timeout=20)
                    assert not inactive()
                    own = [b for b in json.loads(ctl("binds", "-j"))
                           if b["description"] == "Hypr Underlay: toggle focused window"]
                    assert len(own) == 1, "service churn accumulated native bindings"
                dispatch(f'hl.dsp.focus({{window={target}}})')
                assert ctl("eval", "_G.__hyprUnderlayShortcut.invoke()") == "ok"
                wait_for(lambda: purple(screenshot("service-enabled")), "companion shortcut background")
                assert ctl("reload") == "ok"
                wait_for(lambda: not inactive() and service_ready(), "companion reinstallation after reload")
                wait_for(lambda: purple(screenshot("service-reloaded")), "background recovered after config reload")
                service_call("disable")
                wait_for(inactive, "final companion disable")
                wait_for(
                    lambda: not any(p["name"] == "hypr-underlay" for p in json.loads(ctl("plugin", "list", "-j"))),
                    "owned background restoration/native unload",
                )
                restored = next(w for w in json.loads(ctl("clients", "-j")) if w["address"] == generic["address"])
                assert not restored["floating"]
                print("PASS: real Quickshell lifecycle, safe binding reuse, stale-owner cleanup, reload recovery and disable restoration.", flush=True)
                subprocess.run(["make", "uninstall", "PREFIX=" + str(prefix)],
                               env=env, check=True, stdout=log, stderr=log, timeout=30)
                assert not installed_companion.exists()
            finally:
                for child in children:
                    child.terminate()
                for child in children:
                    try:
                        child.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                if compositor.poll() is None:
                    compositor.terminate()
                    try:
                        compositor.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        compositor.kill()
                        compositor.wait()


if __name__ == "__main__":
    main()
