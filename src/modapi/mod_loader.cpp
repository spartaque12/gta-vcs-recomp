// See mod_loader.h and docs/MODDING.md.
#include "modapi/mod_loader.h"

#include "modapi/mod_present.h"
#include "modapi/vcs_mod_api.h"

#include "game/vcs_freecam.h"
#include "game/vcs_hle_world.h"
#include "game/vcs_input.h"
#include "platform/platform.h"
#include "ps2_runtime.h"
#include "runtime/ps2_control.h"
#include "settings/settings.h"

#include "imgui.h"
#include "imgui_internal.h"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <string>
#include <system_error>
#include <vector>

#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace fs = std::filesystem;

namespace vcs::modapi
{
    namespace
    {
        static_assert(static_cast<int>(settings::Type::Toggle) == VCS_SETTING_TOGGLE &&
                          static_cast<int>(settings::Type::Choice) == VCS_SETTING_CHOICE &&
                          static_cast<int>(settings::Type::Integer) == VCS_SETTING_INTEGER &&
                          static_cast<int>(settings::Type::Key) == VCS_SETTING_KEY &&
                          static_cast<int>(settings::Type::Action) == VCS_SETTING_ACTION,
                      "VcsModSetting types follow settings::Type");
        static_assert(VCS_MOD_PAD_RIGHT_STICK == platform::GAMEPAD_RIGHT_STICK + 1 &&
                          VCS_MOD_PAD_DPAD_RIGHT == platform::GAMEPAD_DPAD_RIGHT + 1 &&
                          VCS_MOD_PAD_SOUTH == platform::GAMEPAD_SOUTH + 1,
                      "VCS_MOD_PAD_* are platform::GamepadButton + 1");

        struct Plugin
        {
            std::string file; // the file name (the log)
            std::string name;
            VcsModInstallFn install = nullptr, installLate = nullptr;
            VcsModRegisterSettingsFn registerSettings = nullptr;
        };

        struct Hotkey
        {
            std::string key;
            std::string label, help;
            int defaultKey = 0;
            int padChord = 0;
            void (*pressed)(void *) = nullptr;
            void *user = nullptr;
            bool chordWasDown = false;
        };

        struct DrawCallback
        {
            void (*fn)(void *);
            void *user;
        };

        std::vector<Plugin> g_plugins;
        std::vector<Hotkey> g_hotkeys;
        std::vector<DrawCallback> g_draw;
        PS2Runtime *g_runtime = nullptr;
        bool g_registering = false; // inside a VcsModRegister: add_setting / add_hotkey allowed

        std::mutex g_lookMutex;
        VcsModLookHandler g_look = {};
        bool g_hasLook = false;

        std::string g_gameDir;

        void logLine(const char *text) { std::fputs(text, stderr); }

        fs::path exeDirectory()
        {
#if defined(_WIN32)
            wchar_t buffer[MAX_PATH];
            const DWORD n = GetModuleFileNameW(nullptr, buffer, MAX_PATH);
            if (n > 0 && n < MAX_PATH)
                return fs::path(buffer).parent_path();
#elif defined(__linux__)
            std::error_code ec;
            const fs::path self = fs::read_symlink("/proc/self/exe", ec);
            if (!ec && !self.empty())
                return self.parent_path();
#endif
            return fs::current_path();
        }

        // ---- the API's functions ---------------------------------------------------------------------------------
        uint8_t *apiRdram() { return g_runtime ? g_runtime->memory().getRDRAM() : nullptr; }

        int apiReplace(uint32_t address, VcsGuestFn fn)
        {
            if (!g_runtime || !fn)
                return 0;
            return g_runtime->replaceFunction(address, reinterpret_cast<PS2Runtime::RecompiledFunction>(fn)) ? 1 : 0;
        }

        VcsGuestFn apiLookup(uint32_t address)
        {
            return g_runtime ? reinterpret_cast<VcsGuestFn>(g_runtime->lookupFunction(address)) : nullptr;
        }

        int apiRegister(uint32_t address, VcsGuestFn fn)
        {
            if (!g_runtime || !fn)
                return 0;
            return g_runtime->registerFunction(address, reinterpret_cast<PS2Runtime::RecompiledFunction>(fn)) ? 1 : 0;
        }

        int apiHas(uint32_t address) { return g_runtime && g_runtime->hasFunction(address) ? 1 : 0; }

        std::string str(const char *s) { return s ? s : ""; }

