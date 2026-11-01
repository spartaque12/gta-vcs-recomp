# Decisions log

Newest at the bottom. Each entry: what, why, and what would change it.

## 2026-10-21 - Base toolchain: vendored PS2Recomp
- PS2Recomp (ran-j, GPL-3.0) is vendored into `third_party/PS2Recomp` at upstream
  commit in `third_party/PS2Recomp/UPSTREAM_COMMIT`, without its `.git`,
  `android/` and `vita/` folders. Vendored (not a submodule) because we will patch
  the runtime heavily and can't publish a fork from here. Keep local changes
  small and listed in `docs/PS2RECOMP_PATCHES.md` so they can be upstreamed.
- The project is GPL-3.0 as a result.

## 2026-10-21 - Distribution: source only, bring your own disc
- The repo never contains the ISO, the ELF, or C++ generated from the ELF
  (`.gitignore` blocks them). Users run the pipeline on their own disc.
- The built exe reads game files straight from the user's ISO at runtime.
- Only one executable build is supported (SHA-1 in `tools/vcs_disc.py`).

## 2026-10-21 - Performance is a hard requirement
- Upstream runtime uses raylib + a CPU software GS renderer, which the upstream
  README calls "very bad" for speed. That's fine for bring-up only.
- Target: runs full speed on old/modest hardware (dev box: i7-7700K + GTX 1080 Ti,
  treat it as the *high* end). So:
  - GS: hardware-accelerated renderer (Vulkan/D3D), not a CPU rasterizer and
    preferably not a heavy compute rasterizer either. paraLLEl-GS is an option
    for reference accuracy, but the end state is a native renderer fed directly
    from the game's draw calls (HLE of VU1 programs).
  - VU1: translate the game's microprograms to C++ ahead of time, never interpret.
  - Disc I/O: memory-map the ISO, no per-read file opens.
  - Avoid per-instruction runtime dispatch in hot paths (e.g. indirect jumps
    through lookup tables) where we can resolve statically.

## 2026-10-21 - Function map: Ghidra functions only, no label records
- Ghidra's export script also emits every branch-target label (57,897 of them)
  as a separate "function". With those, ps2_recomp produced 67k files / 572 MB
  with each code chunk duplicated. Without them: 9,584 files / 243 MB, 0 errors.
- ps2_recomp still discovers internal entry points itself and maps each to its
  owner function (the function starts with a `switch (ctx->pc)` that jumps to the
  resume label), so jump tables and thread resumes stay inside one C++ function.
- BlackLine's archived VCS map (`gta.csv`) is for the PAL build SLES-54622, so its
  addresses don't apply to SLUS-21590. Its function count (9,549) matches ours,
  which is a good sanity check that Ghidra's boundaries are complete.

## 2026-10-21 - Compiler: clang-cl + MSVC 2019 STL
- The machine's VS 2022/2026 installs have no C++ toolset; VS 2019 Build Tools
  (MSVC 14.29) do. We build with LLVM clang-cl 23 against that STL and the
  10.0.19041 Windows SDK. clang-cl also handles the huge generated files better
  than cl.exe. `tools/toolchain.py` sets this up (vswhere + vcvars64).
- Baseline CPU: AVX2 (upstream's `/arch:AVX2`). Revisit if we want pre-Haswell
  CPUs; the generated code mostly needs SSE4.1.

## 2026-10-21 - Graphics plan
1. Bring-up: upstream CPU GS backend (slow, but no extra work).
2. Accurate + fast enough: paraLLEl-GS (Vulkan compute, LGPLv3+) for exact
   output with supersampling, as hctp-recomp does.
3. End state for performance and real hi-res/widescreen: native renderer fed by
   high-level hooks on the game's VU1 render paths (VCS has only ~4.8 KB of VU
   microcode + 4 small DVP overlays, so the set of programs is small).
- 2026-10-22: step 3 is now planned in detail in NATIVE_RENDERER.md (SDL3 platform
  layer, own RHI with a D3D11 backend, GS HW backend port, then packet-level HLE).
  Its six decisions were approved by the user on 2026-10-22.

## 2026-10-22 - Movies skipped during bring-up
- `FUN_0021CA70` (from `main`) plays `STINGS.PSS` then `INTRO.PSS` via the movie
  player at `0x40D8B8`. Under the runtime's sceMpeg stubs it stalls after ~8
  stream reads. Skipped (returns 0) in `src/game/vcs_overrides.cpp` for now.
- Plan (Phase 4): native playback - demux the PSS from the disc with FFmpeg and
  draw it ourselves (cheaper than emulating the IPU, and allows clean scaling).

## 2026-10-22 - Iteration speed
- New bindings go in `src/game/vcs_overrides.cpp` (relink only) rather than the
  recompiler config (rebuilds all generated code).
- LTO off for development builds; ThinLTO for release builds.

## 2026-10-22 - Rule for hooks on recompiled functions
- A generated function can return to the EE scheduler in the middle of its body
  (thread switch at a checkpoint, e.g. inside a `DelayThread` poll loop). It is
  later resumed through the function table at the *resume address*, which maps
  to the original generated function, not to a wrapper registered on its entry.
- So a hook may do work **before** calling the original, or replace the
  function entirely, but must not rely on code running after the original
  returns. For "after" logic, hook the next function the caller invokes.

## 2026-10-22 - paraLLEl-GS: integrated, but off by default
- Ported hctp-recomp's paraLLEl-GS backend (runtime/gs/gs_gpu*.{h,cpp}) and hooked
  it into upstream's GS frontend (raw GIF per path, register writes, IMAGE uploads,
  readbacks, present at VBlankStart, frames read back into the raylib window).
- On the dev GPU (GTX 1080 Ti, Pascal) every run hung the GPU > 2 s and Windows
  reset the display driver (TDR, event 4101); NVIDIA's OpenGL driver then
  aborts the process (fail-fast code 7 in nvoglv64.dll). Independent of the
  supersampling rate. Likely the compute rasterizer relies on behaviour Pascal
  lacks (no independent thread scheduling) or on a content-specific hang.
- Because the target is *modest* hardware, a compute-heavy rasterizer that
  doesn't run on a 2017 high-end card is the wrong default. The CPU renderer
  stays default; `PS2X_GS=gpu` opts in to paraLLEl-GS for newer GPUs.
- Next: a conventional hardware-rasterized GS backend (GSdx-HW style) behind the
  existing `GSRasterBackend` interface - broad GPU support, upscaling-friendly.

## 2026-10-23 - Post effects: exact GS emulation at 640x448 first, resolution-aware reads for higher resolutions

The user asked for the post effects to stay as authentic as possible at the original resolution first, then at
higher resolutions and other aspect ratios. At 640x448 the emulated GS draws are the reference, so the first step
made them match the GS (pixel centres) instead of replacing them with approximations, and kept them correct at
higher internal resolutions by reading 1:1 copies at full resolution. Effect-level shaders (one pass per effect,
independent of the PS2 frame-buffer layout) come with the native frame (milestone 3 step 4), checked against this
emulation at 640x448.

## 2026-10-23 - Native HUD: the game names its primitives, the GS packets still carry them

Milestone 3 step 2 draws the HUD natively (docs/NATIVE_RENDERER.md "HUD layer"). Choices:
- **The game's own Im2D calls still run** and build their GS packets; the renderer takes the HUD's primitives out of
  the frame by matching them against the Im2D calls of the frame (vertex positions), then draws them at the window's
  size. Replacing Im2D outright would also need RenderWare's texture cache (VRAM placement, CLUT uploads) and its
  render-state translation reproduced; going through the packets keeps those exact and leaves a switch back
  (`VCS_HUD_NATIVE=0`) at no cost.
- **Textures from the GS backend's decoded cache**, not a decoder for RenderWare rasters: the HUD textures reach VRAM
  through the game's own uploads, and the cache keys them by content. A raster decoder becomes worth having when 2D is
  drawn without GS packets (milestone 3 step 4, a native frame).
- **Anchors from where an element sits** (grouped boxes, the 4:3 screen in thirds with a dead zone around the middle),
  not a table of HUD call sites: it covers text boxes, timers and counters the game positions itself, with nothing to
  keep in step with the code. Elements may change side as they grow (a help box past the middle stays left: the
  rule uses its middle and its left edge).
- The HUD placement **default stays "Keep 4:3"**; "Screen edges" is a choice in the menu (authentic by default).

## 2026-10-23 - Clipped world packets: correct picture first, then the C++ clipper

GPU clipping of the packets the VU sends through its clipper drew GON_C3's poolside ground black. The user chose the
correct picture as the default (clipped packets on the VU1, flyover 30 -> 25.5 fps) and milestone 3 to start with the
VU clipper. It is reproduced bit-exactly in C++ (game-internals.md 6h); its GIF packets go to the GS as the VU's
kicks would, so the picture is the VU's and the cost is close to GPU clipping. GPU clipping stays behind
`PS2X_HLE_CLIPPED=1`.

## 2026-10-22 - Performance status (i7-7700K)
- With GS work discarded (`PS2X_GS=null`) the game now runs at full speed
  (60 VBlanks/s, 15% idle) after two changes: hctp's VU1 throughput mode
  (13 -> 23 VBlanks/s) and batching IOP time (23 -> 60).
- With the CPU GS renderer it is 2.9 VBlanks/s: the rasterizer is ~95% of the
  frame. A GPU GS backend is the critical path.

## 2026-10-22 - VU1 microcode compiled ahead of time
- VCS uploads 22 distinct VU1 microcode blocks at run time (REF payloads from
  `.text`, the MPG VIFcode in the DMAtag). `game/vcs/vu1_uploads.txt` lists their
  ELF addresses; `tools/vu1_recomp.py` (vendored from BigDaddyJRich/hctp-recomp,
  GPL-3.0, plus an uploads-list input) reads the bytes from the user's ELF at
  build time and writes `generated/vu1/vu1_compiled.cpp` (never committed).
- Pieces are split at every upload boundary because VCS overlays parts of its
  big block with per-pass variants and a piece runs only while VU memory holds
  all of its bytes. Result: 99.97% of VU1 pairs run compiled.
- Verified with `PS2X_VU1_VERIFY=1`: registers, VU memory and XGKICK packets match
  the accurate interpreter; only cycle counts differ (throughput variant).
- Frame rate in game (i7-7700K): 11 -> ~35-50 VBlanks/s over this pass
  (compiled VU1, CLUT hash cache, content-keyed textures, upload fast path,
  batched timers). The EE thread is the single saturated thread. Next: VU0
  microprograms 0x0CF8 (sector box clip) and 0x0EB8 (~25% of the EE thread;
  they read MAC flags with pipeline timing, so they run on the exact path).

## 2026-10-22 - Native VU0 programs; no FP contraction
- VU0 programs 0x0CF8 (sector box clip) and 0x0EB8 (3x matrix product) ran
  ~160k times / 5 s on the interpreter's exact path (they read MAC flags):
  ~25% of the EE thread. They are now C++ (`src/game/vcs_vu0_native.cpp`),
  transcribed pair by pair with the flag latency spelled out, using the same
  per-lane maths as the compiled VU1 code. Registered by code hash.
- Verification (`PS2X_VU0_VERIFY=1`) first showed 1-ulp differences: the
  *interpreter* was wrong - /arch:AVX2 let clang fuse `acc + a * b` into FMA
  (one rounding). The PS2 rounds product and sum separately. The runtime and
  runner now build with -ffp-contract=off; after that, 4.2 million live calls
  matched exactly (VF, VI, ACC, VU0 memory), and compiled VU1 still matches.
- In game (i7-7700K): ~46-67 VBlanks/s (was 35-50 before, 11 at the start of
  the performance work). Remaining top costs: generated game code ~31%, T4
  texture swizzle (WriteP4) ~9%, DMA chain copy (memmove) ~7.5%, HW backend
  recording ~7%, scheduler checkpoints ~4%.

## 2026-10-22 - SPU2 emulated in the IOP; IOP time follows the wall clock
- The SPU2 lives in ps2xIOP (`core/iop_spu2.cpp`), behind the IOP's memory map
  and DMA channels 4/7, rather than as a high-level libsd replacement: VCS's
  CDSTREAM.IRX drives libsd directly, and its streaming depends on SPU2 IRQ
  addresses and DMA-complete callbacks, which an HLE layer would have to fake.
- The mix (48 kHz stereo, one frame per 768 IOP cycles) goes to a raylib audio
  stream through a ring buffer with an adaptive target fill (60 ms, +30 ms per
  underrun, max 250 ms). Drift is absorbed by resampling within +-0.5%. A first
  version resampled by up to +-8%: when the buffer ran low the music audibly
  slowed down, which the user heard as "audio slows down with the frame rate".
- IOP time was derived only from accounted EE cycles, so when the EE ran below
  full speed the SPU2 produced 70-90% of real-time audio and playback stuttered
  in step with the frame rate. On hardware the IOP/SPU2 keep real time whatever
  the EE does, so each IOP batch now brings IOP time up to the host clock (at
  most 50 ms at once; lag > 1 s is forgiven). Measured: 100% production and 0
  underruns at 20-60 VBlanks/s (slow host simulated with PS2X_SLOW_VBLANK_MS).
  Stream refills (DMA bytes, IRQs per second) are the same at 20 and 60
  VBlanks/s: CDSTREAM feeds music from the IOP side, not per game frame.
  `PS2X_IOP_REALTIME=0` turns it off.

## 2026-10-22 - Native port roadmap decisions (docs/NATIVE_PORT_ROADMAP.md)
The user's choices on the roadmap's open questions:
- Start with milestone 1 (automation / coverage rig), then milestone 2 (correctness sweep), and
  carry the roadmap out autonomously, committing at milestones and major changes.
- Movies: FFmpeg as the decoder.
- 60 fps: a settings-menu option, off by default (30 fps stays the authentic default). (Superseded 2026-10-30: 60 fps
  with frame-rate independent timing is the default.)
- IOP retirement (milestone 6): do it.
- Windows only for now; milestone 9 (portability / distribution) is out of scope until further notice. (Superseded
  2026-10-30: native Linux, see that entry.)
- Game knowledge goes into docs/game-internals.md (successor of ENGINE.md, each fact with how it was
  found); AGENTS.md is the working contract for agents.

## 2026-10-23 - Render submission on its own thread; frame-rate independence next
- The user's order: the render submission worker first, then frame-rate independence (a variable time step:
  "remove dependence on the framerate for gameplay"), not fixed-step interpolation. The worker comes first because
  with game code and render submission in series on one thread (~18 + ~17 ms driving) a variable step would barely
  raise the frame rate, and one large risky change at a time keeps bugs attributable.
