// The mod loader (docs/MODDING.md): mods built as separate DLLs - build\scripts\*.asi and *.asi next to vcs.exe (on
// Linux *.so) - loaded at start-up and handed the C API of modapi/vcs_mod_api.h. Without any, the game is vcs.exe's own.
// VCS_MODS=0 loads none for one run (the reference).
//
// The exe's side: the settings rows (the Game page after "Window", and the "graphics" slot), the hotkeys (Keyboard
// page), the mouse / right-stick look (game/vcs_input.cpp), the background draw list (a crosshair) and the two hook
// phases (game/vcs_overrides.cpp applyVcs). With no mod loaded each of them does nothing.
#pragma once

class PS2Runtime;

namespace vcs::modapi
{
    // Main thread, in main.cpp's settings registration (before vcs.ini is read): loads the mods and calls each one's
    // VcsModRegister - its settings rows come here, in the Game page after "Window".
    void registerPlugins();

    // Main thread, later in the settings registration: each mod's VcsModRegisterSettings(api, slot) - "graphics" after
    // the Graphics page's renderer rows.
    void registerSlot(const char *slot);

    // The ELF is loaded (applyVcs): VcsModInstall right after the free camera's hooks, before free aim's (game/vcs_aim.h:
    // those then wrap a mod's); VcsModInstallLate after them (a mod's hooks wrap free aim's).
    void install(PS2Runtime &runtime);
    void installLate(PS2Runtime &runtime);

    // Main thread, each host frame, before the menus: the mods' draw callbacks (Dear ImGui's background list).
    void drawCallbacks();

    // Game thread (pad reads): a mod's view takes the mouse and the right stick this frame; look() turns it (radians,
    // yaw left +, pitch up +).
    bool lookActive();
    void look(float yaw, float pitch);

    // The Keyboard page's "Menus" section (game/vcs_input.cpp registerSettings): the mods' hotkeys as Key rows.
    void registerHotkeySettings(const char *page);

    // Main thread, each host frame (ui/trainer_menu.cpp): the mods' hotkeys - a key or Back + a gamepad button pressed
    // while `allowed` (no menu open) runs the mod's callback.
    void pollHotkeys(bool allowed);

    // How many mods were loaded (status; the trainer / logs).
    int loadedCount();
}
