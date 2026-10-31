// The mod loader (docs/MODDING.md): mods built as separate DLLs - build\scripts\*.asi and *.asi next to vcs.exe (on
// Linux *.so) - loaded at start-up and handed the C API of modapi/vcs_mod_api.h. Without any, the game is vcs.exe's own.
// VCS_MODS=0 loads none for one run (the reference).
//
// The exe's side of the coupling the camera mods had: the settings rows (registered where the built-in camera mods'
// were), the hotkeys (Keyboard page), the mouse / right-stick look (game/vcs_input.cpp), the background draw list (the
// crosshair) and the two hook phases (game/vcs_overrides.cpp applyVcs).
#pragma once

class PS2Runtime;

namespace vcs::modapi
{
    // Main thread, in main.cpp's settings registration (before vcs.ini is read): loads the mods and calls each one's
    // VcsModRegister - its settings rows come here, in the Game page after "Window".
    void registerPlugins();

    // The ELF is loaded (applyVcs): VcsModInstall right after the free camera's hooks, before the built-in mods' (the
    // ragdolls' bone hooks then wrap a mod's); VcsModInstallLate after the built-in mods' hooks (a mod's line-of-sight
    // hook wraps the ragdolls').
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
