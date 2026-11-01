# VR for the port - research and plan

Status (2026-11-01): **M0 implemented** as `VR.asi` (VCS-mods `plugins/VR`, off by default: Graphics > VR), checked
without a headset (see "M0 as built" below); M1-M3 not started. The research (2026-10-31) follows.

### M0 as built (2026-11-01)

- OpenXR session on vcs.exe's D3D11 device (the Khronos loader `openxr_loader.dll` next to VR.asi, loaded at run time);
  no loader / runtime / headset / D3D11: one log line, VR.asi inert. A headset that is off is retried every 3 s.
- Frames paced by the headset: xrEndFrame + xrWaitFrame + xrBeginFrame in the exe's present hook (`add_present_hook`).
- First person on foot (CameraAim): the picture without the HUD as a mono projection layer at the game camera's own
  field of view and the head pose it was rendered with (found by the frame's input time); the HUD on a quad (premultiplied
  alpha from the HUD drawn over black and white, `render_set_split_layers`). CameraAim takes the head's yaw / pitch / roll
  (`CameraAimSetHeadLook`); the stick / mouse turn the body. Everything else - menus (F2 / F5), loading screens,
  cutscenes, third person, vehicles - on a "cinema" quad (`present_window_copy`). Why the game's FOV, not the headset's:
  DECISIONS.md 2026-11-01.
- Settings: Graphics > VR (VR on / off `VCS_VR`, view head-tracked / cinema, cinema distance and width, HUD distance),
  recentre key F7 / Back + L3. Control command `vr` (status, why frames went to the cinema screen; `vr recenter`).
- Checked (hidden runs on an exe copy, card copy of `build\rig\saves\user`): the game unchanged without VR.asi and with
  it but no runtime (one log line); against `xr_test_runtime.dll` (VCS-mods `plugins/VR/test`, a simulated head with a
  yaw sweep and roll, CPU-composited eye images): session states to FOCUSED, 90 Hz pacing, head-tracked projection +
  HUD quad on every in-game frame, the F2 menu and loading screens on the cinema quad, the game camera turning and
  rolling with the head. **Not checked on a real headset** (none here): comfort, the real runtimes' swapchain formats,
  frame timing at 72-120 Hz.
- 2026-11-01, later: `<exe folder>\run\vr.log` for players (runtime, headset, views, formats, refresh, every state
  change and XrResult error, what is shown and why) and a "VR status" readout in F2. `xr_test_runtime.dll` now checks
  the spec (call order, states, display time, released images, layers: `VALIDATION` lines) and takes a control file
  (sleep / wake / focus / loss / exit / instance loss / recentre / refresh); `build\vr\vrscenario.py`'s 17 steps (on
  foot, recentre, F2, dashboard, asleep / awake, 72 / 120 / 90 Hz, session loss, runtime restart, runtime exit, off / on,
  a car) pass at 90 Hz RGBA sRGB, 72 Hz BGRA sRGB typeless images, 120 Hz linear RGBA, 0 violations. Fixed on the way:
  a crash switching off / losing the instance mid-frame, a runtime restart during start counted as a failure, the
  status never updating. Not covered (hidden runs): window resize / minimise / alt-tab, cutscenes (same path as the
  car: no first person -> cinema).
- A friend package (`dist\VCS-VR-friend`, local only): the mods built from VCS-mods 3956187, the fork's vcs-mods source
  (93d18e2) as a zip, README_VR.txt. No vcs.exe: upstream releases ship none (source-only, DECISIONS.md 2026-10-21) -
  vcs.exe holds the recompiled game.
