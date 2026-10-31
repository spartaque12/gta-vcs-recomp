# Mods in this build

An index of the gameplay and graphics mods added on 2026-10-31: what each does, where it is switched, what was checked.
The details are in the docs named in each row; decisions in DECISIONS.md, progress in PROGRESS.md.

| Mod | What it does | Where (F2 settings menu) | Default | Status | Details |
|---|---|---|---|---|---|
| First person (on foot) | UltimateFP's camera: the eyes from the head joint, the head hidden, mouse / right stick look | Game > First person (field of view, near clip, eye position right / ahead / up); key B, Back + R3 | off | checked in hidden runs | game-internals.md 12c, CONTROLS.md |
| First person in vehicles | the view from the seat in the vehicle's space, mouse look eased back ahead while driving, L2 / R2 look aside, no camera shake, the body's jolts eased out, the vehicle's windows not drawn | Game > First person in vehicles | on (with first person) | checked in cars; bikes, boats, aircraft not run | 12e, `src/game/vcs_carglass.cpp` |
| Free aim | SA's manual aim: R1 / right click with a gun aims without lock-on, a camera over the right shoulder, the game's own aim pose, a DotCrosshair-style dot (only while aiming, first person too), shots and shotgun pellets along the line through it | Game > Free aim (aim field of view) | off | checked: hits on peds, shotgun pellets | 12d |
| Manual drive-by | SA's Manual Driveby Remake on the game's drive-by: L2 / R2 with an SMG in a vehicle, the mouse aims with the dot | part of free aim | off | checked in cars; the arm does not follow the aim; bikes not run; SMGs only (the game's rule) | 12d |
| Field of view | the game's own cameras' field of view (the car camera's speed widening kept) | Game > Field of view (on foot, vehicles) | 70 | checked | 12e |
| Death ragdolls (Jolt Physics) | Jolt 5.6.0: a ped that dies goes limp; kill pushes by weapon, vehicles carry bodies, shots and blasts move them | Game > Physics > Ragdolls, Hit force | off | checked by `tools/ragdoll_check.py` | 12f, 12h |
| Texture packs + HD HUD | upstream PR #8 (PCSX2 PNG packs, matched by PCSX2's hashes); the "HD HUD - SLUS-21590 - PS Icons" pack installed in `build\textures\SLUS-21590\replacements` | Graphics > Texture replacements (restart) | off | checked: 25 of 160 matched from a story save; the small HUD digits break up below ~4x internal resolution | TEXTURE_PACKS.md |
| Streamed file override | any streamed file (model, texture dictionary, animation) replaced by `build\mods\stream\<id>.*` (`VCS_MODS_DIR`) | - | on when the folder exists | checked | 12g |
| Immersive Weapons Pack | the pack's weapon models (only weapons VCS has), then its animations, then the magazine drop, through the override; `tools/weapon_convert.py` | - | - | done: 27 weapon models + the pack's animations for 7 sets installed in build\mods\stream; magazine drop / moving parts not yet | 12g |
| Project2DFX | distant lights, more stars, distant cars / boats (ThirteenAG's Project2DFX for VCS), and the mod's palms | Game / Graphics, `p2dfx.*` rows | off | done: lights, stars, distant cars checked; boats / flight ceiling not seen; palms + trees installed; Alpha dual pass (Graphics) | game-internals.md 6l |
| RenderHook-style graphics | AO, tonemapping, sun shadows ... in the native renderer | - | - | parked | RENDERHOOK_PLAN.md |

## Where each mod lives (2026-10-31: mods as DLLs, docs/MODDING.md)

| Mod | Lives in | Install |
|---|---|---|
| First person (on foot, vehicles), free aim, manual drive-by, car glass, field of view | `CameraAim.asi` - spartaque12/VCS-mods `plugins/CameraAim` (no longer in vcs.exe) | `build\scripts\CameraAim.asi` (installed); without it the rows, the B key / Back + R3 and the crosshair are gone |
| Death ragdolls (Jolt Physics) | vcs.exe: `src/game/vcs_jolt.cpp`, `src/physics` | built in; next to move to a DLL |
| Project2DFX (distant lights, stars, distant cars / boats, draw / detail distance, flight ceiling) | `Project2DFX.asi` - VCS-mods `plugins/Project2DFX` (no longer in vcs.exe) | `build\scripts\Project2DFX.asi` (installed); needs `p2dfx\lights.bin` beside vcs.exe as before. "Alpha dual pass" stays in the exe (a renderer setting) |
| Streamed file override, Immersive Weapons Pack | vcs.exe: `src/game/vcs_stream_override.cpp`; `tools/weapon_convert.py` | built in; next |
| Texture packs + HD HUD | vcs.exe (upstream PR #8) | built in (part of the port, not a mod to move) |

`VCS_MODS=0` starts without any DLL mod. Build CameraAim.asi from VCS-mods (its README); it needs a vcs.exe with the
mod API (this folder's, or the fork's `vcs-mods` branch).

## Testing and building alongside play

The user plays from `build\vcs.exe`: a build cannot link while it runs, and tests run on a copy of the exe started
through `VCS_EXE` (hidden, a copy of the card in `build\rig\saves\user`, each tester on its own control port). Check
`tasklist` for vcs.exe / ninja / clang-cl / lld-link before building; never leave a non-compiling .cpp under `src/`.

## Git

The finished mods are on the user's fork, spartaque12/gta-vcs-recomp, branch `vcs-mods` (on its `main`): the camera and
aiming mods (first person, vehicles, free aim, drive-by, glass, field of view), the streamed file override and the
weapon converter, the RenderHook plan, the crosshair fix, upstream PR #8 merged (texture packs), and the Jolt ragdolls.
The release folder is not a repository: finished work is copied into a clone of the fork (`F:\games\gta-vcs-recomp-fork`)
without other sessions' work in progress or any game data, committed and pushed. Converted assets (weapons, palms, the HUD pack) are never pushed.
The DLL mods have their own repository, spartaque12/VCS-mods (`F:\games\VCS-mods`): the API header, each mod's sources
and CMake, no binaries or game data; the port's side (the loader, `src/modapi`) is on the fork's `vcs-mods` branch.