- Design (runtime/ps2_render_worker.h): the game keeps its synchronous view - chains are copied when kicked and the
  DMA completes at once, as before - and the work runs behind it in kick order. Everything the game can read back
  fences (waits for the worker) instead of being made asynchronous; measured, the game only reads the GS CSR (~5 a
  frame), so fences cost little. Rare game-thread entries into the GS (library stubs, native GIF fast paths) fence
  or step aside rather than being ported to the queue. At most one frame of lead (latency stays one frame).
- Kept outside ps2_memory.h (a free-function module with its own buffer pool) so the change does not rebuild the
  generated code. `PS2X_RENDER_THREAD=0` is the switch back.

## 2026-10-23 - Profile-guided, ThinLTO build for play; plain build for development
- `tools/build.py --opt pgo` (ThinLTO + PGO) is what to play and measure with: game code ~20-30% faster
  (PROGRESS.md milestone 4). The profile comes from an instrumented build (build/pgo-gen) playing tools/bench.py and
  the reference scenes; it lives in build/pgo (derived from the user's own game, never committed) and is retrained
  with `--opt pgo --train` after large changes - a stale one still builds, changed functions just lose its benefit.
- `--opt none` stays the development setting (no ThinLTO relink); the choice is kept in the CMake cache until changed.
  (2026-10-27: a fresh build directory is now `lto`, with `--quick` for `none` - see that entry.)
- Calls between recompiled functions got an inline fast path in the runtime header rather than a recompiler change:
  same effect on every call site, no regenerated code, and `PS2X_FAST_DISPATCH=0` switches it off.

## 2026-10-25 - Independent timing up to 240 fps; the ped-movement branch below step 0.5 patched
- Found what broke below the 0.5 step (docs/PERFORMANCE.md 5, game-internals.md 4): FUN_001f1d38 turns a ped's
  animation movement into a velocity with `* 0.5` instead of `/ step` when the step is under 0.5 - a branch the PS2
  never takes (CTimer floors the step). One instruction patch (game/vcs/overrides.toml: the constant it compares with
  becomes 0.001) sends every real step down the `/ step` path; steps of 0.5 or more run exactly as before.
- The audit then matches 1/30 - 1/100 at 1/144, 1/200 and 1/240 (running, driving, falling; sprint -5% / -11% at
  1/200 / 1/240), so independent timing's ceiling goes from 100 to 240 fps (step floor 50/240). Caps offered: 30 / 60
  / 100 / 120 / 144 / 165 / 240 / display refresh / unlimited (both up to 240). Missions above 100 fps are not
  playtested yet; the four frame-counter blinkers outside the 2D pass blink faster as before.

## 2026-10-24 - Independent timing capped at 100 fps for now
- VCS clamps its time step to at least 0.5 (1/100 s; Vice City used 0.01). With the clamp lifted, the frame-rate
  audit shows the player running at a fifth of the speed at 1/120 s - code somewhere assumes steps of 0.5 or more.
  Rather than run the game fast (keeping the clamp above 100 fps) or let it break, independent timing keeps the
  game's 0.5 floor and caps the frame rate at 100. The cap setting offers 30 / 60 / 100 / display refresh (up to
  100) / unlimited (up to 100). Finding and fixing what breaks below 0.5 (then 120 / 144) is phase 3 work;
  `VCS_MIN_STEP` lowers the floor to test it.

## 2026-10-24 - Movies played natively; the intro skippable from the settings
- CMoviePlayer::Play is replaced at its entry rather than feeding the game's own libmpeg / IPU player: no IPU, no
  movie sound through the IOP, the picture drawn by our presenter at 4:3 like the PS2's TV. The game thread waits in
  Play as it did in the game's player.
- Skipping as on the PS2: the logos can't be skipped (the game passes a threshold of 1,000,000 frames), the intro can
  with Start / Cross. The user asked to keep skipping the intro possible: Display > Skip intro movies skips both
  movies; off by default (authentic). Test tools set VCS_SKIP_MOVIES=1 so their boot timelines stay as they were.

## 2026-10-24 - Sound without the IOP: Rockstar's sound code ported onto a native libsd and the existing SPU2 core
- The roadmap's "native mixer" is the SPU2 core we already had (ADPCM, ADSR, interpolation, reverb - in C++, checked
  against hardware behaviour); what was emulated around it was MIPS code: Sony's libsd and Rockstar's CDSTREAM sound
  engine. Those are ported function by function (src/sound/libsd.cpp, src/game/vcs_sound.cpp), so the sound is the
  same by construction and checkable write for write; a different mixer would only have added a second way to sound
  different. A higher-quality mixer can later sit behind the same libsd.
- The IOP's threads became steps on the EE thread (RPC work in the call, the music thread one step per semaphore
  signal, max count 1 as the IRX creates it). Disc reads complete at once; DMA transfers keep their duration (the
  game opens a radio station and sends its volume 3 samples later - it relies on the preload taking that long).
- Tables the module carries (112 stream names, SPU2 addresses) are read from the disc's own MODULES\CDSTREAM.IRX at
  start (checked to be SLUS-21590's), so nothing from the game sits in the source; only code constants (bank first
  sound numbers, slot addresses) are written out.
- Checked by record / replay (tools/soundcheck.py) rather than by ear alone: the emulated IOP's sound RPCs are
  recorded with their IOP times and replayed into the native driver; SPU2 writes and audio are compared.
- With streaming and sound native the emulated IOP is off by default (no modules, no IOP time); `PS2X_IOP=1`,
  `VCS_NATIVE_SOUND=0` or `VCS_NATIVE_STREAM=0` bring it back for checking. The emulated IOP's code stays.

## 2026-10-24 - RSL world draws: record and replay at the VIF level, on by default

Phase 2 of RSL_SUBMISSION.md for world sectors. The world draw's geometry is drawn at a MARK put in place of its REF,
from a recording of what the VIF did with the block the first time (UNPACK results, MSCALs, meshes) rather than from a
decoder of our own:
- **Exact by construction**: the recorded VU qwords are the interpreter's own UNPACK results, the MSCALs run through
  the interpreter's own MSCAL routine (`PS2Memory::vu1Mscal`) and the native world handler; a recording is refused when
  its result could depend on state from before the block. A decoder of the UNPACK formats, masks and modes would have
  been a second implementation to keep in step.
- **The MARK keeps the order**: the draw happens where its REF was, after its state flush and GS register writes, on
  whichever thread processes the chain (render worker or not).
- **Invalidation by content**: a block is hashed each time it is drawn (~5% of the chain's bytes; cheaper than copying
  it) - streaming replaces cells without telling us, and the hash notices.
- **On by default** after the verify run (0 of 174,301 replays differ) and the picture / tour checks; `VCS_RSL_WORLD=0`
  keeps the packet path. The timing gain is within noise (world geometry is small); the path is the point - model
  instances come next on the same mechanism.

## 2026-10-24 - RSL model draws: the same record / replay; marked bytes stay in the chain's copy

Model instances (`FUN_002F7D58` / `FUN_002F80A0`) use the world's mechanism, with two changes that apply to both:
- **The marked bytes are copied and skipped, not replaced** (revises "cheaper than copying it" above): the render
  worker processes a chain while the game builds the next frame, so reading a block from guest memory at the MARK
  could see a cell or model streamed out after the kick. The copy is what the guest held at the kick; copying costs
  little next to processing. It also gives a CALLed packet - a sub-chain of tags - as one flat stream without a second
  chain walker of our own.
- **Every CALL in the packet buffer is marked**, not only the ones the hooked draw calls wrote: a recording is the
  interpreter's own result for those bytes, so it is exact whoever built the packet; the hooks only label the
  counts. Packets rebuilt every frame drop to the packet path by themselves (bytes changed three hits running).
- On by default after the verify run (1,217,887 blocks, 0 differ), scenes and tour; worker -1.3 to -2.4 ms in the
  bench. `VCS_RSL_MODELS=0` keeps the packet path for models.

## 2026-10-24 - Game thread: the profile's targets before draw-call replay

