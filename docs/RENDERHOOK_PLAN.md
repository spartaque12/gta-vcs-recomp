# RenderHook-style graphics for the port

Status (2026-10-31): the plan below; **milestone 1, ground-truth ambient occlusion, is done** as a mod, `RenderHook.asi`
(VCS-mods `plugins/RenderHook`), on the render hooks the mod API gained for it (MODDING.md "Rendering",
NATIVE_RENDERER.md "Frame hook for render mods"). Off by default; with the mod not installed or the option off, the
picture is the original's.

## Why not a port of RenderHook itself

gtaRenderHook (GTA SA, D3D11; the user has contributed AO, shadow and motion-vector work to it) hooks San Andreas'
RenderWare D3D9 pipeline inside gta_sa.exe. VCS is Rockstar Leeds' Rsl engine (PS2 VU programs), drawn by this port's
own renderer: the GS hardware renderer (`third_party/PS2Recomp/ps2xRuntime/src/lib/gs/gs_hw.cpp`, shaders in
`src/render/shaders`) on the RHI (D3D11 / Vulkan), with native world sectors, skinned / lit peds and vehicles and native
post effects (NATIVE_RENDERER.md stages 5-8). So RenderHook's *features* are rebuilt there, not its code - and, the user's
choice (2026-10-31), as an `.asi` mod rather than inside vcs.exe.

## What the renderer gives an effect (measured 2026-10-31)

- **Depth.** The GS Z buffer: Z24 at ZBP 280, kept in a D32F target as z / 2^24, filled with 0 (= far) at each frame's
  start; the world, the water, peds and vehicles write it, the sky leaves it 0. It is **reversed and linear in 1/w**:
  GS z = a + b / w with w the view depth in metres; measured a = 10424, b = 115600-115700 (z 395,800 at the 0.3 m near
  plane, 10,480 at 2000 m). Only vertices carry integer z; pixels hold the interpolated float, so the precision is fine
  everywhere (~3 mm at 100 m). At the picture's resolution (native frame / internal scale) and MSAA sample count.
- **The camera.** Every native draw carries its folded window matrix (model -> GS pixels: M = K V L, K the lens, V the
  camera, L the model). The Z mapping (a, b) comes out of any draw exactly; the lens (fx, fy) from the orthogonality of
  the model axes' images (the columns of K^-1 M) with the centre at the picture's middle - valid for rigid models and for
  the world's quantised packets (int16 positions times a scale per axis), not for one matrix alone with "lengths relative
  to the w row" (that read fy 30-545 instead of 1028 from many world packets). The game's own aspect choices show: the
  hospital tutorial's scripted camera projects with fy = 15/16 of the usual (a 5:3 view window, game-internals.md 5).
- **Normals.** None for the world: it is prelit, the lighting and the time-of-day tint baked into vertex colours
  (game-internals.md 6d). Peds, vehicles and props (the lit pipeline) carry normals, lit per vertex by four
  directional lights and ambient the game computes. Screen-space effects reconstruct normals from depth.
- **The frame's order** (game-internals.md 6g, corrected): sky gradient and clouds, the world (native), the water, the
  sky's self-copy, the reflection map, *then* peds and vehicles (native lit) and their environment pass, blob shadows,
  particles and coronas, then the post chain (bloom, trails, motion blur), the Z clear, the HUD layer.
- **Time of day.** The clock at `0x4CD148` / `0x4CD149`. The sun's direction and the timecycle colours are not located
  yet (the first research step of the shadow and sky milestones; the lit pass's light directions are in the VU data,
  folded into model space).

## Features and fit

