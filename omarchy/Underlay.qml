import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

Item {
  id: root
  property var shell: null
  property var manifest: null
  readonly property string owner: "underlay-" + Quickshell.processId + "-" + Date.now()
    + "-" + Math.floor(Math.random() * 0x100000000).toString(16)
  readonly property string controllerPath: {
    const value = String(Qt.resolvedUrl("../tools/hypr_underlay.py"))
    if (!/^(file|qs):\/\/\//.test(value)) throw new Error("Hypr Underlay requires a local controller")
    return decodeURIComponent(value.replace(/^(file|qs):\/\//, ""))
  }
  property bool installed: false
  property bool pending: false
  property int attempts: 0

  function install() {
    installed = false
    if (installer.running) { pending = true; return }
    attempts++
    installer.running = true
  }

  Process {
    id: installer
    command: ["python3", root.controllerPath, "service-start", "--owner", root.owner]
    stdout: StdioCollector {
      onStreamFinished: if (text.trim()) console.info(text.trim())
    }
    stderr: StdioCollector {
      onStreamFinished: if (text.trim()) console.warn("Hypr Underlay:", text.trim())
    }
    onExited: function(code, status) {
      root.installed = code === 0 && !root.pending
      if (root.pending) {
        root.pending = false
        Qt.callLater(root.install)
      } else if (code !== 0 && root.attempts < 3) {
        retry.restart()
      }
    }
  }
  Timer { id: retry; interval: 500; onTriggered: root.install() }
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      if (event.name !== "configreloaded") return
      root.attempts = 0
      root.install()
    }
  }
  Component.onCompleted: root.install()
  Component.onDestruction: Quickshell.execDetached([
    "python3", root.controllerPath, "service-stop", "--owner", root.owner
  ])
}
