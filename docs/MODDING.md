# Mods as DLLs (.asi) - the mod API

Since 2026-10-31 vcs.exe loads mods built as separate DLLs, like an ASI loader for the PC GTAs: drop `Name.asi` into
`build\scripts\` (or next to `vcs.exe`) and start the game. Without any, the game is vcs.exe's own. The mods themselves
live in their own repository, [spartaque12/VCS-mods](https://github.com/spartaque12/VCS-mods); the first one is
`CameraAim.asi` (first person on foot and in vehicles, free aim, manual drive-by, the car's glass, field of view), moved
out of vcs.exe, `JoltPhysics.asi` (ragdolls, hit reactions, gore, pickups, foot IK, jiggle; Jolt linked into the
DLL, only its hooks and settings cross the API), and `Project2DFX.asi` (distant lights, stars, distant traffic, draw distance, flight ceiling). Which mod lives where: [MODS.md](MODS.md). Why: [DECISIONS.md](DECISIONS.md) (2026-10-31, mods as DLLs).

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
| `int VcsModRegisterSettings(const VcsModApi *, const char *slot)` (optional) | later in the settings registration | rows for a later place of the menu: slot `graphics` = after the Graphics page's renderer rows, before the controls pages (Project2DFX's rows, and its flight ceiling at the end of the Game page) |

What the table gives:
- **The game**: `rdram()`, `lookup_function` / `replace_function` on the recompiled function table, and the offsets of
  the guest context's registers (`ctx_gpr_offset`, `ctx_pc_offset`, `ctx_fpr_offset`): a hook reads `$a0` as the low 32
  bits at `gpr_offset + 16 * 4`, writes a register as the runtime does (the low 64 bits, sign-extended), returns to the
  caller by setting `pc` to `$ra`. `register_function` / `has_function` (appended to API 1, check with
  `VCS_MOD_API_HAS`) put a host function at an address that has none - a continuation a guest tail call returns to,
  as Project2DFX's chains do at 0x27C41C. The rules of AGENTS.md "Hooks on recompiled functions" hold for a mod's hooks too.
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
- **Rendering** (appended to API 1 on 2026-10-31, check `VCS_MOD_API_HAS(api, render_pop_marker)`; `RenderHook.asi`'s
  ambient occlusion uses it): `add_render_hook(point, fn, user, flags)` - the main thread, any time (a hook stays until
  the game ends; add it only when an option needs it: until then nothing in the renderer changes). Point
  `VCS_RENDER_BEFORE_POST`: the 3D scene is drawn (sky, world, water, peds, vehicles, blob shadows, particles), the game's
  post effects and the HUD come next. Flags: `VCS_RENDER_NEEDS_DEPTH` (the Z buffer made sampleable),
  `VCS_RENDER_NEEDS_RESOLVED_COLOR` (a resolved copy of the picture to read). The hook gets a `VcsRenderFrame`: the
  backend, the picture (`color`, RGBA8, multisampled with MSAA - draw into it), its Z buffer (`depth`: d = GS z / 2^24,
  0 = nothing drawn; a Texture2DMS with MSAA), the picture's size in target pixels, and the camera - the lens
  (fx, fy, cx, cy: pixel centre (x + 0.5, y + 0.5) at view depth w is ((x + 0.5 - cx) / fx * w, (y + 0.5 - cy) / fy * w, w)),
  the Z mapping (w = depth_b / (d / depth_scale - depth_a)) and the world's fog. Inside a hook the mod draws full-screen
  passes: `render_create_texture` (RGBA8 / R32F render targets), `render_create_constants` / `render_update_constants`,
  `render_create_pipeline` (vertex + pixel shader bytecode for the backend: DXBC from fxc for D3D11, SPIR-V for Vulkan
  with the port's bindings bN -> N, tN -> 16 + N, sN -> 32 + N; vertices from SV_VertexID; a blend preset: opaque,
  multiply (target x output alpha), alpha, add; a write mask; the texture slots declared Texture2DMS),
  `render_begin_pass` / `render_set_viewport` / `render_set_pipeline` / `render_set_texture` (point or linear, clamped) /
  `render_set_constants` / `render_draw` / `render_end_pass`, and `render_push_marker` / `render_pop_marker` (GPU time
  per marker with `PS2X_GPU_TIMING=1`). A pass or marker a hook leaves open is closed for it. Two more points around the
  game's water (appended 2026-11-01; an older vcs.exe refuses them): `VCS_RENDER_BEFORE_WATER` right before its first
  draw (the picture and Z buffer without the water: copy what you need) and `VCS_RENDER_AFTER_WATER` right after the
  last (the water in the picture and the Z buffer: where the Z buffer is nearer than before, water is in front);
  `VcsRenderFrame.point` says which, `water_rect` bounds the water (target pixels), `water_color` is the game's water tint
  (the draws' vertex colour, 1.0 = 0x80). Peds, vehicles and particles come after AFTER_WATER; no velocity,
  reprojection or shadow maps at these points (RenderHook.asi's water, RENDERHOOK_PLAN.md "Water"). The exe's side:
  `src/modapi/mod_render.cpp` over the RHI; the renderer's frame hook: NATIVE_RENDERER.md "Frame hook for render mods".
  VCS-mods' CMake has `vcs_mod_shader()` to build one HLSL source into both kinds of header. Temporal AA (appended,
  `VCS_MOD_API_HAS(api, render_set_jitter)`): `render_set_jitter(phases)` jitters the 3D picture; `VcsRenderFrame` then
  carries `jitter_x / y`, `prev_jitter_x / y` and `reproject` (check its `size`): the camera's motion as a 4x4 on
  (u w, v w, z w, w), for motion vectors. For an SDK (appended, `VCS_MOD_API_HAS(api, render_create_texture_ex)`):
  `render_current_color()` (the picture now, single-sampled, earlier hooks' drawing included), `render_native(what, t)`
  (D3D11 device / immediate context / a texture's ID3D11Texture2D; NULL on Vulkan), `render_create_texture_ex` with
  `VCS_RENDER_TEXTURE_STORAGE` (unordered access) and the RGBA16F format. RenderHook.asi's DLAA uses them.
  Shadows (appended, `VCS_MOD_API_HAS(api, render_shadow_map)`): `VcsRenderFrame.world_to_view` (the camera's rotation
  in the world, `view_valid`) and, in a hook added with `VCS_RENDER_NEEDS_SHADOW`, `render_shadow_map(view_to_clip,
  count, size, &drawn)`: the scene's Z-writing native draws depth only into 1-4 square viewports side by side, one
  view -> clip matrix each (z larger = nearer the light; static world meshes seen before and now off screen included);
  `VcsRenderFrame.camera_position` (`position_valid`) places the camera in a world frame of the renderer's own. RenderHook.asi's sun shadows use them; the sun itself is game
  memory (game-internals.md 6n).
- **VR** (appended to API 1 on 2026-11-01, check `VCS_MOD_API_HAS(api, present_window_copy)`; `VR.asi` uses it,
  docs/VR_PLAN.md M0): `add_present_hook(fn, user)` - the main thread, once per host frame, after the window's picture
  and Dear ImGui are drawn and right before the swapchain presents (`present::present()`, src/render/presenter.cpp): where
  an OpenXR mod ends its frame and waits for the next. The hook gets a `VcsPresentFrame`: the D3D11 device and immediate
  context, the window's size, and with `render_set_split_layers(1)` the shown picture without the HUD (`scene`, post
  effects in) and the native HUD layer drawn over black and over white (`hud_black` / `hud_white`: coverage
  1 - (white - black), premultiplied colour = black), all `ID3D11Texture2D *` RGBA8 at the display's output size, plus
  `has_3d` (the picture shows 3D: decideShape's choice, not one frame's own), `has_hud`, `layer_serial` and `input_ns`
  (the steady-clock time of the input snapshot the shown game frame was built from - a VR mod finds the head pose that
  frame was rendered with by it). `present_window_copy(w, h)` (inside the hook): the window's picture and menus rendered
  off-screen (the "cinema screen"). The hook may use the immediate context; the renderer sets its state again (VR.asi
  calls `ClearState` after its copies). The exe's side: `src/modapi/mod_present.cpp`; the split in gs_hw.cpp
  (`gsHwSetSplitLayers` / `splitLayers` in `composeDisplay`).
  VR pacing and size (appended 2026-11-01, `VCS_MOD_API_HAS(api, render_set_output_size)`): `vr_set_pacing(hz)` - the game at a headset's rate (frame-rate independent timing), the window's limiter and vsync aside, 0 = the settings again; `render_set_output_size(w, h)` - the picture's output size in place of the window's (0 x 0 = the window's).
- **Model geometry** (appended to API 1 on 2026-10-31, check `VCS_MOD_API_HAS(api, set_lit_refiner)`; `WeaponHD.asi`
  uses it): `set_lit_refiner(fn, user)` - the render worker calls `fn` for every lit model batch the native draws take
  (`VcsLitBatch`: kind skinned / rigid / environment-mapped, the strip's VU data as ints, bone encoding, position
  scale / offset); a returned `VcsLitRefined` (vertices in the batch's units, a strip of indices, a content key) is drawn
  in the batch's place: skinned in the exe, lit by vs_lit, the environment pass rebuilt from it. Batches through the VU
  clipper are not offered. `src/game/vcs_hle_world.cpp` (`refineLit`). Several refiners: `add_lit_refiner(fn, user)`
  (appended 2026-11-01, check `VCS_MOD_API_HAS(api, add_lit_refiner)`) adds one to a chain asked before the one
  `set_lit_refiner` set, in the order added; the first to return geometry draws the batch (at most 8). Units, as found
  for WeaponHD: a rigid model's positions are its int16 positions (the batch's `pos_scale` is 1/32768, the model's own
  scale and centre are in the matrices), normals of length ~127, uv in V2-8 units; keep the batch's third uv lane
  (`uv[i][2]`, 255 from the packets' STROW) - the shader reads it, and 0 drew nothing.

Building: the hooks use the guest calling convention (`VCS_GUEST_CC`, clang's `preserve_none` on x86-64), so a mod is
built with clang-cl (Windows) or clang (Linux), against the DLL C runtime (`/MD`, as vcs.exe), with the exe's float flags
(`/arch:AVX2`, `-ffp-contract=off`, `-fno-math-errno`) so host code that reproduces game maths stays bit-exact. VCS-mods' CMake does
all this; its README has the commands. On Linux the loader takes `*.so` from the same folders.

Versioning: `VCS_MOD_API_VERSION` (now 1) changes only when a change breaks built mods; new functions are appended
to `VcsModApi` without a version change, and a mod checks `VCS_MOD_API_HAS(api, field)` before using one newer than
itself.

## In vcs.exe

`src/modapi/mod_loader.cpp`: loading (`LoadLibrary` / `dlopen` of `<exe dir>\*.asi`, then `<exe dir>\scripts\*.asi`,
sorted by name; DLLs without `VcsModApiVersion` / `VcsModRegister` - an ASI for another game - are skipped), the API
table, and the exe's side of the coupling: `registerPlugins()` in main.cpp's settings registration (and
`registerSlot("graphics")` later in it), `install()` /
`installLate()` in `game/vcs_overrides.cpp` applyVcs, `drawCallbacks()` in the UI hook,
`lookActive()` / `look()` in `game/vcs_input.cpp`, `registerHotkeySettings()` there and `pollHotkeys()` in
`ui/trainer_menu.cpp`; the render hooks in `src/modapi/mod_render.cpp` (through `gsHwSetFrameHook`). A mod is never
unloaded.

## Next

- **The streamed-file override** (ModLoader-style `mods\stream\`) and the weapon pack's tools.