        int apiAddSetting(const VcsModSetting *in)
        {
            if (!g_registering || !in || in->size < sizeof(VcsModSetting) || !in->key || !*in->key || in->type < 0 ||
                in->type > VCS_SETTING_ACTION)
            {
                std::fprintf(stderr, "[mods] add_setting refused (%s)\n", in && in->key ? in->key : "?");
                return 0;
            }
            settings::Spec s;
            s.key = in->key;
            s.page = str(in->page);
            s.section = str(in->section);
            s.label = str(in->label);
            s.help = str(in->help);
            s.type = static_cast<settings::Type>(in->type);
            s.min = in->min;
            s.max = in->max;
            if (in->format)
                s.format = in->format;
            s.defaultValue = in->default_value;
            s.env = str(in->env);
            s.apply = in->apply == VCS_APPLY_RESTART ? settings::Apply::Restart : settings::Apply::Live;
            for (int i = 0; in->choices && i < in->choice_count; ++i)
                s.choices.push_back({str(in->choices[i].label), in->choices[i].value});
            s.button = str(in->button);
            if (auto fn = in->on_change)
                s.onChange = [fn, user = in->user](int v) { fn(user, v); };
            if (auto fn = in->read)
                s.read = [fn, user = in->user] { return fn(user); };
            settings::add(std::move(s));
            return 1;
        }

        int apiSettingValue(const char *key) { return key ? settings::value(key) : 0; }
        int apiSetSetting(const char *key, int v) { return key && settings::set(key, v) ? 1 : 0; }

        int apiAddHotkey(const VcsModHotkey *in)
        {
            if (!g_registering || !in || in->size < sizeof(VcsModHotkey) || !in->key || !*in->key || !in->pressed)
                return 0;
            Hotkey h;
            h.key = in->key;
            h.label = str(in->label);
            h.help = str(in->help);
            h.defaultKey = in->default_key;
            h.padChord = in->pad_chord;
            h.pressed = in->pressed;
            h.user = in->user;
            g_hotkeys.push_back(std::move(h));
            return 1;
        }

        void apiAddCommand(const char *verb, VcsModCommandFn fn, void *user)
        {
            if (!verb || !fn)
                return;
            ps2control::addCommand(verb, [fn, user](const std::string &args, ps2control::Reply reply) {
                char answer[1024] = {};
                fn(user, args.c_str(), answer, sizeof(answer));
                answer[sizeof(answer) - 1] = 0;
                reply(answer[0] ? answer : "error no answer");
            });
        }

        void *apiImguiContext() { return ImGui::GetCurrentContext(); }

        void apiImguiAllocators(void **allocFn, void **freeFn, void **user)
        {
            ImGuiMemAllocFunc a = nullptr;
            ImGuiMemFreeFunc f = nullptr;
            void *u = nullptr;
            ImGui::GetAllocatorFunctions(&a, &f, &u);
            if (allocFn)
                *allocFn = reinterpret_cast<void *>(a);
            if (freeFn)
                *freeFn = reinterpret_cast<void *>(f);
            if (user)
                *user = u;
        }

        void apiAddDraw(void (*fn)(void *), void *user)
        {
            if (fn)
                g_draw.push_back({fn, user});
        }

        void apiSetLook(const VcsModLookHandler *h)
        {
            std::lock_guard<std::mutex> lock(g_lookMutex);
            g_hasLook = h && h->active && h->look;
            g_look = g_hasLook ? *h : VcsModLookHandler{};
        }

        void apiLastPad(VcsModPad *out)
        {
            if (!out)
                return;
            const input::PadState p = input::lastPad();
            out->buttons = p.buttons;
            out->lx = p.lx;
            out->ly = p.ly;
            out->rx = p.rx;
            out->ry = p.ry;
        }

