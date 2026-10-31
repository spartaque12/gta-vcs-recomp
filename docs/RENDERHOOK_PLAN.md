# RenderHook-style graphics for the port - plan to pick up later

Status (2026-10-31): researched, **parked by the user before any code** - nothing in `src/` was changed. The research
session is "Plan RenderHook-style graphics for the VCS port" in the Claude app (it can be resumed there); this file
keeps what it established and the plan.

## Why not a port of RenderHook itself

gtaRenderHook (GTA SA, D3D11; the user has contributed AO, shadow and motion-vector work to it) hooks San Andreas'
RenderWare D3D9 pipeline inside gta_sa.exe. VCS is Rockstar Leeds' Rsl engine (PS2 VU programs), drawn by this port's
own renderer: the GS hardware renderer (`src/render/gs_hw.cpp`, shaders in `src/render/shaders`) on the RHI (D3D11 /
Vulkan), with native world sectors, skinned / lit peds and vehicles and post effects (`docs/NATIVE_RENDERER.md` stages
5-8). So RenderHook's *features* are rebuilt in that renderer, not its code.

## Established

- The 3D frame is 640 x 448 (PS2 buffer; internal resolution scales it). **Depth: Z24 at ZBP 280, reversed (0 = far)**,
  filled with 0 at the start of each 3D frame (`[draw] depth fill zbp=280 ... value 0.000000` in a frame dump) - usable
  for screen-space effects as it is.
- A frame dump (one street frame at noon): 44 GS draws + 57 native, ~12k world packets drawn; one draw samples its own
  render target (the renderer reads a copy). Dump and screenshot of that run: `build\run\ao_explore.log`,
  `build\aotest\ao_explore\shot.png`.
- The renderer has GPU timing (F3 overlay) to measure an added pass.

## Features and fit

| RenderHook feature | Fit | Needs |
|---|---|---|
| Screen-space AO (GTAO) | good | the 3D depth (above), after the 3D scene and before the HUD |
| Tonemapping / bloom polish | good | the post-effects stage that exists (NATIVE_RENDERER.md "Post effects") |
| Sun shadow maps (world, peds, vehicles) | possible | the sun's direction / time of day from the game, re-drawing casters (native world sectors, peds, vehicles) from the sun |
| Dynamic point lights | partial | the game's light list (coronas / lights); additive forward lighting on lit models |
| Sky pass | possible | the game's sky colours / time of day |
| Full deferred PBR relighting | no | the world's lighting is baked into vertex colours (prelit, few normals); only peds / vehicles have normals |

## Order of work

1. **GTAO** (the first milestone): `src/render/shaders/gs_ao.hlsl` with four passes - reversed depth -> linear view
   depth; GTAO visibility; a depth-aware 4 x 4 blur multiplied into the frame; a debug view - as a Graphics option, off
   by default (authentic), both backends compiling (HLSL -> SPIR-V through `tools/hlsl_spirv.py` for Vulkan). Verify
   with before / after screenshots in a hidden run on a copy of the card, and the F3 GPU time.
2. Tonemapping / bloom.
3. Sun shadow maps (cascades; the sun from the game's time of day).
4. Dynamic lights, sky.

## Resume

Start the parked session again, or a new one with this file as the brief: read `AGENTS.md`, `docs/NATIVE_RENDERER.md`,
`src/render/gs_hw.cpp` and the RHI first; record findings in `docs/game-internals.md` / decisions in
`docs/DECISIONS.md`.
