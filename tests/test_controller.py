import importlib.util
from pathlib import Path
import unittest
import os
import tempfile
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "hypr_underlay", Path(__file__).resolve().parents[1] / "tools/hypr_underlay.py"
)
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)


def pip(**overrides):
    window = {
        "class": "firefox", "title": "Picture-in-Picture", "mapped": True,
        "floating": True, "workspace": {"id": 1}, "address": "0x123",
        "pid": 123, "stableId": "test-window",
    }
    return window | overrides


class ControllerTests(unittest.TestCase):
    def test_select_pip(self):
        window = pip()
        self.assertEqual(controller.select_pip([pip(title="Netflix"), window]), window)

    def test_never_select_terminal(self):
        with self.assertRaises(ValueError):
            controller.select_pip([pip(**{"class": "foot"})])

    def test_reject_tiled_or_special(self):
        for window in [pip(floating=False), pip(workspace={"id": -1}), pip(mapped=False)]:
            with self.assertRaises(ValueError):
                controller.select_pip([window])

    def test_ambiguous_requires_address(self):
        windows = [pip(), pip(address="0x456")]
        with self.assertRaises(ValueError):
            controller.select_pip(windows)
        self.assertEqual(controller.select_pip(windows, "0x456"), windows[1])

    def test_scaled_monitor_geometry(self):
        self.assertEqual(
            controller.monitor_geometry(dict(width=2560, height=1600, scale=1.6, transform=0, x=100, y=200)),
            (100, 200, 1600, 1000),
        )

    def test_rotated_monitor_geometry(self):
        self.assertEqual(
            controller.monitor_geometry(dict(width=1920, height=1080, scale=1, transform=1, x=0, y=0)),
            (0, 0, 1080, 1920),
        )

    def test_restore_rejects_reused_address(self):
        self.assertTrue(controller.same_window(pip(), pip()))
        self.assertFalse(controller.same_window(pip(), pip(pid=456)))
        self.assertFalse(controller.same_window(pip(), pip(stableId="other-window")))

    def test_select_generic_tiled_application(self):
        window = pip(**{"class": "video-player", "title": "Movie", "floating": False})
        self.assertEqual(controller.select_window([window], window["address"]), window)

    def test_reject_grouped_hidden_or_special_generic_target(self):
        for window in [pip(grouped=["0x123", "0x456"]), pip(hidden=True), pip(workspace={"id": -1})]:
            with self.assertRaises(ValueError):
                controller.select_window([window], window["address"])

    def test_missing_active_window(self):
        with self.assertRaises(ValueError):
            controller.select_window([], None)

    def test_shortcut_normalization(self):
        self.assertEqual(controller.shortcut_spec("super+alt+b"), ("SUPER + ALT + B", 72, "B"))
        for shortcut in ("B", "SUPER + SUPER + B", "SUPER + F12", "SUPER + BAD + B"):
            with self.assertRaises(ValueError):
                controller.shortcut_spec(shortcut)

    def test_shortcut_conflict(self):
        self.assertIsNotNone(controller.shortcut_conflict([{"modmask": 72, "key": "b"}], 72, "B"))
        self.assertIsNotNone(controller.shortcut_conflict([{"modmask": 72, "keycode": 56}], 72, "B"))
        self.assertIsNone(controller.shortcut_conflict(
            [{"modmask": 72, "key": "B", "description": controller.DESCRIPTION}], 72, "B"
        ))

    def test_lua_quoting(self):
        self.assertEqual(controller.lua_string('a"\\\n'), '"a\\034\\092\\010"')

    def test_packaged_companion_prefix(self):
        self.assertEqual(controller.installation_prefix(Path("/usr/share/hypr-underlay/omarchy-plugin")), Path("/usr"))
        self.assertEqual(
            controller.installation_prefix(Path("/some/prefix/share/hypr-underlay/omarchy-plugin")),
            Path("/some/prefix"),
        )
        self.assertEqual(controller.installation_prefix(Path("/checkout")), Path("/checkout"))

    def test_registration_is_user_scoped_idempotent_and_non_destructive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            other = root / "other"
            first.mkdir()
            other.mkdir()
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config")}):
                link = controller.register_companion(first)
                self.assertEqual(link, root / "config/omarchy/plugins" / controller.COMPANION_ID)
                self.assertEqual(controller.register_companion(first), link)
                with self.assertRaises(ValueError):
                    controller.register_companion(other)
                self.assertEqual(link.resolve(), first)

    def test_disable_stops_owner_before_removing_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "payload"
            target.mkdir()
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config")}):
                link = controller.register_companion(target)
                with patch.object(controller, "COMPANION", target), \
                     patch.object(controller, "omarchy"), \
                     patch.object(controller, "Controller") as factory:
                    instance = factory.return_value
                    instance.directory = root
                    instance.ctl.return_value = "test-owner"
                    instance.service_stop.side_effect = lambda owner: self.assertTrue(link.is_symlink())
                    controller.companion_disable("test-instance")
                    instance.service_stop.assert_called_once_with("test-owner")
                    instance.disable.assert_called_once_with(if_active=True)
                self.assertFalse(link.is_symlink())


if __name__ == "__main__":
    unittest.main()