The plan after phase 2 was to replay draws at the RSL draw call instead of building their packets. A drive profile
with call chains showed the draw calls' own writes are a small part of the game thread; a reallocating chain copy
(~10%), four VU0 programs still interpreted (~5%) and the state flush (2.3%) were larger and each could be made
native or fixed with an exact check against the original. Those went first. Native guest functions follow the rules
already used for VU0 programs: bit- / byte-exact against the original in a verify mode, a switch back, and the
original runs whenever the native version would have to call other guest code (the flush's plug-in callbacks).
Draw-call replay stays the way to remove the remaining copy and flush together.

## 2026-10-24 - Block validity by write watch, not by reading the bytes

Step 4 (FULLY_NATIVE.md) needs to know at the frame kick whether a world / model block still holds the bytes its
recording was made from, without copying or hashing it (the distinct blocks are ~85% of the marked bytes: a per-frame
check by content would cost as much as the copy). Chosen: the OS's write watch on guest RAM, folded into per-page
generations once per kick. Not page protection: the stream thread reads the disc straight into guest RAM, and a kernel
write into a protected page fails instead of faulting. Not hooks on the game's streaming / instancing functions: every
path that writes packet memory would have to be found and kept up. Exact by construction (any write to any of a
block's pages makes it dirty), checked with a decide-copy-compare mode (2.4M decisions, 0 wrong).

## 2026-10-25 - Draw items: one tag in the chain per draw, the block decided at the kick

FULLY_NATIVE.md step 4 asked for world / model draws that make no packets. Chosen: the draw call becomes an item (its
flush when all CNTs, its GS registers, its block), and the packet buffer keeps one 16-byte CNT per draw whose MARK /
NOP name the item and the frame. Not "no tag at all": 2D, effects, texture uploads and the setters' own uploads still
go through the chain between the draws (step 5), and the tag is what keeps each draw in its place among them. The
block's validity is decided at the kick, after the write watch's fold, exactly as for a marked block - not at the draw
call: generations there only cover writes up to the last kick, and a cell streamed in this frame and drawn this frame
would be replayed from an old recording. A block that changed is copied from guest RAM at the kick (`flattenBlock`,
the walker's rules; checked against the walker's copy), so nothing reads guest RAM later on the worker.
Draws stay packets where an item would not stand for the same bytes later or cannot be made exactly: while
`FUN_00240ED8` caches a sector (the copy is sent again in later frames: game-internals.md 6i), when the flush calls
plug-in callbacks (guest code: ~15% of draws while driving), for a model block not yet seen copied by the walker.
Speed was not the reason (measured even: the walker's share falls by about what the items cost); the reason is the
path - the draws no longer depend on the chain's bytes, which step 5 needs.

## 2026-10-25 - Draws whose flush calls guest code: captured, not ported

Step 5f could have ported everything a state flush may call (FUN_001CFAE0's float maths, the two immediate-geometry
callbacks) so that every draw is built natively. Chosen instead: those draws run the original and the region they
wrote is captured into items (the 5d mechanism, with CALLs taken as blocks). The chain loses their packets all the
same, nothing new has to be checked bit for bit, and the guest code keeps doing what it does. A port stays possible
later if their CPU time ever matters (small: ~2% of flushes).

## 2026-10-26 - Gaps: take what is between hook points, in place

Step 5h could have gone on adding writers to the captured list one by one (the census by origin named them). Chosen:
every hook point takes what was written since the last one, whoever wrote it, so the list never has to be complete.
Taken in place (item tag + NEXT over the rest; the cursor never moves back), because a gap is settled at arbitrary
hook points where a caller may hold the cursor - one such caller (`FUN_00240ED8`) was found the hard way, and verify
mode cannot see this class (it keeps the packets). The price is a NEXT per run (~32 a frame) and dead bytes in the
buffer; the chain's walk in 5g skips both.

## 2026-10-26 - No second way to start a frame (FULLY_NATIVE.md 5g dropped)

5g would have handed the item list to the worker without walking the chain. Measured after 5h: the kick takes 0.23 ms
a chain, 0.19 ms of it the items' resolve, which stays either way; the walk and copy of the ~300 remaining tags (the
root lists, the item tags, the runs' NEXTs) cost ~0.04 ms. The chain is kept as what orders the frame: one path, the
walker's checks (verify modes, the census) keep working, and nothing is drawn from the chain's own bytes any more.

## 2026-10-26 - zlib natively as an exact port, not a faster inflater

`inflate_fast` could be replaced by a faster decoder (wide bit-buffer refills, multi-symbol tables) with the same output.
Chosen: zlib 1.2.2's own loop, so every call leaves `next_in` / `avail_in` / `hold` / `bits` exactly as the guest's -
checkable call for call against the original (`VCS_NATIVE_INFLATE_VERIFY`) - with only the copies that cannot overlap
done as `memcpy`. A faster decoder would stop at other points and leave zlib's state different between calls (the
final output the same); the ~20 ms an area load costs now did not justify losing the per-call check.

## 2026-10-27 - The optimised build is the default; `--quick` for development
The user asked for installing to be as easy as possible. A fresh build directory now configures with ThinLTO
(`PS2X_LTO=THIN`, `--opt lto`), so `python tools/build.py --recompile` from the README gives the game to play;
`--quick` (= `--opt none`) is the fast-relink build for changing code. Not PGO as the default: training plays the
rig's card copies (build/rig/saves), which a new checkout does not have, and takes ~30 min more. The choice stays in
the CMake cache as before (one build directory: switching recompiles the game, and a non-sticky default would make
every quick build followed by a plain one cost a full rebuild); the build's last line names it so nobody plays a quick
build by accident. The build also writes `iso=` into the vcs.ini next to vcs.exe when there is none: the exe is a
windows-subsystem program, so started by a double click without a disc it fails with no visible message.

## 2026-10-27 - Full screen is borderless only; test runs never write vcs.ini

Full screen covers the monitor at the desktop's resolution with no display mode change. With a flip-model swapchain
Windows 10+ presents a window covering the monitor directly, so exclusive mode buys little, while a mode change costs
seconds per switch, breaks Alt+Tab and moves the other monitors' windows; the game's resolution is the Internal
resolution setting, not the monitor's mode. Exclusive full screen can come later as a third choice if someone needs a
lower monitor mode. Hidden test runs read vcs.ini but never rewrite it, so a scripted check (Alt+Enter, the settings
menu) cannot change the player's settings.

## 2026-10-27 - 4:3 screens sit inside the game's frame, not the window

The user's choice: in a ratio wider than the monitor (32:9 on 16:9) the pause menu stays 4:3 but sits in the game's
strip between the bars, at the strip's height, rather than over the whole window. Loading screens follow the same rule
(they are the same kind of frame: no 3D). The intro movies keep the whole window: they play before there is a game
frame to belong to. The menu switches to 4:3 as soon as it opens rather than after the 3D history runs out.

## 2026-10-27 - Ultrawide: fixed ratios plus Match window, Hor+ between 4:3 and 32:9

The user asked for 21:9 and 32:9. "21:9" monitors are 2.37 (2560x1080) or 2.39 (3440x1440), not 21 / 9 = 2.33. Chosen:
- The menu's 21:9 is exactly 21 / 9 (the label says what it is), and a Match window choice takes the window's own
  shape, so every monitor gets a picture without bars; it follows the window each host frame (resizing, full screen).
- Match window is clamped to 4:3 .. 32:9: narrower than 4:3 would cut the original horizontal view (we only do Hor+),
  wider than 32:9 is untested (triple screens would need checking: the view passes 140 degrees).
- No separate FOV setting: the game's horizontal FOV is kept for the middle 4:3 and the sides are added.

## 2026-10-26 - The trainer: the game's script commands, nothing saved, the game's input taken while open

The user asked for a trainer like RDR2's (docs/TRAINER.md). Chosen:
- Everything the game has a script command for goes through it (run on the game's own script VM), rather than
  writing the game's structures: the commands keep the game's own bookkeeping (wanted level and police, streaming,
  vehicle creation and ownership). Only values that drift every frame (health, ammunition, a clip, a vehicle's
  health) are written directly while their switch is on - a command per frame would cost a script each time.
- Switches are not saved in vcs.ini: the game starts authentic every time; the trainer is used, not configured.
- The menu takes the game's input while open (as the settings menu does): its keys are the game's D-pad, Start and
  Select. RDR2's trainer lets the game keep the keys it does not use; here every menu key is a game button.
- Trainer scripts must never be in a save: started only while the game runs, taken back out when it pauses.
- Models are streamed asynchronously with a time-out rather than `LOAD_ALL_MODELS_NOW`, which froze the game when the
  streaming memory was full.

## 2026-10-28 - Music / effects volume: the game's own levels, kept across loads

The user asked for music, sound effects and voices volume, with the music / effects changes shown in the game's own
menu. The game has exactly two levels (its pause menu's Music / SFX Volume), so those two settings *are* them rather
than extra gains on top: one value, two menus. On the PS2 a save carries the levels and a load restores them; here the
setting wins (every non-menu call of the game's setters gets the player's level), because a PC game keeps its settings
across saves and the newest save loads at every boot - the save's levels would otherwise undo a change made without
saving. The levels are percent of the game's 0..127 (linear, as the game's bars are); a pause-menu step is 16, so the
setting shows the nearest percent and the game keeps its exact level.

Voices volume was added the same day as a gain on the speech voices in the native driver (the game has no level for
speech) and **removed on the user's decision**: it felt inconsistent, since only speech played as effect sounds
followed it, while speech in cutscenes and on the radio is mixed into those streams. The code is gone (the driver is
as before); game-internals.md 9c keeps what was learnt.

## 2026-10-28 - Player settings: bindings in the game layer, the mouse as stick speed, defaults as before

The user asked for flexible settings players can change. Choices:
- **Where the bindings live**: in the game layer (src/game/vcs_input.cpp), feeding the runtime's pad backend through a
  reader hook; the runtime keeps its fixed mapping as the reference (`VCS_INPUT_MAP=0`), as the rules want for any
  replaced path. Injected (control-channel) keys go through the bindings too, so every scripted check exercises them.
- **Two slots per action**, any key / mouse button / wheel notch, Shift / Ctrl / Alt without a side (one slot holds
  "Shift" where the old mapping needed two). One key, one control: binding steals it from the other control, and the
  menu keys can neither take nor lose theirs - a silent double binding was judged more confusing than the steal.
- **Mouse camera**: the PS2 game has only a stick camera, so the mouse's speed becomes the right stick's tilt (not its
  distance per frame), which keeps the turn per hand movement the same at any frame rate; the stick's top speed caps
  flicks. True mouse look would mean writing the camera's angles in the game's memory - later, if the stick feel is
  not good enough. Off by default (it holds the cursor in the window).
- **Vibration**: the game's own motor levels (it already shook the pad; the stub dropped them), 100% = as on the PS2.
- **Defaults**: exactly the old fixed mapping and behaviour (keep running in the background, vsync off as the flip
  model presented before), so nothing changes for a player who opens no menu. The Authentic preset is the Display /
  Graphics defaults; presets never touch controls or sound.
- **Volume** squared (the slider's middle is about -12 dB), master after the mix so the game's own levels and the
  SPU2 output stay bit-identical for the checks (`PS2X_AUDIO_DUMP` records before it).

## 2026-10-27 - Per-frame mission meters: each instruction on the time step, not the scripts at 30 Hz

PHI_A2's heat bar (and meters in eleven more missions, game-internals.md 11f) change by a fixed amount every frame,
so they ran 4.8x fast at 144 fps. Two ways to fix it:
- Run the script VM at the PS2's 30 Hz above 30 fps (skip CTheScripts on frames in between, with the time step summed
  for them). Every per-frame script assumption would be as on the PS2 at once, cutscene camera moves and object
  animations included - but everything scripts move each frame (attached objects, cameras pointed per frame, cars
  held to a speed) would update at 30 Hz inside a 144 fps picture, script reactions would come up to 33 ms late, and
  the timers / WAITs would have to be fed the skipped time. Changes the whole game's behaviour for a few missions.
- Chosen: scale just the listed instructions by the frame's step over 1/30 s, the way the game's own timed opcodes
  (0x0031 - 0x0034) do it - what the mission would have used had the PS2 not been locked to 30. Every site is in a
  table with its mission, offset and decoded operands and is checked before it is touched, so a different build or a
  mod's MAIN.SCM leaves it alone; the survey that found them is written down so the next one is a table row. Visual
  per-frame animations are left at the frame rate for now (looks only).
Off in original timing at 30 fps (the game's own handlers, bit-exact); `VCS_SCRIPT_TIMESTEP=0` turns it off elsewhere.

## 2026-10-28 - Per-frame vehicle physics: scaled by the step, the brake's constants from guest RAM

A car running over a body jumped and a stolen bike flipped at high frame rates (game-internals.md 4): the push of a
body under a wheel (FUN_003F34F0) and ProcessWheel's rolling resistance act a fixed amount once a frame.
- Scaled by the frame's step over 1/30 s, as the mission meters (2026-10-27) and reVC's FIX_BUGS
  (`CTimer::GetTimeStepFix()`) do - only when the frame is shorter than the PS2's. Longer frames keep the game's
  amount: the PS2 game itself applied it per frame when it dropped below 30, so 25 fps plays as it did there.
- The push goes through ApplyTurnForce, so its hook scales the one call by return address; no recompile, and
  `VCS_PHYSICS_TIMESTEP=0` gives back the reference.
- The brake is built from immediates in the middle of ProcessWheel, where no hook reaches (rule 2: nothing after the
  original returns). Reimplementing ProcessWheel natively would mean the guest RNG and two guest calls; instead the
  four constants are patched to `lwc1` from guest RAM 0x7FF00.., which the ProcessWheel hooks write (scaled) before
  every call. Unscaled they are the game's exact floats, so 30 fps stays bit-exact. Those 16 bytes below the runtime's
  callback stacks are ours now (game-internals.md 4); the hooks are required by the patched code, not an option.
- CBike's lean `max(step, 0.5)` patched to 0.001 like the ped and cutscene ones (the same class; above 100 fps only),
  then the same in cars / bikes in water and a boat's rudder. Each patch was measured before and after; one that
  changed nothing measurable (the buoyancy's lift cut-off, game-internals.md 4) was taken back out.

## 2026-10-29 - vcs.exe at the top of build/, native by its own defaults (the user's request)

- The user found the exe "buried": `build/release/third_party/PS2Recomp/ps2xRuntime/vcs.exe`. The main build tree
  (build/release) now links it to `build/vcs.exe`, with its DLLs (staged next to the target, so they follow) and
  `vcs.ini` (CMakeLists.txt, `RUNTIME_OUTPUT_DIRECTORY`). Only that tree: PGO training's build/pgo-gen keeps its exe
  in its own folder, so the two never write the same file. build.py moves a player's vcs.ini from the old folder and
  deletes the old exe / pdb, so no stale build is left to start; clean.py never deletes the game files in build/.
- A double-clicked vcs.exe ran the software GS at ~5 fps: only run.py / scenes.py set `PS2X_GS=hw`, so every test
  ran a configuration players never got. The launcher now defaults to hw, and the tools no longer set it - they run
  vcs.exe with its own defaults, as a player does. Every other native path was already on by default (each switch is
  `=0` to go back to the reference): with no PS2X_* / VCS_* set, gameplay shows gs_draws 0, vu1_programs 0, the
  native sound driver, the emulated IOP off and the render worker on.
- The runtime made empty mc0 / mc1 folders in the working directory before loadELF set the card path; the launcher
  now sets the card folder before the runtime starts.

## 2026-10-29 - Mouse look on foot, driving keys (the user's request)

The user asked for the mouse to move the camera while walking, right click to lock on to peds, and W / S / Space as
accelerate / brake / handbrake while driving.
- **Mouse camera on by default** now: the user wants the mouse to steer the camera, and with it off a new player's
  mouse did nothing but click. It is a control binding, not a change to the game's look or rules, so the
  "authentic by default" rule does not hold it back; it stays a toggle (Keyboard > Mouse camera).
- **True mouse look on foot** (the "later" of the 2026-10-28 entry above): the follow camera's heading is written in the
  game at the pad read, and its source points turned with it - the camera otherwise pulls the heading back to where it
  stands (game-internals.md 12b). The pitch cannot be written that way (the camera rebuilds it from where it stands), so
  it goes through the stick's own pitch speed with the game's stick curve undone and the excess over its top speed
  carried to the next frames: the angle is exact, only very fast vertical flicks arrive a little late. Writing the
  pitch directly would mean moving the source points up / down and their collision with the world - not worth it for
  the ~0.1 s it would save on the fastest flicks.
- Every other camera (vehicles, sniper / first person, lock-on) keeps the stick path: each has its own code, and the
  stick is what they were made for. The stick path now aims past the game's dead third of the stick (FUN_002842e8),
  so slow mouse movements turn those cameras too - before, under a third of full speed did nothing.
- Mouse forward now looks up. The old stick path sent it the other way (the game looks up for a stick pulled back) while
  the menu said "forward looks up".
- **Right click** was already R1 (target / lock-on); checked that it locks on with fists and a pistol and that the mouse
  moving meanwhile does not break the lock. Nothing to change but the check.
- **Driving keys** are a section of their own with their own key group: a key may be W on foot and Accelerate in a car,
  which the one-key-one-control rule of the 2026-10-28 entry would have refused. While the player drives (ped +0x480
  set and state 0x37) the driving bindings apply and the on-foot bindings of the same keys do not (W must not also tilt
  the stick: on a bike that leans, in a helicopter it pitches). The menu keys stay exclusive across groups. Lean
  forward / back (bikes, aircraft) moved to Keypad 8 / 5, since W / S no longer do it in a vehicle. The gamepad keeps
  the game's own layout.

## 2026-10-30 - The trainer's free camera (the user's request)

The user asked for a free-cam mode in the trainer, and chose: the world keeps running while it flies (the player
stands), Hide HUD as a switch of its own, on / off from a trainer row and a hotkey (F6, gamepad Back + LB).
- **The camera written after the game's update, not a script camera.** GTA trainers usually move a script camera
  (SET_FIXED_CAMERA_POSITION + POINT_CAMERA_AT_POINT) every frame. Here that would be a script per frame through the
  trainer's queue, a frame late, and only between frames. Instead the free camera writes the active CCam's source /
  front / up / FOV right after the game's own update of it (in place of the height routine CCamera::Process calls
  next, FUN_002A2ED0; game-internals.md 12b); CCamera::Process does the rest, so culling, LODs and streaming follow
  with no extra work. A hook of the next call, not code after the original returns (AGENTS.md rule 2);
  `VCS_FREECAM=0` keeps the game's code untouched.
- **The game's update keeps running** (changed the same day): the first version replaced CCam::Process while flying,
  and a mission launched under it hung on "Loading..." (the user's report) - its cutscene ends only when the cutscene
  camera has played its path, which that update advances. Running it and overwriting afterwards fixes every cutscene,
  wherever the mission was started. Launching a mission from the trainer also turns the free camera off (the user
  was fine with that as the fix): one starts a mission to watch it.
- **Real time**: the camera moves by the host clock, so its speed is the same at 30 / 60 / 144 fps and under the
  trainer's Game speed (slow-motion shots fly normally).
- **Fixed keys** for flying (W / A / S / D, E / Q, mouse; the gamepad's sticks and triggers): the game gets none of the
  input meanwhile, so they cannot clash with its bindings; only the on / off key is a setting. Rebindable flying keys
  can come later if wanted.
- **Hide HUD** skips CHud::Draw (the hook vcs_hud.cpp already had, now installed with `VCS_HUD_RW=0` too): radar, clock,
  money, weapon, stars. Text drawn after it (zone names, help, subtitles) stays - hiding that too would mean picking
  which text is the HUD's.

## 2026-10-30 - Native Linux (the user's request); the Steam Deck postponed

The user asked for Linux to be as native as Windows, first with Steam Deck support, then (the same day) without it:
"just have strong support for linux for now". Their choices: a **plain host build** (the distro's own compiler and
libraries through the same `tools/build.py`; no container, Flatpak or Steam Runtime), tested on their Linux laptop
(i5 Skylake, HD 520, 7 GB) with the Windows PC kept as the reference. The working list is docs/LINUX.md.
- **clang only** (19+, for `preserve_none` in PS2_GUEST_CC): the same compiler as clang-cl, so the same code and
  numerics. GCC would need its own checks of every bit-exact path and lacks preserve_none.
- **Flags as clang-cl's**, written out: `-march=x86-64-v3 -ffp-contract=off -fno-math-errno`, and `-fno-strict-aliasing`,
  which clang-cl implies (MSVC compatibility) and plain clang does not - the runtime and generated code read guest memory
  through casts. No stack protector / CET, as `/GS-`.
- **Vulkan**, a new RHI backend (`src/rhi/vulkan`), rather than OpenGL or a translation layer: the RHI was shaped for it
  (immutable pipelines, explicit passes), and it can be checked against D3D11 on the same Windows PC
  (`-DVCS_RHI_VULKAN=ON`). D3D11 stays the Windows default and the reference. Vulkan 1.3 with dynamic rendering,
  synchronization2 and push descriptors; volk, VMA and the headers from source (no SDK).
- **Shaders stay one HLSL source**: glslang (a distro package) compiles them to SPIR-V through `tools/hlsl_spirv.py`.
  DXC was the plan, but no distro ships it here and a downloaded binary is a tool the user didn't install; glslang
  handles every shader, and the script fixes the one thing it gets wrong (dual-source output: Location 0 Index 1).
- **Dear ImGui through the RHI** (`render/ui_renderer.cpp`) for Vulkan instead of `imgui_impl_vulkan`: one pipeline
  works for every target format the backend draws to (the swapchain's BGRA and the RGBA captures), and it uses only
  the RHI. D3D11 keeps `imgui_impl_dx11` (the reference stays as it was).
- **Hidden test runs make no swapchain** on Vulkan: the back buffer is a texture. A FIFO present to a hidden Wayland
  window can wait forever, and tests take screenshots off-screen anyway.
- **A null backend** (`VCS_RHI=null`) to bring up and check the CPU side without the renderer.
- The Windows-only debug tools got Linux versions where cheap (crash handler on signals, a SIGPROF sampling profiler);
  `perf` / `gdb` cover the rest. The write watch has no Linux equivalent yet (correct without it, slower); whether it is
  worth userfaultfd is to be measured first.

## 2026-10-30 - Frame-rate independent timing shows every frame it renders

The user asked for more performance on both platforms and chose this first (with specialised GS pixel shaders next).
With frame-rate independent timing the game thread now queues one frame and the window shows every frame rendered
(PERFORMANCE.md 17: 30 -> 76 shown fps on the GPU-bound laptop). Original timing keeps the old pacing on purpose: there
game time is counted in frames, and holding the game thread back would slow the game down when the GPU can't keep up,
where showing fewer frames keeps it at speed.

## 2026-10-30 - Input delay first: host-paced game frames, the frame lead

The user felt more input lag after the show-every-frame change and asked to keep input lag to a minimum. It is measured
now (`PS2X_RHI_STATS`: input snapshot to GPU done) and the frame-rate independent pacing was rebuilt around it
(PERFORMANCE.md 19): the main thread's frames pace the game's, a backlog is drained, and the game's frame starts early
enough (the frame lead) to be ready just in time on input read just before. 60 cap: 50 -> 34 ms. When the GPU is the
limit the one frame waiting stays (dropping it cut 9 ms but cost 4% of the frames and visible judder): smoothness kept
there.

## 2026-10-30 - A launcher for releases (docs/LAUNCHER.md)

The user asked for a launcher, as other recomps have, to be included in releases: locate the game, build, launch;
Windows first; the Python scripts must stay usable on their own.
- **Distribution stays source-only.** A release is the source plus `VCSLauncher.exe`, python.org's embeddable Python
  and `deps/` (the open-source libraries CMake would download) - no game code: the game is still recompiled and built on
  the player's PC. `tools/release.py` checks every file before zipping (no disc images, no MIPS ELF, nothing from
  generated/ or build/) and refuses the release otherwise.
- **The launcher is a front end over `tools/`**, never a second pipeline: it runs `doctor.py`, `build.py`,
  `setup_vs.py`, `backup.py`, `report.py`, `update.py`, `rip_disc.py` and reads their `@vcs {json}` events. A player
  with the launcher and a developer with a terminal run the same code.
- **SDL3 + Dear ImGui** for its window (already dependencies, the look of the in-game menus, portable later), its own
  CMake project so CI builds it without a disc; one static exe.
- **Bundled Python and libraries**: Visual Studio's compiler is the only thing left to install, and the launcher runs
  Microsoft's installer for it (checked for Microsoft's signature first; one UAC prompt). The release builds with no
  git and no internet (`FETCHCONTENT_FULLY_DISCONNECTED`). Cost: an 82 MB zip instead of a few MB.
  From that zip in an empty folder the game built in 8 min 42 s on the dev PC (the README said ~15 min on a laptop).
- **Updates only when asked** (or at start when the player turns it on): the check is one request to GitHub's API.
- The launcher's own settings live in `build/launcher.ini`; the game's stay in `vcs.ini` (F2 in the game).
- Not done: code signing (SmartScreen warns about an unknown publisher; documented in the README).

## 2026-10-30 - 60 fps with frame-rate independent timing by default

The user asked for frame-rate independent timing and 60 fps to be the default for every player from their first
build. `display.timing` defaults to 1 and `display.fps` to 60 (src/main.cpp); everything else stays the PS2's (4:3,
original resolution, no anti-aliasing). This replaces "60 fps off by default" (2026-10-22): the one enhancement on by
default, the rest still opt-in.
- *Authentic (PS2)* sets original timing at 30 explicitly (it used to be "the defaults"); *Reset to defaults* now gives
  60 fps independent timing; the menu's help says so.
- vcs.ini only keeps values that differ from the defaults, so players who never touched the frame rate get 60 fps on
  their next build too; anyone who chose a frame rate keeps it.
- Test runs keep the old timing: hidden runs (toolchain.test_window) pin `VCS_TIMING=0` and `VCS_FPS=30` unless the
  test sets them, so the regression baselines, the bench numbers and the checks mean what they did. controls_check
  passes an empty `VCS_TIMING` (not pinned, ignored by the game) because it tests the presets. The PGO profile is still
  trained at original timing (bench / scenes); retrain at the new default if the gap shows.
- Checked 2026-10-30 in a hidden run: reset -> timing 1, 60; Authentic -> 0, 30; Widescreen, light -> 1, 60; a test
  run -> 0, 30.

## 2026-10-31 - CMake and Ninja from anywhere, else downloaded

A player's build stopped at *Configuring the build* with a traceback: with Visual Studio Build Tools only, cmake is
in Visual Studio's own folders, which the checks looked at and Windows didn't (it starts a child's program from the
launcher's PATH, not the one given to it). The user asked for CMake to be found whatever the setup.
- **Search, then download.** `toolchain.build_tools` takes the first CMake >= 3.21 and Ninja >= 1.10 that run (each
  one is started: `cmake -E capabilities`, `ninja --version`): the build environment's PATH first (what the player
  chose), then every Visual Studio install's bundled copy (vswhere -all and the default folders), Kitware's
  installer's folder, winget, scoop, Chocolatey, pip (this Python and the user's), CLion, Qt, the Android SDK and
  MSYS2's native environments (its POSIX ones refused: msys-2.0.dll / cygwin1.dll beside the program). With none,
  Kitware's / Ninja's own builds are downloaded once into `build/build-tools` - pinned versions (CMake 4.4.5, Ninja
  1.13.2: what the dev machine builds with) and SHA-256 hashes in toolchain.py, so a changed file is refused.
- **Versions are checked, not just names**: VS 2019 bundles CMake 3.20, below the project's 3.21 - found on the dev
  machine itself. A too-old one is skipped with a line saying why.
- **Always by full path**: `resolve` gives cmake its path, `CMAKE_MAKE_PROGRAM` gives CMake Ninja's. The chosen folders
  are not put on PATH, which would let a folder like Chocolatey's or pip's shadow clang-cl. A build tree whose CMake or
  Ninja has gone (`stale_tools`) is set up again with today's.
- `VCS_CMAKE` / `VCS_NINJA` (full paths) choose by hand, checked like the rest. doctor never reports CMake as missing
  any more: it says the build will download it; only a failed download stops a build (`no_cmake`).
- Not bundled into the release zip (55 MB more for the rare player with no CMake and no internet): Visual Studio's
  installer, which the launcher runs, brings CMake anyway.

## 2026-10-31 - Release zips dated a day before the commit; the build repairs future dates

A player in Brazil (UTC-3) couldn't build 0.0.1: Ninja re-ran CMake 100 times and gave up ("manifest 'build.ninja'
still dirty"). Zip dates have no time zone; Python's zipfile writes the packer's local time (Adelaide, UTC+10:30), so
every file came out up to 13.5 h in the future, newer than any build.ninja CMake could write. Both ends are fixed:
- **release.py** dates every file the commit's time minus a day, as UTC (`zip_time`; `SOURCE_DATE_EPOCH` when set):
  in the past in every zone, and one date for the whole zip. Not each file's own time made safe: nothing in the
  build needs those times, and one date makes the zip depend only on its content.
- **build.py / recompile.py** set files dated in the future to now before CMake runs, with a line saying so, rather
  than stopping with a message: the player can't fix the zip, and touching a file's date loses nothing. doctor only
  reports them (it changes nothing). A build tree that already looped recovers without being deleted (checked).
- Ninja's "still dirty" still gets its own failure (`file_dates`) for what the repair can't reach - a clock that is
  wrong, a read-only file.

## 2026-10-31 - First person on foot, a port of UltimateFP's (the user's request)

The user asked for UltimateFP's on-foot first person (a closed GTA SA plugin) in the port. It cannot be loaded (a
32-bit SA plugin patching gta_sa.exe), so its on-foot behaviour is rebuilt on the port's own hooks
(`src/game/vcs_firstperson.cpp`, game-internals.md 12c).
- **The camera written after the game's update**, as the free camera (2026-10-30): the follow camera keeps running
  (missions, transitions and the third-person view after first person are the game's), and first person writes the
  CCam in place of the height routines. It chains after the free camera's hook; the free camera wins while it flies.
- **Only on foot, in the follow and lock-on cameras.** Every other camera (vehicles, the sniper / rocket / camera
  views, cutscenes, script cameras) is the game's own: they are made for what they show, and UltimateFP's in-vehicle
  half is a later step. Locked on, the view follows the player's body (the game turns him to the target, the gun
  points there) with the lock-on camera's tilt - not the lock-on camera's direction, which is from behind his shoulder.
- **The body faces the view standing still** (as in a first-person game), and when attacking or pressing R1: the game
  aims shots and searches R1 targets in front of the body, and R1's search runs in the frame R1 is read, before the
  camera - a body turned only once the view was 100 degrees off (the first version) locked on to nothing in view.
  Moving, the game turns him where he goes, relative to the view.
- **The head hidden by collapsing its bones for the draw**, not by moving the camera out of it: the bones are built
  while the ped is drawn, so a before-hook on the next call in the ped's render (FUN_0020c310 at 0x200738) changes
  them after the game's last write and before the skinning reads them. Hooks only work before the original
  (AGENTS.md rule 2): the bone update itself is left alone.
- **The eyes from the head joint's position, the view from the mouse** - not from the head bone's rotation (head
  turns and idle animations would swing the view), and the head joint of the previous draw carried with the ped's
  current position (no lag while running).
- **UltimateFP's numbers where they carry over**: 60 degrees up / 80 down, a short near plane (0.1; the game's 0.3 cut
  into the arms), the field of view 90 by default (its 92 in SA). The neck / lean / ADS / per-weapon offsets are SA
  model data and are not taken.
- Off by default (authentic by default); key B (free on the default keyboard: V is R3), Back + R3 on a gamepad.

## 2026-10-31 - Free aim, SA's manual aim (the user's request)

The user asked for San Andreas' free aim (no auto-aim, a crosshair, shots where it points) with their SA crosshair
(DotCrosshair: radius 1.4, outline 1.25 px at 1080 lines, white, black outline at alpha 192), switchable in the
settings menu (`src/game/vcs_freeaim.cpp`, game-internals.md 12d).
- **Lock-on is refused, not undone**: CPlayerPed::FindWeaponLockOnTarget answers "nothing found" for the player with a
  gun, so the game never enters its aim state or lock-on camera. Fists and melee weapons keep it (as SA's), the sniper
  rifles and the rocket launcher keep their own first-person sights.
- **The aim pose is the game's own**: VCS has no aim stance without a target, but CPed::AimGun points the gun in a
  direction (the look direction and the player's pitch) when bIsAimingGun is set and there is no seek target - what
  SetAimFlag(heading) sets when the player fires with no target. Its writes are made from the camera update every
  frame of the aim (hooks may not call guest functions mid-way), ClearAimFlag's after; the IK then raises the pistol and
  tilts it up and down. No strafing: the game has no strafe animations (locked on it runs too), so moving while aiming
  he runs where the stick points with the gun turned to the aim.
- **The shots along the camera's line, SA's way** (Find3rdPersonCamTargetVector): FireInstantHit's ProcessLineOfSight
  gets, in a before-hook keyed on its return addresses, the point of the camera's line nearest the muzzle and the
  weapon's range along it - written into FireInstantHit's own start / end, so tracers and impacts agree. A shot from
  the muzzle toward the crosshair's far point would miss near targets by the camera's offset.
- **The camera over the right shoulder is first person's hook's** (one owner of the CCam, one yaw / pitch, the mouse
  routed the same way); the game's follow camera keeps running underneath, so the aim eases in from it and back out,
  and its distance (it keeps its own, ~4.2 m) caps the aim camera's for walls behind the player. In first person the
  aim keeps the eyes' view, the dot shows while aiming (R1) and shots go where the player looks, aimed or not.
- **The crosshair centred in the window** (the picture is centred, presenter::fitRect), DotCrosshair's four discs
  without antialiasing (its soft edges are the extra discs), in ImGui's background list (under the menus), hidden
  when no camera update has shown it for 0.15 s (pause, loading).
- Off by default. Shotgun pellets follow the line too (their own line of sight, each pellet's spread kept about it);
  thrown weapons and the flamethrower keep the game's aim for now (level, along the body, which faces the aim).

## 2026-10-31 - First person in vehicles, vehicle glass, the field of view (the user's requests)

- **In-car first person is ours, not the game's mode 16**: VCS has an in-car view (Select), but it sits at the seat
  with a fixed look; ours keeps first person's eyes (the head joint in the vehicle's space, so passengers and bikes come
  out right), the mouse look with SA-like recentring while driving, the game's L2 / R2 look-aside, and the head hidden.
  It takes modes 18, 22 and 16 and leaves the game's camera running underneath (no jump when it ends).
- **The glass hidden per vehicle at the mesh colour** (FUN_0039e7f0): the glass materials are shared by every vehicle
  of the model, so the player's vehicle's glass meshes get alpha 0 on their way to the VU (the alpha test drops them);
  nothing in game memory is written. By material (alpha < 255) and the game's own "windscreen" rule, so it covers
  every vehicle type (other alpha materials on a vehicle go too).
- **The field of view where the frame hands it to the renderer** (CDraw::SetFOV from CCamera::Process), not in the
  CCam: the car camera eases its FOV from last frame's (speed widening), which a per-frame scale would compound.

## 2026-10-31 - The Immersive Weapons Pack port: converted models through a mods folder (the user's request)

- **Only weapons VCS has**: each pack weapon replaces the model (and texture dictionary) of an existing VCS weapon type;
  no new weapons, slots or model ids. Pack weapons without a VCS counterpart are left out.
- **Files, not a rebuilt disc**: converted files go to `<mods>/stream/<CStreaming id>.<ext>` and
  `src/game/vcs_stream_override.cpp` puts them in the game's own streaming buffers (before-hooks on RequestModel - the
  size word, so the buffer is big enough - and ConvertBufferToObject - the copy); the game relocates and uses them as
  its own. Nothing of the game is shipped: the user converts the pack with tools/weapon_convert.py against their disc.
  Generic on purpose (any streamed model / dictionary / animation id), off with `VCS_STREAM_OVERRIDE=0`.
- **The conversion keeps the game's formats** (rigid lit 'ldm' + 'xet', game-internals.md 12g) so every render path
  (VU1, native HLE, D3D11 / Vulkan) draws them unchanged; SA's 1024-px DXT textures become 128x128 8-bit (a parameter),
  the parts of an animated SA gun are merged at their rest places, the model is moved so its box centre is the VCS
  model's (where the hand holds it).

## 2026-10-31 - PCSX2 PNG packs as optional host textures

The user supplied `SLUS-21590/replacements` and asked to use its PCSX2 textures in the native port. Accept those
filenames directly: PCSX2 pixel/palette hashes and format bits, including the older TCC bit. Keep the original
disc, raster uploads, renderer and fallback intact; match at the shared texture cache so the world, HUD and menus
all benefit. The option is off by default and applies after restart. Decode PNGs asynchronously, share one GPU
copy per pack image, and bound the replacement cache by bytes (512 MiB by default). Keep GS logical sizes separate
from physical replacement sizes, including non-integer scales and region wrap. Start with the format actually
provided (full-texture PNGs); DDS, archives and separate region/mipmap files are outside this first implementation.
The pack remains external, ignored by git and rejected by the release guard. See `docs/TEXTURE_PACKS.md`.

The user subsequently requested `textures/SLUS-21590/`: automatic discovery checks `textures/` beside the exe and,
for the default source build, in the checkout root before the older bare serial folders. The pack-check tool uses
this layout by default too. Tests were skipped at the user's request for this folder-discovery change.

- **The whole pack, baked to a budget** (stage A, same day): SA's guns are 6k - 60k triangles cut into many small
  texture islands (a third of their edges are texture seams), so a simplifier that keeps their texture coordinates
  stops near 4.5k triangles (~290 KB a pistol) while the streaming heap is 5.4 MB and every carried weapon stays in
  it (game-internals.md 12g). So the geometry is simplified alone (tools/mesh_simplify.py: quadrics, unweighted so
  thin parts count, short edges first; back layers of double-sided faces and pieces under 2 % of the size dropped;
  meshes are only drawn, so holes may close) to 500 - 1700 triangles, given six box-projection views as one atlas
  (128x64 - 256x128, 8-bit) and the pack's textures baked onto it (tools/mesh_bake.py: rays along the normal, 2x2
  samples). One material and texture per weapon, as VCS's own; 25 - 110 KB a weapon (1.9 MB for all 28 files).
  `--no-bake` keeps the old path. Placements: fitted to VCS's own models (grip region for guns, the whole shape with a
  rotation for the rest), checked in the game; the table in weapon_convert.py.