        int apiFreecamFlying() { return freecam::flying() ? 1 : 0; }
        const char *apiGameDir() { return g_gameDir.c_str(); }

#if defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Winvalid-offsetof"
#endif
        VcsModApi makeApi()
        {
            VcsModApi a = {};
            a.version = VCS_MOD_API_VERSION;
            a.size = sizeof(VcsModApi);
            a.rdram = &apiRdram;
            a.replace_function = &apiReplace;
            a.lookup_function = &apiLookup;
            a.ctx_gpr_offset = static_cast<uint32_t>(offsetof(R5900Context, r));
            a.ctx_pc_offset = static_cast<uint32_t>(offsetof(R5900Context, pc));
            a.ctx_fpr_offset = static_cast<uint32_t>(offsetof(R5900Context, f));
            a.add_setting = &apiAddSetting;
            a.setting_value = &apiSettingValue;
            a.set_setting = &apiSetSetting;
            a.add_hotkey = &apiAddHotkey;
            a.add_command = &apiAddCommand;
            a.log = &logLine;
            a.imgui_version_num = IMGUI_VERSION_NUM;
            a.imgui_sizeof_io = sizeof(ImGuiIO);
            a.imgui_sizeof_style = sizeof(ImGuiStyle);
            a.imgui_sizeof_vec2 = sizeof(ImVec2);
            a.imgui_sizeof_vec4 = sizeof(ImVec4);
            a.imgui_sizeof_drawvert = sizeof(ImDrawVert);
            a.imgui_sizeof_drawidx = sizeof(ImDrawIdx);
            a.imgui_sizeof_context = sizeof(ImGuiContext);
            a.imgui_context = &apiImguiContext;
            a.imgui_allocators = &apiImguiAllocators;
            a.add_draw_callback = &apiAddDraw;
            a.set_look_handler = &apiSetLook;
            a.last_pad = &apiLastPad;
            a.freecam_flying = &apiFreecamFlying;
            a.game_dir = &apiGameDir;
            a.register_function = &apiRegister;
            a.has_function = &apiHas;
            a.set_lit_refiner = [](VcsLitRefineFn fn, void *user) {
                vcs::hleworld::setLitRefiner(reinterpret_cast<const void *>(fn), user);
            };
            present_hooks::fillApi(a); // add_present_hook, render_set_split_layers, present_window_copy (mod_present.cpp)
            return a;
        }
#if defined(__clang__)
#pragma clang diagnostic pop
#endif

        const VcsModApi &api()
        {
            static const VcsModApi a = makeApi();
            return a;
        }

        // ---- loading -----------------------------------------------------------------------------------------------
#if defined(_WIN32)
        constexpr const char *kExtension = ".asi";
        using Library = HMODULE;
        Library openLibrary(const fs::path &p, std::string &error)
        {
            const HMODULE h = LoadLibraryW(p.wstring().c_str());
            if (!h)
                error = "LoadLibrary error " + std::to_string(GetLastError());
            return h;
        }
        void *symbol(Library h, const char *name) { return reinterpret_cast<void *>(GetProcAddress(h, name)); }
#else
        constexpr const char *kExtension = ".so";
        using Library = void *;
        Library openLibrary(const fs::path &p, std::string &error)
        {
            void *h = dlopen(p.c_str(), RTLD_NOW | RTLD_LOCAL);
            if (!h)
            {
                const char *e = dlerror();
                error = e ? e : "dlopen failed";
            }
            return h;
        }
        void *symbol(Library h, const char *name) { return dlsym(h, name); }
#endif

        std::vector<fs::path> candidates(const fs::path &dir)
        {
            std::vector<fs::path> out;
            std::error_code ec;
            if (!fs::is_directory(dir, ec))
                return out;
            for (const fs::directory_entry &e : fs::directory_iterator(dir, ec))
            {
                std::string ext = e.path().extension().string();
                std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
                if (ext == kExtension && e.is_regular_file(ec))
                    out.push_back(e.path());
            }
            std::sort(out.begin(), out.end());
            return out;
        }

