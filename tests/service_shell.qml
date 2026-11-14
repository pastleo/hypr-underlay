import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
  Loader {
    id: service
    source: Quickshell.env("UNDERLAY_SERVICE_SOURCE")
    active: true
  }
  IpcHandler {
    target: "underlay-test"
    function enable(): void { service.active = true }
    function disable(): void { service.active = false }
    function status(): string {
      return JSON.stringify({
        installed: !!service.item && service.item.installed,
        owner: service.item ? service.item.owner : "",
        loaderStatus: service.status,
        controller: service.item ? service.item.controllerPath : "",
        attempts: service.item ? service.item.attempts : -1
      })
    }
  }
}