| RenderHook feature | Fit | Needs | Cost | Order |
|---|---|---|---|---|
| Screen-space AO (GTAO) | good | the depth, the camera, a point after the 3D scene and before the post effects | S-M | **1 - done** |
| Colour grading / tonemapping | partly: a curve / LUT over the finished picture (LDR: the PS2's 8-bit colour maths with clamping, blends defined in 8 bits - no HDR) | a hook point after the post chain, before the HUD layer, reading the resolved picture (the API's `VCS_RENDER_NEEDS_RESOLVED_COLOR` exists for it) | S | 2 |
| Bloom polish | possible (a mip-chain bloom instead of VCS's 256x256 one), but the game's bloom / trails are its look | the native post buffers (`nativeBloom`) | S-M | optional |
| Sky pass (atmospheric scattering) | possible | replacing the sky gradient strips (an untextured 18-vertex strip at the far plane, ZTST ALWAYS), the sun's direction and time of day, the camera's rotation (from a world packet's matrix, whose L has no rotation), the timecycle's sky colours to keep the art direction | M | 3 |
| Sun shadow maps (world, peds, vehicles) | partly | the sun's direction; the casters: the frame's native meshes are cached on the GPU, re-drawn from the sun with L = (K V)^-1 M per draw - an API to replay native draws into a mod's target; casters off screen need the game's sector walk for the light's volume (FUN_0023E748 / FUN_00240ED8: RenderHook's "shadows disappear by camera angle" problem again); receivers: the world's baked colours darkened by a time-of-day factor, lit models with the directional term split in `vs_lit` | L-XL | 4 |
| Dynamic point lights (lamps, headlights) | partly | the game's light list (not located), positions and normals from depth, an additive pass before the particles | M | 5 |
| Full deferred PBR relighting (RenderHook's core) | no | albedo without baked light, world normals, materials - none exist; it would replace the game's art direction | - | - |
| SSR | later, water and car paint only | normals (lit models), material masks | M | - |
| TAA / DLAA, velocity motion blur | possible, separately | per-object previous transforms (native draws keyed by mesh) and a velocity target | L | - |

## Milestone 1: ambient occlusion (done 2026-10-31)

- **vcs.exe**: the renderer's frame hook (`gsHwSetFrameHook`, runtime `gs_hw.cpp` `RhiExecutor::runSceneHook`): armed by
  the frame's native 3D, run before the first post-effect read of the picture (the bloom / trails downsample), the motion
  blur's blend or the Z clear before the HUD; the depth buffer made sampleable once a hook reads it; the camera from the
  frame's draws (above). The mod API's render part (`src/modapi/mod_render.cpp`, `vcs_mod_api.h` "Rendering": a hook
  point, textures, constants, full-screen pipelines from DXBC / SPIR-V, passes - the RHI behind opaque handles). The RHI's
  multisampled texture slots (`PipelineDesc::multisampledTextures`; Vulkan binds a multisampled depth only there).
- **RenderHook.asi** (`VCS-mods/plugins/RenderHook`, `shaders/gtao.hlsl`, DXBC by fxc and SPIR-V by glslang at build
  time): three full-screen passes - the Z buffer to view depth (R32F; sample 0 with MSAA), GTAO visibility (2 slices per
  pixel x 4 steps each way, the slices rotated in a 4x4 pattern, normals from depth, XeGTAO's falloff and integral), a
  depth-aware 4x4 blur (each window holds the 16 rotations once) multiplied into the picture; faded by the game's fog
  (visibility from the world draws' fog constants) and out between 120 and 350 m.
- **Settings** (F2 > Graphics > Lighting (RenderHook)): Ambient occlusion Off (original) / Subtle / Normal / Strong
  (`renderhook.ao`, `VCS_RH_AO`), Occlusion radius 50-300 cm (`renderhook.ao_radius`, default 120, `VCS_RH_AO_RADIUS`);
  `VCS_RH_AO_VIEW=1` (or the control command `renderhook view 1`) shows the occlusion alone; `renderhook` reports frames,
  the camera and the depth mapping.
- **Checked** in hidden runs on a copy of the user's card, from a privately linked exe: 16:9 1920x1080 native frame with
  MSAA 4x (as the user's settings had it then) at Fort Baxter, a Downtown street (-675, 1425), the hospital tutorial's
  scripted shot and the sea; 4:3 640x448 without MSAA at Fort Baxter. Off / Normal / Strong / occlusion-only shots:
  `build/aotest/rh_final`, `rh_final_1x`, side by side in `build/aotest/compare*`. The hook ran in every 3D frame (0
  missed), the lens was agreed in every frame (1028.27 x 1028.27 px at 1080p - tan 0.933 x 0.525; 457.0 x 426.5 GS pixels
  at 4:3). GPU time of the three passes (`PS2X_GPU_TIMING=1`, RTX 4070 Ti SUPER): 0.5-0.7 ms per frame at 1080p with
  MSAA 4x, 0.05 ms at 640x448. The Vulkan backend and the renderer library compile with `VCS_RHI_VULKAN=ON`; not run on
  Vulkan. `python tools/renderhook_check.py --asi <RenderHook.asi> [--exe <copy>] [--small]` repeats the check (fails
  when the mod does not load, the hook misses or skips frames, or the camera is implausible); `tools/exe_copy.py` links
  the private exe it can run while build\vcs.exe is in use.
- **Known**: particles, blob shadows and coronas are drawn before the hook point, so they are darkened where the surface
  behind them is occluded (an earlier point would leave out peds and vehicles, which VCS draws after the reflection map);
  seams in the sea surface give faint dots; no temporal filter (none needed for the noise, the blur removes the pattern).

## DLAA, step 1: jitter and camera motion vectors (done 2026-10-31)

The user's RHDLAA (DLAA for RenderHook in SA through NGX, with a 64-bit helper) shows the inputs: the picture before the
post effects, depth, jitter, motion vectors. vcs.exe is 64-bit, so NGX can run in the game's process (step 3).
- **Jitter** (`gsHwSetJitter`, mod API `render_set_jitter(phases)`): the 3D picture's draws - native and GS, into the
  640-wide targets, not copies or layers - are offset by a Halton (2, 3) point per frame, added in `gs_draw.hlsl` after the
  PS2's 1/16-pixel snapping (`cbuffer Draw.jitter`); advanced at each frame's Z clear. Off by default.
- **Camera reprojection** (`sceneReprojection` in gs_hw.cpp): a static world mesh drawn once in this frame and the last
  has S_prev = M_prev M_cur^-1 S_cur whatever its model matrix, so R = M_prev M_cur^-1 is the camera's motion; the R that
  at least two meshes agree on (moving meshes give others), between consecutive frames only, composed with both frames'
  target-pixel mappings into `VcsRenderFrame.reproject` (with this / the last frame's jitter). A mod turns pixel + depth
  into a motion vector with it (RenderHook.asi `shaders/temporal.hlsl previousPosition`).
- **Checked** (hidden run, Downtown street, 1080p MSAA 4x, `build/aotest/rh_taa1`, `compare/renderhook_motion_vectors.jpg`):
  reprojection agreed in all but one frame; turning the camera, the previous picture differs from the current by 56.6
  (mean of 0-255, centre of the screen) unwarped and 6.2 warped by the vectors (0.13 standing still) - the static world
  lines up, moving cars and peds do not (no object vectors yet). With an 8-point jitter the warped residual is ~9:
  edge aliasing between differently jittered frames, what DLAA resolves.
- Debug: `VCS_RH_JITTER=N`, `VCS_RH_MV_VIEW=1` (vectors as colour) / `2` (warped previous - current) / `3` (unwarped);
  control command `rhtaa [mv N | jitter N]`.

## DLAA, step 2: per-object motion vectors (done 2026-10-31)

- **Velocity pass** (`velocityNote` / `velocityPass` in gs_hw.cpp, `src/render/shaders/gs_velocity.hlsl`, hook flag
  `GSHwFrameHookVelocity` / `VCS_RENDER_NEEDS_VELOCITY`, `VcsRenderFrame.velocity`): at the hook point the scene's native
  draws are drawn again into an RGBA16F target (own depth buffer) with this frame's and the last frame's window matrix:
  xy = pixels moved (unjittered), z = view depth, w = covered. Cached meshes (world, vehicles, wheels, props) are matched
  by mesh key, skinned draws (peds) by kind and vertex count with their last-frame vertices kept; among several instances
  the one whose model origin was nearest on screen (by draw order, the followed car got another car's motion). RHI:
  `Format::RGBA16F`.
- **The mod** (`temporal.hlsl previousPosition`) takes the object's motion where the velocity buffer covers the pixel at
  the Z buffer's depth (2% + 5 cm), the camera's reprojection elsewhere; `rhtaa objects 0|1` compares; `rhtaa mv 4` shows
  the buffer (red covered, green moved, blue depth agrees).
- **Checked** (hidden run, standing player, three AI cars driving off and crashing, `build/aotest/rh_taa6`,
  `compare/renderhook_object_motion.jpg`): warped-previous error on the cars 11.8 -> 6.8 (mean, six alternating
  frames; every pair lower). Not covered: draws through the VU clipper's GS path (geometry crossing the guard band - the
  road near the camera, often the car the camera follows closely; static parts still get the camera's reprojection),
  particles, the GS-path draws in general. A fix for clipped packets would hand their matrix over from
  `game/vcs_hle_world.cpp` with the clipper's output. Step 3: DLAA through NGX in RenderHook.asi (the API then needs the native D3D11 / Vulkan
handles, a float motion-vector target and an output size), MSAA off while it runs.

## DLAA, step 3: DLSS at native resolution through NGX (done 2026-10-31)

- **API** (appended to API 1): `render_current_color()` - the picture as it is now, single-sampled, with what earlier
  hooks drew (`GSHwFrameView::currentColor`, gs_hw.cpp `hookCurrentColor`: the target marked dirty, resolved again);
  `render_native(VCS_RENDER_NATIVE_DEVICE / CONTEXT / TEXTURE, t)` - the D3D11 device, immediate context and a texture's
  `ID3D11Texture2D` (RHI `Device::native`; NULL on Vulkan for now); `render_create_texture_ex(..., flags)` with
  `VCS_RENDER_TEXTURE_STORAGE` (RHI `UsageStorage`: an unordered-access view, DLSS's output) and
  `VCS_RENDER_FORMAT_RGBA16F`.
- **The mod** (`plugins/RenderHook/src/dlaa.cpp`, built only with `-DVCS_NGX_DIR=<DLSS SDK>`, else `dlaa_none.cpp`): a
  BEFORE_POST hook after the AO's (so DLAA sees the occlusion) needing depth and velocity; passes `ps_dlaa_depth`
  (reversed depth 0.05/w, sky 0) and `ps_dlaa_motion` (the step 1/2 motion as previous - current pixels) into its own
  R32F / RGBA16F targets; NGX initialised in the game's process with the folder of RenderHook.asi as the path for
  `nvngx_dlss.dll`; the feature is DLAA (`PerfQuality_Value_DLAA`, render = output size, flags `DepthInverted |
  MVLowRes`; LDR, no auto exposure); jitter = the frame's Halton offset in pixels (8 phases while on); reset on the
  first frame, a size change and frames without the camera's reprojection. The result is copied back over the picture
  (RGB). nvsdk_ngx_s.lib is built with the static CRT, so the NGX build of RenderHook.asi is `/MT`.
- **Settings**: Graphics > Anti-aliasing (RenderHook): `renderhook.dlaa` Off / On (`VCS_RH_DLAA`), `renderhook.dlaa_preset`
  Default / F / J / K. Command `rhdlaa` (mode, frames, failures, status / why not). Diagnostics:
  `VCS_RH_DLAA_JITTER_SIGN=-1`, `VCS_RH_DLAA_MV_SIGN=-1`.
- **Checked** (hidden run, 1080p, MSAA off, RTX 4070 Ti SUPER, `build/aotest/rh_dlaa2`): NGX starts, 0 failed
  evaluations; toggled off / on / off / on standing still, the picture otherwise unchanged (mean difference off-on 2.1
  vs off-off 1.9: the same idle motion) with edges smoothed (lamp posts, cables, roof lines); turning the camera no
  smearing seen. GPU: about 1.5 ms a frame at 1080p (`PS2X_GPU_TIMING=1`, marker "renderhook dlaa": both passes + DLSS). Not done: Vulkan (needs NGX's Vulkan path and `render_native` for it), MSAA left on wastes its cost,
  no binaries in VCS-mods (the user's own DLSS SDK folder).
- **Known gap**: Project2DFX's vegetation wind sway (Graphics > Vegetation wind, vs_world `nat[15..17]`) is not replayed by
  `vs_velocity_mesh`, so swaying palm crowns get the camera's motion only and may ghost under DLAA; matching it needs this
  and last frame's wind constants per draw in the velocity pass.

## Sun shadows, step 1 (done 2026-11-01)

The user asked for GI with shadows; the order agreed: the sun's direction, sun shadows, then screen-space GI.
- **The sun**: the timecycle's ring of sun vectors at `0x4E7200`, the newest at the index in `0x4EA568` (game-internals.md
  6n: how it was found, values per hour).
- **Renderer** (gs_hw.cpp): `sceneView` - the camera's rotation in the world from the static world's window matrices
  (their model matrices have no rotation), `GSHwFrameView.worldToView`; `GSHwFrameHookShadow` keeps the scene's native
  draws that write Z (`shadowNote`: cached meshes by key, skinned positions copied; blending is no filter - VCS blends
  nearly every draw, the first version filtered on it and kept nothing); `shadowPass` draws them depth only (D32F,
  larger = nearer the light) into up to 4 viewports side by side with view -> clip matrices the caller gives, each draw's
  window matrix taken back into view space through the lens (`src/render/shaders/gs_shadow.hlsl`).
- **API** (appended to API 1): `VCS_RENDER_NEEDS_SHADOW`, `VcsRenderFrame.view_valid / world_to_view`,
  `render_shadow_map(view_to_clip, count, size, &drawn)`.
- **The mod** (`plugins/RenderHook/src/shadows.cpp`, `shaders/shadows.hlsl`): the sun into view space; 3 cascades
  (practical split, lambda 0.75, 0.5 m to the shadow distance) fitted as bounding spheres of the frustum's depth slices,
  the light basis tied to the world's east axis and the centres snapped to whole texels from the camera (steady while the
  camera turns; moving the camera still shifts the grid), casters reach 250 m towards the sun; one full-screen pass: the
  view point from the Z buffer, its normal from the neighbours' depths, a normal offset of 1.5 texels, a 3x3-texel filtered
  compare (16 loads, bilinear weights), the band before a cascade's end blended into the next; faces turned from the sun
  count as shadowed, side-on ones partly (smoothstep -0.15..0.25 of N.L); faded out over the last 20% of the distance,
  by the game's fog, and by daylight (sun height 0..0.2; nothing at night). Multiplied into the picture like the AO.
- **Settings**: Graphics > Lighting (RenderHook): `renderhook.shadows` Off / Soft / Normal / Dark (darkening 0.3 / 0.45 /
  0.6; `VCS_RH_SHADOWS`), `renderhook.shadow_distance` 50-400 m (150; `VCS_RH_SHADOW_DISTANCE`),
  `renderhook.shadow_quality` 1024 / 2048 / 4096 per cascade (`VCS_RH_SHADOW_QUALITY`). Debug: `VCS_RH_SHADOW_VIEW=1` /
  `rhshadow view 1` (lit / shadowed as grey, a tint per cascade); `rhshadow` reports the sun in world and view space,
  daylight and the casters drawn. DLAA's hook is added after the shadows' when both are on (DLAA sees them).
- **Checked** (hidden runs, 1080p, MSAA off, Downtown street, `build/aotest/rh_sh2..4`): at 09:00, 12:00 and 17:00 the
  shadows fall where the sun says (the player's south-west in the morning, towards the camera at noon facing north, east
  at 17:00), buildings shade the street and the facades opposite, poles stripe the walls, peds and vehicles cast and
  receive; no acne seen on the road. Cost: ~0.2 ms GPU a frame (shadow maps 0.15-0.18 ms, the pass the rest), render
  thread +0.3 ms (1024) to +1.1 ms (4096); 377-756 casters x 3 cascades.
- **Limits**: only what the game drew this frame casts - a building behind the camera throws no shadow into view (the
  game culls to the view frustum; drawing more needs the world's sectors drawn for the light, a project of its own);
  alpha-tested leaves cast their solid quads (the pass has no texture: next, the native pipeline with the texture for
  alpha-tested casters); draws through the VU clipper's GS path cast nothing; the game's own blob shadows under peds and
  cars stay (an option to hide them would be a game-side hook); shadows from the moon / at night none; weather (overcast,
  rain) does not dim them yet (the timecycle's values not read).

## Sun shadows, fix: casters off screen (done 2026-11-01)

The user's report: shadows "artefact or disappear when turning the camera" - a building's shadow vanished once the
building left the view, and half-drawn buildings left straight-cut shadows (the game draws only what the camera sees).
- **The camera's position** (`sceneTrack` in gs_hw.cpp, `GSHwFrameView.cameraPosition` / `VcsRenderFrame.camera_position`):
  static world meshes drawn once a frame keep their place, so with the camera's rotation each known mesh gives the camera
  (place - R^T v); the median the known meshes agree on (two within 10 cm), then the places of new meshes. A frame of
  reference of the renderer's own (world axes, metres); no agreement (a teleport, a cut) starts a new one.
- **Remembered casters** (`shadowCacheUpdate`): every static world draw is kept at its place (model -> tracking frame) and
  drawn into the shadow maps while off screen, up to 600 m away, for 7200 tracked frames unseen. Two traps found in the
  checks: meshes that move with the camera (sky, horizon) left a trail of copies that darkened everything - a caster now
  needs 4 frames at one place; and coarse LOD meshes seen from afar were still drawn after the game swapped in the
  detailed ones, shading them - a remembered caster is drawn only when its bounding sphere is out of view (`inView`; the
  game draws everything in view, so one in view but not drawn was replaced). Peds and vehicles off screen still cast none.
- **Steady while moving**: the mod snaps the cascades to whole texels in that world frame (camera_position), not from the
  camera.
- **Checked** (`build/aotest/rh_turn1..3`: turning on the spot at 17:00, debug view): before, shadows of the buildings
  around vanished as they left the view; after, 900-1400 remembered casters keep them in every direction. Cost: render
  thread +1 ms or less, GPU unchanged (~0.2 ms at 1080p). `PS2X_HW_SHADOW_CACHE=0` draws only the frame's own casters.

## Blob shadows hidden with AO / sun shadows (done 2026-11-01)

The user's request: no blob under peds and cars while AO is on (the two together left a dark smudge under every ped).
`blobs.cpp` hooks `CShadows::StoreShadowToBeRendered` (0x38A000, game-internals.md 6o) and drops the shadows whose
texture is the ped, car or bike one; helicopter / RC shadows, the explosions' light and everything else pass. Setting
`renderhook.blob_shadows` Auto (hidden while AO or sun shadows are on; the default) / Shown (original) / Hidden
(`VCS_RH_BLOB_SHADOWS`); `rhblobs` reports dropped / passed; `VCS_RH_BLOB_HOOKS=0` hooks nothing; `VCS_RH_BLOB_LOG=1`
logs the first calls. Checked (`build/aotest/rh_blob3`): with AO on, the blob under the player gone in Auto, back in Shown.

## Next

2. Sun shadows step 2: alpha-tested casters (palm leaves) with their textures, the game's blob shadows optional, weather.
3. Screen-space GI (bounce light from the picture and depth, temporal filter with the motion vectors). 4. Colour grading
(a second hook point, `VCS_RENDER_BEFORE_HUD`). 5. The sky pass. 6. Point lights.