- 2026-11-01, real-headset feedback ("first person occludes", "performance not great"): (1) in VR CameraAim hides the
  player's body (Game > First person > "In VR: your body": Hidden - the default -, Arms and gun, Body), collapses the
  neck too, takes the near plane down to 5 cm, drops the flat-screen "eyes ahead when looking away" push and adds the
  headset's position (leaning, ducking; within 0.6 m); eye captures looking ahead / down / down-right / behind / left /
  leaning show nothing of the player (`build\vr\vrperf.py occlusion`; Body mode shows the torso filling the lower view,
  the friend's "occlusion"). (2) The window's frame limiter paced the loop: with the default cap of 60 a 90 Hz headset
  got 60 frames a second (each shown 1.5x: judder). `vr_set_pacing(hz)` (frame-rate independent timing) runs the game
  at the headset's rate with the limiter and vsync out of the way while VR runs. Measured in the city (575, 175),
  test runtime, hidden: before 59.8 host fps / 59.8 new frames into 90 Hz; after 90.0 / 90.0 (8.4 ms of each 11.1 ms
  spent waiting for the headset), 120 Hz: 119.9 / 119.9 (5.6 ms waiting); VR.asi's own work 0.04 ms CPU, 0.015 ms
  GPU per frame. Render scale (Graphics > VR, 50-150%): the picture sized for the headset's pixels over the game's
  field of view (`render_set_output_size`), not the window's. Original (PS2) timing keeps its 60 Hz host loop.
- Next: M1 (stereo by frame replay). Known gaps: vehicles are cinema-only; the HUD is world-locked (it does not follow
  the body's turn); the window still presents (vsync on can halve the headset's rate: turn Display > Vertical sync off).
yes, and this port is better placed for it than any PC GTA. The renderer records every frame as a list of draw
commands (`Frame` in gs_hw.cpp) and runs that list on the main thread. Native draws carry their window matrix, and every
3D vertex still carries its GS z (and z gives view depth). So the renderer can draw the same game frame twice, once per
eye: real stereo, one game tick, no alternate-eye rendering and no image warping.

## Prior art (GitHub / web, checked 2026-10-31)

| Project | Stars, activity, licence | Technique | What to borrow |
|---|---|---|---|
| [hrydgard/ppsspp](https://github.com/hrydgard/ppsspp) `Common/VR/` | 14.8k, active, GPL-2 | OpenXR (PC + Quest). The PSP GE gets separate world / view / projection matrices: the headset view is put in front of the game's view (`UpdateVRView`: hmdView x gameView), the projection is replaced with the eye FOV, 2D draws are found from their matrices (`Is2DVRObject`) and drawn flat. Per-game hacks in `assets/compatvr.ini` | **VCS (PSP: ULUS10160 etc.) is already listed there**: `Skyplane` hack (the sky plane is removed and the frame is cleared with the fog colour) and `UnitsPerMeter = 1.0`. Same engine (Rsl), so game units are metres and the sky plane needs care. Also the `VR_MODE_*_SCREEN` vs `*_6DOF` split (menus / cutscenes on a screen). |
| [dolphin-emu/dolphin](https://github.com/dolphin-emu/dolphin) stereoscopy | 15.7k, active, GPL-2+ | The emulated GPU's draws are doubled into a 2-layer target by a geometry shader. Each vertex gets `pos.x += eyeOffset * (pos.w - convergence)` (`GeometryShaderGen.cpp`), so pre-projected geometry works too | The cheap per-vertex stereo for draws already in screen space: shift x by depth. Our version is exact (unproject from GS z, then reproject per eye). |
| [CarlKenner/dolphin](https://github.com/CarlKenner/dolphin) (Dolphin VR) | 144, inactive since 2023, GPL-2 | Oculus / OpenVR: headset pose put into the GC/Wii projection, a 3D HUD by depth heuristics, free look, per-game scale | The UX checklist: life-size scale, HUD as a layer in space, aiming separate from the head. |
| [Crementif/BotW-BetterVR](https://github.com/Crementif/BotW-BetterVR) | 1.6k, 2026-08, MIT | Cemu (Vulkan layer + game patches). **Full stereo, no AFR**: the game's camera is patched per eye and both eyes are rendered for one game tick. Hands / arms, two-handed weapons, snap turn, OpenXR | The closest in spirit: an emulated console game with the renderer and the game's camera both under the mod's control. CPU-bound, as we will be. |
| [praydog/UEVR](https://github.com/praydog/UEVR) | 4.7k, active, MIT-like | UE4/5 injector, D3D11/12 + OpenXR/OpenVR. Three modes: Native Stereo (the engine's own stereo path), Synchronized Sequential (two views rendered in one engine tick), AFR (one eye per frame, eyes out of sync, nausea) | Why AFR is a last resort. The 3DoF/6DoF split, UI on a quad, aim method (head / controller), roomscale, decoupled pitch. |
| [praydog/REFramework](https://github.com/praydog/REFramework) | 5.7k, active, MIT | RE Engine VR in a plugin DLL: OpenXR + OpenVR backends, D3D11/12 swapchains, the engine's camera driven per eye, motion-controller aim, UI on an overlay | Clean OpenXR-in-a-DLL code: `src/mods/vr/runtimes/OpenXR.cpp`, D3D11 swapchain copy, the action set. **Best code to read for VR.asi.** |
| [LukeRoss00/gta5-real-mod](https://github.com/LukeRoss00/gta5-real-mod) (R.E.A.L. VR) | 1.2k, frozen 2022 (Take-Two DMCA), no licence | Alternate-eye rendering: each game frame renders one eye, the next frame the other (the game's camera offset per frame). Frame rate per eye is halved and the eyes are out of sync | GTA UX: first-person on foot / in cars, free aim, recentring, cutscenes on a screen. **Legal risk: Take-Two shut it down.** |
| [vittorioromeo/quakevr](https://github.com/vittorioromeo/quakevr) | 346, active, GPL-2 | Source port: native two-pass stereo, OpenVR, hands, melee, weapon offsets per gun | Weapon / hand offset tables, aiming and the viewmodel from the controller (like CameraAim's arms). |
| [vittorioromeo/HL2VRU](https://github.com/vittorioromeo/HL2VRU), [DrBeef/HL2VR_d3d9](https://github.com/DrBeef/HL2VR_d3d9) | 195 / 6 | Source engine renders each eye's view. D3D9 proxy into a VR swapchain | A D3D-proxy design for a game that already draws a second view |
| [Team-Beef-Studios](https://github.com/Team-Beef-Studios) (QuakeQuest 146, Doom3Quest 136, Lambda1VR 252, RTCWQuest 80) | active, GPL | Native stereo (multiview) on Quest. Weapon on the controller, comfort vignette, snap / smooth turn | Comfort options and how they are set (snap angle, vignette, height) |
| [amwatson/CitraVR](https://github.com/amwatson/CitraVR) | 987, active, GPL-3 | 3DS emulator on Quest. Uses the 3DS's own stereo pair, shown on a panel in space | Panel / "screen" mode for menus and cutscenes |
| [KhronosGroup/OpenXR-SDK-Source](https://github.com/KhronosGroup/OpenXR-SDK-Source) `hello_xr` (839, Apache-2), [maluoi/OpenXRSamples](https://github.com/maluoi/OpenXRSamples) (100, MIT, D3D11 single file) | | The minimal D3D11 OpenXR session: `XR_KHR_D3D11_enable`, swapchains, `xrWaitFrame` / `xrBeginFrame` / `xrEndFrame`, projection + quad layers | M0's skeleton. Vulkan: `XR_KHR_vulkan_enable2` from the same sample. |
| [mbucchia/OpenXR-Toolkit](https://github.com/mbucchia/OpenXR-Toolkit) (460, MIT), [fholger/vrperfkit](https://github.com/fholger/vrperfkit) (1.5k) | | OpenXR API layer: upscaling, foveated rendering (VRS), overlay | Later: fixed foveated render (VRS) and upscaling for the GPU cost |
| vorpX (closed) | | "Geometry 3D" (per-draw shader stereo, like ours) vs "Z3D" (one image + depth shifted into two eyes) | Z3D shows the artifacts of approach (c) |
| GTA III / VC / SA: [gta-sa-vr-quest](https://github.com/dubrovskiy-yevhen-stakelogic/gta-sa-vr-quest) (106, SA Android on Quest), [SA DE VR](https://github.com/Gangbusters1337/SAN-ANDREAS-VR-DEFINITIVE-EDITION) (13) | | Patched mobile / DE executables. No re3 / reVC VR fork found on GitHub | RenderWare-era GTA UX on a headset |

Not found: a PCSX2 VR fork (OpenXR was only discussed). This port would be the first stereo PS2 title. It can be done
here because the renderer is native. A PS2 emulator could not do it, since VU1 projects vertices before the GS sees them.

## How the frame reaches D3D11 (what stereo has to cope with)

- **Native draws** (world sectors, peds, vehicles, props, wheels: most of the 3D). They are recorded as `NativeDrawCmd`
  with the folded window matrix M = K V L (lens x camera x model, into GS pixels, z = a + b / w) in their constants.
  Per eye this becomes M_e = K_e D_e K^-1 M, where D_e is the eye's offset / rotation in view space. The velocity pass
  already redraws these draws with another matrix (`velocityPass`), so the mechanism exists.
- **Packed / GS-path draws** (VU clipper output near the camera, env-map pass, 0x02c0 sprites / particles / shine,
  coronas, blob shadows, the sky strips, PATH2 effect quads). These arrive as GS pixels with z, after the PS2's 1/16-pixel
  snap. Each vertex can still be unprojected exactly: w = b / (z - a), x_v = (x - cx) / fx * w, ... Then apply D_e and
  K_e, and re-snap. This goes in `gs_draw.hlsl` next to the jitter (`cbuffer Draw.jitter` is the same kind of hook). The
  sky at z ~ 0 (infinite w) takes the rotation only. Screen-aligned sprites (particles, coronas) keep their size and
  only move by parallax. That is what the PS2 drew, and it looks right in stereo.
- **Full-screen 2D on the picture** (frame copy, self-copy over the sky, bloom, trails, motion blur, colour filters,
  fades) runs per eye on that eye's targets, unchanged. Trails and motion blur are off by default in VR (comfort).
- **Reflection map** (FBP 420, a 128x128 sample of the picture plus a sun sprite) is built once, from the left eye. A
  mono reflection is fine.
- **HUD and menus** are already a separate layer (`composeDisplay`'s HUD layer, its own target at output size). In VR
  that layer goes to an OpenXR quad layer, not onto the picture. Frames with no 3D (menus, loading) are quad only.
- **Culling.** Sectors and the VU matrices follow the view window (0x21cdd4, our Hor+). Entity culling follows the FOV
  global alone (`FUN_0037b2c8`, v = 0.7 h), and LOD scales are 70 / FOV. The game camera must cover both eyes'
  combined FOV plus margin for late head motion. Keep LOD at 70 / 70 so a wider FOV does not lower detail.
- **Timing.** "Frame-rate independent" timing already runs the game up to 240 fps, so 72 / 90 Hz game frames are
  possible. The game thread is ~3-5 ms. The render worker is 8-12 ms in the city, the main bottleneck.

## Approaches assessed

| | How | Verdict |
|---|---|---|
| **(a) Synchronized stereo by frame replay** | One game tick. The renderer executes the recorded `Frame` twice into per-eye picture targets, with D_e / K_e applied per draw (native: matrix; packed: unproject / reproject). Resource side effects (texture uploads, mesh creates, VRAM write-backs, rt drops) happen on eye 0 only | **Recommended.** Correct stereo for everything that has a depth, with no game-side changes for the second eye. Cost: about 2x GPU and executor time. The game thread and worker (the expensive part) are unchanged. |
| (b) AFR | The game camera is offset left / right on alternate game frames (R.E.A.L.-style), at 2x game rate | Fallback only. It is the easiest (game-side only), but the eyes are out of sync on every moving object, the game must run at 144-180 fps, and particles / physics step between the eyes. UEVR warns about nausea. |
| (c) Depth reprojection | One mono render plus the Z buffer, warped into two eyes in a full-screen pass (Z3D) | Useful as a cheap "comfort stereo" toggle and for low-end GPUs. Disocclusion holes, and wrong depth for particles, water and transparencies (they do not write Z). Not the main mode. |
| (d) Game camera from the headset | CameraAim's first person (eye at the head bone) gets the HMD orientation as the look. The body yaw follows the head with a dead zone, aim is separate. The view in vehicles comes from the seat | **Needed with (a)**: (a) gives two eyes around the game's camera; (d) makes that camera the player's head. Third-person / cutscenes: the game camera with head rotation only, or a "cinema" quad (PPSSPP's screen mode). |

Late head motion: the game camera uses the pose predicted at the game frame's start. The replay applies the newest
predicted pose's delta through D_e (a re-render, not a warp, so no edge artifacts). The runtime's own reprojection
covers the rest. If the game drops below the HMD rate, the last `Frame` can be replayed with the new head pose: a real
6DoF "re-render", better than ASW for head rotation.

## Recommended approach

The stereo renderer goes in vcs.exe (as with jitter, only the renderer can move every draw). OpenXR, input and comfort
go in a mod, `VR.asi` (VCS-mods `plugins/VR`), using the OpenXR loader (Apache-2) and modelled on REFramework's
OpenXR runtime. CameraAim gets a small "external look / aim" input.

### What the exe needs (renderer + mod API, appended to API 1)

1. `render_native_device()`: the D3D11 device / immediate context, or the Vulkan instance / physical device / device /
   queue family. OpenXR needs these to make its session (`XrGraphicsBindingD3D11KHR` / `...VulkanKHR`).
2. `render_set_views(count, VcsView[])`: count 1 or 2. Per view: target size, the eye's D_e (view-space 4x4 relative to
   the game camera) and its asymmetric lens (tan left / right / up / down). The executor replays the frame per view
   into per-view picture targets (FBP 140 / 0 / Z 280 each get a view index; effect buffers shared and redrawn per
   view; side effects on view 0).
3. A hook point `VCS_RENDER_VIEW_DONE(view)`: the finished picture per view, after post effects and before the HUD
   layer. `VCS_RENDER_HUD_LAYER`: the HUD / menu layer as its own texture (transparent background). The mod copies them
   into OpenXR swapchain images (or the exe renders straight into textures the mod hands over: swapchain wrap,
   M1 polish).
4. `set_frame_pacer(fn)`: called by the main loop before it lets the game start a frame, so the mod can block in
   `xrWaitFrame` and read the predicted display time. Also "present to window: mirror / off".
5. Camera input for the game: `set_view_override(yaw, pitch, roll, pos offset)`, used by CameraAim (on foot and in
   vehicles, it already owns the camera), and the culling margin: FOV global and view window set to the combined
   FOV + margin, LOD scale pinned.
6. Controllers: `set_pad_override(VcsPad)` (OpenXR actions mapped onto the DualShock 2 report the controls build) and
   CameraAim's `set_aim_ray(origin, dir)` (free aim shoots along the controller ray instead of the dot's line).
   The viewmodel arms take the controller pose as the IK target (the two-bone IK for the support hand exists).

### Milestones

- **M0 - OpenXR session, head-tracked mono (1-2 weeks).** VR.asi creates the session on the exe's D3D11 device, paces
  frames with `xrWaitFrame`, and submits the mono picture as a projection layer (same image both eyes, rendered at the
  HMD's combined FOV with the pose it was rendered for). The HUD / menus go on a quad 2 m ahead. CameraAim's first
  person takes the head orientation. Menus, loading screens and cutscenes go on a "cinema" quad. Done when: Fort
  Baxter and a Downtown street on foot at 72-90 Hz, head look correct and level, HUD readable, recentre key, D3D11 only.
- **M1 - stereo by frame replay (3-5 weeks).** `render_set_views(2)`. Per-eye native matrices. Packed draws unprojected
  / reprojected in `gs_draw.hlsl`. Per-view picture targets. Post effects per eye. Reflection map once. Sky as
  rotation only. Late-pose D_e. IPD and world scale (1 game unit = 1 m, PPSSPP agrees). Checks: a stereo-pair
  screenshot rig (`PS2X_HW_FRAME`, hidden runs), vertical disparity 0 on static scenes, particles / coronas / blob
  shadows at the right depth, GPU time per eye, Vulkan compiles.
- **M2 - controllers and aim (2-4 weeks).** OpenXR action set (Index / Touch / WMR profiles) to the pad. Aim ray from
  the right controller (free aim's shot line). Arms / gun from the controller pose. Two-handed rifles (support hand to
  the left controller). Drive-by aim. Vehicle steering stays on the stick (no wheel grab at first).
- **M3 - comfort and HUD (2-3 weeks).** Snap / smooth turn, vignette while moving and in cars, seated / standing
  height, the HUD on a body- or vehicle-locked quad (radar at the wrist as an option), crosshair as a 3D reticle at the
  hit depth, cutscenes as "cinema" or head-rotation-only, trails / motion blur / screen shake off, a VR page in F2
  (the mod's rows), the desktop mirror.
- Later: fixed foveated rendering (VRS on the per-eye targets), per-object stereo for the reflection map, a 6DoF
  body / neck model, a third-person "follow cam" stereo mode.

Total: roughly 2-3 months of focused work to a playable on-foot + driving VR.

## Risks

- **Executor replay side effects.** The recorded `Frame` mixes draws with uploads, rt drops, VRAM write-backs (the
  bloom buffers back into VRAM for the vehicles' FBP 420) and copies between targets. These have to be split into
  "once" and "per view". This is the biggest M1 task. Bugs show up as one eye wrong.
- **Packed draws with no meaningful z** (flat 2D drawn inside the 3D picture, ZTST ALWAYS strips) get eye-dependent
  wrong depth. They need classifying, as the HUD classifier does.
- **Near plane 0.3 m.** The arms and gun get clipped close to the eyes, and an eye offset can push near vertices behind
  w = 0 (clipper guard band). Lower the near clip in VR (CameraAim has the setting) and clip per eye on the GPU.
- **Performance.** 2x the picture at ~2k x 2k per eye with MSAA. The render worker (8-12 ms) caps the rate in the city.
  It may need 72 Hz plus replay re-render for the missing frames. Entity culling at a wide FOV draws more peds and cars.
- **Game logic tied to the camera.** Stream / LOD distance, peds spawning out of view, the radar's heading, and
  scripted cameras (cutscenes, missions) that fight the head pose. Mission cameras fall back to the quad.
- **Comfort.** Vehicle camera shake, car rolls and camera lag must be removed in VR. AFR is never the default.
- **Vulkan backend.** OpenXR's Vulkan path needs the instance / device created through `xrCreateVulkanInstanceKHR`, or
  extensions chosen by OpenXR. That is a device-creation change, not just a handle hand-over. D3D11 first.
- **Legal.** Take-Two DMCA'd R.E.A.L. VR for GTA V. Keep VR.asi in the user's own repository, distribute no game data.

## Starting points in the code

`third_party/PS2Recomp/ps2xRuntime/src/lib/gs/gs_hw.cpp`: `Frame`, `NativeDrawCmd`, the executor's frame loop (~4975
`composeDisplay`), `velocityPass` (redrawing native draws with other matrices), `runSceneHook`, jitter
(`gsHwSetJitter`). `src/render/shaders/gs_draw.hlsl`: snap + jitter (where the per-eye reproject goes).
`src/render/presenter.cpp`: present / swapchain. `src/modapi/mod_render.cpp` and `vcs_mod_api.h`: the API surface.
CameraAim (VCS-mods `plugins/CameraAim`): the look handler, head-bone eye, free aim line, viewmodel IK.
game-internals.md 5 (FOV / view window / entity culling), 12c-12e, 12t.
