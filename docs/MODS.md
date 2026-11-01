# Mods in this build

An index of the gameplay and graphics mods added on 2026-10-31: what each does, where it is switched, what was checked.
The details are in the docs named in each row; decisions in DECISIONS.md, progress in PROGRESS.md.

| Mod | What it does | Where (F2 settings menu) | Default | Status | Details |
|---|---|---|---|---|---|
| First person (on foot) | UltimateFP's camera: the eyes from the head joint, the head hidden, mouse / right stick look | Game > First person (field of view, near clip, eye position right / ahead / up); key B, Back + R3 | off | checked in hidden runs | game-internals.md 12c, CONTROLS.md |
| First-person viewmodel | UltimateFP SA's look: the player's own arms hold the gun in view (lower right, barrel on the crosshair), the support hand on the fore-grip (two-bone IK), sway, bob, recoil; first person kept while getting in / out of vehicles; the eyes ahead of the collar running backwards | Game > First person: Arms and gun in view, Gun position right / ahead / up, Gun sway (CameraAim.asi) | on (with first person) | checked in hidden runs: pistol, SMG, rifle, shotgun standing / walking / up / down / aimed / fired, hits at the dot; one-frame head glimpse on a bike dismount left | 12t |
| Manual reload | SA's manual reload: R (Back + Square) reloads the gun in hand when its clip is short, through the game's own reload (anim, sound, refill); the viewmodel's reload pose | Game > Manual reload; Keyboard > Reload (CameraAim.asi) | on | checked: M4, Uzi, Colt45, first person on / off | 12t |
| First person in vehicles | the view from the seat in the vehicle's space, mouse look eased back ahead while driving, L2 / R2 look aside, no camera shake, the body's jolts eased out, the vehicle's windows not drawn | Game > First person in vehicles | on (with first person) | checked in cars; bikes, boats, aircraft not run | 12e, `src/game/vcs_carglass.cpp` |
| Free aim | SA's manual aim: R1 / right click with a gun aims without lock-on, a camera over the right shoulder, the game's own aim pose, a DotCrosshair-style dot (only while aiming, first person too), shots and shotgun pellets along the line through it | Game > Free aim (aim field of view) | off | checked: hits on peds, shotgun pellets | 12d |
| Manual drive-by | SA's Manual Driveby Remake on the game's drive-by: L2 / R2 with an SMG in a vehicle, the mouse aims with the dot | part of free aim | off | checked in cars; the arm does not follow the aim; bikes not run; SMGs only (the game's rule) | 12d |
| Field of view | the game's own cameras' field of view (the car camera's speed widening kept) | Game > Field of view (on foot, vehicles) | 70 | checked | 12e |
| Death ragdolls (Jolt Physics) | Jolt 5.6.0: a ped that dies goes limp; kill pushes by weapon, vehicles carry bodies, shots and blasts move them | Game > Physics > Ragdolls, Hit force | off | checked by `tools/ragdoll_check.py` | 12f, 12h |
| Texture packs + HD HUD | upstream PR #8 (PCSX2 PNG packs, matched by PCSX2's hashes); the "HD HUD - SLUS-21590 - PS Icons" pack installed in `build\textures\SLUS-21590\replacements` | Graphics > Texture replacements (restart) | off | checked: 25 of 160 matched from a story save; the small HUD digits break up below ~4x internal resolution | TEXTURE_PACKS.md |
| Streamed file override | any streamed file (model, texture dictionary, animation) replaced by `build\mods\stream\<id>.*` (`VCS_MODS_DIR`) | - | on when the folder exists | checked | 12g |
| Immersive Weapons Pack | the pack's weapon models (only weapons VCS has), then its animations, then the magazine drop, through the override; `tools/weapon_convert.py` | Graphics > Texture replacements (the full-resolution atlases); WeaponHD.asi (the full meshes) | on with the files | done: small models + animations in build\mods\stream, full meshes (`--hd`) in build\mods\weaponhd drawn by WeaponHD.asi (VCS-mods), 1024-px atlases in textures\SLUS-21590\replacements\weapons (`tools/weapon_textures.py`); magazine drop / moving parts not yet | 12g, 12i |
| Project2DFX | distant lights, more stars, distant cars / boats (ThirteenAG's Project2DFX for VCS), and the mod's palms | Game / Graphics, `p2dfx.*` rows | off | done: lights, stars, distant cars checked; boats / flight ceiling not seen; palms + trees installed; Alpha dual pass (Graphics) | game-internals.md 6l |
| RenderHook-style graphics | gtaRenderHook's features rebuilt on the port's renderer: ground-truth ambient occlusion (GTAO from the game's depth) now; colour grading, sky, sun shadows, lights planned | Graphics > Lighting (RenderHook): Ambient occlusion, Occlusion radius; Graphics > Anti-aliasing (RenderHook): DLAA (NGX build, RTX, D3D11); Lighting: Sun shadows, Shadow distance, Shadow quality | off | milestone 1 (AO) done: checked in hidden runs at 1080p MSAA 4x and 640x448 (before / after shots), 0.5-0.7 ms GPU at 1080p MSAA 4x; Vulkan compiles, not run | RENDERHOOK_PLAN.md |
| VR (OpenXR, M0) | the game in an OpenXR headset, mono: first person on foot follows the head (CameraAim), the HUD on a panel; menus, cutscenes, third person and vehicles on a cinema screen; frames paced by the headset | Graphics > VR (on, view, cinema distance / width, HUD distance); recentre F7 / Back + L3 | off | checked without a headset (inert without a runtime; a test runtime's eye images); not on a real headset | VR_PLAN.md "M0 as built", game-internals.md 12u |
| Head shots with any gun (PedSkills) | one bullet in a ped's head kills it with any gun - pistols, SMGs, rifles, shotgun pellets, M60 / minigun, drive-bys - through the game's own head-shot death (head off with gore, armour no help), the player's shots only unless "Applies to everyone" (then Vic too); missions' protected peds stay protected | Game > Ped skills: Headshots with any gun, Applies to everyone | on / off | checked in hidden runs: Colt45, Uzi, M4, Shotgun, Python head shots kill at once (500-health peds), ragdolls follow, body shots and the setting off as the game; "everyone" not run | game-internals.md 12v |

## Where each mod lives (2026-10-31: mods as DLLs, docs/MODDING.md)

| Mod | Lives in | Install |
|---|---|---|
| First person (on foot, vehicles), free aim, manual drive-by, car glass, field of view | `CameraAim.asi` - spartaque12/VCS-mods `plugins/CameraAim` (no longer in vcs.exe) | `build\scripts\CameraAim.asi` (installed); without it the rows, the B key / Back + R3 and the crosshair are gone |
| Jolt Physics: death ragdolls, bike falls, hit reactions, catch falls / blind fire, dismemberment, pickups on the ground, foot IK, jiggle | `JoltPhysics.asi` - VCS-mods `plugins/JoltPhysics` (Jolt 5.6.0 vendored there; no longer in vcs.exe since 2026-11-01) | `build\scripts\JoltPhysics.asi`; without it the Physics rows and the `jolt` / `footik` / `jiggle` commands are gone. An older vcs.exe with the ragdolls built in keeps its own (the mod logs a line and does nothing) |
| Project2DFX (distant lights, stars, distant cars / boats, draw / detail distance, flight ceiling) | `Project2DFX.asi` - VCS-mods `plugins/Project2DFX` (no longer in vcs.exe) | `build\scripts\Project2DFX.asi` (installed); needs `p2dfx\lights.bin` beside vcs.exe as before. "Alpha dual pass" stays in the exe (a renderer setting) |
| Streamed file override, Immersive Weapons Pack | vcs.exe: `src/game/vcs_stream_override.cpp`; `tools/weapon_convert.py` | built in; next |
| Texture packs + HD HUD | vcs.exe (upstream PR #8) | built in (part of the port, not a mod to move) |
| RenderHook-style graphics (ambient occlusion) | `RenderHook.asi` - VCS-mods `plugins/RenderHook` (shaders built with fxc + glslang); vcs.exe gives it the render hooks (`src/modapi/mod_render.cpp`, the renderer's frame hook) | `build\scripts\RenderHook.asi` once vcs.exe has the render hooks; installed with DLAA 2026-10-31 (a vcs.exe without them refuses the mod with a log line) |
| VR (OpenXR) | `VR.asi` + `openxr_loader.dll` (Khronos, built by VCS-mods' CMake) - VCS-mods `plugins/VR`; vcs.exe gives it the present hook and split layers (`src/modapi/mod_present.cpp`); the head look is CameraAim's export (`CameraAimSetHeadLook`); tests: `xr_test_runtime.dll` (`-DVR_TEST_RUNTIME=ON`, never installed) with `VCS_VR_RUNTIME` | `build\scripts\VR.asi` and `build\scripts\openxr_loader.dll`, with a CameraAim.asi that has the export; needs a vcs.exe with the present hook (older exes: one log line, inert) |
| Head shots with any gun | `PedSkills.asi` - VCS-mods `plugins/PedSkills` | `build\scripts\PedSkills.asi`; without it the game's rule (sniper rifles, M4, Ruger, M60 always; other guns 1 head hit in 16) |

`VCS_MODS=0` starts without any DLL mod. Build CameraAim.asi from VCS-mods (its README); it needs a vcs.exe with the
mod API (this folder's, or the fork's `vcs-mods` branch).

## Testing and building alongside play

The user plays from `build\vcs.exe`: a build cannot link while it runs, and tests run on a copy of the exe started
through `VCS_EXE` (hidden, a copy of the card in `build\rig\saves\user`, each tester on its own control port). Check
`tasklist` for vcs.exe / ninja / clang-cl / lld-link before building; never leave a non-compiling .cpp under `src/`.
`python tools/exe_copy.py DIR` links such a copy (DIR\vcs.exe, its DLLs and vcs.ini) from the current sources without
touching the locked build\vcs.exe; the copy's mods go in DIR\scripts.

## Git

The finished mods are on the user's fork, spartaque12/gta-vcs-recomp, branch `vcs-mods` (on its `main`): the camera and
aiming mods (first person, vehicles, free aim, drive-by, glass, field of view), the streamed file override and the
weapon converter, the RenderHook plan, the crosshair fix, upstream PR #8 merged (texture packs), and the Jolt ragdolls.
The release folder is not a repository: finished work is copied into a clone of the fork (`F:\games\gta-vcs-recomp-fork`)
without other sessions' work in progress or any game data, committed and pushed. Converted assets (weapons, palms, the HUD pack) are never pushed.
The DLL mods have their own repository, spartaque12/VCS-mods (`F:\games\VCS-mods`): the API header, each mod's sources
and CMake, no binaries or game data; the port's side (the loader, `src/modapi`) is on the fork's `vcs-mods` branch.
