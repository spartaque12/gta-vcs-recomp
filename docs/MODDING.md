# Mods as DLLs (.asi) - the mod API

Since 2026-10-31 vcs.exe loads mods built as separate DLLs, like an ASI loader for the PC GTAs: drop `Name.asi` into
`build\scripts\` (or next to `vcs.exe`) and start the game. Without any, the game is vcs.exe's own. The mods themselves
live in their own repository, [spartaque12/VCS-mods](https://github.com/spartaque12/VCS-mods); the first one is
`CameraAim.asi` (first person on foot and in vehicles, free aim, manual drive-by, the car's glass, field of view), moved
out of vcs.exe. Which mod lives where: [MODS.md](MODS.md). Why: [DECISIONS.md](DECISIONS.md) (2026-10-31, mods as DLLs).

## For players

- Put the `.asi` into `build\scripts\` (create the folder) beside `vcs.exe`. Restart the game: its settings rows appear
  in F2 where they always were, its keys on the Keyboard page.
- The log (`build\run\*.log`, or the console) says `[mods] CameraAim loaded (CameraAim.asi, API 1)`. A mod built for
  another API version is refused with a line that says so; get the mod's build for your vcs.exe.
- `VCS_MODS=0` starts the game without any mod (to tell whether a problem is a mod's).
- Settings of a mod stay in `vcs.ini` while it is not installed (lines vcs.exe does not know are kept as they are).

## For mod authors

The API is one C header, [`src/modapi/vcs_mod_api.h`](../src/modapi/vcs_mod_api.h) (copied into VCS-mods as
`api/vcs_mod_api.h`): a versioned table of function pointers, `VcsModApi`, and the functions a mod exports. Nothing of
C++ crosses it, so a mod is built on its own and keeps working with later builds of the same API version.

| Export | When | What it does there |
|---|---|---|
| `uint32_t VcsModApiVersion(void)` | before anything | the `VCS_MOD_API_VERSION` it was built with; another version is not loaded |
| `int VcsModRegister(const VcsModApi *)` | start-up, before `vcs.ini` is read | settings (`add_setting`), hotkeys (`add_hotkey`), the look handler, draw callbacks, control-channel commands. 0 = failed: the mod is left out |
| `int VcsModInstall(const VcsModApi *)` (optional) | the ELF loaded, before the game runs | hooks (`lookup_function` + `replace_function`), in before the built-in mods' hooks - those wrap it |
| `int VcsModInstallLate(const VcsModApi *)` (optional) | right after, once the built-in mods' hooks are in | hooks that must wrap the built-in mods' (game-internals.md 12o) |
| `const char *VcsModName(void)` (optional) | | the name in the log |

What the table gives:
- **The game**: `rdram()`, `lookup_function` / `replace_function` on the recompiled function table, and the offsets of
  the guest context's registers (`ctx_gpr_offset`, `ctx_pc_offset`, `ctx_fpr_offset`): a hook reads `$a0` as the low 32
  bits at `gpr_offset + 16 * 4`, writes a register as the runtime does (the low 64 bits, sign-extended), returns to the
  caller by setting `pc` to `$ra`. The rules of AGENTS.md "Hooks on recompiled functions" hold for a mod's hooks too.
- **Settings**: `add_setting` (a `VcsModSetting`: key, page, section, label, help, type, range, format, default,
  environment override, callbacks with a user pointer) becomes a `settings::Spec`; `setting_value`, `set_setting`.
  Rows are shown where `VcsModRegister` runs: on the Game page after "Window", before "Physics".
- **Hotkeys**: `add_hotkey` - a Key row in the Keyboard page's "Menus" section (exclusive with the other menu keys,
  unbindable) and optionally Back + a gamepad button; the callback runs on the main thread outside the menus.
- **Input**: `set_look_handler` - while its `active()` says so, the mouse and the right stick turn the mod's view
  (`look(yaw, pitch)`) and the game's camera gets no stick; `last_pad` (the DualShock 2 report the controls made);
  `freecam_flying` (the trainer's free camera has the camera).
- **Drawing**: `add_draw_callback` runs every host frame before the menus; the mod draws into Dear ImGui's background
  list in the exe's context (`imgui_context`, `imgui_allocators` for `ImGui::SetAllocatorFunctions`). The mod builds
  the same Dear ImGui (1.92.7-docking, no imconfig changes) and compares `imgui_version_num` and the `imgui_sizeof_*`
  fields with its own before using it.
- **Control channel and log**: `add_command` (a rig / gamectl command answered with one line), `log`, `game_dir`.

Building: the hooks use the guest calling convention (`VCS_GUEST_CC`, clang's `preserve_none` on x86-64), so a mod is
built with clang-cl (Windows) or clang (Linux), against the DLL C runtime (`/MD`, as vcs.exe). VCS-mods' CMake does
all this; its README has the commands. On Linux the loader takes `*.so` from the same folders.

Versioning: `VCS_MOD_API_VERSION` (now 1) changes only when a change breaks built mods; new functions are appended
to `VcsModApi` without a version change, and a mod checks `VCS_MOD_API_HAS(api, field)` before using one newer than
itself.

## In vcs.exe

`src/modapi/mod_loader.cpp`: loading (`LoadLibrary` / `dlopen` of `<exe dir>\*.asi`, then `<exe dir>\scripts\*.asi`,
sorted by name; DLLs without `VcsModApiVersion` / `VcsModRegister` - an ASI for another game - are skipped), the API
table, and the exe's side of the coupling: `registerPlugins()` in main.cpp's settings registration, `install()` /
`installLate()` in `game/vcs_overrides.cpp` applyVcs around the ragdolls' install, `drawCallbacks()` in the UI hook,
`lookActive()` / `look()` in `game/vcs_input.cpp`, `registerHotkeySettings()` there and `pollHotkeys()` in
`ui/trainer_menu.cpp`. A mod is never unloaded.

## Next

- **Project2DFX** as `Project2DFX.asi`: needs `register_function` / `has_function` in the API (its guest tail-call
  chains return to a continuation address of its own, 0x27C41C) and a settings slot after the Graphics page's renderer
  rows (its rows are registered there, after the camera ones).
- **Jolt Physics** (ragdolls, `src/game/vcs_jolt.cpp`, `src/physics`): a mod of its own once its work settles; it links
  Jolt itself, so only its hooks and settings cross the API.
- **The streamed-file override** (ModLoader-style `mods\stream\`) and the weapon pack's tools.
