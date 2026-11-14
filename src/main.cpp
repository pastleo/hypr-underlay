#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/desktop/state/WindowState.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/render/Renderer.hpp>

#include <cstdint>
#include <format>
#include <stdexcept>
#include <string>

namespace {
HANDLE g_handle = nullptr;
CFunctionHook* g_renderWindowHook = nullptr;
PHLWINDOWREF g_target;
CHyprSignalListener g_renderListener;
SP<SHyprCtlCommand> g_statusCommand;
SP<SHyprCtlCommand> g_controlCommand;
bool g_injected = false;
uint64_t g_backgroundFrames = 0;
uint64_t g_suppressedDraws = 0;

// Exact signature from Hyprland 0.56.2. The implicit C++ `this` is explicit.
using RenderWindowFn = void (*)(Render::IHyprRenderer*, PHLWINDOW, PHLMONITOR,
                               const Time::steady_tp&, bool, Render::eRenderPassMode, bool, bool);

RenderWindowFn originalRenderWindow() {
    return reinterpret_cast<RenderWindowFn>(g_renderWindowHook->m_original);
}

void renderWindowHook(Render::IHyprRenderer* renderer, PHLWINDOW window,
                      PHLMONITOR monitor, const Time::steady_tp& now,
                      bool decorate, Render::eRenderPassMode mode,
                      bool ignorePosition, bool standalone) {
    // Only suppress the ordinary draw after successfully inserting the same
    // window earlier in this render. Snapshots and standalone exports must
    // retain their original behavior.
    if (g_injected && window == g_target.lock() && !standalone &&
        !renderer->m_bRenderingSnapshot &&
        renderer->renderData().projectionType == Render::RPT_MONITOR) {
        ++g_suppressedDraws;
        return;
    }
    originalRenderWindow()(renderer, window, monitor, now, decorate, mode, ignorePosition, standalone);
}

void onRenderStage(eRenderStage stage) {
    if (stage == RENDER_BEGIN || stage == RENDER_POST_WINDOWS || stage == RENDER_POST) {
        g_injected = false;
        return;
    }
    if (stage != RENDER_POST_WALLPAPER || !g_pHyprRenderer || g_pHyprRenderer->m_bRenderingSnapshot)
        return;

    // This stage is inside the compositor's ordinary workspace render path;
    // its lock-screen checks have already run. Do not add our own render loop.
    auto window = g_target.lock();
    auto monitor = g_pHyprRenderer->renderData().pMonitor.lock();
    if (!window || !monitor || !window->m_isMapped || window->isHidden() ||
        !window->m_isFloating || window->m_monitor != monitor ||
        window->onSpecialWorkspace() || !g_pHyprRenderer->shouldRenderWindow(window, monitor) ||
        g_pHyprRenderer->renderData().projectionType != Render::RPT_MONITOR)
        return;

    originalRenderWindow()(g_pHyprRenderer.get(), window, monitor, Time::steadyNow(),
                           false, Render::RENDER_PASS_ALL, false, false);
    g_injected = true;
    ++g_backgroundFrames;
}

void damageTarget() {
    if (auto window = g_target.lock()) {
        if (auto monitor = window->m_monitor.lock())
            g_pHyprRenderer->damageMonitor(monitor);
    }
}

SDispatchResult dispatch(std::string args) {
    if (args == "off") {
        damageTarget();
        g_target.reset();
        g_injected = false;
        return {};
    }
    constexpr std::string_view PREFIX = "on address:";
    if (!args.starts_with(PREFIX))
        return {.success = false, .error = "Usage: underlay on address:0x... | off"};

    const auto address = args.substr(PREFIX.size());
    for (const auto& window : Desktop::windowState()->windows()) {
        if (std::format("{:p}", static_cast<void*>(window.get())) != address)
            continue;
        if (!window->m_isMapped || window->isHidden() || !window->m_isFloating ||
            window->onSpecialWorkspace() || window->m_group)
            return {.success = false, .error = "Select a mapped, ungrouped floating window on a normal workspace"};
        damageTarget();
        g_target = window;
        g_backgroundFrames = 0;
        g_suppressedDraws = 0;
        damageTarget();
        return {};
    }
    return {.success = false, .error = "Window not found"};
}
}

APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    g_handle = handle;
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
        throw std::runtime_error("hypr-underlay: Hyprland ABI mismatch; rebuild against the running compositor");
    // The internal render function is version-specific, even beyond the ABI.
    if (HyprlandAPI::getHyprlandVersion(handle).hash != GIT_COMMIT_HASH ||
        std::string(GIT_TAG) != "v0.56.2")
        throw std::runtime_error("hypr-underlay: this experiment targets Hyprland v0.56.2 only");

    const auto matches = HyprlandAPI::findFunctionsByName(handle, "renderWindow");
    void* address = nullptr;
    for (const auto& match : matches) {
        if (match.demangled.starts_with("Render::IHyprRenderer::renderWindow(")) {
            if (address)
                throw std::runtime_error("hypr-underlay: ambiguous renderWindow symbol");
            address = match.address;
        }
    }
    if (!address)
        throw std::runtime_error("hypr-underlay: renderWindow symbol not found");
    g_renderWindowHook = HyprlandAPI::createFunctionHook(handle, address, reinterpret_cast<void*>(&renderWindowHook));
    if (!g_renderWindowHook || !g_renderWindowHook->hook())
        throw std::runtime_error("hypr-underlay: cannot hook renderWindow");

    if (!HyprlandAPI::addDispatcherV2(handle, "underlay", dispatch))
        throw std::runtime_error("hypr-underlay: dispatcher registration failed");
    g_statusCommand = HyprlandAPI::registerHyprCtlCommand(handle, {
        .name = "underlay-status",
        .exact = true,
        .fn = [](eHyprCtlOutputFormat, std::string) {
            auto window = g_target.lock();
            return std::format("{{\"enabled\":{},\"background_frames\":{},\"suppressed_draws\":{}}}",
                               window ? "true" : "false", g_backgroundFrames, g_suppressedDraws);
        },
    });
    if (!g_statusCommand)
        throw std::runtime_error("hypr-underlay: status command registration failed");
    g_controlCommand = HyprlandAPI::registerHyprCtlCommand(handle, {
        .name = "underlay ",
        .exact = false,
        .fn = [](eHyprCtlOutputFormat, std::string request) {
            const auto result = dispatch(request.substr(std::string("underlay ").size()));
            return result.success ? std::string("ok") : "error: " + result.error;
        },
    });
    if (!g_controlCommand)
        throw std::runtime_error("hypr-underlay: control command registration failed");
    g_renderListener = Event::bus()->m_events.render.stage.listen(onRenderStage);
    return {"hypr-underlay", "Render a selected application below tiled windows", "hypr-underlay contributors", "0.3.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    damageTarget();
    g_target.reset();
    g_injected = false;
    g_renderListener.reset();
    // Hyprland removes plugin-owned dispatchers, commands, and hooks on unload.
    g_statusCommand.reset();
    g_controlCommand.reset();
}