        void loadOne(const fs::path &path)
        {
            const std::string file = path.filename().string();
            std::string error;
            const Library lib = openLibrary(path, error);
            if (!lib)
            {
                std::fprintf(stderr, "[mods] %s: not loaded (%s)\n", file.c_str(), error.c_str());
                return;
            }
            const auto version = reinterpret_cast<VcsModApiVersionFn>(symbol(lib, "VcsModApiVersion"));
            const auto reg = reinterpret_cast<VcsModRegisterFn>(symbol(lib, "VcsModRegister"));
            if (!version || !reg)
            {
                // an ASI of another kind (an ASI loader's plugin for another game): left alone, never called
                std::fprintf(stderr, "[mods] %s: not a VCS mod (no VcsModApiVersion / VcsModRegister) - skipped\n", file.c_str());
                return;
            }
            const uint32_t v = version();
            if (v != VCS_MOD_API_VERSION)
            {
                std::fprintf(stderr,
                             "[mods] %s: built for mod API %u, this vcs.exe has API %u - not loaded (get the mod's build for "
                             "this version)\n",
                             file.c_str(), v, VCS_MOD_API_VERSION);
                return;
            }
            Plugin p;
            p.file = file;
            const auto name = reinterpret_cast<VcsModNameFn>(symbol(lib, "VcsModName"));
            p.name = name && name() ? name() : file;
            p.install = reinterpret_cast<VcsModInstallFn>(symbol(lib, "VcsModInstall"));
            p.installLate = reinterpret_cast<VcsModInstallFn>(symbol(lib, "VcsModInstallLate"));
            p.registerSettings = reinterpret_cast<VcsModRegisterSettingsFn>(symbol(lib, "VcsModRegisterSettings"));
            g_registering = true;
            const int ok = reg(&api());
            g_registering = false;
            if (!ok)
            {
                std::fprintf(stderr, "[mods] %s: VcsModRegister failed - left out\n", file.c_str());
                return;
            }
            std::fprintf(stderr, "[mods] %s loaded (%s, API %u)\n", p.name.c_str(), file.c_str(), v);
            g_plugins.push_back(std::move(p));
        }
    }

    void registerPlugins()
    {
        const fs::path dir = exeDirectory();
        const auto utf8 = dir.u8string();
        g_gameDir.assign(reinterpret_cast<const char *>(utf8.data()), utf8.size());
        if (const char *e = std::getenv("VCS_MODS"); e && e[0] == '0')
        {
            std::fprintf(stderr, "[mods] VCS_MODS=0: no mods loaded\n");
            return;
        }
        for (const fs::path &folder : {dir, dir / "scripts"})
            for (const fs::path &p : candidates(folder))
                loadOne(p);
    }

    void registerSlot(const char *slot)
    {
        for (const Plugin &p : g_plugins)
        {
            if (!p.registerSettings)
                continue;
            g_registering = true;
            const int ok = p.registerSettings(&api(), slot);
            g_registering = false;
            if (!ok)
                std::fprintf(stderr, "[mods] %s: VcsModRegisterSettings(%s) failed\n", p.name.c_str(), slot);
        }
    }

    void install(PS2Runtime &runtime)
    {
        g_runtime = &runtime;
        for (const Plugin &p : g_plugins)
            if (p.install && !p.install(&api()))
                std::fprintf(stderr, "[mods] %s: VcsModInstall failed\n", p.name.c_str());
    }

    void installLate(PS2Runtime &runtime)
    {
        g_runtime = &runtime;
        for (const Plugin &p : g_plugins)
            if (p.installLate && !p.installLate(&api()))
                std::fprintf(stderr, "[mods] %s: VcsModInstallLate failed\n", p.name.c_str());
    }

    void drawCallbacks()
    {
        for (const DrawCallback &d : g_draw)
            d.fn(d.user);
    }

    bool lookActive()
    {
        std::lock_guard<std::mutex> lock(g_lookMutex);
        return g_hasLook && g_look.active(g_look.user) != 0;
    }

    void look(float yaw, float pitch)
    {
        std::lock_guard<std::mutex> lock(g_lookMutex);
        if (g_hasLook)
            g_look.look(g_look.user, yaw, pitch);
    }

    void registerHotkeySettings(const char *page)
    {
        for (const Hotkey &h : g_hotkeys)
        {
            settings::Spec s;
            s.key = h.key;
            s.page = page;
            s.section = "Menus";
            s.label = h.label;
            s.help = h.help;
            s.type = settings::Type::Key;
            s.group = "keys";
            s.optional = true;
            s.defaultValue = h.defaultKey;
            settings::add(std::move(s));
        }
    }

    void pollHotkeys(bool allowed)
    {
        for (Hotkey &h : g_hotkeys)
        {
            bool chord = false;
            if (h.padChord > 0 && platform::gamepadConnected())
                chord = platform::gamepadButton(platform::GAMEPAD_BACK) &&
                        platform::gamepadButton(static_cast<platform::GamepadButton>(h.padChord - 1));
            const bool chordPressed = chord && !h.chordWasDown;
            h.chordWasDown = chord;
            const int key = settings::value(h.key);
            if (allowed && ((key && (platform::keyPressed(key) || ps2control::keyPressed(key))) || chordPressed))
                h.pressed(h.user);
        }
    }

    int loadedCount() { return static_cast<int>(g_plugins.size()); }
}
