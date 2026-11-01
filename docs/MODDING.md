# Mods as DLLs (.asi) - the mod API

vcs.exe loads mods built as separate DLLs, like an ASI loader for the PC GTAs: drop `Name.asi` into `build\scripts\`
(or next to `vcs.exe`; on Linux `Name.so`) and start the game. Without any, the game is vcs.exe's own: every place the
exe calls into the loader does nothing when no mod is loaded. Example mods (first person, free aim, distant lights,
ragdolls...) live in their own repository, [spartaque12/VCS-mods](https://github.com/spartaque12/VCS-mods). Why:
[DECISIONS.md](DECISIONS.md) (2026-11-01, mods as DLLs).

## For players

- Put the `.asi` into `build\scripts\` (create the folder) beside `vcs.exe`. Restart the game: its settings rows appear
  in F2 (the Game page after "Window", or where the mod asks), its keys on the Keyboard & mouse page under "Menus".
- The log (`build\run\*.log`, or the console) says `[mods] CameraAim loaded (CameraAim.asi, API 1)`. A mod built for
  another API version is refused with a line that says so; get the mod's build for your vcs.exe. A DLL that is not a
  VCS mod (an ASI for another game) is skipped, never called.
- `VCS_MODS=0` starts the game without any mod (to tell whether a problem is a mod's).
- Settings of a mod stay in `vcs.ini` while it is not installed (lines vcs.exe does not know are kept as they are).
- A mod is native code with the game's rights: install only mods you trust, as with any ASI.

## For mod authors

The API is one C header, [`src/modapi/vcs_mod_api.h`](../src/modapi/vcs_mod_api.h): a versioned table of function
pointers, `VcsModApi`, and the functions a mod exports. Nothing of C++ crosses it, so a mod is built on its own (only
this header and, to draw, Dear ImGui) and keeps working with later builds of the same API version.

| Export | When | What it does there |
|---|---|---|
| `uint32_t VcsModApiVersion(void)` | before anything | the `VCS_MOD_API_VERSION` it was built with; another version is not loaded |
| `int VcsModRegister(const VcsModApi *)` | start-up, before `vcs.ini` is read | settings (`add_setting`), hotkeys (`add_hotkey`), the look handler, draw callbacks, control-channel commands. 0 = failed: the mod is left out |
| `int VcsModInstall(const VcsModApi *)` (optional) | the ELF loaded, before the game runs | hooks (`lookup_function` + `replace_function`), in after the free camera's and before free aim's - those wrap it |
| `int VcsModInstallLate(const VcsModApi *)` (optional) | right after, once free aim's hooks are in | hooks that must wrap vcs.exe's own |
| `const char *VcsModName(void)` (optional) | | the name in the log |
| `int VcsModRegisterSettings(const VcsModApi *, const char *slot)` (optional) | later in the settings registration | rows for a later place of the menu: slot `graphics` = after the Graphics page's renderer rows, before the controls pages |

What the table gives:
- **The game**: `rdram()`, `lookup_function` / `replace_function` on the recompiled function table, and the offsets of
  the guest context's registers (`ctx_gpr_offset`, `ctx_pc_offset`, `ctx_fpr_offset`): a hook reads `$a0` as the low 32
  bits at `gpr_offset + 16 * 4`, writes a register as the runtime does (the low 64 bits, sign-extended), returns to the
  caller by setting `pc` to `$ra`. `register_function` / `has_function` put a host function at an address that has
  none - a continuation a guest tail call returns to. The rules of AGENTS.md "Hooks on recompiled functions" hold for a
  mod's hooks too.
- **Settings**: `add_setting` (a `VcsModSetting`: key, page, section, label, help, type - toggle, choice, integer, key,
  action -, range, format, default, environment override, callbacks with a user pointer) becomes a `settings::Spec`;
  `setting_value`, `set_setting`. Rows from `VcsModRegister` are shown on the Game page after "Window"; rows from
  `VcsModRegisterSettings` at the slot's place.
- **Hotkeys**: `add_hotkey` - a Key row in the Keyboard & mouse page's "Menus" section (exclusive with the other menu
  keys, unbindable) and optionally Back + a gamepad button; the callback runs on the main thread outside the menus.
- **Input**: `set_look_handler` - while its `active()` says so, the mouse and the right stick turn the mod's view
  (`look(yaw, pitch)`, radians) and the game's camera gets no stick; free aim stands aside meanwhile, the free camera
  comes first. `last_pad` (the DualShock 2 report the bindings made); `freecam_flying` (the trainer's free camera has the
  camera).
- **Drawing**: `add_draw_callback` runs every host frame before the menus; the mod draws into Dear ImGui's background
  list in the exe's context (`imgui_context`, `imgui_allocators` for `ImGui::SetAllocatorFunctions`). The mod builds
  the same Dear ImGui as the exe (no imconfig changes) and compares `imgui_version_num` and the `imgui_sizeof_*` fields
  with its own before using it.
- **Control channel and log**: `add_command` (a `tools/rig.py` / `tools/gamectl.py` command answered with one line),
  `log`, `game_dir`.

Building: the hooks use the guest calling convention (`VCS_GUEST_CC`, clang's `preserve_none` on x86-64), so a mod is
built with clang-cl (Windows) or clang (Linux), against the DLL C runtime (`/MD`, as vcs.exe), with the exe's float flags
(`/arch:AVX2`, `-ffp-contract=off`, `-fno-math-errno`) so host code that reproduces game maths stays bit-exact.
VCS-mods' CMake does all this; its README has the commands.

Versioning: `VCS_MOD_API_VERSION` (now 1) changes only when a change breaks built mods; new functions are appended
to `VcsModApi` without a version change, and a mod checks `VCS_MOD_API_HAS(api, field)` (against the table's `size`)
before using one newer than itself.

### Not in this build

The fork spartaque12/gta-vcs-recomp (branch `vcs-mods`), where the API grew, has more of API 1, appended after
`has_function` in this order: render hooks inside the renderer (full-screen passes over the RHI with the frame's depth,
camera and fog: ambient occlusion), temporal AA jitter and motion vectors, shadow maps, a lit-model geometry refiner,
present hooks and VR pacing. This vcs.exe's table ends at `has_function`, so for a mod that uses them
`VCS_MOD_API_HAS` is false and it leaves those features out (the example mods' `VcsModRegister` refuses to load when
it needs them); they can follow at the same offsets.

## In vcs.exe

`src/modapi/mod_loader.cpp`: loading (`LoadLibrary` / `dlopen` of `<exe dir>\*.asi`, then `<exe dir>\scripts\*.asi`,
sorted by name; DLLs without `VcsModApiVersion` / `VcsModRegister` are skipped), the API table, and the exe's side:
`registerPlugins()` in main.cpp's settings registration (and `registerSlot("graphics")` later in it), `install()` /
`installLate()` around `aim::install` in `game/vcs_overrides.cpp` applyVcs, `drawCallbacks()` in the UI hook,
`lookActive()` / `look()` in `game/vcs_input.cpp`'s pad read, `registerHotkeySettings()` in its settings and
`pollHotkeys()` in `ui/trainer_menu.cpp`. A mod is never unloaded.