- **Animations by the same override** (stage B): the pack's IFPs retargeted by bone id onto VCS's blocks, the blocks'
  anims kept in count, order and name (the game copies them to fixed slots); no rest-pose rotation needed (the frames
  agree, game-internals.md 12i). Pistols take the pack's two-handed fire (its default option); the shotgun the
  chromegun's set, the sniper the bolt-action set; VCS's one rifle group the AK's set. VCS's weapon timings
  (loop / fire points, reload time) stay. Standing fire anims are aimed to VCS's own at the fire point and keep only
  the arms (game-internals.md 12i): SA's rely on SA's aiming IK. TEC (unused by the player) is converted by the tool
  but not installed.
- **Rework after the user's report** (same day: the gun did not follow free aim, an M4 muzzle floated, muddy
  textures): fire anims take **VCS's own body under SA's aligned arms** (the arms-only conversion had dropped the
  rifle stance's turned shoulders: 53 degrees off the aim); the **Colt45 keeps VCS's fire anims** and takes only the
  pack's reloads - it aims with the arm, and SA's two-handed pistol pose cannot follow that IK (game-internals.md 12i;
  moving it to the torso IK would change its CWeaponInfo flag, not done). The CJ's-anims idea has the same problem
  (SA's anims all lean on SA's IK). Models: **each separate piece simplified on its own** with a floor by length (the
  barrel survives), **4-bit atlases with the two sides sharing texels** (twice the texels for the bytes of the old 8-bit
  ones; 16 colours, k-means), the pack's textures read at the mip that fits the atlas (no aliasing noise). **Budgets
  stay inside the streaming heap**: measured, it has no headroom (game-internals.md 12g) - the old set already made the
  vegetation port thrash - so a full inventory is ~0.53 MB (guns 1000 - 1200 triangles, 32K-texel atlases; small items
  400 / 16K), 1.3 MB for all files.
- **Full-resolution textures through the texture replacements, not the heap** (the user's "use full-res textures"):
  the atlas is baked at four times its size (1024 px wide for a gun) and written as a PCSX2-named PNG for
  `render/texture_replacements` (upstream PR #8); the game keeps its small 4-bit atlas, which the PNG replaces on the
  host GPU (no guest memory). The name is the game's own hash of the uploaded texture, so `tools/weapon_textures.py
  name` learns it from a traced run (each atlas has its own CLUT: matched by the palette hash, XXH3 computed in
  weapon_convert.py) and installs the PNGs in `textures/SLUS-21590/replacements/weapons/`. Needs Graphics > Texture
  replacements on; without it the small atlas shows.
- **The full meshes on the host, not a better simplifier** (2026-11-01, the user's "holes in gun"): any small model the
  streaming heap can hold (~1000 triangles of a 50k-triangle gun) tears thin, open parts (the carry handle, sights),
  and the +384 KB the heap can borrow from the main heap buys too little. So **WeaponHD.asi** (VCS-mods) draws the pack's
  full mesh in the small model's place through the lit refiner, which the exe now chains (`add_lit_refiner`). The atlas
  is laid out and painted from the full mesh (its box views, z-buffered: `tools/weapon_hd.py`), so both meshes share
  it and its full-resolution PNG; each small-model batch gets the full-mesh triangles nearest to it (it then follows
  that batch's culling), found in the game by a hash of the batch's positions. Data: `<mods>/weaponhd/<model>.whd`
  (`weapon_convert.py --hd`, 16 MB for 28 weapons), host memory only. Batches the VU clipper takes still draw the small
  model (rare: a weapon crossing the guard band).

## 2026-10-31 - Jolt Physics, milestone 1: death ragdolls (the user's request: SA's "[SA] Jolt Physics" mod)

The mod's binary can't be used (an SA ASI): it is re-implemented on the same engine in stages - death ragdolls, the
world's collision, bullet / explosion impulses, gun and cash props, knockdowns, then active ragdolls, ballistics, gore
and IK (game-internals.md 12f). Milestone 1 (game-internals.md 12h):
- **Jolt Physics 5.6.0 vendored unmodified** in `third_party/JoltPhysics` (MIT; tag v5.6.0, UPSTREAM_COMMIT): its
  `Jolt/` sources, `Build/CMakeLists.txt`, LICENSE and README only - no samples, tests or assets (5.6 MB). In the
  repository rather than fetched like SDL3: nothing to download, a release's deps/ unchanged; tools/release.py puts its
  licence into THIRD_PARTY_LICENSES.txt.
- **A library of its own** (`src/physics`, target `vcs_physics`, the only code that includes Jolt): Jolt's target
  carries PUBLIC defines and instruction-set options, which linked into ps2EntryRunner would reach the 240 MB of
  generated code (a full rebuild, with flags it was never built with). vcs_physics links it PRIVATE and offers a plain
  API (bone matrices in, bone matrices out). Jolt's own flag handling is off (OVERRIDE_CXX_FLAGS,
  FLOATING_POINT_EXCEPTIONS_ENABLED, the static MSVC runtime, its warnings as errors, LTO, the object stream, debug
  renderer, profiler, GPU compute); single precision (floats hold the 4 km map to a quarter of a millimetre).
- **x86-64-v3, the game's own baseline**: the game is built with /arch:AVX2 / -march=x86-64-v3 (AVX2, FMA, BMI, LZCNT,
  F16C), so Jolt at AVX2 adds no CPU requirement; AVX-512 off. FMA inside Jolt is fine (its maths isn't the PS2's).
- **Round-to-nearest around every Jolt call**, the caller's MXCSR given back: the VU paths leave the game thread in
  toward-zero at times.
- **One thread**: JobSystemSingleThreaded, stepped on the game thread in the before-hook after CWorld::Process. A few
  ragdolls cost well under a millisecond (8 falling: 0.5 ms), with no workers competing with the game's threads and the
  same result every run. To be revisited when the world's collision makes steps heavier.
- **The ragdoll is made at the ped's next draw, not inside SetDie**: the bones exist only from a draw (12c), so at
  SetDie there is only last frame's pose (and none for a ped that died off screen). The draw after the death has fresh
  bones, the tree and the hook point before the skinned draw. A ped that died unseen gets its ragdoll when it is first
  drawn (in its death animation's pose, without its speed).
- **11 parts on VC's bones** (hips on the spine bone 2 - the thighs' parent -, chest, head on the head joint, upper
  arms, forearms, thighs, calves); every other bone rides on its parent as it was at death (root, pelvis, neck,
  clavicles, hands, feet). Jolt's SkeletonMapper reorients chains of unmapped bones between two parts - here it turned
  the chest bone toward the left arm through the neck and clavicle -, so its chains are dropped after Initialize and
  those bones mapped like the others. The parts' bones keep their joints' places (no stretch shown).
- **Joint limits by anatomy, not by the death pose**: hinges at the elbows and knees (-150 .. +3 degrees about the Z
  both bones share; flexion measured negative), swing-twist cones elsewhere with their rest in the middle of the joint's
  range (arms 40 degrees out from the sides, thighs 50 degrees forward), as Jolt's cones are symmetric.
- **A ground of its own per ragdoll** until the world's collision: a slab 1 m under the ped's position (or under its
  lowest bone) that only its own parts see (a group filter wrapping RagdollSettings' table), so corpses at different
  heights never rest on each other's grounds; ragdolls still collide with each other.
- **The ped follows its body** (x / y to the root bone) so culling and the world's lists go where it lies, and
  ApplyMoveSpeed is not run for it; a move by the game itself (more than 2 m: a teleport, Vic's respawn) ends the
  ragdoll instead of being undone. At most 24 simulated: the oldest then keeps its last pose until the game removes the
  ped. Off by default (an enhancement).
- **The killing blow moves the body** (the user's report: a point-blank shotgun victim only crumpled, cars drove
  through bodies; brought forward from the bullet / explosion milestone). CPed::InflictDamage is hooked (before) for the
  attacker, weapon and piece; the blow that killed pushes the ragdoll once it exists. A shot or melee hit: an impulse
  from the attacker's side on the part hit, the trunk taking the rest, sized by weapon after SA's mod's DeathPush column
  (a shotgun spread over the trunk, harder close up). It replaces the game's own knock-back (applied before
  InflictDamage: a shotgun's 5.6 m/s), which on top threw bodies 7 m: the victim keeps only its own walking / running
  speed (2 m/s at most). A vehicle: its speed at the blow to the legs, lifted, and in shares to the trunk and head (0.6
  hips .. 0.15 head), not the game's throw - the body rotates back onto the bonnet. Game > Physics > Hit force (0 - 300
  %) scales both.
- **Vehicles as kinematic obstacles** near ragdolls (15 m), from their col model's bounding box, swept with them each
  step (placed, not swept, after a jump of 5 m: a teleport would fling bodies): bodies are thrown, carried and rolled
  over instead of passed through. One box is a wall - a body hit by its front face is bulldozed flat ahead of the car -,
  so a car is two: its lower body to the bonnet's height and the cabin set back from the front, a body then folds onto
  the bonnet as it should. The boxes are raised 0.25 m off the ground (a lying body goes under, as between wheels).
  Nothing pushes back on the vehicle (the game moves it); the world's collision is still milestone 2's.
- **Shots on bodies already down are cast against the ragdolls, not taken from the game's hits** (the user's request).
  The game's collision for a dead ped is not where the ragdoll lies (shots at a body's hips hit the road under it), so
  hooking its impact functions (DoBulletImpact, the pellet loop's dead-ped branch - both tried) missed most shots.
  Instead every bullet's line (CWeapon::ProcessLineOfSight: pistols, SMGs, rifles, each pellet, drive-bys) is cast in
  Jolt against the ragdoll parts and the part it meets is pushed at that point: what the player sees hit is what moves.
  The bullet still flies on in the game (the road under the body gets the hole and the blood stays the game's). Jolt's
  hook is installed before free aim's, which then wraps it, so the line is the camera's when the player aims.
- **Blasts throw ragdolls part by part** (CWorld::TriggerExplosion, before): each part within the radius gets a velocity
  away from the centre and up, up to 12 m/s for power 300 at the centre falling to 0 at the edge - nearer parts faster,
  so bodies tumble. Peds the blast kills get the same when their ragdoll is made (any recent blast reaching them; the
  damage comes as the blast's weapon, a grenade's 12 or 0x31), in place of the game's push (one rigid 11 m/s throw
  given before the damage). Hit force scales it.

## 2026-10-31 - Jolt Physics, milestone 2: the world's collision for the ragdolls (the user's request)

Ragdolls land on, roll down and stop against the game's own collision (game-internals.md 12k):
- **The game's col models, read where the game keeps them**, not a collision export of the disc's files: the sectors
  CWorld itself walks (its building and object lists) around each ragdoll, each entity's col model through its model
  info, in its own matrix. Whatever the game has streamed in is what the bodies meet, the same as the game's own peds
  and cars, with nothing to convert or ship; what it has not streamed in has no primitives (their counts 0) and is left
  out.
- **Only near the ragdolls**: every step the buildings and objects whose bounding sphere comes within 10 m of a
  ragdoll's hips are bodies in Jolt, the others are taken out (a few to a few dozen bodies; SA's mod keeps similar
  radii). Buildings are static bodies; objects (street furniture, palms, props) kinematic ones moved with the game's
  matrix each step, so a moved object carries or pushes a body and nothing a body does moves the object (the game
  owns it). Vehicles stay milestone 1's boxes.
- **One shape per col model, cached**: its triangles as a MeshShape (Jolt builds its own tree; the game's triangle
  sections are not needed), its boxes and spheres beside it in a compound. Kept while the col model's counts, array
  pointers and first vertices are unchanged - streamed collision can be freed and loaded again, and a changed col model
  is made again - and dropped after 10 s unused. The triangles' winding is turned round: the game's front face is
  clockwise, and Jolt ignores back faces.
- **A ground of its own only where the world has nothing**: a ragdoll is made after the world around it is put in, then
  a ray looks for a surface up to 50 m under the ped; with none (collision not streamed in) it gets milestone 1's slab
  at its feet, otherwise none - a slab would catch a body falling off a roof in mid-air. A body 60 m under where it
  started is frozen (whatever was under it is gone). `VCS_JOLT_WORLD=0` gives milestone 1's grounds back.
- **The ped's height follows its body** (1 m over its lowest bone, as a standing ped's position is over its soles) once
  they differ by 0.5 m: down stairs or off a ledge the game's position, its culling and the camera on a dead Vic go
  with it. Small differences are left alone.
- **Corpse shots stop at walls**: the ray of a bullet's line also meets the static world in the physics, and only a
  ragdoll part met before any of it is pushed. Vehicles and objects don't stop it (a drive-by's line starts inside its
  own car), nor do the ragdolls' own grounds.
- **More room**: 2048 bodies (the world's capped at 1648, room left for 24 ragdolls and their vehicles), 8192 body
  pairs, 4096 contacts. Still one thread: a body falling off a roof among 9 buildings stepped in 0.26 ms at most.

## 2026-10-31 - Jolt Physics: bike falls - knockdown ragdolls (the user's request)

The user asked for peds hit on bikes, and Vic crashing, to fall off as ragdolls (game-internals.md 12l) - the first of
the mod's knockdowns, brought forward:
- **Where the game throws a rider off, not a collision rule of our own**: CBike::KnockOffRider is hooked (before) and
  the ragdoll made once the game has thrown the rider (its next draw in PED_FALL). The game keeps deciding who falls -
  its bike damage (impulse per mass by hit direction: head on throws a rider at speeds a side hit does not), a car's
  hit on the ped, a burst tyre, a killing shot - and its throw (the bike's speed and an upward kick) is the ragdoll's
  start. Riders the throw kills get the death ragdoll (their SetDie is taken although their vehicle pointer is still
  set then); a rider that dies while down becomes a dead body.
- **The game's own fall state, held while the body moves**: the ped stays in PED_FALL with its get-up time held at -1
  and its own speed at 0 (ApplyMoveSpeed is skipped for it as for the dead; gravity would pile up in its speed). Once
  its bodies have slept (or its hips have stayed within 3 cm) 0.4 s, and at least 2.5 s after the fall (8 s at the latest) the ped is placed on the body - its position on the root bone, 1 m
  over the lowest bone, facing along the body (feet first on its back, head first on its front, as the get-ups stand
  up) - and its get-up time set to now: the game's own CPed::Fall gets it up with its own animation and control comes
  back as usual. Removing the ragdoll for any other reason (switched off, moved by the game) also lets it up.
- **The body's last pose eased into the get-up**: drawn as it lay until the game starts the get-up, then blended into
  the animation over 0.35 s (positions in a line, rotations along the shortest arc), so the switch from physics to
  animation is a quick roll, not a pop.
- **Its own bike is no obstacle for it while it is down**: the rider starts astride it, and the bike's box would throw
  the body out sideways the first step.
- **Swept collision for the ragdoll parts** (Jolt's LinearCast): thrown at 15 - 30 m/s a limb moves more than its
  thickness in a step, and the world's walls are single triangles, so a body could pass through one; cost only for
  parts moving that fast.
- **Game > Physics > Bike falls** (on by default, with Ragdolls on; VCS_JOLT_BIKES): the knockdowns can be left out
  while death ragdolls stay. Other knockdowns (a car's hit on foot, blasts that leave a ped alive, melee) are not
  ragdolls yet.

## 2026-10-31 - Jolt Physics: hit reactions, GTA IV / Euphoria style (the user's request)

The user asked for Euphoria-like shot reactions as in SA's Jolt Physics mod (game-internals.md 12n):
- **A short active ragdoll on the animated ped, not a full takeover**: hips kinematic on the animation, muscles (Jolt's
  joint motors) pulling every limb back to the animated pose, the bullet's push on the part hit. The game keeps the
  ped - its state, AI, movement, aim -, so a reacting ped walks, flees or shoots on; only its drawn pose takes the hit,
  0.2 s of physics then eased back into the animation by 0.9 s. Euphoria's full balance controller (staggering steps,
  catching itself) is not attempted: the game's own knockdown decides when a ped falls, and that fall is 12l's
  knockdown ragdoll, up again with the game's get-up.
- **Muscle strength by the part**: per-joint torque (trunk and thighs 400 N m, arms 120, forearms and neck 60, calves
  250) at 0.6 when hit, 1.0 at the end - strong enough that limbs come back without wobbling, weak enough that the hit
  part jerks (up to ~0.3 m drawn). The push is 0.8 of the killing push by weapon; Hit force scales it.
- **Game > Physics > Hit reactions** (on by default with Ragdolls on; VCS_JOLT_HITS). Not done from the SA mod: catching
  the fall with the hands, blind fire from the ground, melee reactions.
- **Wound clutch and stumble on the drawn pose and the position, not in the physics or the game's state** (the user's
  follow-up): the hand to the wound is two-bone IK over the drawn blend (exact, cheap, no fight with the muscles); a
  hard hit's stumble moves the ped's position along the push with procedural steps drawn on the legs - VCS's own
  stagger state was not found among SetPedState's constant callers, and moving the position keeps its AI and
  animation (running, aiming) as they are. Walls stop it (a ray against the world in the physics). A clutch is kept
  when the ped flees (as GTA IV's do); neither for Vic.

## 2026-10-31 - Jolt Physics: catching falls and firing back from the ground (the user's request)

game-internals.md 12s.
- **Arms by motors, not by an animation**: the knockdown ragdoll's shoulder and elbow motors reach the arms toward the
  ground along the way the hips fall, so a forward fall puts the hands out in front and a backward one behind; limp
  once the hips are near the ground, so the body still lands and lies as a ragdoll.
- **The game fires the gun**: a host hook may not call into the game except as a tail call, so the shot is a tail call
  to CWeapon::Fire from ApplyMoveSpeed (called for the ped each frame, its own work skipped for ragdolls, its caller
  ignoring a return value). With no fire source the game puts the muzzle 0.6 m up the ped's axis from its position, so
  the ped is turned to its shooter and moved for that one frame to put the muzzle at its hand - no guest memory of our
  own is needed - and the next step puts it back on its body. Everything after is the game's: ammo, tracer, sound,
  hits, the shooter's reaction.
- Only peds shot down by a ped (not bike falls), never the player; 4 shots at most. Two toggles beside Hit reactions,
  on by default with Ragdolls on (VCS_JOLT_CATCH, VCS_JOLT_BLINDFIRE).

## 2026-10-31 - Foot IK: feet on the ground on slopes and stairs (the user's request)

After SA's Jolt Physics mod's [FootIK] (game-internals.md 12q):
- **The game's own collision, read directly**: Jolt's world bodies exist only around ragdolls, so the feet query the
  col triangles of the entities in the sector under them, transformed once per entity and cached (an entity's ground
  faces, rebuilt when its col model or position changes). A foot is a point query a frame: 0.011 ms for two peds.
- **An IK on the drawn pose, not physics**: the pelvis down by the lower foot's need, a two-bone leg IK keeping the
  knee in its bend plane and the step's lift, the foot tilted 0.7 to the slope - SA's MaxOffset / Smoothing /
  AlignStrength values. The game's position, collision and animation are untouched; only what is drawn.
- **A module of its own** (`VCS-mods plugins/JoltPhysics/src/footik.cpp`), chained on the same render hooks as the ragdolls and installed
  after them so ragdoll poses win; Game > Physics > Foot IK (off by default, VCS_FOOTIK) and Foot IK for peds (25 m).

## 2026-10-31 - Jolt Physics: dismemberment (the user's request)

After SA's Jolt mod's [Dismemberment] (game-internals.md 12p):
- **Stumps by collapsing bones, not by new models**: the severed part's bones are drawn at zero scale on the joint they
  hang from, the skin weighted to them shrinks into it. VCS has no gore models and its ped is one skinned mesh drawn
  by the game, so the cut part is gone rather than a loose limb (SA's DetachedMesh); its ragdoll bodies stay on their
  joints as sensors so nothing feels the missing limb.
- **The game's own blood**: CParticle::AddParticle(blood) reached by a tail call from ApplyMoveSpeed, with the dead ped's
  position and move speed lent as the particle's position and direction for that frame - no guest memory of our own.
  A burst, then a bleed for 3 s.
- **SA's chances by weapon** (blades and shotguns high, pistols and SMGs near none), on lethal hits, shots on bodies down
  and blasts (2 parts at most). Off by default; with the game's own gore setting off there is none.

## 2026-10-31 - Jiggle physics on the chest and pelvis bones (the user's request)

SA's Jolt mod jiggles breast and glute bones its adapted models have; VCS's peds have none (game-internals.md 12r).
- **Bone-level, not vertex-level**: a per-vertex jiggle would rewrite each ped's skinned VU1 packets every frame. The
  skinned draw takes each bone's matrix on its own, so springs on the chest (spine1) and pelvis bones' drawn matrices
  move just the skin weighted to them - the parts that should bounce - without moving the arms, neck or thighs.
- **The SA ini's numbers**: frequency, damping, max offset and angle per part, gravity scale, inward limit, the nearest
  8 peds within 30 m, female only (ped type 5); Intensity 1.8 is the setting's 100 %. A spring is driven by its bone's
  world acceleration, so walking, stopping, turning, getting hit and ragdolls all move it.
- **Its own file and hooks** (src/game/vcs_jiggle.*, not Jolt: no physics engine is needed for two springs), chained
  in the ped's render before Jolt's so that it rides on the ragdolls' poses too.
- Off by default like the other enhancements; `VCS_JIGGLE_ALL=1` takes every ped (for tests).

## 2026-10-31 - Jolt Physics: guns and cash on the ground, GTA IV style (the user's request)

The user asked for physics on cash pickups and for weapon pickups as in the SA mod "GTA IV Pickups On The Ground" (CLEO
scripts that lay pickups on the ground instead of floating and spinning; a replaced glow model; sounds; a key to
swap a weapon whose slot is taken). game-internals.md 12m:
- **The pickup's drawing taken over, not its logic**: the game spins and scales pickups in DoPickUpEffects /
  DoMoneyEffects from the render, and nothing else moves the object. Hooking those two for guns (models 331 - 368)
  and cash (type 8) leaves creation, collection, timeouts and respawns to the game; only where the object is drawn
  changes, and the pickup's position is moved with it so collection happens where it lies.
- **Each lands by physics, from where the game put it**, instead of a fixed lying pose per model: a Jolt box from the
  model's own bounds tumbled about its length settles on a broad side - guns on their side, cash flat - on whatever is
  there (kerbs, slopes, car roofs). A dead ped's drops are thrown out a little, so a body's gun and cash scatter.
  Real size: the game's 1.84 x scale for guns goes with the spin.
- **Short-lived bodies**: a prop leaves the physics once still for 0.5 s (or unseen for 3 s) and is drawn from its
  last pose; at most 64 move at once (more keep the game's spinning look). The world's collision is put in around
  moving props as around ragdolls, and vehicles there are boxes, so a car can knock one along.
- **Game > Physics > Pickups on the ground** (off by default like the other enhancements; VCS_JOLT_PICKUPS), apart
  from Ragdolls. Health, armour and other pickups keep the game's look. Not done: the swap key (taking a weapon whose
  slot holds another only on a key press) and the mod's sounds.

## 2026-10-31 - Project2DFX: distant lights, stars, traffic, draw distance (the user's request)

The user asked for ThirteenAG's Project2DFX for the PCSX2 fork (GTAVCS.PCSX2F.Project2DFX: LOD lights, more stars,
distant traffic), then for draw-distance options. The plugin is PS2 code built against the fork's hook runtime, so it
is rebuilt in `src/game/vcs_project2dfx.cpp` from its MIT source (game-internals.md 6l).
- **The light table is never in this repository**: Project2DFX took its 4,423 lamps from the game's map - game data.
  `tools/p2dfx.py import` reads it from the plugin the player has (the zip, its .elf - symbol `vcsfx::lights` - or the
  source's Lights.hpp) into `p2dfx/lights.bin` next to vcs.exe (kept by tools/clean.py).
- **Per-light work on the host, game functions as a chain of guest tail calls.** The plugin calls the game's
  projection and sprite writer for every light; here those two are ported bit-exactly (FPU / VU0 macros; checked
  against the game's own calls with `VCS_P2DFX_VERIFY=1`) and the calls that must stay the game's (render states, the
  sprite flush, Im3D) run one at a time: each returns to a continuation address of ours (`0x27C41C`, CCoronas::Render
  + 4, neither an entry nor a resume point, refused if it ever becomes one), whose host function sets up the next
  call, until the last returns to where the game's own call would have. No host code runs after a guest call inside
  one C++ frame, so AGENTS.md rule 2 holds: the chain is driven by the scheduler's dispatch, and a checkpoint unwind
  in the middle just resumes it.
- **The game's buffers, the game's limits**: sprites go through the sprite buffer in batches of its 96, traffic
  through the temp buffers (512 vertices, 1020 indices); the plugin's packet-buffer reserves are kept.
- **Draw distance = the world camera's far plane**, a constant 2000 every frame, scaled where the render sets it: the
  sector frustum and entity culling follow it, and every island's low-detail buildings are already in each level's
  data, so nothing has to be preloaded - the far plane was what hid them. The fog ends at the far plane, so a longer
  one also clears the haze (the PS2 picture at 1x). **Object detail distance = CRenderer::ms_lodDistScale** (0x4887F8,
  1.0, read only by CCamera::Process): what PC VC's draw-distance slider changes.
- **The flight ceiling** (80 -> 800 m, part of the plugin's light install) is a setting of its own on the Game page.
- Everything off by default (authentic by default); Live settings (atomics read each frame); `VCS_P2DFX_HOOKS=0` hooks
  nothing.

## 2026-10-31 - PCSX2 PNG packs as optional host textures

The user supplied `SLUS-21590/replacements` and asked to use its PCSX2 textures in the native port. Accept those
filenames directly: PCSX2 pixel/palette hashes and format bits, including the older TCC bit. Keep the original
disc, raster uploads, renderer and fallback intact; match at the shared texture cache so the world, HUD and menus
all benefit. The option is off by default and applies after restart. Decode PNGs asynchronously, share one GPU
copy per pack image, and bound the replacement cache by bytes (512 MiB by default). Keep GS logical sizes separate
from physical replacement sizes, including non-integer scales and region wrap. Start with the format actually
provided (full-texture PNGs); DDS, archives and separate region/mipmap files are outside this first implementation.
The pack remains external, ignored by git and rejected by the release guard. See `docs/TEXTURE_PACKS.md`.

The user subsequently requested `textures/SLUS-21590/`: automatic discovery checks `textures/` beside the exe and,
for the default source build, in the checkout root before the older bare serial folders. The pack-check tool uses
this layout by default too. Tests were skipped at the user's request for this folder-discovery change.

## 2026-10-31 - 80's VC True Vegetation: VC's palms in place of VCS's (the user's request)

The user asked to port the "80's VC True Vegetation" mod (VC PC palms and trees) and to pick the fitting palms.
- **By name**: VCS kept VC's vegetation names (game-internals.md 12j), so each of the pack's seven palms replaces the VCS
  model of the same name - `veg_palm01..04`, `veg_palmbig14`, `veg_palwee01..02` - through the streamed-file overrides
  (`tools/veg_convert.py` -> `<mods>/stream`), with that model's own texture dictionary, which nothing else uses. The
  user then asked for the pack's four leaf trees too (`veg_tree3`, `veg_treea1`, `veg_treea3`, `veg_treeb1`): all
  eleven by default, `--only` for fewer.
- **Alpha dual pass in the renderer** (the user's request, after skygfx): Graphics > "Alpha dual pass", on by default
  (the user's choice, 2026-10-31: it fixes the game's own foliage too, for about 0.3 ms of GPU time). Its cost
  (the user: "eats way too much performance"): the second pass ran for every alpha-blended world draw, nearly all of
  them; it now runs only for textures with partly transparent texels (alpha strictly between 0 and half), the others
  draw once as before - 60% of the eligible draws in a Havana palm view. Both passes stay on the GPU: the draw shader
  writes SV_Depth (GS depth), so early depth rejection cannot cull the second pass. Measured there at the user's
  settings (240 cap, window resolution, 16x anisotropic, a 1080p frame): 148 - 161 game fps off, 158 - 164 on - the game
  thread limits, not the GPU; GPU 3.8 -> 4.4 ms before the change. Blended draws with the low alpha-test reference draw their half-alpha-and-up texels with depth
  writes, then the rest without, so half-transparent leaf edges stop hiding what is drawn after them
  (PS2RECOMP_PATCHES.md). It works for every such draw, the game's own foliage and fences included; the converter's
  0 / 255 alpha stays, as the result must also hold with the option off.
- **Full-size textures as a texture pack** (the user's request, 2026-10-31, "as the HD HUD"): the streamed models keep
  their small 4-bit textures (streaming memory; Texture replacements off still looks right), and `veg_convert.py --hd`
  writes the pack's own images as PCSX2-named replacements. The names come from the renderer itself
  (`VCS_TEXTURE_DUMP`) rather than a Python copy of XXH3 and the GS's block layout: one hidden run, exact by
  construction. The pack's alpha is kept at full size (scaled to 128): alpha dual pass, on by default, handles its
  half-transparent edges.
- **Scaled to VCS's heights**: VCS's palms are the same designs drawn 0.8 - 1.4 times VC's size; the map is placed
  around them, so each new palm takes the old one's height (its footprint then matches too).
- **The game's formats and colour**: prelit like the game's own palms (flags 0xD), their flat grey times the pack's
  material colour; textures 32 - 256 px by the share of the model each covers, 4-bit like two thirds of the game's own
  (8-bit below 32 x 16). The seven palms take 0.77 MB of streaming memory against the game's own 0.12 MB (1.18 MB with
  8-bit textures, which looked the same side by side), memory the game otherwise fills with vehicles and peds.
- **Leaves as made**: a first version cut every palm to 1,000 triangles (simplified, the smallest frond cards left
  out); in the game its crowns were confetti with pale veils (the user's report). Each frond card maps its own patch of
  the texture, and collapses inside the cards smeared it. Now the cards stay as made, but of each double-sided card
  (every face twice, reversed, for PC's back-face culling) one face is kept, since VCS draws both sides of a triangle:
  half the triangles. Only the opaque parts (trunks, stems) are simplified, to 600 triangles, and materials with a fully
  transparent texture (`a` in `veg_palmbig14`) are left out. In the densest view measured the GS stage went
  6.0 -> 10.3 ms (1,325 -> 4,631 native draws; every 68 strip vertices are a draw). Fewer draws for everything would
  come from merging consecutive same-state batches in the renderer - a renderer task of its own, not done here.
- **Alpha for the game's alpha test**: world draws are alpha-tested GREATER 8 (of 128) and write depth for every texel
  that passes (game-internals.md 12i), so half-transparent texels let the sky through and hid the parts of the tree drawn
  after them - pale patches where downscaled fibres and leaflets had blurred half transparent (`veg_palmbig14`'s skirt:
  half its texels at 128 px). Cut-out textures keep at least 128 px; their colour is averaged by alpha and bled into the
  transparent texels (no dark or white fringes), their alpha scaled to keep the full-size share of solid texels and then
  made 0 or 255; opaque materials are drawn first. Left is the filtered edge band: a fine sky-coloured speckle between
  leaflets, as alpha-tested foliage has.
- `tools/veg_convert.py --remove` takes the palms out again; `VCS_STREAM_OVERRIDE=0` runs without any override.
- **Feet on the ground** (2026-10-31, the user's report of a palm on a low wall, 1 m above the lawn): each pack model is
  scaled to the VCS model's full height and its trunk's foot moved onto the VCS model's (x, y, z) - the origins are not
  the feet, in VCS or in either pack (game-internals.md 12j has every model's numbers).

## 2026-10-31 - BSOR Vegetation (SA) as the vegetation source (the user's request)

The user switched the source from the 80's VC pack to BSOR Vegetation, a GTA SA modloader folder.
- **Only models that fit a VCS model**: BSOR has all eleven VCS names (`veg_palm01..04`, `veg_palmbig14`,
  `veg_palwee01..02`, `veg_tree3`, `veg_treea1`, `veg_treea3`, `veg_treeb1`), so each replaces the same name as before;
  no stand-ins were needed. Its `sjmpalm*`, `vgs_palm*` and `veg_palwee03` have no VCS model with data, and the
  `veg_palmkb*` names exist in VCS without data, so none of them is used.
- **One tool, two sources**: `--pack` takes either; a folder with `files dff` is BSOR (`BsorPack`), anything else the
  VC zip / folder as before. BSOR's textures come from the dictionaries `thetxdp.ide` names as parents (one,
  `bsor5s_txdp.txd`, 51 MB, read for the 16 textures the models use). SA's night colours, 2dfx and prelighting are
  not carried over: the result keeps the VCS palms' flat grey, as with the VC pack.
- **Heights**: with the feet aligned (above) every BSOR trunk meets the ground at the instances checked
  (build/veg_test/feet/bsor); without it BSOR's `veg_palwee02` would have floated 0.7 m and its `veg_palm01` stood
  3.6 m from its collision. Sizes: 1,140 - 5,465 triangles, 3,000 - 10,735 strip vertices per model (the VC pack:
  up to 8,088), 18 - 62 model sectors.
- `--hd` names 16 full-size textures (512 - 1024 px); `veg_treea3` / `veg_treeb1` stand nowhere on the map, so their
  three textures are not seen and get none. The VC pack's 25 replacement images were moved out of the vegetation
  folder (build/veg_test/feet/hd_vc), since their names no longer match anything.

- **Upright palms only** (the user's request, 2026-11-01: "swap all these angled palms in whole game with straight
  placed palms"): `veg_convert.py --straight` builds BSOR's leaning / bent designs from upright ones of the same pack -
  veg_palm01 from veg_palm02, veg_palm03 from veg_palm04, veg_palwee01 from veg_palwee02 (crown offsets from the foot
  were 17, 27 and 16 m; now under 1 m for every palm). Scaled to the VCS model's height and stood on its foot as the
  others; the textures are the sources' (same names, so the full-size pack still matches). The game's collision is
  still the VCS model's own (VCS's veg_palm01 / 03 / palwee01 lean too): a car can touch an unseen leaning trunk.
  Installed in build/mods with --straight; the leaning set's full-size images kept in build/veg_test/feet/hd_bsor_lean.
- **The game's prelighting and brightness** (the user, 2026-11-01: "need fix prelight, its lit in evening"): the
  converter gave every vertex VCS's flat 88 grey, so SA's pale bark stayed light grey at 22:00 beside the game's dark
  palms (SA darkens it with its own night lighting; VCS draws prelit colour x texture). Now each vertex takes the game
  model's mean grey at its height, times the factor that brings the pack texture to the game's texture brightness for
  its class (bark / leaves): 0.42 - 0.90 on the palms, 0.30 - 0.77 on the leaf trees. Never brightened (at most 1).
  Textures are untouched, so the names, the full-size pack and the wind list stay. Checked at 22:00 and 13:00 against
  the game's own palms (build/veg_test/wind/night_lit_cmp.png, noon_lit_cmp.png).

## 2026-10-31 - SkyGfx Extended's vegetation wind: what it is, a plan for the native renderer (research, not built)

Read from the user's copy (extracted to build/analysis/skygfx_ext, nothing run; the two D3D9 vertex shaders in
skygfx.asi disassembled with fxc /dumpbin): v4.2b Extended v1.7 (aap, Junior_Djjr). Wind lives in its building
pipeline's vertex shaders (`vs_2_x`, with and without the env-map normals), constants `windPos` (c21, float2) and
`windIntensity` (c22); the ini has only a hidden `forceWindShader` key. Per vertex, in model space:
`p = pos.xy + windPos`; value noise `n` = bilinear, smoothstep-weighted blend of `frac(sin(k) * 43758.5469)` at the
four integer corners (`k = floor(p.x) + 57 floor(p.y)`, + 1, + 57, + 58); `w = (n - 0.5) * windIntensity`;
`k = 1 - nightColour.a`; `pos.xy += w * k`, `pos.z += 0.3 * w * k`. So what moves is chosen per vertex by the
model's night vertex colour alpha (SA's 0x253F2F9; 255 = still), authored into the DFF - BSOR's are all 255, so in SA
SkyGfx would not move BSOR's palms either. How the asi sets windPos / windIntensity (from CWeather::Wind, time) is in
its x86 code, not read.

**Built 2026-10-31 (the user's request)**, Graphics > Vegetation wind (off by default) and its strength. What changed
from the plan below:
- **One position convention instead of per-model numbers**: the BSOR palms share textures between models of different
  sizes, so the converter quantizes every converted tree with 2 mm per unit and its crown (the top of the trunk: the
  middle of the opaque parts' highest metre) at position 0, and the wind list (tools/veg_convert.py --hd ->
  mods/wind.txt: "name, metres per unit x y z, 0, reach") repeats one set of numbers. Texture data is unchanged by
  it, so the dump's names stay valid.
- **Only the leaves sway, by their distance from the crown** (the user, 2026-11-01: "vegetation wind should not work
  on bark of palms"): only cut-out textures are in the wind list - the bark is never moved -, and the weight is the
  square of the distance from the crown up to 6 m, then linear, so the fronds' bases stay on the trunk's top and their
  tips move most. (The first version weighted by height above the foot and moved the bark too.) Two noise samples (x
  and y apart) instead of SkyGfx's single diagonal one; an integer hash instead of `frac(sin)`.
- **Strength from the game's wind** (`0x4CD2A4`, game-internals.md 12j): 0.3 + 0.6 x wind metres (clamped 0 - 2),
  times the strength setting; the field drifts at 0.6 + 1.2 x wind m/s in a slowly turning direction, on the game's
  clock (still while paused).

Plan for VCS (as researched; another session owns gs_hw.cpp):
- **Data**: VCS's prelit vertex has no free channel (RGBA 5551 colour; the uv's z lane is the batch's STROW row), so
  the weight comes from the position: the converter's quantizer centres each model's box, so `h = (pos.z + 32768) /
  65536` is the height within the model; weight `saturate((h - 0.15) / 0.85)^2` keeps the foot still and moves the
  crown most, and since trunk top and fronds sample the same noise at nearby positions they stay joined.
- **Which draws**: a per-draw flag. Best: by texture - the converter already learns each converted texture's PCSX2 name
  (`--hd`); it would also write `<mods>/wind.txt` (names + amplitude), and the renderer, which hashes textures for
  replacements anyway, sets the flag for those. By model id (540 - 578) needs the RSL level to pass the entity's model
  to the native draw (not plumbed today). A magic word in the batch header (the V4-32 at VU address 0, x / y zero in
  the game's palms) would need proof that the VU program 0x0030 ignores those lanes.
- **Shader**: in `vs_world`, before both transforms, `pos.xy += w * k * A`, `pos.z += 0.3 * ...`, in raw position
  units (A a fraction of 32768, so a tall palm sways more in metres than a small one); constants in `nat[15]` (windPos,
  intensity, flag) - slots 15 - 30 are unused by VcsWorld, so `GSNativeDraw` (gs_backend.h, a full rebuild) need not
  change. The mesh cache is unaffected (positions stay as cached; the offset is GPU-side). SPIR-V regenerated by
  tools/hlsl_spirv.py.
- **Time and strength**: windPos advances along the wind's direction each frame (the game's own wind value - VCS's
  CWeather::Wind address still to be found - or a fixed speed), intensity from it; a Graphics setting, off by default
  (authentic by default).
- **Cost**: ~45 ALU slots per flagged vertex (four sin hashes; a cheaper integer hash would do), only on flagged draws:
  a Havana palm view has ~50 - 100k strip vertices of palms - well under 0.1 ms of GPU. No new draws; the CPU adds one
  set lookup per draw. The PS2 path, PS2X_HLE_VERIFY (CPU-side kicks) and collision are untouched; the culling sphere
  covers an offset of a few per cent of the model's size.

## 2026-10-31 - Upstream PR #8 (PCSX2 texture packs) in this build, for the HD HUD pack (the user's request)

The user asked for the "HD HUD - SLUS-21590 - PS Icons" PCSX2 pack in the port by way of upstream's open PR #8
(gothamor/gta-vcs-recomp "Feature/texture replacements", head db33c50; the section "PCSX2 PNG packs as optional host
textures" above and docs/TEXTURE_PACKS.md are its own). It is not merged upstream: this folder carries it ahead of
upstream, and nothing was pushed.
- **A three-way merge, not a patch**: the PR branch starts at v0.0.1 (9b9211d), this folder's base, so each touched
  file was merged from v0.0.1, this folder and the PR head; local work (first person, free aim, Jolt, Project2DFX,
  the JoltPhysics licence in release.py) is untouched. Two conflicts: `tools/toolchain.py` `cmake_build` keeps this
  folder's `program("cmake", env)` (same fix as the PR's `_resolve_command`, and what `configure` / build.py's
  launcher use), while the PR's `_resolve_command` in `run_with_progress` and its clang-cl fallback came in too; this
  file kept both sides' sections.
- **Added**: `tools/texture_check.py --port` (default 47664, the PR's), so its game check can run beside other rigs.
- **The pack** is in `build/textures/SLUS-21590/replacements/` beside `build/vcs.exe`, where the PR's discovery finds
  it; `build/` is ignored, so it never reaches git or a release. The option stays off by default (F2 > Graphics >
  Texture replacements, then restart). Checks and the low-resolution digit caveat: TEXTURE_PACKS.md, Checks.

## 2026-10-31 - Mods as DLLs (.asi) and the VCS-mods repository (the user's request)

The user asked to separate each mod, to put them in a repository "VCS mods", and whether mods could ship as ASIs. They
can: vcs.exe now loads `build\scripts\*.asi` (and `*.asi` beside it) through a C API (docs/MODDING.md), and the camera /
aim mods left the exe for `CameraAim.asi` in spartaque12/VCS-mods. Phase 1; the rest is listed in MODDING.md "Next".
- **A C ABI, not C++**: a versioned table of function pointers (`src/modapi/vcs_mod_api.h`), strings and C callbacks
  with a user pointer; std::function, std::string and the settings / control types stay on each side (the mod's
  `mod.h` adapts them back to the style the code was written in). A mod built once keeps working with later exes of
  the same API version; a mod for another version is refused with a log line, never half-loaded.
- **The guest context through offsets**: the API hands over where the GPRs, pc and FPU registers are in the runtime's
  R5900Context instead of the runtime headers, so a mod needs no part of the port's source to build (only the API
  header and Dear ImGui) and survives runtime changes that move other fields.
- **Same compiler, same Dear ImGui**: hooks share the guest calling convention (clang's preserve_none), so mods are built
  with clang-cl / clang; the crosshair draws into the exe's ImGui context with the exe's allocator, so the mod builds
  the same ImGui (vendored in VCS-mods) and checks the version and structure sizes the API reports (no crosshair
  otherwise, the rest works).
- **Two hook phases**: the camera mod's hooks and the ragdolls' share three game functions, and their order matters
  (game-internals.md 12o): VcsModInstall runs where first person was installed (after the free camera, before the
  ragdolls), VcsModInstallLate where free aim was (after them). The behaviour is as when built in.
- **The exe keeps the coupling points, not the mod**: the hotkey row and the Back + R3 chord, the mouse / right-stick
  look and the background draw list are API services (`add_hotkey`, `set_look_handler`, `add_draw_callback`), so the
  key row, the chord, the look and the crosshair are gone with the DLL and come back with it - nothing in the exe
  names first person any more. Settings rows register where the built-in ones did (the Game page after "Window"), with
  the same keys, so the player's vcs.ini carries over; while the mod is absent its lines stay in vcs.ini untouched.
- **Without any DLL the game is v0.0.1 plus the mods still built in** (ragdolls, Project2DFX, the streamed-file
  override): checked in hidden runs (MODDING.md, game-internals.md 12o). `VCS_MODS=0` loads none.
- **Not moved yet**: Jolt and the streamed-file override / weapon tools (other work in progress on them) and
  Project2DFX (its guest tail-call chains need `register_function` in the API).

Later the same day, at the user's request: **Project2DFX left the exe too** (`Project2DFX.asi`, VCS-mods
`plugins/Project2DFX`). The API grew without a version change - `register_function` / `has_function` appended (its
guest tail-call chains return to a continuation of its own, 0x27C41C) and an optional export
`VcsModRegisterSettings(api, slot)` called at named places of the settings registration, so its rows stay where they
were (slot "graphics": the end of the Graphics page; its flight ceiling at the end of the Game page). Its bit-exact
projection uses the runtime's EE float helpers: a copy of them goes with the mod (`ps2_float.h`) and the mods are built
with the exe's float flags (`-ffp-contract=off`, AVX2). "Alpha dual pass" stays in the exe: it is a renderer setting,
not part of the mod. The light table stays where it was (`p2dfx\lights.bin` beside vcs.exe). Checked in hidden runs on a
privately linked exe (port 47690): at 23:00 4,423 lights loaded, 823 drawn, 41 more stars, 15 distant vehicles, the
rows in place; without the DLL the rows and the `p2dfx` command are gone and the game runs.

## 2026-10-31 - RenderHook-style graphics as RenderHook.asi; ambient occlusion first (the user's request)

The user asked whether GTA SA's gtaRenderHook (which they have contributed to) could be ported. Not as code (it hooks
SA's RenderWare D3D9 pipeline); its features are rebuilt on this renderer - the plan, with what fits and what does not,
is docs/RENDERHOOK_PLAN.md. The user then asked for the result to be an `.asi` mod.
- **A mod, with render hooks in the API**: the effects live in `RenderHook.asi` (VCS-mods `plugins/RenderHook`); vcs.exe
  gains a generic way for a mod to draw at a point of the frame (MODDING.md "Rendering"), appended to API 1. The mod
  never sees D3D11 or Vulkan: the RHI behind opaque handles, shaders as bytecode for the device's backend (DXBC and
  SPIR-V built from one HLSL in VCS-mods' CMake), so one mod works on both backends as the port's own passes do.
- **Full-screen passes only, for now**: textures, constants, pipelines from vertex-ID quads, a few blend presets. Enough
  for screen-space effects (AO, colour grading, a sky); shadow maps will need more (replaying the frame's native draws
  into a mod's target) - added with that milestone, not guessed now.
- **The point: after the whole 3D scene, before the post effects.** VCS draws peds and vehicles after the reflection map
  (later than game-internals.md 6g said), so the hook runs at the first post-effect read of the picture, the motion blur's
  blend or the Z clear before the HUD; particles drawn before it are darkened where the surface behind them is occluded,
  accepted (earlier would leave peds and vehicles without AO). The bloom then reads the occluded picture, as RenderHook's
  bloom reads the lit one.
- **The camera from the game's own draws, not from RAM**: the frames the renderer executes are up to three behind the
  game thread, so reading the game's camera there would mismatch; each native draw's window matrix gives the Z mapping
  exactly and the lens by the orthogonality of the model axes' images (the world's packets are scaled per axis, so the
  similarity shortcut was wrong at most spots). 24 candidates a frame, the one two agree on, else the last agreed lens.
- **Off means off**: the mod adds its hook the first time the option is switched on; until then the Z buffer is not made
  sampleable and the frame is untouched. Defaults: Off; three strengths (Subtle / Normal / Strong) and a radius.
- **No temporal filter**: the 4x4 rotation pattern and a 4x4 depth-aware blur remove the noise in one frame, so the AO
  never trails or ghosts at the game's frame rates; GTAO's quality at 2 slices x 4 steps x 2 sides per pixel.
- **DLAA groundwork in the renderer, DLAA in the mod** (later the same day): jitter is a renderer feature (only it can
  move every draw of the picture, after the PS2's vertex snapping); motion vectors are not drawn by the renderer but given
  as the camera's reprojection, from the frame's own static meshes (M_prev M_cur^-1, agreed by several) - no game-thread
  data has to travel with the frames, which run up to three behind it. Object vectors next, NGX last.
- **DLAA in the game's process, the SDK not shipped** (step 3): vcs.exe is 64-bit, so NGX runs in-process (RHDLAA for SA
  needed a 64-bit helper); the mod gets the native D3D11 objects through `render_native` rather than the API wrapping NGX,
  so vcs.exe stays free of vendor SDKs. The DLSS SDK (nvsdk_ngx_s.lib, nvngx_dlss.dll) is NVIDIA's binary: VCS-mods
  builds DLAA only with `-DVCS_NGX_DIR`, and the DLL goes beside RenderHook.asi. The NGX build uses the static CRT, as
  the SDK's lib. D3D11 first; Vulkan later.
- **Shadow maps drawn by the renderer, fitted by the mod** (2026-11-01, sun shadows): only the renderer has the frame's
  draws (meshes, skinned vertices, window matrices), so it draws the casters when asked (`render_shadow_map`), inside the
  hook and with the caller's matrices - no frame of lag and no light model in vcs.exe; the mod owns the sun, cascades,
  filtering and look. View space is the common space: each draw's window matrix is taken back through the lens, and the
  camera's world rotation comes from the world's own draws, so nothing of the game's camera has to be read from memory.
  Casters are what the game drew (no off-screen ones) for now: drawing the world for the light is a project of its own.
- **Tested from a privately linked exe** (`build\rh_exe`: the game's objects built by ninja, the link run with its own
  /out) because the user was playing from `build\vcs.exe`; the normal build relinks build\vcs.exe as usual.

## 2026-10-31 - "Not smooth when facing the sun": no code change, a frame-pacing finding

Measured instead of guessed (game-internals.md 6l, last row): the sun, its glow sprites, bloom and trails cost 0.2-0.5 ms
GPU in any direction and nothing on the EE; there is no synchronous GPU readback; the first-person look advances evenly
with each frame's real time. The user's own video shows the game's counter at 116-119 fps (cap 120) while turning toward
the sun over palms and buildings, 120 elsewhere: the scenery's load, not the sun, pushes frames just past the 8.3 ms
slot, and in a window on a 240 Hz monitor (vsync "Off, allow tearing", no VRR in a window) each miss holds a frame for
three refreshes. Nothing in the renderer or CameraAim is wrong, so nothing was changed there; the remedy is settings:
fullscreen with G-Sync / FreeSync (VRR absorbs a few fps), or a cap with headroom that divides the refresh (80 at 240 Hz),
or vertical sync On with a cap of 120 and MSAA 2x for headroom. Smoothing the look over host frames was not done: game
and host frames are one-to-one at these settings, so it would only add delay.

## 2026-10-31 - The first-person viewmodel: the ped's own arms posed by IK, not SA's animations (the user's request)

The user asked for UltimateFP SA's viewmodel ("same viewmodel based on gta sa anims maybe?"). Converting SA's IFPs
(tools/anim_convert.py) was weighed and not used: an anim block replaces the third-person anims too, VCS has no layer
to play a first-person anim over the body, and SA's own fire anims only point the gun with SA's aiming IK (12i). What
UltimateFP shows is SA's ped with its arms held up; here the arms are posed in the bone hook CameraAim already has
(the matrices built for the draw, 12c): the right hand at a fixed place of the view per kind of gun with the barrel on
the crosshair, the left hand on a fore-grip point per weapon, both shoulders moved under the eyes and two-bone IK for
each arm - a rigid move of the arm put the shoulder in front of the lens, and VCS's hip holds leave the left hand
0.47 m out on a rifle with the palm open (the user: "the left hand floats above the gun ... VCS's own animation").
Recoil, sway and bob are made in code. The grip points are per weapon type constants measured by eye on the converted
Immersive Weapons Pack models, not read from the model (a model-derived point would need the clump's geometry; a
table is enough for the 13 guns). Third person keeps VCS's anims untouched (the support hand IK there would fight
every hip / fire anim). Rows: Game > First person (Arms and gun in view, gun position right / ahead / up, gun sway).
In the same change first person keeps the view while getting in and out of vehicles and moves the eyes ahead of the
collar when looking away from the body (running backwards) - both the user's reports (12t).

## 2026-11-01 - VR.asi milestone M0: OpenXR, head-tracked mono, panels (the user's request)

- **What the headset shows**: in first person on foot (CameraAim) the 3D picture without the HUD goes in as an OpenXR
  projection layer, the same image for both eyes, declared with the game camera's own field of view (from the frame's
  lens, `VcsRenderFrame` fx / fy / cx / cy) and the head pose it was rendered with; everything else (menus, F2 / F5,
  loading screens, cutscenes, third person, vehicles) goes on a world-locked "cinema" quad, the HUD on its own quad
  1.5 m ahead. Chosen over rendering at the headset's field of view because the game's FOV, Hor+ shape, render size and
  the culling (game-internals.md 5) stay as they are - nothing in the renderer or the game's camera maths changes for
  M0 - while the runtime still gets an exact description (pose + FOV) of the picture: it places it in the world and
  reprojects it to the newest head pose, so the world stays put despite the game's frame lag. The cost is black around
  the picture where the headset's FOV is wider: raise CameraAim's first-person field of view for more. Mono at
  infinity (no stereo) until M1.
- **Head and body**: the head's yaw / pitch / roll go to CameraAim through exports of CameraAim.asi
  (`CameraAimSetHeadLook`, `CameraAimHeadLookApplied`) rather than an exe API: the look is CameraAim's own state, and
  a mod-to-mod call needs nothing from vcs.exe. The mouse / stick still turn the body (CameraAim's yaw); the head adds
  to it and alone pitches and rolls the view.
- **Exe API** (appended to API 1 without a version bump): a present hook (`add_present_hook`, D3D11 device / context
  in `VcsPresentFrame`) right before the window's present - one place for xrEndFrame + xrWaitFrame + xrBeginFrame,
  which paces the host loop to the headset; `render_set_split_layers` (the picture before the HUD, the HUD over black
  and white); `present_window_copy` (the window with its menus, off-screen) for the cinema screen. The renderer change
  is `splitLayers` in `composeDisplay`, off unless a mod asks.
- **The loader**: the Khronos `openxr_loader.dll` (OpenXR-SDK release-1.1.65, Apache-2.0) built by VCS-mods' CMake
  and loaded at run time from VR.asi's folder: without it, a runtime, a headset or D3D11, VR.asi logs one line and
  stays inert (verified). `VCS_VR_RUNTIME=<runtime.dll>` loads a runtime directly (tests: the loader ignores
  `XR_RUNTIME_JSON` in an elevated process). No OpenXR runtime is installed on the dev machine and installing one was
  ruled out, so VR.asi was checked against `xr_test_runtime.dll` (VCS-mods `plugins/VR/test`, never installed): a
  minimal D3D11 runtime that simulates a head and composites what each eye would see into PNGs.
- **Defaults**: off (Graphics > VR > VR); recentre F7 / Back + L3; cinema 4 m ahead, 5 m wide; HUD 1.5 m.

## 2026-11-01 - Jolt Physics as a DLL mod: JoltPhysics.asi (the user's request)

- **What moved**: the ragdolls and everything on them (bike falls, hit reactions, catch falls / blind fire, gore,
  pickups on the ground), foot IK and jiggle physics - `src/game/vcs_jolt.*`, `vcs_footik.*`, `vcs_jiggle.*` and
  `src/physics` - into VCS-mods `plugins/JoltPhysics` (spartaque12/VCS-mods), with its own vendored copy of Jolt 5.6.0.
  vcs.exe no longer builds `src/physics` or links Jolt; `third_party/JoltPhysics` stays in the tree, unused.
- **Unchanged behaviour**: same settings keys and rows (Game > Physics), same control commands (`jolt`, `footik`,
  `jiggle`: the tools' checks run as before against an exe with the DLL in `scripts\`), same hook order - the mod's
  VcsModInstall runs where the built-in install was (right after the mods' Install, CameraAim.asi first by name), free
  aim's VcsModInstallLate still wraps its line of sight.
- **An older vcs.exe** (ragdolls built in): the DLL notices in VcsModInstallLate that the exe's death hook wrapped its
  own and makes all its hooks pass through (one log line) - never two sets of ragdolls.

## 2026-11-01 - The VR test package for a friend has no vcs.exe

Asked for a package with vcs.exe for a friend with a headset. The upstream v0.0.1 release ships no vcs.exe (the
launcher, Python, the libraries; the player's PC recompiles the game from their own disc: 2026-10-21, docs/LAUNCHER.md
"A release"), and vcs.exe contains the recompiled game code. So `dist\VCS-VR-friend` holds the mods (VR.asi,
openxr_loader.dll, CameraAim / Project2DFX / RenderHook .asi), the fork's vcs-mods source as a zip and
README_VR.txt: the friend overlays the source on their v0.0.1 folder, builds with the launcher and copies the scripts.
