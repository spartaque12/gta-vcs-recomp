# Game internals - GTA: Vice City Stories (PS2, SLUS-21590)

Everything known about how the game works inside, gathered while recompiling it. Addresses are EE
RAM addresses in SLUS_215.90 (identical to ELF virtual addresses; see [DISC.md](DISC.md)). Names in
`CamelCase::Like()` are our labels, modelled on the GTA III-era naming (re3 / reVC) where the code is
clearly the same lineage; they are guesses until marked **confirmed**.

Each fact says how it was established, so it can be re-checked. Tools: `tools/eedis.py` (EE
disassembly with names from `game/vcs/functions.csv`), `tools/vudis.py` (VU microcode), Ghidra
(`ghidra/`), the runtime's traces (`PS2X_*`, `VCS_*` switches in PROGRESS.md), the control channel
(`tools/gamectl.py`) and frame dumps (`PS2X_HW_DUMP`). Listings derived from game code go to
`build/analysis/` and are never committed.

**When you learn something about the game, add it here in the same change.**

---

## 1. Background (outside sources)

- Rockstar Leeds engine, shared with the PSP original (2006). The PS2 port (2007) reuses PSP-side
  data formats (`.PSP` frontend files).
- Descends from the GTA III / VC codebase but renders through Leeds' own "RenderWare Stories"-style
  layer (RSL), not stock RenderWare.
- Runs at 30 fps with a frame limiter. GTA III-era code scales movement by `CTimer::ms_fTimeStep`
  (1.0 = 1/50 s), so 60 fps mostly works, but earlier games had known 60 fps bugs (physics, some
  animations, script timers, water cannon). The PSP recomp (OverkillLabs3) and ThirteenAG's PPSSPP
  fix both patch these for 60 fps - references for milestone 4 of NATIVE_PORT_ROADMAP.md.

## 2. Code map

- 9,550 functions (Ghidra 12.1.4 + EE extension) plus 833 indirectly referenced ones Ghidra missed
  (`tools/find_missing_functions.py`). 8,521 below `0x443000` are game code; 1,029 from `0x443000`
  up are Sony SDK / libc / libgcc.
- SDK libraries, identified by ps2_analyzer's SCE symbol DB (`game/vcs/vcs.toml`):
  - `0x4431F8..` libgcc (`__divdi3`, `__muldi3`, soft-double `dpadd`...)
  - `0x447670..` libgraph (`sceGsResetGraph`, `sceGsSwapDBuff`, `sceGsSyncV`)
  - `0x448688..` libdma (`sceDmaSend`...)
  - `0x448D98..` libpad (`scePadRead`... - libpad, not libpad2)
  - `0x44E5F8..` libcdvd incl. **streaming** `sceCdStInit/StStart/StRead/StStop`
  - `0x44F668..` libmc (`sceMcOpen/Read/Write/GetDir`...; stubs: `0x450120` = `sceMcGetDir`,
    `0x44fe80` = `sceMcSync`)
  - `0x452320..` libmpeg (`sceMpegCreate`, `sceMpegDemuxPssRing`) + libipu
  - `0x45C1D8..` libsdr (`sceSdRemoteInit`, `sceSdRemote`) - audio goes over SIF RPC to SDRDRV.IRX
  - `0x467xxx` kernel syscall wrappers, `0x469E00..` libsif / RPC, `0x46B980..` libfileio
  - `0x46EA98..` Deci2 (dev-kit debug channel; dead on retail)
- `fiprintf` at `0x1A9EF0` lives inside game code (newlib linked early). `FUN_0045f378` = `sprintf`
  (seen building memory card paths).
- Largest game functions (state machines / script interpreter candidates): `0x141FE8` (41.7 KB),
  `0x13A0A0` (25 KB), `0x337208` (25 KB), `0x33F010` (20 KB).
- The analyzer found only 2 jump tables; the recompiler reports ~1,150 unresolved `jr` sites (switch
  tables) and falls back to dispatch through the function table. The memory card state machine
  `FUN_002788e0` is one (`jr` through the table at `0x4B0400`, indexed by the state at `0x487730`).

- Small hot leaf functions seen in game-thread profiles (2026-10-25): **FUN_003F9E50** = 4x4 identity matrix at $a0
  (zeroes 16 words in a loop, then 1.0 at +0, +0x14, +0x28, +0x3C; native since 2026-10-25); **FUN_00408058** = rand()
  (Park-Miller: seed at 0x48A5B8, q 127773, a 16807, r 2836; `div` then two `mult`, + 0x7FFFFFFF when <= 0);
  **FUN_002560D8** = the script VM's command dispatch (reads the 16-bit opcode at the script's ip, bit 15 = negate the
  result, handler table at 0x4BEAF0, 8 bytes per entry).

## 3. Boot

- Entry `0x001DD6A0` is standard crt0: zero GPRs / FPRs, clear .bss (`0x4CD100..0x74DF54`), set
  gp / sp, SDK init, `main`.
- `sceSifInitRpc`, then IOP modules from the disc in this order: `SIO2MAN, LIBSD, SDRDRV, CDVDSTM,
  CDSTREAM, PADMAN, SIO2MAN (again), MCMAN, MCSERV`. All nine run as real IRX code on the emulated IOP
  (SDRDRV prints "SDR driver version 4.0.1"); `SDRDRV`, `CDVDSTM`, `MCMAN`, `MCSERV` stay resident.
- `_lf_bind` (`0x46CD10`) polls for the ROM LOADFILE server - absent in the recomp, stubbed.
- **Disc indexing**: `FUN_002209F0(path)` walks `cdrom0:` recursively with
  `sceDopen/sceDread/sceDclose`, and for each file (`st_mode & 0xF000 == 0x2000`) calls the
  `sceCdSearchFile`-like `0x44E480` and appends (name ptr, lsn, size) to a table at `0x5038A8`
  (count at `0x486E8C`, string pool cursor at `0x486E88`). Every file is resolved to an LSN up
  front; reads are by sector afterwards.
- **Movies** (milestone 5, 2026-10-24): `FUN_0021CA70` (from `main`) initialises the player (FUN_0040D7D8), calls
  **CMoviePlayer::Play(path, 0, n) at 0x40D8B8** for `cdrom0:\MOVIES\STINGS.PSS;1` (0x4AC5F8, the Rockstar logos,
  n = 1,000,000) and `cdrom0:\MOVIES\INTRO.PSS;1` (0x4AC618, n = 10), shuts it down (FUN_0040D898) and clears
  the scratchpad. Play -> FUN_0040D930 (libmpeg + IPU, sound through the IOP) compares a frame count with n before
  it reads the pad: the logos can't be skipped, the intro can after 10 frames. `INTROP` / `STINGSP` are the PAL
  versions (unused by the USA game).
- **PSS layout** (read from the files): an MPEG-2 program stream; video in stream 0xE0 (MPEG-2, 512x448, 29.97 fps,
  shown across a 4:3 TV; STINGS 10.6 s, INTRO 84 s); sound in private stream 1 (0xBD), sub-stream 0xFF, each
  packet's payload behind a 4-byte header (`ff a0 00 00`) and split at odd byte counts. The joined bytes are a Sony
  "SShd" header (u32 size 0x18, type 1 = **16-bit little-endian PCM**, 48000 Hz, 2 channels, interleave 512 bytes),
  "SSbd" + u32 data size, then blocks of 256 left samples, then 256 right (byte order and interleave told apart by
  how smooth the samples are). First PTS: sound 0.043 s, video 0.110 s. FFmpeg's demuxer finds the video only.
- **Played natively** (`src/game/vcs_movie.cpp`): Play is replaced; the file read from the disc, demuxed, the video
  decoded with FFmpeg and shown by the presenter at 4:3 (`ps2ShowMovieFrame`), the sound mixed into the audio
  output (`ps2AudioMoviePush`), whose played-sample count is the clock (the host clock without audio output, and
  after the sound ends - the last pictures are due 30 ms after it). Start / Cross skip once the game's count
  allows. Display > Skip intro movies skips both. The game thread waits in Play, as in the game's player.

## 4. Frame and timing

- The game updates and draws at 30 fps on the 60 Hz VBlank: in a frame dump the 3D is in every
  other VBlank's GS frame; the in-between VBlanks carry no draws (found when `PS2X_HW_DUMP` kept
  landing on empty frames, 2026-10-22; the dump now waits for a frame with draws).
- **Main loop** (2026-10-23, from the guest-stack return addresses of the 2D work and the callers in the generated
  code): `entry` (0x1dd6a0) -> FUN_0021c928 -> FUN_0021c5e8 (start-up: init calls, then the loop) -> per frame
  FUN_0021ed88: CTimer / game updates (FUN_002f4858 / FUN_002f4960 / FUN_0021e720 ...), FUN_0021e950 (render: 3D,
  then the 2D pass FUN_0021f348, the frontend FUN_0021f7d8), then the frame's end.
- **VBlank**: FUN_00370480 creates a semaphore (id at 0x488E9C) and installs **FUN_00370300** as the INTC handler for
  VBlank start (cause 2) and end (3), through FUN_002f46f8 (AddIntcHandler + EnableIntc with a use count). On
  VBlank start it sets a flag (0x6F4268 = 1), counts VBlanks (0x488EA0) and calls up to 8 callbacks registered with
  FUN_003703f0(fn, arg) (table 0x6F4248, args 0x7490B0); on VBlank end it clears the flag. FUN_003703a8 returns the
  count, **FUN_003703b8 = WaitVBlank** (spins on the flag, clears it).
- **Frame limiter**: the graphics object at 0x520F90 counts VBlanks at +0x4 (callback FUN_00317aa8 ->
  FUN_00317ac8: +1, registered by FUN_00317788). At the frame's end **FUN_003179a0** (from FUN_0018f450) waits for
  the previous frame's work, kicks the next display list (FUN_00272268), then `do { WaitVBlank(); } while (vblanks
  < 2);` (0x317a48..0x317a58) and resets the count: **30 fps**, two VBlanks a frame.
- **CTimer** (read from the generated code of Update and Initialise, 2026-10-23; names as in reVC, whose
  CTimer::Update has the same shape): FUN_002f4858 = Initialise (registers VBlank callback 0x2f4840, which only
  counts VBlanks at 0x488290; step = 1.0, time scale 0x4CD168 = 1.0, pauses / times / frame counter = 0).
  **FUN_002f4960 = Update**:
  - Ticks: **FUN_00451C00(timer id 0x488288)** = a kernel timer's 64-bit count at the bus clock (147.456 MHz),
    only ever called from here; previous count at 0x488298, this frame's ticks at 0x4CD564. FUN_002f47c0 creates
    the timer when missing (called twice per Update); FUN_0030c984 = `cvt.w.s` (float -> int, truncating).
  - Clocks: 0x488280 (ms, also while paused) += ticks / 147456; `m_snPreviousTimeInMilliseconds` 0x4CD16C;
    **`m_snTimeInMilliseconds` 0x4CD104** and 0x4CD448 += (int)(ticks * scale / 147456) - truncated per frame.
  - Paused (`m_UserPause` 0x4CD2AC or `m_CodePause` 0x4CD11C): the step goes to 0x4CD174 (pause-mode step) and the
    frame's ticks are zeroed, so the game clocks stand still.
  - **`ms_fTimeStep` 0x4CD110** = ticks * scale * 50 / 147456000 (1.0 = 1/50 s; 0x34B60B61 = 3.3908e-7), then
    **at least 0.5** (1/100 s; VC had 0.01) unless paused or a chase recording (0x481CF8) is on;
    `ms_fTimeStepNonClipped` 0x4CD300 = that; then unless replaying (0x4CD444 == 2) **at most 3.333** (1/15 s) and
    the ms clock at most +60 per frame. Chase recording mode (0x4CD138 == 1): step 1.0, clock +16 ms.
  - **`m_FrameCounter` 0x4CD124** += 1.
  - (The earlier note "time step at 0x4CD174" was wrong: that is the pause-mode step.)
- **Frame-rate dependence found in CTimer itself**: the ms clock adds each frame's milliseconds truncated, losing up to
  1 ms a frame - game time (script waits, timers, the in-game clock) ran 1.5% slow at 30 fps and ~4% at 80 fps
  (measured: game clock vs wall clock, `m_snTimeInMilliseconds`). And the 0.5 minimum step makes the game run fast
  above 100 fps. Independent timing feeds whole milliseconds of ticks and lifts the minimum (below).
- **Display flip FUN_003706c8** (right after the limiter's wait): toggles the buffer index (+0x44 of the struct at
  *0x488E88), reads CSR, writes PMODE, SMODE2, DISPLAY1/2, DISPFB1/2. The limiter's first loop waits VBlanks until
  the previous display list is done (+0xC of 0x520F90 back to -1; set by the DMA end); with our DMA completing at
  once it does not loop. In gameplay the limiter is the only caller of WaitVBlank (counted by return address).
- **Independent timing** (`src/game/vcs_framerate.cpp`, Display > Game timing): FUN_00451C00 returns the host clock
  in whole milliseconds of bus ticks (`VCS_TIMESTEP=<fps>`: exactly 1/N s per frame, unpaced); the second
  FUN_002f47c0 call (ra 0x2F4C04) puts back a step the 0.5 minimum raised (floor 0.05); the limiter's WaitVBlank
  (ra 0x317A50) presents the frame, paces to the cap on the host clock, brings the EE clock up to real time on the
  VBlank chain (`EeScheduler::syncToRealTime`) and sets the VBlank count to 2. Measured: game clock = wall clock
  (x1.001) at 30 and 144; steps 1.65-1.70 at 30, 0.55-0.60 at ~85 fps.
- **Steps below 0.5 break the game** (frame-rate audit `tools/framerate_audit.py`, 2026-10-24): with the minimum lifted
  the player runs at 4.7 m/s up to 1/100 s steps, then 1.4 m/s at 1/110, 1.0 at 1/120, 0.5 at 1/240 (per-frame
  movement shrinks with the step squared); with the game's own 0.5 floor at 1/110 he runs 5.15 m/s (= 4.7 x 0.5 /
  0.4545, the step just too long). Code was written for steps >= 0.5 (VC's minimum was 0.01; VCS raised it) - not
  found yet. Independent timing therefore kept the 0.5 floor and capped at 100 fps until 2026-10-25 (below).
- **Found (2026-10-25): FUN_001f1d38 (ped animation movement)** turns the frame's animation root displacement into the
  ped's target velocity at +0x794 / +0x798 (FUN_001f25f0 then eases the move speed +0x140 towards it):
  `if (ms_fTimeStep < 0.5) v *= 0.5; else v *= 1.0 / ms_fTimeStep;` (0x1f2154 - 0x1f21c0, the 0.5 loaded once by
  `lui $at, 0x3F00` at 0x1f2158). The `< 0.5` branch never runs on the PS2 and is wrong - `* 0.5` where `/ step` is
  2 or more - so below the floor the ped got ~a quarter of its velocity. At 1/110 s (`VCS_TIMESTEP` feeds 9 / 10 ms
  frames, steps 0.45 / 0.5) the speed alternated 0.021 / 0.083 units - found with a write watch on the player's move
  speed (`VCS_WATCH`, writers by return address), then on +0x794. Patched (game/vcs/overrides.toml: the constant
  becomes 0.001, so every real step takes the `/ step` path); steps >= 0.5 are unchanged. Audit afterwards: run /
  drive / fall at 1/144 - 1/240 as at 1/30 - 1/100, sprint -5% / -11% at 1/200 / 1/240. Independent timing's ceiling
  is now 240 fps (step floor 50/240, `vcs_framerate.cpp` kMaxFps).
- **Found (2026-10-25): FUN_0031ae38 = CCutsceneObject::ProcessControl** (as in reVC) has the same dead branch:
  `if (ms_fTimeStep < 0.5) speed *= 2 (add.s x, x, x); else speed *= 1 / ms_fTimeStep;` (0x31b19c - 0x31b234, the
  0.5 from `lui $at, 0x3F00` at 0x31b19c, used only for the compare), then the object's offset +0x210 += step * speed
  and its position = +0x200 + +0x210. Below the floor each frame kept only 2 * step of the animation's root movement,
  so cutscene characters drifted off their animation: at 144 fps (step 0.35) Vic floated over the trailer and Marty
  sat sunk in his truck in MAR_A1 "Shakedown"'s opening cutscene (user report). Found by checking that the cutscene was
  right with original timing and with `VCS_MIN_STEP=0.5` at 144 fps, then scanning the generated code for
  `lwc1 -0x2EF0(...)` (the step) next to a `lui 0x3F00` and a compare. Patched like the ped one
  (game/vcs/overrides.toml: 0.001). The scan's other hits are not this pattern: FUN_001f4bf0 / FUN_0033bb2c use
  `max(step, 0.5)` (below), FUN_00348128 compares `step * 0.5` with 0.05, FUN_002f4960 is CTimer itself.
- **Audit results in the supported range** (`tools/framerate_audit.py`, steps 1/15 .. 1/100, per simulated second,
  2026-10-24): game clock exact (1/15 gets 60 ms a frame: the +60 ms cap, below ~17 fps the game slows, as on the
  PS2); car acceleration the same within 3% (speed at 2 / 3 / 4 s, distance in 4 s); running / sprinting the same
  from 1/30 up (1/15 runs ~10% faster); **falling and jumping depend on the frame rate**: 15 m of fall takes 0.90 /
  1.11 / 1.19 / 1.20 s at 1/15 / 30 / 60 / 100, a jump rises 0.73 / 0.81 / 0.86 / 0.88 m. **This is the
  engine's integration, not a per-frame bug**: the jump heights follow explicit Euler's error exactly - a peak
  v0^2/2g - v0*dt/2 with a continuous peak of 0.893 m predicts 0.726 / 0.81 / 0.85 / 0.868 (measured 0.725 / 0.814 /
  0.864 / 0.884) - and the ped's vertical speed agrees within 1-3% between 1/30 and 1/60 through a whole fall,
  quadratic air drag included (traced at ped+0x148). Shorter frames are closer to the continuous motion, as on the
  PC GTAs; matching 1/30 exactly would need a correction term in the integration (not done: <= 6%).
- **A `max(step, 0.5)` in the bike's lean**: FUN_00337208 is **CBike::ProcessControl** (not ped code, as first noted:
  it calls ProcessWheel FUN_003E7618, the springs FUN_0034E0E8 / FUN_0034E1D8 / FUN_0034E348, and keeps the bike
  fields of reVC's CBike - lean +0x680 / +0x684, wheel ratios +0x540..). At 0x33bb2c it divides the frame's sideways
  change of speed by `max(ms_fTimeStep, 0.5) * 0.008` (GRAVITY; VC: max(step, 0.01)) for the lean angle (+0x684,
  radians; the physics matrix stays upright, the lean is drawn and steers the wheels). Above 100 fps the bike leant
  less: a gentle turn peaked at 22 degrees at 144 fps against 30 at 30 (yaw rate the same; hard turns hit the lean
  limit, ~42 degrees, at both). **Patched 2026-10-28** like the ped one (0.5 -> 0.001, `lui $at` at 0x33BB10; the
  0.5 is only the max.s operand).
- **The same `max(step, 0.5)` elsewhere** (scan for `lwc1 -0x2EF0` then max.s / c.lt.s with a `lui 0x3F00` nearby,
  2026-10-28). **Patched 2026-10-28** (0.5 -> 0.001 as the others, game/vcs/overrides.toml; above 100 fps only):
  - FUN_00138b68 (cars in water; the 0.5 loaded on two paths, 0x138c48 / 0x138c6c, max.s at 0x138c88) and FUN_00336cb8
    (bikes in water, 0x336d60 / 0x336d78) divide the buoyancy impulse's z by `mass * max(step, 0.5) * GRAVITY` for the
    share under water, which sets the water's drag (`pow(1 - share * 0.05, step)`) and the sinking thresholds. Measured
    (a vehicle dropped from 8 m into the sea at (-675, -75), water at z ~5.9, with 15 m/s forwards): a Sentinel kept
    1.6 m/s one second into the water at 144 fps, 0.6 at 30; a PCJ-600 sank to the bottom (z 1.2 on average over 3-8 s)
    where it settles at 3.2. After: 0.75 / 0.69 / 0.76 m/s and depth 2.75 / 2.9 / 2.95 m at 1/30 / 60 / 144
    (`framerate_audit.py` carwater, bikewater).
  - FUN_0019fda0 (CBoat::ProcessControl, 0x1a2468 / 0x1a2480) multiplies one rudder turn force by `max(step, 0.5)` where
    the others use the step. A Speeder steered for 1.5 s: turn rate the same (42 degrees/s), speed after the turn 19.7
    m/s at 144 fps against 21.4 at 30, 21.1 after the patch - within the waves' noise, patched on the code.
  - Left: FUN_001f4bf0 (CPed::ProcessControl, 0x1f7378 / 0x1f7474 / 0x1f7bac).
- **The buoyancy's lift cut-off is per frame on paper, but no effect measured**: FUN_00369950 (from FUN_00369450, the
  buoyancy for cars, bikes and boats) makes the lift impulse `share * buoyancy * step` and drops it to
  `max(lift - momentum, 0)` when the vehicle rises with more than 4 times that impulse (`lui $at, 0x4080` at
  0x369994) - 4 frames of lift. Patched to scale the 4 with the step and measured: a Sentinel floats at z 6.02 on
  average at 30 fps and 5.96 at 144 with or without it (bobbing +-0.3 m). Not kept.
- **Vehicle physics that acts once a frame without the step** (found 2026-10-28 from a user report: a car running
  over a body jumped, a stolen bike flipped forward, both at high frame rates only). Fixed in
  `src/game/vcs_physics_timing.cpp` (scaled by step / (50/30) when the frame is shorter than the PS2's;
  `VCS_PHYSICS_TIMESTEP=0` off):
  - **FUN_003F34F0, the bump of a body under a wheel**: called after each wheel's ProcessWheel, for cars from
    FUN_00152E18 (a pair of wheels, from CAutomobile::ProcessControl FUN_0013A0A0 at 0x13e478 / 0x13e4cc) and for bikes
    from CBike::ProcessControl. If the vehicle has a driver (+0x384), the player drives (FUN_0020C310), its type
    (+0x354; 0 cars, 6 / 8 bikes) isn't 1 / 2, up.z >= 0.1 and it moves (|v|^2 >= 0.0001), it walks the driver's
    nearby peds (driver +0x6F8, count +0x77A): one that is dead (state +0x8C4 == 0x3A) or knocked down (FUN_002192E0)
    within 1 m horizontally of the wheel's contact point gets the vehicle `ApplyTurnForce((0, 0, mass * 0.01, * 1.5
    for cars), contact point)` - per frame. Measured (`tools/framerate_audit.py` scenarios runover / bikebody; a dead
    ped 14 m ahead of a Sentinel at full throttle): the car's front wheels on the body pitched it at 0.042 rad / 0.02 s
    at 30 fps but 0.072 at 144; its rear bumper then hit the ground (CPhysical::ProcessCollisionSectorList FUN_0034FD60
    -> ApplyCollisionAlt FUN_0034D670 against the road) and threw the car up at 3.3 m/s (1.4 at 30 fps; rise 0.55 m
    against 0.17). A PCJ-600 rolling slowly past a body at its rear wheel ended on its nose (forward vector z -0.995)
    at 144 fps; at 30 it pitches to -0.29 and settles. Found with the rig's `trace` (per-frame vehicle state) and write
    watches on the car's move speed z (+0x148) and turn speed x (+0x70), summing each writer's changes (return address
    and the callers on the stack): at 144 fps most of the extra pitch came from ApplyTurnForce called at 0x3F36CC.
  - **ProcessWheel's rolling resistance** (FUN_003E6C18 cars, FUN_003E7618 bikes; CVehicle::ProcessWheel, args f12
    thrust, f13 brake, f14 adhesion (multiplied by the step inside), a0 vehicle): with brake 0, thrust 0 and the gas
    pedal (+0x25C) under 0.01, the brake becomes 0.9 / handling mass (handling +0xBC; 0.09 under 500 kg, 0.18 for the
    RC Bandit (model 0xFC51), 0.54 / (mass + 200) for vehicle types 6 / 8, 0 for type 5; the bike version has 0.18
    under 500 kg) and clamps the wheel's forward correction - per frame, never times the step (reVC fixes the same line
    with `brake *= CTimer::GetTimeStepFix()` under FIX_BUGS). Coasting from 10 m/s a Sentinel slowed at 3.4 m/s^2 at
    30 fps and 16 at 144; a PCJ-600 at 2.4 and 11, which pitched it forward. Patched (game/vcs/overrides.toml): the
    four constants load from guest RAM 0x7FF00 / 04 / 08 / 0C (0.54, 0.09, 0.9, 0.18), which the ProcessWheel hooks
    fill before every call - unscaled at 30 fps and below, so the PS2's values bit for bit. **Guest RAM 0x7FF00..0x7FF0F
    is ours**: below the runtime's async callback stacks (0x80000..0x100000); a write watch on it through eight runs
    (run-overs and coasting at 30 / 60 / 144 fps) saw no game write.
  - **Audit** (`tools/framerate_audit.py --only coast,runover,bikebody,bikecoast,bikelean --steps 30,60,144`,
    2026-10-28; in brackets 144 fps with `VCS_PHYSICS_TIMESTEP=0`, the lean from the build before the patch):

    | | 1/30 | 1/60 | 1/144 |
    |---|---|---|---|
    | car coasting, m/s^2 | 3.44 | 3.45 | 3.45 (16.2) |
    | run-over: rise m / thrown up m/s / pitch rate | 0.13 / 1.37 / 0.042 | 0.10 / 0.97 / 0.043 | 0.09 / 0.70 / 0.041 (0.59 / 3.9 / 0.072) |
    | bike past a body: forward z at most / up z at the end | 0.53 / 1.0 | 0.39 / 1.0 | 0.31 / 1.0 (1.0 / 0.42: on its side) |
    | bike coasting, m/s^2 | 2.38 | 2.38 | 2.37 (11) |
    | bike lean per g of sideways acceleration | 0.56 | 0.60 | 0.64 (0.49) |

    The bumps are smaller at higher frame rates: a car's collision with a body or the road is sampled in finer steps
    (at 30 fps and 16 m/s a frame moves the car 0.55 m into it). The per-frame part is what made them grow.
  - **Still per frame** (read in ProcessWheel, not measured or fixed): a burst tyre's wobble - a random sideways amount
    added every frame when the wheel status (last argument) is 1.
- **Physics read for the audit**: ped -> its vehicle at ped+0x450 (also +0x480 / +0x484; found by scanning the ped for
  the address of the car it was warped into); **CPhysical move speed (x, y, z) at +0x140** (units per 1/50 s, x 50 =
  m/s; z found at +0x148 mid-fall, y at +0x144 in a car driving north); written through a vector setter
  FUN_00356288 / FUN_003562c0 (write watch on +0x148: callers FUN_001f93b0, 00232de8, 001f25f0 (peds),
  00348128 / 00348538 / 00348628); FUN_00348098 = ApplyMoveSpeed (position += move speed * step). Terminal fall
  speed ~1.0 units (50 m/s) after 3.5 s. A new car (`CREATE_CAR`) faces north; its matrix can be poked (right
  +0x00, forward +0x10, up +0x20, position +0x30).
- **Frame counter readers** (`m_FrameCounter` 0x4CD124; the generated code has constant addresses folded, so a text
  search of generated/ee lists them - 52 functions; the time step 0x4CD110 has 93, the ms clock 0x4CD104 198):
  - work spread over frames, `(entity seed (+0x48 >> 54) + frame) & mask` or `frame & mask` with masks 1-0xFF:
    FUN_0011c958, 00138b68, 00140b28, 00186aa8, 001effb0, 0020db30, 00203240, 00238bb0, 00243730, 0025bba8,
    00267928, 00268048, 002c3e48, 0033d5a0, 00378dd8, 00421320 ... - run more often per second at higher rates;
    harmless where the work itself scales by the step;
  - blinking, `frame & 8 / 4 / 2` toggles: FUN_0031e3f8, 0031fce8, 00321500 (& 8), 003209d0, 00320f28 (& 4) -
    right after CHud::Draw (0x31c628), reVC's CHud flashing (a flashed item on `& 8`, health under 10 on `& 4`);
    001419d0, 0033dca0, 003f29d8 (& 2), 002af6e0 (& 8) elsewhere. They flashed twice as fast at 60 fps. **Fixed**
    for the 2D pass (radar, HUD, text: FUN_0021f348): above 30 fps it runs on a counter whose low 6 bits advance
    30 times a game second (from the game clock), put back as CTimer::Update starts (`vcs_framerate.cpp`
    twoDPass / timerUpdate) - the value stays within 63 of the real counter for anything else reading it then.
    The four outside the 2D pass are not covered yet;
  - timestamps (stored, compared with frame - 1: "seen last frame"): FUN_00383028 .. 003868c0, 003ac9c8 - harmless.
- **Mission scripts that count per frame**: a meter changed by a fixed amount each `WAIT 0` pass (PHI_A2's heat bar,
  eleven more missions) moved with the frame rate - section 11f.
- **Emulated time and the VBlank chain** (found when independent timing first ran at 5 fps): VBlank events are chained
  in EE cycles (+1/60 s each) and each is also held to its host-clock moment. An EE clock moved past the chain makes
  every following VBlank due at once by cycles, and the EE is held at each until its real-time moment - the game
  crawls. Topping the clock up must therefore aim at the chain's real-time position, not at elapsed host time.
- **60 fps, original timing** (`src/game/vcs_framerate.cpp`): the VBlank-counting callback adds 2 instead of 1, so the limiter lets a
  frame through after one VBlank. Measured outside the barracks (2026-10-23, i7-7700K): 31-37 fps - a gameplay
  frame costs ~27 ms on the game thread (game code 19-24 ms, render submission ~8 ms), more than 1/60 s; the
  emulated VBlank keeps real-time pace only while the game thread keeps up (events need both the EE cycle and the
  host deadline). A steady 60 needs ~40% less game-thread time per frame (milestone 7).
- **What the game watches of the GS / VIF1** (counted by the render worker's fences, `PS2X_RENDER_THREAD_LOG=1`,
  2026-10-23): in gameplay the GS privileged CSR / SIGLBLID ~5 reads a frame (300/s at 60 fps); GIF and VIF1
  registers only a few times at boot; never VU1 memory or the VIF1 / GIF FIFOs. The work it hands over is ~3 items a
  frame: the frame's VIF1 display list (one chain, FUN_00272268 above), one or two GIF chains (texture uploads), then
  the VBlank. It never enables the VU1 D / T stop bits (FBRST). So the GS and VU1 can run behind the game thread
  as long as the CSR reads see the finished work (runtime/ps2_render_worker.h).

## 5. Camera, projection and widescreen

Found in the widescreen spike (SETTINGS_MENU_WIDESCREEN.md), by forcing the preference and logging
the globals each frame:

| What | Where | Notes |
|---|---|---|
| FOV global | `0x487484` (float, degrees) | written by `FUN_002653e0` (a `CDraw::SetFOV`); 45 in the frontend, 120 in the flyover, 70 in game |
| Aspect global | `0x487488` (float) | written only by `FUN_002653f0` (`CDraw::CalculateAspectRatio`) |
| Aspect choice | `FUN_002653f0` | widescreen preference on: 16/9, or 5/3 when `[0x6f4d14]` is set; off: 4/3, or 1.25 when set. `[0x6f4d14]` is 0 in the frontend and 1 in game (not a PAL flag) |
| Widescreen preference | `*(int *)(*(0x48F3D0) + 0x30)` | getter `FUN_002af658` (`lw v0, 0x30(a0)`); the object at `[0x48F3D0]` (prefs / menu manager) is created by `FUN_00470fa8` |
| View window | `FUN_001ab9e0(camera a0, raster rect a1, tan f12, aspect f13)` | x = tan(FOV/2), y = x / aspect, raster 640x448 (null rect), then `FUN_0018f2d8` = RwCameraSetViewWindow. Called at `0x21cdd4` with the aspect global, at `0x21f9c8` with a fixed 16/9 (same camera `[0x51E490]`; probably the letterboxed cutscene view) |

- The game's own widescreen is **Vert-**: same horizontal view, vertical view cut, for a TV that
  stretches the anamorphic picture. The HUD does not change with it (the radar keeps its shape); the
  preference's 106 readers are mostly 3D-projected sprites (e.g. `0x1147e0`: a size without the 4/3
  factor).
- RenderWare derives the frustum (EE culling) and the VU matrices from the view window, so widening
  it (our Hor+, `vcs_display.cpp`) widens 3D, sector culling and both renderers at once.
- **Entity culling does not follow the view window** (found 2026-10-27, the user's "models at the screen edges are
  culled as if the screen were 4:3"). `CCamera::IsSphereVisible` = `FUN_003816F8(cam, centre, camera matrix, radius)`
  transforms the centre to camera space (x right, y forward, z up) and tests it against near / far (`0x4CD130` /
  `0x4CD12C`) and four camera-space plane normals in the camera object: right `cam+0xB60` = (cos h, -sin h, 0),
  left `+0xB70` = (-cos h, -sin h, 0), bottom `+0xB80` / top `+0xB90` = (0, -sin v, -+cos v); culled when
  dot > radius. They are built in `FUN_0037b2c8` (called from `FUN_00378dd8`, the camera update) from the FOV global
  alone: h = FOV x pi / 360 (`0x3C0EF921`), v = 0.7 x h (`0x3F333333`) - never from the aspect or the view window.
  Found by grepping the generated code for stores to `0xB60(` (one writer) and loads of the FOV global `0x487484`
  (13 readers; the others are a FOV < 60 branch in the sector draw `0x240ff4`, LOD / sprite scales 70 / FOV). With
  the view window widened the planes still cut at the 4:3 edge (tan h = 0.700 vs 0.934 at 16:9): buildings, peds and
  cars in the outer eighths of a 16:9 picture were not drawn, and the car / ped spawners (which also ask
  IsSphereVisible) treated those parts as off screen. Fix: `vcs_display.cpp` wraps FUN_003816F8 and, before it runs,
  widens side planes the game has rebuilt to the Hor+ edge (normal (a, r b) normalised); the vertical planes stay
  (Hor+ keeps the vertical view). No other reader of those planes (the writes are only in FUN_0037b2c8, the reads
  only in FUN_003816F8). Regression check: `tools/regress.py` step "widecull" (the planes' edge equals the view
  window's x at `0x742AC0`, which holds (tan(FOV / 2) x r, aspect x r, near 0.3, far 2000)).
- The sector test (6b) builds its clip planes in `FUN_002F7620` from that `0x742AC0` view window, so it was already
  wide: its side planes at 16:9 are (-+0.73095, -0.68243), the same 43.0 degrees as the widened entity planes.
- `FUN_0039fc48` (3D point to screen for sprites: coronas, light glows) only rejects by near / far; it sizes the
  sprite with the aspect global (`0x39fd2c`: 448 / z x 1.4286 / aspect), which Hor+ leaves at the game's 4:3 value.

## 6. Renderer

### 6a. Frame structure

- One VIF1 DMA chain per frame, kicked at `0x27245C` (D1_CHCR = 0x145, chain + TTE); TADR alternates
  between static root lists `0x480D20` / `0x480DE0`. The kick: the flip `FUN_003706c8` -> `FUN_002721f8` (the chain
  pointer at `0x510438`, cleared after) -> `FUN_002723E8(channel, tadr, chcr regs)`, the DMA library's start (clears
  the channel's D_STAT bit, writes TADR / QWC, then CHCR). There is no wait for VIF1 to finish before the next frame
  rewrites what the chain reads: `FUN_00272480(channel, timeout)` (the DMA sync) is called only from `FUN_003177e0`,
  `FUN_00317930`, `FUN_00317b50`. (2026-10-25, from the recompiled code's disassembly comments: the callers of
  `func_2723E8` / `func_272480`; Ghidra was not available.) Full frames are 7-14k tags (CALL / RET per
  model) - more than the runtime's original 4096-tag guard.
- Models are prebuilt packets in the model heap, entered with CALL tags and ended by RET; CALL tags
  are written by the RSL draw functions (6i; `FUN_003298D8`, named here before, builds texture uploads). VU1 microcode sits inside
  `.text` and is uploaded each frame by REF tags with `MPG` VIFcodes (`0x2AC130`, `0x2F13D0`,
  `0x368730`, ...).
- VIF1 payloads come from packet buffers (`0x500000-0x6FFFFF`) and the model heap
  (`0x1200000-0x17FFFFF`). DMA packet buffer `0x520F90`: two halves of 0xE6670 bytes;
  `FUN_00476770` returns the bytes used; draw code skips work when < 0x12C00 are left (peak ~400 KB).
- Z buffer: Z24 640x448 at ZBP 280, cleared each frame by 40 column strips (640x224 CT32 in total)
  drawn at FBP 280, whose own Z write goes to ZBP 350 (the second half).
- Display: PMODE 0x8027 = both circuits on the same buffer one line apart, blended (anti-flicker);
  DISPFB FBP 0, FBW 10 (640), DBY 2 / 1; 640x445 shown.
- **The flip (FUN_003706c8) reads GS CSR** at `0x370714` (`ld $v1, 0($a0)`, $a0 = 0x12001000) and keeps only the
  FIELD bit: `dsrl $v1, 13` then `andi $s4, $v1, 1` in the next branch's delay slot; $v1 is overwritten right after.
  It is the game's only CSR read per frame (2026-10-25, a game-thread profile with call stacks: the runtime's CSR
  fence - waiting for the render worker to finish all queued GS work, for SIGNAL / FINISH - was ~25% of the game
  thread uncapped). FIELD is set at VBlank by the EE scheduler, so that read skips the fence
  (`PS2Runtime::addCsrReadWithoutFence`, src/game/vcs_display.cpp; `VCS_CSR_FENCE=1` = as before).
- **Scratchpad**: the per-frame render state lives at `0x70002020+` (e.g. FUN_002b8ed0, the busiest draw function,
  stores ~10 words there per call through `$s0 = 0x70002020`). The recompiler resolves those addresses as constants;
  the runtime's Load / Store for them are inline since 2026-10-25 (they were out-of-line calls taking a mutex).

### 6b. World and culling

- World sectors: `FUN_0023E748(level, pass)` (3 passes per frame; takes a lock, scrolls water UVs at
  level+0x5D0/0x5D4) walks the sector slots at level+0x248.., and per entry calls `FUN_00240ED8`,
  which culls with `FUN_002F7528` = unit box transformed by the sector matrix, tested by a VU0
  microprogram (CMSAR0 0x19F, VI15 = 0xDC) via `FUN_0030C8D4`; 0 = culled, 1 = inside, 2 = partly.
  Visible sectors go to `FUN_002409C8`.
- Entities: `CCamera::IsSphereVisible` = `FUN_003816F8` (VU0 macro transform of the centre by the
  camera matrix, near / far at `0x4CD130` / `0x4CD12C`, planes at cam+0xB60).
- Level object `0x750340` (pointer at `0x48F4F8`). The world is a hex grid of cells (125 x 108.25
  units, odd rows offset by half a cell; origin = ((x + 0.5 - (y & 1) / 2) * 125 - 2400,
  (y + 0.5) * 108.25 - 2000), `FUN_00241F00`). Cell slots at `0x75036C` (+0xA0 each): grid x / y at
  +8 / +0xC, loaded flag +0x18, draw lists via +0x20. `level+0x248` = current cell, `+0x250` = next;
  `FUN_0023C820` (per frame) follows TheCamera (`0x6F44D0`, position at +0x30) and `FUN_0023D740`
  swaps them. Each cell streams ~0.3-0.5 MB of MAINLA.IMG in 6 pieces into `0xCB7A80..0x112A660`.
  Fort Baxter is around cells (5..7, 16..18).
- **Buildings' detail is per cell, not per distance** (2026-10-31, from a RAM dump over Little Havana compared with the
  previous cell still in its slot; `level+0x258` is a third slot, `+0x25C` a coarse 3 x 3 block, `FUN_0023C188` loads
  the block (`FUN_0023BDF8`) and the cell (`FUN_002415B0`)). A cell's `+0x20` holds 8 draw lists (passes 0: lists 0-3,
  1: 4-5, 2: 6-7), entries of 0x50 bytes: +2 the resource (`*(*(level + 0x1C)) + res x 12`: geometry, cached packet),
  +0xC a matrix pointer or the matrix inline at +0x10, **positions relative to the cell's centre** (the world offset
  `0x6FE980` is minus the current cell's centre). The lists name the whole level: the cell's own detailed sectors,
  streamed with it into the buffer above (cell (13, 13): 65 sectors, median 200 m from its centre, ~1.7 MB of geometry
  plus 246 KB of lists), and everything else as resident low-detail sectors (the level's data at ~0x700000-0xCFFFFF).
  The same place is drawn by a different resource from another cell (16 such swaps between the two cells), and a
  cell left behind keeps its lists but not its detail (its streamed resources read as not loaded). So no distance
  decides a building's detail: it is the cell the camera is in; more detail farther out would mean several cells'
  streamed detail at once, more than the 4.66 MB buffer holds.
- In-world draws are mostly MODULATE + alpha test GREATER 8, fogged, vertex colours from V4-5
  unpacks.
- **Levels**: the world is three levels, each a `WRLD` image (`.LVZ`) plus an archive (`.IMG`): 1 = BEACH (east
  island), 2 = MAINLA (mainland: Little Havana, Little Haiti, Downtown, the airport, Fort Baxter), 3 = MALL. The
  executable names them with the developers' paths (`cdrom0:/RUNDATA/BEACH.LVZ`... table at `0x4ADAE0`, resolved
  through the disc index). Only one level's WRLD is in memory. `FUN_0023baf0(level, newLevel, ...)` switches;
  `FUN_0023c188(level, camera position)` (per frame) calls it when the wanted level - global `0x4CD118`, set from
  the player's zone - differs from the loaded one (`level + 0x18`). Teleporting across islands switches levels by
  itself within half a second (rig `level_test`, 2026-10-23).
- The cell the streaming focuses on is computed from the camera position in `FUN_0023c188` with float maths and
  `cvt.w.s` (float -> int). The EE FPU's `cvt.w.s` truncates; the runtime rounded to nearest, so at places the
  game picked a neighbouring hex cell 100+ units away (camera (-675, 1172) -> cell (14, 30), centre
  (-587.5, 1301.6), instead of (13/14, 29)) and streamed that cell's geometry and collision: nothing drawn or solid
  under the player, who fell through the world (the user's falling-through report; `VCS_TRACE_CELL=1` shows the
  focus).

### 6c. VU microcode

- `.vutext` holds four small VIF `MPG` packets (DVP overlays: `0x48055C` -> VU 0x000, 245 pairs;
  `0x4810EC` -> 0x400, 4; `0x48146C` -> 0x000, 24; `0x48176C` -> 0x200, 20). They are **VU0**
  helpers: program 0 (0x000..0x7A8; identical in VU0 code memory during play) holds **0x020 = segment vs
  triangle** and **0x3A0 = sphere vs triangle** (with the nearest-point-on-segment subroutine at 0x228, called with
  `BAL vi15`); they were ~22% of the EE thread interpreted (2026-10-23, `PS2X_TRACE_VU0`) and are native now
  (`src/game/vcs_vu0_native.cpp`, checked bit-exact with `PS2X_VU0_VERIFY=1` over 4.7M runs while driving). Inputs:
  vf17 (12.4 / 7-bit fixed point: normal or segment), vf14..16 the triangle (7-bit fixed point), vf12 / vf13 the
  sphere or segment; out vi1 = hit, vf1 contact point, vf2 / vf3 direction and depth. Program 0 has E-bit exits at 0x000 / 0x010, converts fixed point with `ITOF0` /
  `MULi 1/128`, builds edge vectors and runs `CLIP` / `FMAND` / `FCAND` / `DIV` - most likely
  collision (line / sphere vs triangle). Found by disassembling with hctp-recomp's `vu1dis.py`.
- **The other VU0 programs while driving** (2026-10-24, `PS2X_TRACE_VU0=1` per 5 s; code dumped with
  `PS2X_VU0_DUMP=0c10`, disassembled with `tools/vudis.py`; all native now, `PS2X_VU0_VERIFY=1` 0 differ): 0x0CF8
  sector box vs three plane sets (~240k calls), 0x0EB8 three 4x4 matrix products (~220k), 0x03A0 / 0x0020 above,
  **0x0C10 sphere vs three plane sets** (19k calls, 190 ms interpreted - 10 us a call: vf1 = centre + radius in w,
  matrices at vi15+24, vf31 = (1,1,1,1); vi1 / vi2 = per set the MAC sign flags of radius - distance /
  distance + radius, read by FMAND 4 pairs after the FMAC), **0x0068** = the segment-vs-triangle program entered after
  its fixed-point conversion (5.8k, 60 ms), **0x0E98** = the 0x0EB8 loop on the matrices at vi15 into vi15+12 (2.9k,
  25 ms), **0x0E30** = vf1..vf12 stored to vi15+0..11, the last in the E bit's delay slot (2.9k, 8 ms). Together the
  four were ~5% of the game thread while driving. 0x0CF8 / 0x0C10 are called through `FUN_0030C8D4` / `FUN_0030C8A8`,
  the matrix programs through `FUN_0030C940` / `FUN_0030C900` (e.g. `FUN_002F7620`, which builds the camera's plane
  matrices from `0x742AC0` into `0x520AD0` / `0x5208A0` / `0x520860`).
- The **VU1** rendering microcode is not a static MPG packet: it is uploaded from `.text` each frame
  (6a). `game/vcs/vu1_uploads.txt` lists the uploads seen; `tools/vu1_recomp.py` compiles them.
- Setup programs that never XGKICK (normal): 0x0148 (clear state), 0x0418 (lighting dispatch via
  JALR table at VU mem 34..37), 0x0478 (matrices), 0x2B50 (matrix copy).

### 6d. VU1 pipeline (found with PS2X_HLE_SURVEY, NATIVE_RENDERER.md stage 4)

Program **0x0030** produces ~95% of all GS vertices (3.0-3.5M/s) and ~88% of VU1 time. 0x02c0
(V4-32 x4 per call: sprites / particles / text) ~3%. Disassemble samples with
`python tools/vudis.py <vucode.bin> --start 0x30 --to-ebit` (`PS2X_HLE_SURVEY_DUMP=2
PS2X_HLE_SURVEY_DUMP_EVERY=40000`).

**0x0030 is a dispatcher**: `JR` to instruction `[38].x` inside itself, then a chain of `JALR vi15`
calls whose targets / `vi01` parameters come from VU data qwords 38-41 (set per batch by the setup
programs). Stage tables (instruction indices):

| entry | stages (vi01) | used by |
|---|---|---|
| 0x19 | 0x0da, 0x4e0 (0x9c), 0x2b6 | prelit world: V3-16 pos @1, V2-8 uv @0x48, V4-5 colour @0x8f (+ V4-32 matrix @0x2c x3 in some) |
| 0x19 + 0x4ff | 0x0da, 0x4ff (0x9c), 0x2b6 | rigid lit models (vehicles, props): int8 normals V3-8 at `[47].y` |
| 0x16 | 0x5a5 (0xa8), 0x0da, 0x4ff (0x9c), 0x2b6 | lit, skinned models (peds): V3-16 pos, V2-8 uv @0x55, V3-8 normal @0x2b, V4-32 weights @0x7f |
| 0x13 | 0x0da, 0x4ff (0x9c), 0x2b6, 0x5b1 (0xa8), 0x2b2 | rigid lit models with an **environment map** (vehicles): native since 2026-10-23 |

Code at 0x2700.. (instr 0x4e0..) is swapped by per-pass MPG uploads, so programs are keyed by the
code at the start PC *and* 0x2700-0x2fff.

VU data layout of the world pipeline (qwords; "top" = XTOP double buffer):
- 28-31: combined world -> GS window matrix (rows; includes the viewport scale / 2048 offset).
  24-27: the clip matrix.
- 42: position scale (1/32768 for int16), 43: position offset (folded into the matrix).
- 44-46: 3x3 matrix for the V2-8 texture coordinates, applied with I = 1/255.
- 47: input offsets: .x positions (1), .y normals, .z uv (0x48), .w colours (0x8f).
- 48: .z = mask applied to TOP, .w = output buffer offset (0xd6).
- 49 / 50: GIF tags for the kick (PACKED, NREG 3: ST, RGBAQ, XYZF2; PRIM strip with IIP TME FGE ABE);
  NLOOP = vertex count from `[pos-1].w`. 51: default RGBA (255,255,255,128) / material colour.
- 52: .x transform routine (0x0e9 normal / 0x0da first call), .y flags (bit 1 fog, bit 0 extra pass
  at 0x1440), .z kick variant (698 / 711). 53: fog (.z bias 255.6, .w scale -0.128 per unit of w).
- 0x9c-0x9e (vi01 of stage 0x4e0): colour scale (time-of-day tint), offset, clamp (255).

Routines (byte addresses): 0x0748 normal path (`BAL 0x0c38` clip test; all inside -> 0x06f0 fast
path; some outside -> clipper 0x11f8 + 0x13d8); 0x07f0 transform (`p = M * (itof(pos) * scale +
offset)`, `Q = 1/p.w`, XYZ = FTOI4(p.xyz * Q), STQ = (uvMatrix * itof(uv) / 255) * Q); 0x1048 fog
(F = clamp(53.z + 53.w * w, 0, 255)); 0x2700 prelit colour (RGBA = MINI(itof(c) * [0x9c] + [0x9d],
[0x9e])); 0x15b0 GIF tag + `XGKICK`. Lit models: 0x2d28 (stage 0x5a5) 4-bone skinning (weights'
low bits are bone indices, bones 4 qwords each from 0xa9, result written back over the position /
normal slots); 0x27f8 (stage 0x4ff) 4 directional lights + ambient, scaled by `[51]` * 1/510, RGB
only. All reproduced bit-exact in `src/game/vcs_hle_world.cpp` (`PS2X_HLE_VERIFY=1`), except the
STQ.w lane and its fog in the lit pass, which the runtime's VU1 core leaves inconsistent.

**Environment map (stage table 0x13, 2026-10-23).** The rigid lit pass (0x0da, 0x4ff with 0x9c, kick 0x2b6 = tag 49)
followed by **0x5b1** (vi01 = 41.y = 0xa8) and kick **0x2b2** (tag 50). 0x5b1 first XGKICKs the GIF packet at vi01
(seen: one A+D write of TEXFLUSH), then for every vertex (at least 6): ST = (rows vi01+5..7, x / y lanes times
I = 1/256) . normal + 0.5, times the vertex's Q from the output, written over the output's S and T. Kick 0x2b2 sends
the same output (colours, XYZF2, Q unchanged) again with tag 50: PRIM 0x25c - strip, Gouraud, textured, blended,
no fog, **context 2** (the environment texture set by the game's own GS packets). The kick tag's x lane is the
packet header's .w via ILW + MFIR - sign-extended (0xffff80nn). Reproduced (`envKicks` in vcs_hle_world.cpp) and
checked against the VU's three kicks: 27,243 packets over the reference scenes, all exact; native drawing: pass 1
as a rigid lit model on the GPU, the TEXFLUSH and the second pass as the VU's kicks (PATH1). Clipped table-0x13
packets stay on the VU1.

**Code images.** The code below 0x2700 is not fixed either: VCS uploads different variants of the transform
(0x07f0) and clip test (0x0c38) per pass - every reproduction is tied to a hash of the exact code it was read from.
Seen so far:
- the prelit world image (integer positions folded with 42 / 43, integer UVs through the texture matrix 44-46 / 255,
  prelit colour stage at 0x2700);
- the **float images**: positions are floats, the matrices 24-27 / 28-31 are used as stored (no fold), RGBA is
  qword 51 from the transform, the fog stage FTOI4s into XYZF.w. Two flavours: the one 0x02c0 runs with (UVs as
  floats, used as they are) and the "variant C" prelit one (UVs ITOF0'd through the texture matrix, a colour stage
  at 0x2700 that copies the colour qwords - layout V4-32 @001 / @049 / @091 x72; a second copy differs only in
  padding after a JR). Variant C's transform epilogue leaves the *next* vertex's w in STQ.w for vertices N-4..N-2
  (N = max(count, 7) processed): a MOVE.w waits for the MULw right before it - and the fog reads w there.
- Clip tests run over at least 5 / 6 vertices, so stale data past the count reaches CLIP: the VU treats exponent-255
  bit patterns as huge finite numbers (no NaN / Inf), so such a vertex can flag the packet for the clipper -
  reproduced with the VU's operand / result clamping (vcs_vu_math.h, from the runtime's vu1fast helpers).

**0x02c0 - instanced re-draws** (setup slot 0xc8, entry 0x1c): copies the packet's object matrix (4 qwords at TOP)
to 0-3, 0x04d8 builds clip (view 16-19 x object) and window (viewport 12-15 x clip) matrices into 24-27 / 28-31,
0xc8 the camera in object space (33 = R^T (32 - T)), then transform 0x0da + kick only, over a mesh resident at
absolute addresses (48.z mask 0). **Entry 0x0d** draws a resident mesh twice: setup slot 35 = 0x4e0 normalises the
object's rotation rows (ERLENG) into a 3x2 environment matrix (P+5..7, P = 0x9c); 0x4ff / 0x509 write an A+D TEX0_1
/ TEX0_2 qword at P+1 from P+2 / P+3 and kick the packet at P; pass 1 = the float transform + tag 49; 0x546 sets
RGBA = Q.xyz (Q = 0xa4) with alpha = FTOI0(clamp(Q+1.x * w + Q+1.y)); 0x513 kicks P again and writes the
environment ST ((P+5..7 x / y * 0.5) . normal + 0.5) * Q; pass 2 = tag 50 (context 2). A shine over a texture.

**Shine through the clipper / culled (2026-10-24).** The kick routines load their tag into vf01 and jump through
52.z: 0x15b0 (stage 0x2b6) loads tag 49, **0x1590 (stage 0x2b2) tag 50**; 52.z is 698 (0x15d0, plain kick) or 711
(0x1638, the per-triangle clipper, which builds its fan tags from vf01 - 0x1650 / 0x1660). So a shine object that
crosses the guard band is clipped twice: pass 1 with tag 49, then 0x509 / 0x546 / 0x513 run as usual over the
clip test's output (ST undivided with w in .w, the clip position + fog) and pass 2 is the same clipper with tag 50.
A culled packet (all vertices outside one plane) leaves the stage table at once: 0x0748 -> `B 0x0178` = XGKICK of
qword 58 (the empty tag) and the program's end - only the TEX0_1 kick of 0x4ff was sent. Both reproduced
(`shineKicks`, `vcsclip::clipFromOutput(..., tagQword)`); PHI_A1 in verify mode: 421,694 0x02c0 packets exact,
among them 9,629 clipped and 26,518 culled shines.

**Setup programs** (VU1 starts other than 0x0030 / 0x02c0, no primitives; `PS2X_TRACE_VU1=1`, code dumps in
`build/analysis/vu1setup`; one flyover sample each, so other code images may differ):
- 0x01e0 (and 0x02c8, a copy): object matrix at TOP -> 0-3, 0x04d8 (vi01..04 = 0, 16, 12, 24: clip = view 16-19 x
  object into 24-27, window = viewport 12-15 x clip into 28-31), then the slot routines in qwords 34-37 (routine in
  .x, vi01 = .y: 0xc8 camera into object space, 0x3a nothing, 0x4e0 env matrix), then `B 0x0178` (kick qword 58, end).
- 0x0250: the slot part of 0x01e0 alone, then the kick. 0x03a8: the slots from the .w lanes, then the kick.
- 0x0418: the .w slots, then falls into 0x0478 and ends without a kick. 0x0478: 0x04d8 (4, 8, 12, 16), then
  0x04d8 (0, 16, 12, 24).
- 0x0000 (same image): 42 / 43 (position scale / offset) from TOP, then the end kick. 0x0148: qword 58 = the empty
  tag (0x8000, 0, 0, 0). 0x2b50 (lit image): a block copy - the header at TOP to header.z, then 4 x header.x qwords
  after it (the bone matrices), four loads then four stores per step.
- Slot routines of the lit image (code at 0x2700+, so per image): **0x4e0** (byte 0x2700, vi01 = P = 0x9c) the light
  directions P+0..2 into object space: rows 0-2 normalised (ERLENG, MUL.xyz), P+9+i = L0 r.x + L1 r.y + L2 r.z (all
  lanes); **0x57e** (byte 0x2bf0, vi01 = A = 0xa8) the env matrix: A+5+i .xy = rows A+2..4 . normalised row i, stored
  as whole qwords - A+7.z is the last ERLENG, the other z / w lanes are stale registers (the env pass reads x / y).
- **The Z-clear image** (a second low image, different code before 0x0178; about 2 runs a frame each, reproduced
  2026-10-24 in `zclearProgram`): **0x0200** kicks two 4-qword GIF packets at qwords 0 and 4 in turn, the strips' x
  edges stepped by I = 32 (FTOI4 into the x lanes of qwords 2 / 3 of the other buffer), [0].w pairs of kicks (10:
  20 strips over 640) - the Z clear into FBP 280 that the renderer turns into depth fills; **0x0000** the same with
  6-qword packets at 0 / 6, x lanes of 2-5 stepped by the floats in 4 / 5 (read once; the floats carry 2^23 so the
  sum's low bits are the coordinate) - an SQ paired with an ADD of the same register stores the value from before the
  ADD; **0x0400** XGKICKs the packet at qword 128. Their kicks go to the GS front end (depth fills, register packets).
- **Slot routines are found by their code**, not their number: the light and env routines are position independent
  and 0xf8 bytes long, and the lit images put them at 0x2700 or 0x2bf0 - in one image slot 0x4e0 is the env routine
  (that 0x0250 fell back until slots were named by the hash at their address).
- Table-0x13 packets through the clipper (reproduced 2026-10-24, `envClipKicks`): the clip test / fog write the output
  buffer as for the prelit world (ST undivided + clip w, qword 51, clip position + fog), the lighting stage 0x4ff
  writes RGBA over it, kick 0x2b6 = clipper with tag 49; 0x5b1 kicks the packet at 41.y and writes the env ST (lane z
  of the output as Q) over x / y; kick 0x2b2 = clipper with tag 50. Reference scenes in verify: 216 exact.
With these, **no VU1 program runs in a normal frame** (reference scenes, tour subset: `vu1_programs` 0).
About 330 runs a frame in the flyover and cutscenes before (`PS2X_TRACE_VU1=1`: 0x01e0 30k, 0x03a8 12.6k, 0x0478
9.3k, 0x0250 5.3k, 0x0418 1.5k per 5 s). **Reproduced (2026-10-24)**, each routine tied to a hash of its code
(`CodeCheck` in vcs_hle_world.cpp), checked with `PS2X_HLE_VERIFY=1` against the whole VU memory after the VU's run
(stale lanes excepted): reference scenes 434,692, PHI_A1 217,489, a city spot 80,557 - all exact. The matrix and
camera routines need the VU's float edge cases (0x0478 / 0x0418 reach denormal or huge inputs: `vuMul` / `vuMadd` /
`vuAdd` / `vuSub`). Left on the VU1: 3-4 programs a frame (the second low image). `PS2X_HLE_SETUP=0` = VU1.

**A second world image** (2026-10-26, found by the mission smoke test: MAR_A1 was the only mission with GS-path draws,
0.6 a frame, all from 0x0030 on the VU1). `PS2X_HLE_STATS=1` showed its packets passed over with `code 0` - the
handlers' hash of the 0x0030 image (bytes 0x30-0x118, 0x6d0-0x7e0, 0x7f0-0xc20, 0xc38-0x1030, 0x1048-0x11f8,
0x1360-0x13d8, 0x15b0-0x1638, 0x2700-0x28a8) did not match. `PS2X_HLE_DUMP_CODE=1` (writes the VU1 code memory the first
times the check passes / fails) showed MAR_A1 loading other code at bytes 0x7f8-0xbcf, 0xc58-0xfe7, 0x1460-0x156f (and
0x28b0-0x2f6f, outside the hash); the dispatcher and the routines its packets call (stage table entry 0x19: 0x6d0,
0x748, 0x15b0, the light slot at 0x2700) are unchanged. Hash 0xdffe680d06eb60d0, accepted after `PS2X_HLE_VERIFY=1` over
the mission: 1.55M fast-path packets, 133k C++-clipped, 264k setup programs, all exact. The clipper's own check
(0x13d8-0x15b0) fails under this image, so clipped packets would still go to the VU1 there; none did in the run.

**0x02c0 code images.** Three images with the shine / re-draw stage routines are seen (PS2X_HLE_DUMP_IMAGES=1 writes
the first shine packet of each: build/analysis/shine): hash (0x30..0x2b20) 1a8edffd (the one reproduced first),
da70874b (differs only at 0x1030 - dead code after a JR's delay slot) and 97eecb5d (also in 0x0a88-0x0c10 and
0x0ef0-0x1020, alternative transform / clip-test routines the stage table never calls: the shine and re-draw enter
through 52.x = 0xde / 0xe9 only). The second and third were seen in the city (e.g. (-675, -75)) and fell back to the
VU1 until accepted; verify there: 85,413 re-draws exact.

All of these are reproduced in `vcs_hle_world.cpp` (floatKicks / shineKicks) with the VU memory they write, and
checked against the VU's kicks and memory (174,110 packets over the reference scenes, MAR_A1 / GON_C3 / a drive
~50k / 51k / 120k - all exact). With them native, **nothing of the 3D runs on the VU1** in the reference scenes
except clipped environment-pass packets (63 in two minutes); clipped 0x02c0 / variant-C packets go through the C++
clipper read back from VU memory (`vcsclip::clipFromOutput`).

### 6e. GS usage (VCS_GS_STATS, title / intro)

- ~95% triangle strips; also triangles, fans, sprites, points. CT32 colour (some CT16 for effects);
  Z24 (some Z32), test GEQUAL.
- Blend: 84% `(Cs-Cd)*As+Cd`; also `(Cs-Cd)*FIX+Cd`, `Cs*FIX+Cd` (FIX up to 255), `Cs*FIX`,
  `Cd-Cs*FIX`. Alpha test GREATER (+KEEP) and GEQUAL with AFAIL=FB_ONLY; no DATE.
- Textures: 83% PSMT4 + CT32 CLUT (world), CT32, T8, CT16; modulate / decal; repeat / clamp /
  region clamp; bilinear. Fog on most world geometry. CT32 / CT16 textures inside render targets
  = post effects. COLCLAMP on, no dithering, no FBA, no PABE.

### 6f. 2D: HUD, text, radar, menus, effects

- **The render-target reads' packets** (2026-10-26, `PS2X_HW_FRONT_DRAW_LOG`): the reflection map's copies into FBP 420
  (0x1A4) and FBP 452 (0x1C4) and the self-copy into FBP 140 (0x8C) sample target 140 (TBP 0x1180) through PATH2 A+D
  packets: one tag (NLOOP 0x36 or 0x10, A+D) of UV / RGBAQ / XYZ2 writes - a triangle strip whose PRIM (0x31C:
  TRISTRIP, IIP, TME, FST, context 2) came in an earlier state packet - or, for the sky's copy, XYOFFSET_2 (0x19),
  TEST_2 (0x48), SCISSOR_2 (0x41), then PRIM, then the strip. The flyover also draws one Im2D packet a frame with
  PRIM LINESTRIP (two vertices).

Found from frame dumps (`PS2X_HW_DUMP`, draw lists with depth) during the widescreen work:
- RenderWare keeps **ZTE on for 2D** (ZTE=0 is prohibited on the GS) and uses ZTST ALWAYS or GEQUAL.
- The HUD, text (font texture 256x256), radar and menus (RwIm2D) are all drawn at the **largest Z**
  (0xFFFFFF; 0.99999994 after scaling by 2^-24, never exactly 1.0).
- 3D-projected sprites - clouds (64x64 textures at z ~0.0006), coronas, the mission marker glow -
  take the same RwIm2D path but at their real depth.
- The sky is a full-width gradient at z = 1 (n=18 strip, x -0..852); a horizon band full width too.
- The colour filter / trails effect is drawn as **strips that sample the frame** itself (textures
  inside render targets, `texIsRt`), plus an alpha-only quad (FBMSK 0xFFFFFF) over x 80..560 at
  z = 0.
- The radar is drawn straight onto the screen (corrected 2026-10-24 from a frame dump at Fort Baxter: there is no
  off-screen radar target - the 128x128 at FBP 420 is the reflection map, 6g): the round outline is a fan at far Z
  (GEQUAL, Z write on) and the map tiles (128x128 T4 textures, far Z, GEQUAL) are clipped by the **scissor** to the
  radar's rectangle (37,336 - 120,412 at 4:3). Menu labels are scissored too.
- Pause menus have no depth-tested geometry below the far plane (that is how "3D frame" vs "2D
  frame" is told apart for the widescreen presentation).

**At the RenderWare level (2026-10-23, `src/game/vcs_hud.cpp`).** Found from the HUD's format strings (`$%08d` at
0x4b73a0, `%02d:%02d` at 0x4b73a8, used at 0x31ec08 in the money / clock routine FUN_0031eb18) and a trace of the
calls (`VCS_TRACE_IM2D=<n>`, `VCS_TRACE_IM2D_MARKERS=5`):
- **Im2D**: FUN_002fbe08(prim, vertices, count) = RwIm2DRenderPrimitive, FUN_002fbe68(prim, vertices, count, indices,
  indexCount) = the indexed one. **RwRenderStateSet** = FUN_00175198(state, value) (a switch over states 1..12; 6 =
  ZTESTENABLE). Font setters around 0x3f4000-0x3f4050 write the font state at 0x711f30.
- **Vertex** (16 bytes; the PSP-style packed form): u, v as u16 fractions | RGBA bytes | x, y as s16 pixels in
  640x448 | z (u32; the HUD's is 0xfffffe).
- **The 2D pass** (FUN_0021f348, after the 3D): sky gradient (0x3e0c6c) and horizon band (0x3e0d4c), the radar map into
  its off-screen target (indexed, 0x39fec4), clouds (0x3a1260), then **CHud::Draw = FUN_0031c628**: text glyphs
  (0x3dffc0, quads), the weapon icon (0x3a07a8: a sprite routine, z 0x4dcc3, depth test off), ammo digits (0x3dfe24),
  the radar on screen (0x3e0018, 0x3e0094, 0x3dff64); then FUN_001676c8, FUN_00396670, FUN_003aee80, FUN_002a9708,
  FUN_0025cd98 (messages / text when shown); the frame's display list goes out after (FUN_002723e8).
- The radar map is masked to its circle by **depth**: its HUD draws are depth-tested and their z matters.

**Weapon icon and ammo count** (2026-10-29, FUN_0031f478, called from CHud::Draw; decompiled, Im2D vertices with
`VCS_TRACE_IM2D`). The layout is the PSP's, in 480x272 units scaled by 4/3 x 1.647: the icon is a 72x72 quad
(FUN_003a03a8: centre in f12/f13, half sizes in f15/f16) over the rect 416..470 x 16..60 (465 with FUN_002af658), at
x 554..626. The ammo is text in rects: a single number centred in 411..462; "total-clip" as the total right-aligned in
414..438 (justify 0x14), the separator centred in 438..444 (0x12; "." with x - 4 for weapon types 0x22 / 0x23) and the
clip left-aligned from 444 (0x11). The icon texture's dark box is not centred in its quad: it covers about u 0.06..0.70
(centre ~436.5 PSP units, where the single number is centred), so the separator sits at ~63% of the box's width and a
short total ("95-29") looks right of centre. **The PS2 original does the same** (a PS2 capture on Grand Theft Wiki's
HUD page, "9993-6": separator at ~65%); not a port bug.

The **16:9 weapon-icon bug** (the icon at the right edge, away from its ammo count): the renderer's widescreen placement
treats far-plane 2D as HUD, and the icon is not at the far plane. Fixed at the source: from CHud::Draw to the frame's
end, Im2D primitives drawn with the depth test off get the HUD's z (`VCS_HUD_RW=0` = off).

**From Im2D to the screen (2026-10-23, F12 draw dumps at 16:9, `PS2X_HW_DUMP`; `VCS_TRACE_HUDKEY=<n>`).**
- The GS sees an Im2D vertex at (x - 0.5, y - 0.5) (the 2D code's pixel-centre bias) for most HUD draws, within 1/16 of
  (x, y) for others (the zone name, fades): a vertex's whole-pixel position finds it again with either rounding.
- The game draws the frame into the buffer at FBP 140 and copies it into the displayed one (FBP 0, DISPFB DBY = 2)
  with a plain full-screen copy in 40 strips (decal, no blending) at the start of the **next** frame. So what is shown
  is the previous frame's FBP 140, HUD included.
- Just before the HUD, a full-screen draw writes Z = 0 everywhere (FBMSK 0xffffffff: Z only). HUD draws use ZTST
  ALWAYS (most) or GEQUAL with Z writes at z = 1.0 (help text, zone name): later depth-tested HUD draws do not overlap
  earlier ones. Blending is (Cs - Cd) * As + Cd or additive; no draw seen uses the destination alpha.
- (Corrected 2026-10-24: the 128x128 drawn into FBP 420 is the reflection map, not the radar's map - the radar's tiles
  are drawn onto the screen directly.)
- Indoors the radar is the ring alone. Help text hides the rest of the HUD while it is up; on leaving the barracks
  the radar flashes for a while (a tutorial).
- **Radar on screen** (dump outside the barracks door, 16:9): first an untextured, colourless draw (blend
  (0 - 0) * As + Cd, Z write) of 24 triangles fills the radar box's corners outside the circle with Z 0xFFFFFE; then
  the map as four 128x128 tiles (large quads around the box) at Z 0xFFFFFD with ZTST GEQUAL, scissored to the box:
  they fail in the corners. Then the ring (64x64), the north / blip icons (16x16), all with bilinear filtering.
- **Menus** (2026-10-23; `VCS_TRACE_IM2D_STACK=1` lists the return addresses on the guest stack at each 2D call):
  FUN_0021f7d8 is the frontend's draw, called every frame; it returns early unless a menu is up, else calls
  FUN_00471400, then **FUN_003b53f8 (the menu / pause-menu draw)** (through 0x3b568c / 0x3b56d8 and 0x3cdfbc to the
  page drawing), then FUN_003e0b10 (a full-screen overlay). In the pause menu no 3D is drawn and CHud::Draw is not
  called: the frame is the copy of FBP 140 into FBP 0, then 2D only into FBP 140 (backdrop, map, icons, text, the
  overlay). The map's player arrow blinks.
- **HUD textures**: the clock and money digits (orange and green, with outlines) and the wanted star are one
  128x64 atlas with 16-texel cells side by side; the ammo count and text use a 256x256 font atlas. All HUD textures
  are bilinear-filtered (TEX1 MMAG / MMIN linear) and drawn smaller than their texels (a clock digit: 15 x 21.5
  texels into about 5 x 9 pixels).

Milestone 3 step 2 builds on this (docs/NATIVE_RENDERER.md "HUD layer"): `vcs_hud.cpp` collects the HUD context's Im2D
primitives each frame, groups them into elements (boxes closer than 12 px across / 3 px down: a line of text, the
radar and its blips, the clock / weapon / money cluster) and gives each an anchor from where it sits on the 4:3
screen: left edge when its middle is left of 280 and it starts before 160, right edge when its middle is right of 360
and it ends after 480, the middle otherwise; full-width draws (fades, letterbox bars) stretch. At the frame kick the
whole-pixel positions of its vertices go to the renderer, which finds each GS primitive's element by them.

**What reaches the GS as PATH2** (2026-10-24, `PS2X_TRACE_PATH2_TAGS=1`, decompiled with `tools/eedecomp.py`):
- **Im2D's packet** (`FUN_002FB690`, called through `FUN_002FB9D0`): `CNT` (3n + 1 qwords) with `DIRECT 3n + 1`, one
  PACKED GIFtag - NLOOP n, EOP, PRE with the RenderWare primitive as PRIM (`0x5D` fan / `0x5B` triangles / `0x4D`
  untextured fan / `0x25C` context-2 strip ...), NREG 3, REGS `0x512` = ST, RGBAQ, XYZ2 - then per vertex ST (u, v
  from the u16 fractions, Q 1.0), RGBAQ (the bytes, halved when `*0x488370`) and XYZ2 (x + 0x6C0 / y + 0x720 in
  1/16 pixel, minus 8: the half-pixel bias; z 32-bit). Every PATH2 packet that draws in normal play has this shape
  except a few effect strips.
- **Effect strips** in A+D packets: `PRIM`, then per vertex `UV` / `RGBAQ` / `XYZ2` register writes (the full-screen
  flat quads, 20 strips of 6 vertices; the reflection map's copies of FBP 140 into FBP 420, context 2, `PRIM 0x35C`
  with UV). Packets that set other registers before their `PRIM` (TEX0, ALPHA, TEST, ...) are state.
- The rest of PATH2 is A+D register setting and texture uploads (IMAGE).

**Frames outside gameplay** (2026-10-24): `FUN_0021ED88` is the main loop around `FUN_0021E950`, the per-frame
function (`FUN_0021CE80` begins the 3D frame - camera, clear, sky via `FUN_0018DDC0`; then the world, the 2D pass
`FUN_0021F348`, the menu `FUN_0021F7D8` -> `FUN_003B53F8`, and `FUN_0021DAD8(1)` ends the frame). **`FUN_0021E170`
is `LoadingScreen`**: its own frame - `FUN_0021CD20` begins it (clear), the splash full-screen through the sprite
routine `FUN_003DFF20` (raster from `FUN_0021DBF0`), the loading texts (`*0x486E64` 1..3), the progress bar
(`FUN_0021DFB0`, steps of 1/18 or 1/11) - and `FUN_0021DAD8(0)` ends it (kicked through `FUN_002723E8` like every
frame). It is called from many load paths (`0x346BAC`, `0x3C817C`, `0x45F3E4`, `0x46FE98`, `FUN_0021E950` when a game
is being loaded). **There is no title menu**: with an empty card the game goes from the loading screens straight into
the opening sequence (the reference scenes' "flyover"), where Start does nothing; the frontend menu is the pause menu.

### 6g. How a frame is put together (draw-list dumps, 2026-10-23)

From `PS2X_HW_DUMP` / F12 with `PS2X_HW_DUMP_BATCHES=4` at the hospital (-884, -470), noon and 20:00; the draw
log names the render target each copy reads (`src rt fbp=...`). The game draws a frame in one VBlank and nothing in
the next (30 fps). In order:

1. Opaque full-screen copy of buffer **140 -> 0** (240 vertices: strips) - the previous picture kept in FBP 0.
2. Sky gradient (24 vertices, `Cs*FIX`, z = far), cloud sprites (64x64, additive), horizon band (full width).
3. Alpha-only full-screen quad into 140 (FBMSK 0xFFFFFF), then the **native 3D** (~900-1300 world / lit draws,
   all into FBP 140).
4. Opaque full-screen **self-copy 140 -> 140** (120 vertices) - a shifted / filtered copy of the scene onto itself.
5. The reflection map: a 128x128 sample of 140 into FBP 420 plus sun glow sprites (not the radar - corrected
   2026-10-24); more 3D (particles, peds' second pass) into 140, the vehicles sampling 420.
6. Bloom: 256x256 ping-pong between FBP 420 and 452 (4 passes: clear `Cs*FIX` black, add the other at FIX 128 with
   tint 0x13), then added into 140 (`Cs*FIX + Cd`, FIX ~100).
7. Trails / colour: 512x512 downsample 140 -> FBP 384 (opaque), blended back into 140 at FIX 8 (`(Cs-Cd)*FIX+Cd`,
   624 vertices of strips) and added with a tint (0x10, 0x03, 0x09 at noon; 0x10, 0x01, 0x04 at 20:00).
8. Blend with the previous picture: FBP 0 -> 140 at FIX 16 (motion blur), alpha-only clear.
9. HUD / text at the far plane; the cinematic bars (zero height when closed) and text boxes (alpha 0x40).

**Where the lit models come (corrected 2026-10-31**, a frame dump on the user's card copy, `build\run\ao_explore.log`):
step 3's native 3D is the *world* only (kind 1, the prelit pipeline: sectors and buildings), then the water (large
blended draws with Z writes), the self-copy (4) and the reflection map (5); **peds and vehicles (native kind 2, the lit
pipeline) are drawn after the reflection map** - vehicles need it for their environment pass - followed by blob-shadow /
particle sprites (no Z writes), and only then the bloom. So the whole opaque 3D scene is in the Z buffer at the bloom's
first read of FBP 140 (its downsample into a 256-wide buffer; the reflection map reads 140 into a 128x128 corner of 420
first) - the point where render mods' screen-space passes run (NATIVE_RENDERER.md "Frame hook for render mods").

**The Z buffer's mapping and the camera's lens** (2026-10-31, from the native draws' window matrices, `sceneCamera` in
gs_hw.cpp): GS z = a + b / w with w the view depth in metres, a = 10424, b = 115,600-115,700 (both near-constant across
places; the GS z at the 0.3 m near plane is ~395,800 and at 2000 m ~10,480 of Z24's 16.7M - reversed, cleared to 0 = far).
Each draw's folded matrix is M = K V L: many world packets have L = a scale per axis (int16 positions,
game-internals 6d "42: position scale") times a placement, so M alone cannot tell the lens (fx, fy) from a squashed model
- but the camera-space images of the model's axes are orthogonal for any such L, which fixes fx and fy with the centre at
(320, 224). At 16:9 the lens is fx = fy = 1028.3 target pixels at 1920x1080 (the 70-degree FOV, Hor+: tan = 0.933 x
0.525); **in the hospital tutorial's scripted camera fy is 964, 15/16 of that, fx unchanged** - a 5:3 view window (one
of FUN_002653f0's aspect choices) instead of 16:9, so that shot is squashed vertically by 6% on a 16:9 screen (not
investigated further; the display code's Hor+ follows the aspect global).

**The post effects' exact draws** (2026-10-23, noon outside the barracks, 640x448 4:3, `PS2X_HW_DUMP_ALLVERTS=1`;
UV mapping per primitive fitted from the vertices, u = du/dx * x + offset in texels, x the GS position):
- Copy 140 -> 0 (frame start) and motion blur 0 -> 140 (`(Cs-Cd)*16/128 + Cd`): bilinear, **u = x + 0.5,
  v = y + 0.5** - on the GS (which samples pixel X at X) exactly texel X's centre: a plain copy.
- Self-copy 140 -> 140 after the 3D: point sampling, REGION_CLAMP, colour 0x7f, alpha 0, ZTST GEQUAL at z = 0 (only
  where nothing was drawn: the sky); strips with u = x + 0.94..1.88, v = 1.004 y + 0.94 - the sky shifted by about
  a pixel.
- Bloom: 640x448 -> 256x256 at FBP 420 (bilinear, 2.5 x 1.75 texels per pixel, +0.5), threshold `Cd - 255 * 35/128`,
  four blur passes (420 <-> 452: clear, then 35 quads at FIX 128 with colour 0x13 = a ~15% weight each, point
  sampling, tap offsets of a texel), added into 140 at FIX 100 (bilinear upsample, 0.4 x 0.57 texels per pixel).
- Trails: 640x448 -> 512x512 at FBP 384 (bilinear, 1.25 x 0.875), blended back at FIX 7 from 103 strips with offsets
  of up to 11 texels (a smear), then added at FIX 128 with a tint colour (0x10 0x03 0x09 at noon).
- A 128x128 sample of the picture (5 x 3.5 texels per pixel, no offset) goes into the corner of FBP 420, blended
  with what is there at FIX ~6-19 (a running average), plus an additive sun / glow sprite (64x64); right after,
  3D draws (vehicles, z ~0.001, blend FIX 6) are textured from that 128x128 corner - a reflection map refreshed
  every frame. After the bloom (which overwrites FBP 420) the sample is added again for the next frame.

**Pixel centres** (found from the copies above, fixed 2026-10-23): the GS samples a pixel at its integer position,
D3D at +0.5. Our renderer had drawn without the offset, so the copies (u = x + 0.5) read halfway between two texels:
the shown picture and the motion-blur feedback were averaged with their neighbours every frame - visibly softer than
the PS2 (barbed wire and fences smeared at 640x448). NATIVE_RENDERER.md "Post effects".

**Evening black frames (fixed 2026-10-23)**: between about 20:00 and 22:15 most frames came out black -
everything but the last text - with normal draw counts, native and VU path alike. Found by dumping the render target
after every full-screen draw (`PS2X_HW_DUMP_STEPS`): the scene in FBP 140 was fine until the bloom was added back
(step 6) and then 0 - the GPU copy of FBP 140 had been thrown away mid-frame. Cause, in our HW renderer, not the
game:
- In the evening the game uploads a 512x512 8-bit texture to block 8960 (page 280 = the Z-buffer area; Z is no
  longer needed by then). It also uploads a 16x16 CLUT at block 13588 (page 424, inside the bloom buffer FBP 420)
  and streams textures into the VRAM around 420 all the time (~6000 small uploads a second). VCS reuses VRAM freely.
- The renderer drops a render target (forgets its GPU copy) when an upload touches its pages. FBP 140 was tracked
  24 page rows tall (pages 140-380) instead of 14 (140-280), because the sky gradient's vertices reach y 738 and
  the height was taken from vertices, not from what the scissor (0..447) lets the GS write. So the Z-area texture
  "hit" the picture and dropped it. FBP 0 likewise stayed 32 rows tall after the boot-time clear of all VRAM.
- Fix (gs_hw.cpp `noteTarget`, `shrinkTargets`): a target's height is the last scissored line it can be drawn to;
  heights shrink back to what was drawn in the last 300 frames. Now 19:30-22:45 show a picture with the night
  bloom, and no target is dropped by the Z-area texture. A regression check (`tools/regress.py`, step "evening")
  keeps it fixed.
- Still dropped (as before): the bloom buffers FBP 420 / 384 when textures are uploaded around them, and the Z-clear
  view FBP 280. Copying uploads into targets block by block (`PS2X_HW_PATCH_TARGETS=1`) is exact but costs ~200 ms
  a frame with VCS's upload rate; it needs lazy patching (resolve only when the target is read) - milestone 3.

### 6h. The VU1 clipper and native drawing (GON_C3, 2026-10-23)

Found by the full mission smoke test: in mission 94 (`GON_C3`) the poolside cutscene showed the ground as black /
fog-blue on the native path, dim brown on the VU1 path (`PS2X_HLE=0`). `PS2X_HLE_VERIFY=1` was clean (26.5M
fast-path vertices exact, every cull decision right), and drawing only the *clipper* packets on the VU1
(`PS2X_HLE_CLIPPED`, now the default) reproduced the reference - so the difference is the GPU clipping that native
drawing used for packets the VU sends through its clipper. Not the cause (each tried and reverted): the GIF tag
(the kick's tag 49 is right - tag 50 is the second lit pass's, routine 0x2b2 = byte 0x1590, PRIM 0x20c: context 2,
untextured; stage table 0x19 always ends with 0x2b6 = 0x15b0, tag 49), perspective-correct ST, perspective-correct
depth, and the near / far clip planes.

The VU's clipper path, read from vu1_code_full.txt and reproduced bit-exactly in `src/game/vcs_vu_clipper.cpp`
(milestone 3, 2026-10-23):
- **Clip test 0x0c38** (all vertices, at least 6) writes per vertex three qwords to the output buffer: ST from the
  texture matrix *not* divided by w, with the clip-space w in lane w; the default colour (qword 51); the clip-space
  position (folded matrix 24-27). The 12 clip flags (plain in bits 0-5, guard band x 65 in bits 6-11) go into the
  input position's .w.
- **0x11f8** fog (when 52.y bit 1): F = clamp(53.w * w + 53.z, 0, 255) into the position's .w (w stays in the ST
  qword). **0x13d8** runs the backface pass 0x1440 when 52.y bit 0 (not reproduced: such packets stay on the VU1;
  none seen). The prelit colour stage then writes integer RGBA as on the fast path.
- **Kick 0x2b6 -> 52.z = 711 = 0x1638**, the per-triangle clipper. Tag 49's **w lane holds a second upper half with
  PRIM 0x7d** (triangle fan, IIP TME FGE ABE); the clipper builds its tags from it (y lane = 49.w). Qword 58 is an
  empty GIF tag (NLOOP 0, EOP) it kicks before every triangle - a sync, draws nothing.
- Per strip triangle (i, i+1, i+2): skip when the third vertex has ADC (0x8000) or all three share a plain flag;
  when no vertex crosses the guard band (flags & 0xfc0 = 0), emit the three as they are (0x23c0); otherwise copy
  them (colour as float) into a ping-pong buffer (66+1 / 111+1, four qwords per vertex) and clip:
  - planes (a x + b y + c w + d, from qwords 64..59): w > 0.3 (near, flag 32, routine 0x1b10), w < 2000 (far, flag
    16), y = -w, y = w, x = -w, x = w (flags 8, 4, 2, 1; 45-degree planes, routine 0x1f68) - each only when the
    polygon's OR of flags has its bit; inside / outside by the flag bit, intersection t = d0 / (d0 - d1), every
    lane of ST+w, colour and position lerped (a * (1 - t) + b * t, the inside vertex first), flags recomputed;
  - after the near plane, colours are multiplied by w (perspective-correct interpolation) and divided again when
    emitted (0x2608; after the near plane alone 0x2520 emits them undivided);
  - rejected when the AND of the output flags is non-zero; emitted as soon as no guard-band bit of a later plane is
    set (masks 1984, 960, 448, 192, 64, 0) - the GS scissor handles the rest.
- Emit: viewport matrix 12-15 applied to (x, y, z, w), / w, FTOI4 with the fog in F; STQ = ST / w; colours FTOI0
  after + 0.001. One GIF packet per polygon (fan, NLOOP = vertex count, EOP).

Checked with `PS2X_HLE_VERIFY=1` against the VU1's own XGKICKs (`runtime/ps2_vu1_tap.h`): GON_C3 98,906 clipped
packets / 1,199,117 GIF packets, the reference scenes 143,963 / 2,837,560 - all exact (ST, Q, RGBA, XYZF2; STQ.w is
not read by the GS). Native drawing hands those packets to the GS as PATH1 (`PS2X_HLE_CLIPPER=0` = the VU1; the
GPU clipping that drew the ground black is `PS2X_HLE_CLIPPED=1`). Cost over the reference scenes, means per
section: flyover render 14.6 ms (GPU clipping 14.1, VU1 17.7), cutscene 11.8 (11.3, 14.5), gameplay 5.9 (5.6, 7.6);
frame time at the 30 fps cap again. The intro office, which the stage-5 notes called black on the VU clipper, draws
correctly on it.

### 6i. RSL submission: how a frame's packets are built (2026-10-24, docs/RSL_SUBMISSION.md phase 0)

Found by decompiling the candidates (`tools/eedecomp.py`, headless Ghidra on the analysed EE project; output in
`build/analysis/decomp/`), a scan of the code for the packet buffer object, and two runtime measurements:
`VCS_TRACE_RSL=1` (before-hooks on every function that moves the cursor; bytes per function per frame,
`src/debug/rsl_trace.cpp`) and `PS2X_CHAIN_CENSUS=1` (every VIF1 chain tag by where it sits, its id and where its data
comes from).

**The packet buffer** is an object at `0x520F90`: +0x14 the half in use (two halves of 0xE6670 bytes from +0x20),
+0x18 the DMA cursor growing up from the half's start, +0x1C a data pointer growing down from its end.
`FUN_00476770` = bytes used (both ends), `FUN_00478628` = bytes free (checked before each write). About 33 functions
write it (the scan: `0x2F0360..0x2FB690`, `0x1CEF18`, `0x266868`, `0x2A92C0`, `0x2ABF68`, `0x32CD60..0x32D880`,
`0x40C430`, `0x40F6C8`).

**State, then draw.** RSL keeps render state in memory and writes it into the buffer only when a draw needs it:
- Matrices: blocks at `0x520860..0x520B8C` (view / projection / object, with dirty flags); `FUN_002F7620` computes the
  camera's. `FUN_002F8710` is the **state flush**: every dirty block as CNT + UNPACK into VU1 memory. Small setters
  upload single constants directly: `FUN_002F7090` (3 qwords at VU 0x2c = 44-46, the texture matrix),
  `FUN_002F9FA0` (one vector), `FUN_001CEF18` (3 qwords at VU 0).
- GS registers: queued as A+D pairs at `0x729510`, count at `0x488308`; each draw (and `FUN_002F7B30` on its own)
  sends the queue as one DIRECT GIF packet (CNT, `0x51` DIRECT, tag `0x1000000000008000 | n`).
- Textures: the texture bind `FUN_00408F30` -> `FUN_00317FB8` (material) -> `FUN_002F62B8` / `FUN_002F6A78` queue
  TEX0 / CLUT state and, when the raster is not resident, its upload: `FUN_003298D8` keeps a binary tree of transfer
  headers (nodes of 0x70 bytes from `0x6EE3F0`, pool at `*0x488760`, used / max `0x4CD58C` / `0x4CD588`: a cached
  BITBLTBUF / TRXPOS / TRXREG / TRXDIR packet per destination) and writes two REF tags - the header packet and the
  image - both sent as VIF DIRECT (PATH2).
- **Texture streaming** (2026-10-24, `FUN_002F62B8` decompiled; `PS2X_HW_UPSTATS=1`): `FUN_002F62B8(slot, psm,
  log2 w, log2 h, mip count, ..., source address, flags)` uploads a raster into a fixed VRAM slot - base
  `*(0x742B30 + slot * 8)`, each further mip at the next 64-block boundary - and skips everything only when the slot's
  key `0x742B50[slot]` (psm, sizes, mips, source) is unchanged. Flag bit 0 per mip: T8 uploaded as CT32 (and T4 as CT16)
  at half width / height - the RAM data is laid out for that. It then queues TEX0 (with the CLUT) / TEX1 / MIPTBP1 /
  MIPTBP2 for the draw. The texture's CLUT is uploaded with it, so while driving every bind uploads texture + CLUT
  (~390k uploads / 5 s, nearly all the same slots again). The header packet ends with the IMAGE GIFtag; the pixels
  follow in the next DIRECT: a REF straight to the raster in RAM whose VIFcodes are `NOP; DIRECTHL n` with n = its
  qwc (how docs/FULLY_NATIVE.md step 3d names textures by raster). T4 textures (the radar tiles among them) are sent
  as CT16, and their CLUT goes into the same GS page right after (other blocks).
- **Draws**, each starting with the state flush and the GS-register queue:
  - `FUN_002F7D58(packet)`: a **model instance** - CALL to the model's prebuilt packet in the model heap (444 calls a
    frame while driving); `FUN_002F80A0(packet)` the same shape (a variant);
  - `FUN_002F7EB0(addr, qwc)`: **world geometry** - REF to a sector's prebuilt packet in the streamed cells (called by
    the sector draw `FUN_002409C8`, whose texture / material setup is itself cached: the first frame copies the
    setup packet into a block on the heap at `0x6F3DB8`, later frames CALL it);
  - `FUN_002F8250(...)`: REF with its own UNPACK / MSCAL (immediate geometry);
  - `FUN_002FB9D0` -> `FUN_002FB690`: **Im2D** (the 2D primitives of 6f: CNT + DIRECT, vertices converted from the
    16-byte Im2D format; 515 calls a frame while driving).

**Measured** (one bench run, i7-7700K, 60 fps cap; per frame):

| | standing in the city | driving (AI car) |
|---|---|---|
| bytes built in the packet buffer | 90-150 KB | ~470 KB |
| VIF1 chain | 720-1,300 tags, ~33-48k payload qwords | ~9,600 tags, ~294k qwords (~4.7 MB) |

Driving, by function (bytes are charged to the hooked function entered last, so a draw's own CALL / REF lands on
`FUN_002F8710`, which every draw enters first): `2F8710` 848 calls / 135 KB, `2FB690` 515 / 125 KB (2D),
`2F62B8` 326 / 64 KB (textures), `2F7090` 304 / 33 KB, `2F7908` 238 / 23 KB, the rest < 20 KB each. The chain while
driving: REFs from cell packets to data in the `0x6EDC70..0xCB7A80` range 78k qwords, the per-frame REFs into the
model heap 55k, cell geometry 34k, CALLed model packets 31k, per-frame CNT data (2,250 tags) 16k, VU1 code (REFs to
`.text`) 8k. **About 10% of what VIF1 receives is built each frame; the rest is prebuilt** (cells, model heap,
cached blocks).

Game thread while driving (`VCS_PROFILE=5`, `VCS_PROFILE_GUEST_FILE`, the two drive windows: 70% guest code, no
waiting): the RSL range `0x2F0000..0x2FD000` 12.5% of samples (the packet emitters 10.1%), the world sector walk 1.5%,
plus `memmove` 3.8% (the runtime flattening the ~4.7 MB chain when it is kicked) - **about 17% of the game thread,
~3 ms of a ~19 ms frame**, goes into building and handing over packets. The rest is spread thin (no other function
above 2.3%).

**Coverage of the draw functions** (docs/RSL_SUBMISSION.md phase 1a, `VCS_RSL_SHADOW=1`, `src/debug/rsl_shadow.cpp`):
before-hooks record every call of the draw functions with its argument and the cursor at entry; as the runtime copies
the frame's chain (`runtime/ps2_chain_observer.h`) each packet-buffer tag is placed in the record whose range holds
it. Every draw wrote exactly its own tag - a model instance a CALL to its packet, a world draw a REF to its geometry
(address and qwc): city spot (1325, -325) 394 model / 42-47 world draws a frame, driving 495 / 79 plus 19.5 immediate
(`FUN_002F8250`) - **all matched**. The only VU1-bound tags outside a draw's range (7 a frame standing, 14 driving)
are state: at the frame's start `FUN_002F53D8` and `FUN_002F9FA0` CALL the camera object's packet (`0x16E7B90`,
object at `*0x4882DC` + 0x10), the sector draw `FUN_002409C8` CALLs its cached setup blocks, one CALL follows a
`FUN_001CEF18` upload. The blocks allocated from the top of the half (+0x1C) hold only RET tags (the ends of CALLed
per-frame blocks). All 32 functions that store the cursor (a scan of the code following register copies) are hooked.

**What a draw carries in state** (`FUN_002F8710`, the flush every draw runs first; dirty bits in `0x4882A0`):
bit 0 CALL the current object's packet (object `*0x4882A4` + 0x10) and its plug-ins' callbacks (object + 0x114 list,
+0x48); bit 1 CALL `*0x4882A8`; bit 2 three qwords from `FUN_001CFAE0(object + 0x134, ...)`; bits 0 / 4 with 0x200 /
0x400 MSCAL 0x4A / 0x75 (the setup programs 0x0250 / 0x03A8, 6d); bit 0x2000 CALLs from the table at `0x742AB0`;
bit 8 UNPACK 5 qwords to VU 49-53 (the GIF tags, colour, flags, fog) from `0x742AE0`; bit 0x1000 UNPACK the viewport
(VU 12-15) from `0x520920`, MSCAL 0x8F (setup 0x0478), the guard band (VU 65) from `0x520AC0`.

**Where a draw program's VU state comes from** (phase 1b, `VCS_RSL_SHADOW=1`: each MSCAL of 0x0030 / 0x02C0 is tied to
the draw whose stream started it by its offset in the copied chain, and the VU memory it starts with is compared with
the draw's RSL state snapshotted at the draw call; the map below found from `VCS_RSL_SHADOW_DUMP` samples):

| VU qwords | what | RSL source | same as the RSL source |
|---|---|---|---|
| 0-3 | object matrix | `0x520860` | 85-97%; the rest whole matrices the chain itself uploads (object packets, cell data) |
| 4-11 | camera matrices | `0x5208A0`, `0x5208E0` | 100% |
| 12-15 | viewport | `0x520920` | 63-98%; the rest a depth range (rows 14-15) some model packets upload, which stays for the draws after them |
| 32 | camera position | `0x520990` | 100% |
| 34-37 | setup slot table | render context (`*0x4882A4`) + 0x60 | 100% |
| 49-51, 53 | GIF tags, colour, fog | `0x742AE0` | 100% |
| 52.y | flags | `0x742AE0` + 0x34 | 100% (52.x / .z are written per packet / by the programs) |
| 59-64 | clip planes | `0x5209A0` | 100% |
| 65 | guard band | `0x520AC0` | 100% |
| 16-31 | view, clip and window matrices | computed by the setup programs (6d) from the rows above | - |

Every differing value is accounted for (bench run: city spots and the drive, 0.000% unexplained): uploaded by the
draw's own stream (its state flush, setters, its packet), carried over from an earlier draw (VU memory persists), or a
whole block uploaded earlier in the chain. World draws match the RSL state completely; model draws add their packets'
own state. The "render context" (`*0x4882A4`) is not a per-instance object: a few values recur (`0x16EEEC0`,
`0x16EF040`, `0x16EF1C0`); the per-instance matrix is the block at `0x520860`.

**Sectors cache their own packets** (2026-10-25, `FUN_00240ED8` read from its decompile; found when packet-buffer
tags turned up in the chain of later frames). `FUN_00240ED8(level, sector entry)` draws a sector through
`FUN_002409C8(level, sector, pass)`, and the first time a sector is drawn in the caching branch (the frustum test
`FUN_002F7528` not 2, `*0x487484 >= 60.0`, the entry's cache word `entry + 4` still 0) it notes the cursor, lets
`FUN_002409C8` write the sector's packets (its material setup, the GS registers and every world draw's flush, GS packet
and REF), puts a RET after them, copies the whole range into a block allocated from the pool at `0x6F3DB8`
(`FUN_002BC730`, copied by `FUN_0045CE10`), stores the block in `entry + 4` and draws it with `FUN_002F7D58(block)` -
a model draw of the copy. Later frames only make that model draw: the sector's packets as written on the first frame
are sent again for as long as the block lives. The caching call of `FUN_002409C8` returns to `0x241060`. (When the
pool has no room the sector is drawn a second time by a plain call and the first copy's packets stay in the buffer.)
`FUN_002409C8` itself caches each material's setup the same way (texture bind, `FUN_002F7B30`'s GS packet) into a
block at `entry + 4` of the material and CALLs it on later frames: the cursor noted, `FUN_00408F30` called from
`0x240D14` (returns to `0x240D1C`), `FUN_002F7B30` from `0x240D1C` (returns to `0x240D24`), the range copied by
`FUN_0045CE10` at `0x240D9C`. Code that writes something frame-specific into
the packet buffer while a sector is cached therefore has it sent again in later frames - the draw items of
docs/FULLY_NATIVE.md step 4c stay packets there.

**A world block** (the REF payload of `FUN_002F7EB0`, sector geometry in the streamed cells; listed from a RAM dump,
2026-10-24) is one shape throughout: per packet `UNPACK V4-32 x1 -> TOP+0` (the header: count, nloop), `STMASK`,
`STROW`, `UNPACK V3-16 x n -> TOP+1` (positions, masked: w from ROW), `STMASK`, `STROW`, `UNPACK V2-8 usn x n -> TOP+0x48`
(UVs, masked), `UNPACK V4-5 x n -> TOP+0x8F` (colours), `MSCAL 6` (program 0x0030) - no constants; everything else the
world program reads is VU-resident state from the draw's flush (6d table 0x19). Sizes seen: 208-2,340 qwords, packets
of up to 70 vertices. Phase 2 draws these from recordings (docs/RSL_SUBMISSION.md).

**A model packet** (the CALL of `FUN_002F7D58` / `FUN_002F80A0`; decompiled with `tools/eedecomp.py`, packets listed
from a RAM dump and checked by the phase 2 recorder, 2026-10-24):
- Both functions run the state flush, write the queued GS registers (`0x729510`, count `0x488308`) as a
  `CNT` + `DIRECTHL`, then `CALL a0` with qwc 0 and VIFcodes 0 (`a0 << 32 | 0x50000000`). `FUN_002F80A0` first CALLs
  the packet at `*0x48830C` when bit 31 of the dirty word `0x4882A0` is set (and clears it) - a state packet shared
  by the draws after it.
- The CALLed packet is a sub-chain, not one block: up to ~64 tags (`CNT` with inline data, `REF`s into the model
  heap - e.g. 6-qword constant blocks shared between packets - and a closing `RET`); single-packet models are one
  `RET` with its payload. VIFcodes seen: FLUSHE, UNPACK V4-32 (constants: matrices, the depth range of 6i's VU table
  rows 14-15), DIRECTHL (GS registers), STMASK / STROW, UNPACK V3-16 / V2-8 / V4-5 / V3-8, STCYCL, MSCAL 0x0030
  (most), 0x0478 (setup) and 0x02C0 (re-draw).
- **Fields an UNPACK leaves alone**: an unmasked V3 / V2 UNPACK writes only x y z (x y) - w keeps what VU memory held
  (the runtime's VIF interpreter; not checked against hardware) - and masked UNPACKs leave write-protected
  fields (mask 3). Skinned packets rely on it: two recordings of the same packet bytes differed only in such a w
  (`0x802A` / `0x801A`), left by the packet drawn before.
- **Other CALLs** in the packet buffer: packets at `0x1FDA020`-`0x1FDA120` (320-1,088 bytes) are rebuilt every frame or
  every other frame; a few state packets in the `0x16EExxx`-`0x16EFxxx` render-context blocks (6i above) use VIF BASE.
- Volume at city spot (-700, -500), per 10 s: 248k `FUN_002F7D58` CALLs, 106k `FUN_002F80A0` CALLs, 89k other CALLs,
  61k world REFs; ~1.29M draw program MSCALs among them.

**Texture uploads** (2026-10-25, from the decompiles of `FUN_003298D8`, `FUN_002F62B8`, `FUN_002F6A78`; native as
reference ops since FULLY_NATIVE.md step 5b):
- `FUN_003298D8(slot, psm, log2 w, log2 h, bytes, source, dest)` writes **two REFs into a 32-byte slot its caller
  reserved**: one to the destination's transfer header (qwc 6, VIFcodes FLUSHE, DIRECTHL 6) and one to the pixels
  (qwc `bytes / 16`, VIFcodes NOP, DIRECTHL `bytes / 16`). The header is a 0x70-byte node of a binary tree rooted at
  `0x6EE3F0`: key at +0x60 = `(dest >> 6) << 48 | (psm & 0xFFFF) << 32 | (h & 0xFFFF) << 16 | (w & 0xFFFF)` (compared
  unsigned; smaller keys left at +0x68, larger right at +0x6C), the packet at +0x00: GIFtag `0x1000000000000004` A+D,
  BITBLTBUF (0x50), TRXPOS (0x51), TRXREG (0x52) from the sizes, TRXDIR (0x53) and the IMAGE GIFtag
  (`bytes >> 4 | 1 << 59`). A missing node is made from the pool at `*0x488760` (used / max `0x4CD58C` / `0x4CD588`);
  with the pool full both REFs are written empty (qwc 0).
- `FUN_002F62B8` (the bind into a VRAM slot) reserves 32 bytes per mip level and calls it for each (128 bytes and
  `FUN_00266608` instead when `*0x488318 == 0` - not seen), then writes a CNT 5 with DIRECTHL 5 (A+D: TEXFLUSH, MIPTBP1,
  MIPTBP2 for the slot, register 0x42, TEXFLUSH) at the cursor, and queues TEX0 into `0x4882E0 + slot * 8` with the
  dirty bits. `FUN_002F6A78` (the CLUT) reserves 32 bytes for one call (CT32 16x16 or 8x2 by the palette size) and may
  write a CNT 2 (A+D: register 0x42, TEXFLUSH).

**Im2D's packet writer** `FUN_002FB690(prim, n, vertices, indices, context, screen)` (2026-10-25, from the recompiled
code's disassembly; its only caller is `FUN_002FB9D0`, which does not touch the packet after it): nothing while
`*0x488398` is set; else one CNT of 3n + 1 qwords whose VIFcodes are NOP, DIRECT 3n + 1. The GIFtag: NLOOP n, EOP,
PRE, PRIM = prim | IIP | TME (when the context's texture entry `0x6EDCBC + context * 4` is set) | ABE | CTXT (context << 9), NREG 3, REGS
`0x512` (ST, RGBAQ, XYZ2). Per vertex (16-byte Im2D vertices, through the index list when there is one): ST = the
16-bit u / v * 2^-15 with Q 1.0 (kept from the vertex before when untextured), RGBA from bytes 4-7 with alpha halved
(every channel halved while `*0x488370` is set), XYZ2 = ((x + 0x6C0) << 4) - 8, ((y + 0x720) << 4) - 8 from the
16-bit coordinates (or x << 4, y << 4 when `screen` is set) and Z = the 32-bit word at +0xC through int -> float ->
int. The HUD layer draws these (NATIVE_RENDERER.md "HUD layer"); since FULLY_NATIVE.md step 5c they reach it as ops.

**The frame's fixed structure** (2026-10-25, `PS2X_DUMP_CHAIN=<n>` - every tag of one kick - read with the census).
The chain starts in the static root list (`0x480D20` / `0x480DE0`, 6a): CALLs to fixed packets in `.data` around
`0x480EA0`-`0x481760` that send GS setup (CNT + DIRECT), VU1 setup (CNT STCYCL + UNPACK, NEXT, CNT MPG - VU1
microcode - and RET with an MSCAL) and finally a NEXT into the packet buffer's half. **Render-context packets**
(CALLed by the state flush, bits 0x1 / 0x2 / 0x2000; in the model heap and the heap) open with a REF whose VIFcodes
are **BASE / OFFSET** (VU1's double buffer), then CALL a block of **MPG REFs into `.text`** (the draw programs: e.g.
five of 128 / 112 qwords from `0x2AC130`, one of 27 from `0x25E890`, three from `0x368730`) and end with a REF of the
context's matrices (STCYCL, UNPACK) and an MSCAL. Every frame re-sends the same microcode (the runtime copies it only
when it differs). The Z clear (6a: 40 column strips) is a VU1 program in the chain, run natively (`zclearProgram`,
`src/game/vcs_hle_world.cpp`).

**The other packet writers** (2026-10-25, step 5d of FULLY_NATIVE.md; callers from the recompiled code's `jal`s, shapes
from decompiles and the census of what each writes): `FUN_002F8250` is **Im3D's submit** (called by `FUN_002FC2E8` /
`FUN_002FC838`, `FUN_002FC210` writing the vertices): it runs the state flush, then REFs the vertices with an UNPACK
and an MSCAL. `FUN_0040F6C8(vu, src)` (called by `FUN_0040F798`) writes one CNT with a 9-qword UNPACK and returns 9;
`FUN_002A92C0(program, block)` (called by `FUN_002A9538`) writes a CNT UNPACK, a REF to the block's data with an UNPACK
and an empty REF carrying an MSCAL - immediate geometry with its own program. `FUN_0040C430` and `FUN_00266868` have
no direct callers (reached through function pointers - plug-in or pipeline callbacks). `FUN_002F0360` and
`FUN_0032D880` (which calls `FUN_0032D480` / `FUN_0032D7C8`) are called from `FUN_001ACE40`; `FUN_002F39D8` from
`FUN_0035C9E0`, `FUN_002F3DD0` from `FUN_002F4080`, `FUN_002F5520` from `FUN_0018F1C8` / `FUN_0018F450`, `FUN_002ABF68`
from `FUN_002AC048`. None of them patches its packets after returning (checked: every captured region is unchanged
at the kick).

**The state setters** (2026-10-25, decompiled before / read from the recompiled code's disassembly comments; native as
state ops since FULLY_NATIVE.md step 5a):
- `FUN_002F7908` and `FUN_002F7B30` are the same code: queue FOG (6) / FOGCOL (7) / registers 0x14 / 0x15 by the
  dirty bits 0x80 / 0x100 / 0x20 / 0x40 (values at `0x4882E0` / `E8` / `F0` / `F8`), clear bits 0x1E0, and when the
  queue is not empty send it as the draws do (CNT n + 1, FLUSHE, DIRECTHL n + 1, GIFtag `0x1000000000008000 | n`, the
  pairs) and empty it.
- `FUN_002F7090(m)`: CNT 3, FLUSHE, UNPACK V4-32 x3 -> VU 0x2C, the three qwords at `m` (the texture matrix, VU
  44-46; with too little room it writes them through a null pointer).
- `FUN_001CEF18(vu, m)`: CNT 3, FLUSHE, UNPACK V4-32 x3 -> VU `vu` (the code word `vu | 0x6C030000`), the three
  qwords at `m`; returns 3. No room check.
- `FUN_002F9CE8()`: CNT 0 with NOP, FLUSHA.
- `FUN_002F9FA0(x, y, z)` runs the flush, then an UNPACK of a vector computed with float divides (`/ 65535.0`,
  `* -32768.0`); `FUN_002F53D8(...)` the frame's camera packet: CNT 0 (STCYCL 1 1, FLUSHA), CALL `*0x4882DC + 0x10`,
  dirty word `0x3E1F`.

**The state flush** `FUN_002F8710` (decompiled with `tools/eedecomp.py`, 2026-10-24; native in
`src/game/vcs_rsl_native.cpp`, byte-exact against the original). The dirty word `0x4882A0`, in the order written:
- 0x1 render context `*0x4882A4` changed: `CALL context+0x10`, then each plug-in on the context's list (head
  `context+0x114`, end `context+0xB0`, next `+0x64`) with a callback at `+0x48` is called (args at `+0x54` / `+0x58`);
  0x2: `CALL *0x4882A8`; 0x4: `FUN_001CFAE0` -> UNPACK of 3 qwords; then the plug-ins' `+0x4C` callbacks (bit 0x1) or
  `+0x50` (bit 0x10 alone); 0x11 unless 0x600 are both set: MSCAL 0x75 / 0x4A (the ones bits 0x400 / 0x200 do not
  send themselves).
- 0x2000: three CALLs from the table `0x742AB0[*0x4CD57C]`; 0x8: UNPACK V4-32 x5 -> VU 0x31 from `0x742AE0`;
  0x1000: viewport `0x520920` -> 0x0C (4 qw, MSCAL 0x8F) and `0x520AC0` -> 0x41; 0x800: `0x5208E0` -> 0x08 (MSCAL
  0x8F) and lights `0x5209A0` -> 0x3B (6 qw); 0x400: `0x520990` -> 0x20 and `0x5208A0` -> 0x04 (MSCAL 0x83); 0x200
  (when `*0x4882B0 == 0`): the instance matrix `0x520860` -> 0x00 (MSCAL 0x3C), or a REF to `*0x4882B8` instead.
- GS registers to the queue `0x729510` (`{value, register}` pairs, count `0x488308`; the draw sends them as a
  `CNT` + `DIRECTHL` right after the flush): 0x80 FOG (6) `0x4882E0`, 0x100 FOGCOL (7) `0x4882E8`, 0x20 register
  0x14 `0x4882F0`, 0x40 register 0x15 `0x4882F8`. The word is left with bit 31 only.
- **The plug-in callbacks** (2026-10-25, `VCS_RSL_PLUGIN_LOG=1`: which callbacks the flushes would call, while
  driving; the callers' code read from the recompiled functions): only `+0x50` callbacks (bit 0x10 without 0x1) occur,
  called as `cb(node[+0x34], node[+0x54], node[+0x58])` in the list's order, after the CALLs of bits 0x1 / 0x2 and before
  the MSCALs; their return values are not used. Four functions: `0x1CEF90` = `FUN_001CEF18(vu, src)` (CNT 3: 3 qwords
  -> VU `vu`), `0x40F798` = `FUN_0040F6C8(vu, src)` when the word at `src + 0x90` is set (CNT 9: 9 qwords, and the word
  cleared), `0x2A9538` -> `FUN_002A92C0` and `0x2F4080` -> `FUN_002F3DD0` (immediate geometry with REFs and their own
  program). The first two are ~85% of the callback flushes; the native flush writes them since FULLY_NATIVE.md 5f.
- **Inside a draw, by return address** (2026-10-25): a hook cannot tell "inside a draw" from "after it" by the guest
  stack pointer alone - a draw's caller often calls a helper next, whose own draws run deeper on the stack than the
  first draw did. What runs inside a draw is called from the draw function itself (`FUN_002F7EB0` 0x2F7EB0-0x2F8024,
  `FUN_002F7D58` 0x2F7D58-0x2F7EAC, `FUN_002F80A0` 0x2F80A0-0x2F8250), its flush (`FUN_002F8710` 0x2F8710-0x2F937C),
  the callback wrappers (`0x2A9538`, `0x2F4080`, `0x40F798`, `0x1CEF90`) or `FUN_001CFAE0`: a hook is inside a draw
  when it is deeper on the stack *and* its `$ra` lies in one of those (bounds from `game/vcs/functions.csv`). With
  stack depth alone every later draw of the caller's helper counted as "inside" (items fell from ~31k to ~12k per 10 s
  while driving).
- **Emitters draw models** (2026-10-25): some captured emitters call the RSL draw functions inside them (the draws run
  the original there: their packets belong to the emitter's region). The draws' tags then sit inside the emitter's
  region, in the order the draws were made. A region that takes such a tag into an item must also drop the draw from
  the frame's draw list - the walker matches the list against the chain's tags in order, and one missing tag puts it
  out of step for the rest of the frame: no model packet is ever learned (`not known`), and standing at Fort Baxter no
  model draw became an item at all.
- **The texture binds' own packet** (2026-10-26, `VCS_RSL_CENSUS=2` and a dump of the payloads): after its uploads
  (`FUN_003298D8`, called at 0x2F660C), `FUN_002F62B8` writes a `CNT 5` + `DIRECTHL 5` itself (0x2F66A4 on: reserves
  0x50 bytes after `FUN_00478628`'s free-space check) - an A+D GIF tag with TEXA (0x3B), MIPTBP1_1 (0x34), TEX2_1 (0x36,
  the CLUT load) and TEXFLUSH (0x3F); values from the bind's locals and the table at 0x742B30. ~80 a frame while
  driving. The binds reserve their upload slots first and fill them through `FUN_003298D8`: a capture must never read
  the buffer between the two (half-filled slots).
- **Callers hold the cursor across calls** (2026-10-26): `FUN_00240ED8` keeps the start of the range it copies into a
  sector's cache across its call of `FUN_002409C8`; moving the cursor back at a hook point inside that call shifted the
  copied range (the frame lost its alpha pass, effects, HUD and post passes). Packets may be taken at any hook point,
  but the cursor may only move back where no caller can hold it - in practice: only for an emitter / draw region
  settled at its own stack level, never for a gap (FULLY_NATIVE.md 5h).
- **The material cache's last packet** (2026-10-26): `FUN_002409C8` calls `FUN_002F7B30` at 0x240D1C+8 (return
  0x240D24) to write the material's GS packet, and copies the material's packets (bind and that GS packet) into its
  cache after it returns - the window covers that packet, so it ends at the next hook point, not at the call.
- The buffer's free space is `0xE6670 - FUN_00476770(0x520F90)` (`FUN_00478628`); with too little the flush writes
  through a null pointer (never seen). While driving ~9% of flushes have plug-in callbacks (skinned / effect
  plug-ins) and ~1% bit 0x4; those still run the original.

### 6j. The helicopter's dust: the heaviest fill in the game (2026-10-30)

Found from a user report (frame time spiking at 3x internal resolution while a helicopter flew low): a 4-star wanted
level brings the police helicopter, and while it hovers near the ground the game draws its rotor dust as **one GS-path
draw a frame of ~1,040 large triangles** (~3,100 vertices, quads as triangle pairs; texture 32x32, bilinear, REPEAT;
blend `Cs*FIX + Cd` with FIX 128 - additive - colour 0x03-0x13; ZTST GEQUAL, no Z write). Measured from an F12 draw log
with every vertex (`PS2X_HW_DUMP_ALLVERTS=1`, triangles clipped to the screen): **60-66 full screens of overdraw**,
~18 Mpixels at 640x448 - on the PS2's GS (~1.2 Gpixel/s textured) about 15 ms, so the effect is heavy on the console
too. A few smaller draws with other 32x32 textures (the same blend, up to ~6 screens) go with it. At 3x internal
resolution in 16:9 (2560x1344) it is ~206 Mpixels a frame through the GS-emulating pixel shader: that, not the CPU, was
the spike (NATIVE_RENDERER.md "The GS bilinear by Gather", PERFORMANCE.md section 15).

How it was found: the perf line showed the render worker and the GS stage mostly waiting (sampling profiles of both
threads: ~85% in a wait), the main thread too (~90% in `ZwWaitForSingleObject`: on the GPU); the overlay's "GPU" figure
is the main thread's submit time, not GPU time. `PS2X_GPU_TIMING=1` (timestamp queries per draw) then put 46 of 61 ms
of a presented frame on `gs draw fbp 140 tex blend`, and per texture key on this one 32x32 texture.

Seen on the way (not the helicopter's doing - the same before it arrives, every frame): the GPU targets of the effect
buffers FBP 420 and 384 are re-created ~4 times a frame. A 16x16 CLUT upload at block 13588 (page 424, inside both
buffers' pages) drops both targets every frame (`PS2X_HW_LOG_DROPS=1`); FBP 420 is then made at the window scale for
the reflection map's 128-wide draws (role windowScale, 4.0 x 3.0 at 3x 16:9), regrown at 3x for the bloom's write-back
(fbw 4), and back again - each a new texture plus a rescaling blit (`PS2X_RHI_LOG_CREATES=1` lists them). The CLUT is only
the first of many: with patching on (`PS2X_HW_PATCH_TARGETS=1`, every upload kept in the target) ~75 uploads a frame
land in the pages of FBP 420 / 384 - the game streams textures into its effect buffers' memory, which is why patching
them all costs so much and why they are dropped. Fixed 2026-10-30 without changing what a target holds (PERFORMANCE.md section 15): one scale per FBP (any
windowScale role there), a dropped or outgrown target's texture reused by the next target of its size (cleared as a new
one), a dropped target re-made at the size it had. The drop itself stays (the reflection map starts from cleared each
frame, as before).

### 6k. Plane trails and RenderWare's Im3D line clipper (2026-10-30)

Found from a user report: long thin white lines across the picture in the morning, starting at the white trails that
planes leave in the sky (seen outside the Little Havana Empire site, 08:28, 16:9 - and at 4:3 too).

- **The trails** (VC's `CPlaneTrails`): six of them at `0x50B5D0`, 0x140 bytes each - 16 points (`CVector` + pad, 16
  bytes) then 16 times (`u32` ms, at +0x100). Drawn by `FUN_00245A28`, which calls **`FUN_00245768` = `CPlaneTrail::
  Render(this, visibility)`**: `CCamera::IsSphereVisible(TheCamera 0x6F44D0, point 0, 1000)`, alpha = visibility * 110,
  a point older than 30 s (`now - time >= 30001`, the clock at `0x4CD104`) gets time 0 and is skipped, the rest go to
  a vertex buffer at `0x709650` (stride 0x18, white, alpha fading over the last 10 s), then `RwIm3DTransform`
  (`FUN_002FBFA8`) and `RwIm3DRenderIndexedPrimitive(2, 0x4873B0, 2 * (n - 1))` (`FUN_002FC2E8`; the static
  indices 0,1,1,2,...). The points are 500-600 units up and sane (read with the rig while the lines showed).
- **Lines go through the EE, not the VU1**: `FUN_002FC2E8` with type 2 loops over the index pairs and calls
  **`FUN_002F95E0`, the line clipper**: each end to clip space (`FUN_001AAA38`, the VU0-macro matrix multiply with
  the camera's matrix at `0x520A80`), clip flags from **`FUN_0032E508`** (`ctc2 $zero, vi18; vclipw.xyz vf1, vf1w;
  cfc2 $v0, vi18`), trivial reject on a shared outside bit, otherwise a cut per plane by bit (`FUN_002F97F0`, plane
  table `0x5209A0`, 16 bytes a plane), then emitted as a PATH2 GIF packet (ST / RGBAQ / XYZ2, `FUN_002F9AA0`).
  `FUN_0032E508` is the only VCLIP in the EE code.
- **The bug was the recompiler's VCLIP**: it set bit 0 for x < -w and bit 1 for x > +w (swapped; the VU sets bit 0
  for x > +|w|, bit 1 for x < -|w|, then y, z) and compared with w, not |w|. A trail segment leaving the view on the
  right was cut at the left plane; the side planes meet at the eye, so the cut point landed next to the camera (w
  0.11 - 0.12, Q ~8.9 in the F12 log) and its projection, far outside the GS's 16-bit coordinate range, wrapped to
  anywhere on screen: a line from the trail across the picture. Fixed in `ps2xRecomp/src/lib/vu_translator.cpp`
  (the VU1 interpreter's CLIP, `ps2_vu1_upper.cpp`, was right); `VCS_SELFTEST=1` checks the flags.
- How it was found: F12 with `PS2X_HW_DUMP_ALLVERTS=1` showed one line draw with one vertex at Q 8.9 and the same in
  every path (compiled / interpreted VU1, `PS2X_HLE=0`, the GS front end), so the game itself sent it; a trace of the
  kicks showed PATH2 and no ADC; `VCS_TRACE_IMMEDIATE=1` (callers of the Im2D / Im3D entries, `vcs_overrides.cpp`)
  named `0x245904` in the trail renderer.

### 6l. Coronas, sprites, stars, signals, draw distance (2026-10-31, Project2DFX)

Found porting ThirteenAG's Project2DFX for the PCSX2 fork (its MIT source names the addresses it patches:
github.com/ThirteenAG/III.VC.SA.IV.Project2DFX, `source/console/GTAVCS.PCSX2F.Project2DFX`), each checked in the
generated code and a headless Ghidra decompile (`src/game/vcs_project2dfx.cpp` uses them; since 2026-10-31 the
Project2DFX.asi mod, spartaque12/VCS-mods `plugins/Project2DFX`: its float helpers are a copy of the runtime's, built with
the exe's `-ffp-contract=off`, docs/MODDING.md).
- **CCoronas::Render = `FUN_0027C418`**, called once a frame at `0x21F268` (return `0x21F270`) in the 3D render
  `FUN_0021EFB8`, between packet-buffer checks (`FUN_00476770`). 56 coronas at `0x512560`, 0x90 bytes each (position
  +0x10, id +0x20). States on entry: Z write off (6, 0), (10, 1), src / dest blend 2 / 2; a second pass draws the
  streaks with Z test off; it leaves Z write on, Z test on (GEQUAL), blends 2 / 2, no raster.
  **CCoronas::RegisterCorona = `FUN_0027DD10`**(id, r, g, b, a, pos t1, type t2, ...) -> `FUN_0027DD80` with the
  texture `gpCoronaTexture[type]` (`0x487758 + type x 4`; a texture's raster at +0).
- **RwRenderStateSet = `FUN_00175198`**, jump table at `0x4A50A0` (states 1..12): 1 texture raster (the bind
  `FUN_00408F30(raster, 1.0)`), 4 Z test (1: TEST_1 ZTST GEQUAL `0x50000`, 0: ALWAYS `0x30000`), 6 Z write (ZBUF_1's
  ZMSK), 8 / 9 source / destination blend (`0x486018` / `0x48601C`, then `FUN_00175088` builds ALPHA_1), 11
  `FUN_002F5F10(0, on)`, 12 a word at `0x4E1B30`; 2, 3, 5, 7, 10 do nothing.
- **CSprite::CalcScreenCoors = `FUN_0039FC48`**(in, out, &w, &h, farClip t0): the point plus RSL's world offset
  (`0x6FE980`, also added by RwIm3DTransform) through the screen matrix at `0x520A00` (`FUN_002F9E70`: the VU0
  multiply-add `FUN_001AAA38`, x and y scaled by 1 / w, out.z = w); 0 when w is under the near plane `0x4CD130` (or past
  the far one `0x4CD12C` with farClip); h = 448 / w, w = h x 1.4285715 / the aspect global `0x487488`.
- **The sprite buffer**: `CSprite::RenderBufferedOneXLUSprite = FUN_0039FF48`(f12-f16 x, y, z, w, h; r, g, b, intens
  a3 (s16), f17 recipz (unused), a t0) writes four Im2D vertices (16 bytes: u, v u16 | RGBA | x, y s16 | z u32) at
  `0x709650 + n x 64` - corners clamped to 640 x 448 with u / v moved to match, colour x intens / 256, z through
  `FUN_0039FBF0` (`FUN_002F9F58`: (P.z z + P'.z) / (P.w z) from the matrix at `0x520A40`, to int, >> 4) - and six
  indices (b, b+1, b+2, b+3, b, b+2) at `0x70C650 + n x 12`; n = `0x489EC0`, it flushes at 96. **FlushSpriteBuffer =
  `FUN_0039FDE8`**: while particles render (`0x4883A0`) it drops the sprites when the packet buffer is low; otherwise
  `FUN_002FBE68(3, 0x709650, n x 4, 0x70C650, n x 6)` (Im2D indexed; with `0x489EC8` set between Z test 0 / 1).
- **The temp buffers**: `0x709650` (0x3000 bytes: 512 Im3D vertices of 24 bytes - position, u, v, RGBA - or the
  sprites' 96 quads) and `0x70C650` (1024 indices) are shared: the sprites, plane trails (6k) and a 2D batcher whose
  counts are `0x4CD624` / `0x4CD628` (flushed by `FUN_003DFDD8`; "full" at 381 vertices / 1019 indices, `FUN_003DFDA0`).
  Im3D: RwIm3DTransform `FUN_002FBFA8`(vertices, count, matrix or 0; returns 1), RwIm3DRenderIndexedPrimitive
  `FUN_002FC2E8`(type, indices, count), RwIm3DEnd `FUN_002FC1F0`.
- **Stars**: `CClouds::Render = FUN_0018CE80` draws the game's 11 stars (tables at `0x4863D8` / `0x486400` /
  `0x486428`, twinkle from `FUN_00408058`), flushes them at `0x18D450` (return `0x18D458`), then binds the corona raster
  and draws the moon.
- **Traffic signals**: `CTrafficLights::DisplayActualLight = FUN_00313480`(signal; kept in `$s6`) calls
  `FindTrafficLightType = FUN_003155C0` (forward (+0x10, +0x14): atan2 in degrees, 60-150 or 240-330 -> 1, else 2),
  then `LightForCars1 = FUN_00313390` or `LightForCars2 = FUN_003133F0`: 0 green, 1 amber, 2 red, 3 off - blinking
  amber ((ms & 0x400) ? 3 : 1) when the wind `0x4CD2A4` > 1.1, all green when `0x4883C0` is set, else from
  t = (ms & 0x7FFF) >> 1 (1: green < 5000 < amber < 6000 < red; 2: red < 6000 < green < 11000 < amber < 12000 < red).
  Its RegisterCorona calls return to `0x313E04`, `0x313EA4`, `0x3154A8`, `0x315568` (position in t1, on the stack).
- **The flight ceiling**: `FUN_003EA618`(f12 height, a1 type), called from the flying controls `FUN_003EA6C8`
  (helicopters / planes: lift x 10 / (excess + 10) when it returns > 0): types 1 / 2 -1 under 70 m, height - 70 under
  80 m, height + 70 above; other types -1 under 80 m, height - 80 above. Project2DFX moves both 80s to 800.
- **The packet buffer's free bytes** `FUN_00478628` = 0xE6670 - `FUN_00476770` (6i); the game checks it before costly
  passes (`FUN_00240ED8` skips sectors under 0x12C00).
- **Draw distance**: the render `FUN_0021E950` sets the world camera's far plane with `RwCameraSetFarClipPlane =
  FUN_0018F400(camera, f12)` (stores +0x7C) to a **constant 2000 every frame** (call at `0x21EBB0`, return
  `0x21EBB8`), then the fog start from the time cycle (`FUN_0018F4A8(camera, *(*0x486838 + 0x3310))`); the fog ends at
  the far plane. CCamera::Process copies the far plane into `0x4CD12C` (entity culling), the sector frustum is built
  from it, so it alone limits how far the world goes. The follow camera (`FUN_0029DAB0`) sets 1000 in interiors
  (`0x489F7C` = CGame::currArea not 0 or 4). Every level's data carries the other islands' low-detail buildings: from
  the mainland the beach island is drawn whole once the far plane reaches it (checked at 6000 from (-1500, -400):
  hazy and cut at 2000, all of it at 6000).
- **LOD distances**: CCamera::Process (`0x37AEE4..0x37B078`) sets `TheCamera + 0x7DC` = 70 / FOV (1.0 in the
  frontend), raised with the camera's height over 55 m, capped at 2.0, copies it to `+0x7D0` (VC's generation
  distance multiplier) and multiplies `+0x7DC` by **`0x4887F8` = CRenderer::ms_lodDistScale** (1.0 in the ELF; no code
  writes it, CCamera::Process alone reads it). `+0x7DC` scales CSimpleModelInfo's LOD distances (+0x2C, count +0x38:
  `FUN_003A52F8` GetAtomicFromDistance, `FUN_003A5380` the largest, `FUN_003A53E0`) and the vehicles' light coronas
  (x 50 / 90 / 100, `FUN_00141FE8`). Raising the scale to 4 brought lamp posts, trees and small objects in along a
  Little Havana road seen from 60 m up.
- **Facing the sun costs nothing measurable** (2026-10-31, a user report "the first-person camera is not smooth when I
  look at the sun"). Hidden runs on an exe copy (user card copy, Fort Baxter, 15:00 / 17:00, sunny, first person, 120 fps
  independent timing, `PS2X_GPU_TIMING=1`): at 2560x1440 MSAA 4x the sun on screen took 2.6-3.5 ms GPU a frame and the
  game held 120.0 fps (frame time sd 0.0-0.1 ms), the opposite direction (buildings) 6.7-7.4 ms GPU and 109-114 fps; the
  sun's glow sprite (64x64, `gs draw fbp 140`), bloom and trails are 0.2-0.5 ms together in both directions. game_ms
  (EE) 4.4 ms toward the sun, 5.8 away. There is no GS readback: a local->host transfer is served from the CPU GS copy
  (`ConsumeLocalToHostBytes`, no GPU wait), and the corona code (6l above) projects on the CPU. The first-person view
  itself is regular: a per-frame trace (rig `trace` of the camera's front at `0x6F4550`) while the right stick turned the
  view at 2.5 rad/s gave 0.0208 rad a frame with sd 0.0005 facing the sun (8.33 ms frames) - the look follows each
  frame's real time (`vcs_input.cpp`). The user's video (2560x1440, the game's own counter) reads 120 fps looking away
  and 116-119 fps turning toward the sun, where palm fronds and city blocks filled the view: the frame rate dipping just
  under the 120 cap on a 240 Hz display in a window (no VRR in a window unless the driver allows it) is what judders - a
  missed 8.3 ms slot shows a frame for three refreshes instead of two.

### 6m. Lit model batches as a mod sees them (2026-10-31, the lit refiner API; WeaponHD.asi)

- **Not in guest memory**: the streaming heap has 0.1 - 0.4 MB free in play (the measurements above, "Measured headroom");
  one level of subdivision is 4x the triangles of every ped / vehicle model (~1.8 MB of models loaded), so smoothed
  meshes cannot live in the game's memory. Done on the host instead, where the native lit draws (6d, `vcs_hle_world.cpp`)
  read each batch from VU memory.
- **What a batch is**: one MSCAL of the lit pipelines - skinned (table 0x16: peds, Vic, cutscene characters), rigid
  (0x19 + 0x4ff: vehicle parts without paint, wheels, weapons, props) or environment-mapped (0x13: vehicle paint) - a
  triangle strip of up to 256 vertices (`[pos-1].z` vertices, `.w` drawn) whose runs are joined by repeated vertices
  (no ADC: the native path draws them as one D3D strip). Models are cut into many batches and per material; vertices at
  the cuts are exact copies (same ints), so geometry computed from a position and the normals seen there agrees across
  batches. Positions are ints scaled by qwords 42 / 43; normals ints of length ~127 (rigid) / ~128 (skinned, `* 1/128`);
  skinned inputs are bind-pose ints, overwritten in VU memory by the skinned floats once `skin()` ran (a refiner must
  read them before the write-back - the first version did not and hashed skinned floats).
- **Layers drawn over the coarse mesh**: refining a car's paint batches (even split flat, no curvature) showed patches
  of another layer (an orange rust / dirt shape on the trunk) and the licence plate greyed out: some layers of a vehicle
  are drawn by paths that still use the original mesh (likely the 0x02c0 re-draws over a resident mesh, 6d; not
  confirmed), so the refined and the coarse surface fight in depth. Peds show nothing of the kind.

### 6n. The sun's direction and the camera's rotation (2026-11-01, RenderHook.asi sun shadows)

- **Sun vectors**: `0x4E7200` holds 16 vectors of 16 bytes (x, y, z, 0: unit length, world space - x east, y north, z
  up, pointing **towards** the sun), a ring as GTA III / VC's `CTimeCycle::m_VectorToSun[16]`; `0x4EA568` (u32) is the
  index of the newest (VC's `m_CurrentStoredValue`). Found 2026-11-01: RAM dumps at 08:00, 12:00, 17:00 and 21:00 (the
  rig's `set_time`, `dump`), `findvec` for VC's formula (sin a, 1, 0.2 - cos a) normalised (a = the day's angle) gave a
  run of 16-byte-spaced matches at 17:00; the ring's newest slots were 6, 10, 14, 2 at the four hours and the only word
  holding exactly those values is 0x4EA568. Not refreshed every frame (a few slots per second; the ring shows several
  consecutive values). Values: 08:02 (0.640, 0.655, 0.401), 12:02 (-0.006, 0.581, 0.814), 17:02 (-0.673, 0.674, 0.304),
  21:02 (-0.557, 0.793, -0.247): the sun rises in the north-east, stands high in the north at noon (y stays
  0.58 - 0.79 all day), sets in the north-west, below the horizon (z < 0) at night. The formula is close to VC's but
  not exact (a least-squares fit leaves ~0.04 per component); reading the ring is exact.
- **The camera's rotation** (for anything in world space, e.g. the sun): the static world's packets have model matrices
  without rotation (a scale per axis: their positions are int16 times a scale), so the columns of K^-1 M of a world
  packet's window matrix (K the lens, 6g) are the world axes in view space times those scales; normalised they are the
  camera's rotation (`sceneView` in gs_hw.cpp; checked: the sun at noon comes out up and ahead with the camera facing
  north, at 17:00 to the left).

## 7. Textures: `.XTX`

**Host replacement identity (2026-10-31).** PCSX2 packs match the GS texture as it is sampled, rather than the RAM
raster pointer or the upload format. Tested against the user's SLUS-21590 pack: the pixel-block XXH3 hash plus the
expanded current-CLUT hash and TEX0 PSM/TW/TH identify 25 pack files over Fort Baxter and four city spots. This
includes the game's T4 data sent as CT16 by `FUN_002F62B8` / `FUN_003298D8` (section 6i): hashing the transfer's
linear bytes would not identify the sampled texture. The host implementation materializes queued uploads on a
candidate cache miss, then hashes the same GS blocks PCSX2 hashes; the CLUT is read from the CPU backend's loaded
palette. For nearest/bilinear sampling, the original GS dimensions and region limits still govern wrapping while
the host samples replacement pixels at their own resolution. See `docs/TEXTURE_PACKS.md`.

**Automation readiness (2026-10-31).** During the title flyover `CGame::currArea` (`0x489F7C`) is already 0 and
frames advance; that alone is not evidence of a playable game. Found when the first texture-pack city captures
showed the flyover without a HUD and no matching HUD/radar textures. `rig.Game.new_game()` now also requires the
`player` control command to return a non-null player ped (`CWorld::Players[0].m_pPed`, `0x4E4910`, as already read by
`src/debug/rig.cpp`) before reporting success, and keeps pressing Cross while
waiting. Earlier empty-card benchmarks using only the area check may have measured the title camera.

**The HUD's textures as the GS samples them (2026-10-31).** Seen through the HD HUD pack's matches with the user's save
(Fort Baxter and two city spots, PCSX2 identity bits = PSM | TW << 6 | TH << 10, the pack's PNGs looked at): the radar
map is drawn from 128x128 PSMT4 sections (bits 0x1DD4; 12 different ones over three places, each its own CLUT); the
radar's north marker and blips are 16x16 PSMT8 (0x1113); the HUD's small pixel font (the ammo count "199-17") is one
256x256 PSMT4 page (0x2214). The clock and money digits do not take the renderer's anisotropic path (bilinear with
plain repeat / clamp): their 16x replacement alias the way only the unfiltered full-resolution path does, so those
sprites are nearest-filtered or region-clamped (TEXTURE_PACKS.md, Checks).

Confirmed from `LOADSC*.XTX` (263,372 bytes each, 512x512 8-bit):
- `0x00` magic `"xet\0"`; `0x08` file size; `0x0C` / `0x10` offset of the trailing relocation table
  (0x404B0); `0x60` name (`"loadsc0"`).
- Pixels at **0xB0**: 512x512 linear PSMT8 indices (no swizzle). CLUT at **0x400B0**: 256 x RGBA8888,
  alpha 0x80 = opaque, already in **CSM1 order** (index bits 3 and 4 swapped).
- The game uploads both unchanged: CLUT to CBP 13584 (16x16 CT32), pixels to TBP 8960 (TBW 8, T8),
  through a VIF1 DIRECT (BITBLTBUF / TRXPOS / TRXREG / TRXDIR + IMAGE GIF tag) and a REF tag whose
  upper half is `NOP; DIRECTHL n` (this split exposed the upstream VIF bug in PS2RECOMP_PATCHES.md).
- The legal screen (copyright text + logo) is also a 512x512 T8 upload.

## 8. Data loaded at boot

- `PS2/GAME.DTZ` = zlib -> 6.6 MB `GTAG` v1 memory image (header: size, then table offsets), loaded
  at `0x016FE800` and relocated by `FUN_00324A50`; main copies ~50 global pointers out of it.
- `MAINLA.LVZ` / `BEACH.LVZ` / `MALL.LVZ` are zlib streams of a `WRLD` image (header `"DLRW"`);
  MAINLA inflates to 0x54F358 bytes at `0x756680` (read into `0xA8FE00`, inflated by
  `FUN_0021FA38`, relocated by `FUN_00324A50`). Sectors then stream from the matching `.IMG`
  through CDSTREAM.
- **zlib 1.2.2** (version string at file offset 0x3A6250; message strings "invalid distance too far back" ...),
  built with the EE's 64-bit `long`: `z_stream` = next_in 0, avail_in 4, total_in 8 (8 bytes), next_out 0x10,
  avail_out 0x14, total_out 0x18, msg 0x20, state 0x24; `inflate_state` = mode 0, ..., wsize 0x2C, whave 0x30,
  write 0x34, window 0x38, hold 0x40 (8 bytes), bits 0x48, lencode 0x58, distcode 0x5C, lenbits 0x60, distbits
  0x64 (mode BAD = 27). **FUN_00184428 = inflate_fast** (OFF = 1, pre-increment pointers) - read from its loads,
  2026-10-25. It is the busiest guest function while streaming: ~12% of guest time in a standing profile window.
  Native since 2026-10-26 (PERFORMANCE.md 14). The game's whole-file inflates (GAME.DTZ, the LVZ images) pass
  `avail_in` ~16 MB - "enough" - so the input buffer is not known by its length; one stream decodes ~8 KB chunks
  into a ring at 0x4D3E80 / 0x4D6080 / 0x4D8280 and relocates pointers in each chunk in place right after.
  With the native inflate the boot's loading screen shows 0.7-1.2 s (1.2-1.6 s before; `tools/scenes.py` shoots it
  at 1.0).

## 9. Streaming and sound (CDSTREAM.IRX)

- CDSTREAM.IRX is Rockstar's IOP driver for **both** disc streaming and sound. Three SIF RPC servers
  (IOP threads):
  - `0x65686577` - stream reads. EE client `0x505B48`: fn 1 = read `{channel, EE dest, LSN, -bytes}`
    (size negated), fn 2 = poll (`0xFA` busy, `0` done). The first request is GAME.DTZ (0x217E70 bytes).
    EE side (2026-10-24): **FUN_00221818(channel, dest, lsn, size)** - size in sectors or -bytes - flushes the
    cache over the buffer, calls fn 1 (reply 1 = accepted), then **FUN_00221678(error word)** shows the disc error
    screens (codes 0xFB-0xFF, jump table 0x4ACFA0); **FUN_002218f0(channel)** = fn 2; **FUN_00221968()** = fn 5
    (no arguments, always 0 seen); fn 0 = init `{6}` from FUN_002215a0. Channel 5 carries most reads. Counted in
    boot + 35 s of play: fn 5 x3011, fn 2 x577, fn 1 x336. **Native since milestone 6 step 1**
    (`src/game/vcs_stream.cpp`): the three EE functions replaced, reads copied from the disc image by a host
    thread, a poll waits up to 20 ms for its read (the game polls at once and would otherwise lose a frame per
    read). 14 MB take ~5 ms; boot and LOAD_SCENE teleports as fast as through the IOP (game-bound).
  - `0x65686578` - EE client `0x4CE2C0`, bound by `FUN_0010DCE8`.
  - `0x65686579` - EE client `0x4D3D40`, bound by `FUN_0010E918`. Commands go through
    `FUN_0010E970(cmd, arg)`: buffer `0x4CE300`, the reply's first word is the result. Seen:
    `0xA0000` (count, 0x6D8 = 1752 sounds), `0xA0B00` / `0xA0C00` per-sound queries, `0xA0D00` load
    bank, `0xB0100` bank-load status (1 = loaded).
- `FUN_0010D868` = sound init (skipped if `*(0x481900) != 0`), called from `FUN_002A6330`, which then
  loads a bank and loops `while (FUN_0010DE78() != 1) DelayThread(1000)`.
- On the IOP the load handler (`0x22DC0`) builds `\AUDIO\SET%s_PS.SDT;1` with sysclib `sprintf` and
  spins `while (!sceCdSearchFile()) WaitVblankStart()`. Banks: `AUDIO/SETn/SFXnn_PS.RAW` (ADPCM) +
  `.SDT` (table).
- CDSTREAM's audio thread (entry `0x1FCE8`) waits on a semaphore signalled by libsd
  transfer-complete and SPU2 IRQ handlers (`sceSdSetTransCallback`, `sceSdSetIRQCallback`).
- The bank-load RPC handler (fn `0xA0D00`) signals the reader thread and then polls for completion
  *inside the RPC call* (the runtime's nested-RPC model needed `yieldFromCall` for this).
- Bank load: ~1.7 MB of ADPCM by IOP DMA channel 4/7 into SPU2 RAM; music and dialogue stream
  through voice loops refilled on SPU2 IRQ-address interrupts.
- `DelayThread` (`0x468318`) = `SetTimerAlarm` (EE T0, handler `0x451038`) + `WaitSema`; a fresh
  semaphore per call. libsd `sceSdInit` waits for `STATX & 0x7FF == 0` after reset; STATX bit 7
  (DMA busy) only while `ATTR & 0x30`.
- SPU2 features in use (measured 2026-10-23 with `PS2X_TRACE_SPU2=1` at Fort Baxter, on foot): no pitch
  modulation (PMON 0), no noise (NON 0). Reverb is configured *off* the way libsd does it: both cores route every
  voice to the wet path (VMIXEL/ER `0xFFFFFF`, MMIX `0x0FF0` / `0x0FFC` with the wet gates set), but the work area
  is an 8-halfword dummy at the top of sound RAM (core 0 ESA `0xEFFF8`..EEA `0xEFFFF`, core 1 `0xFFFF8`..`0xFFFFF`),
  ATTR bit 7 (effects enable) is clear (`0xC000` / `0xC041`), EVOL and vIIR are 0. Main volumes `0x3FFF` (direct).
  Gameplay peaks at Fort Baxter are low (~400-1700 of 32767); AutoDMA input is idle on foot.

- **CDSTREAM.IRX's structure** (48,540 bytes, ~6,400 MIPS I instructions; `tools/irxdis.py`, 2026-10-24): the three
  servers are registered with handlers at module offsets 0xDF4 (0x65686577, streaming), 0x36DC (0x65686578) and
  0x57C0 (0x65686579, sound effects); the sound code is ~4,800 instructions (module 0x0F00-0x5A00). It drives the
  SPU2 only through libsd - no direct SPU2 register access: SetParam x36, VoiceTrans x7 + VoiceTransStatus x8
  (bank / stream data into SPU2 RAM), SetSwitch x7 (key on / off), SetCoreAttr x6, SetAddr x5, GetParam x1 (ENVX),
  Set{Trans,IRQ}Callback, Init; cdvdman (Read / Sync / SearchFile / GetError / DiskReady / Break ...) for its own
  reads; 7 threads, 8 semaphores. libsd's import ordinals (LIBSD.IRX's order, 4 = sceSdInit) were told apart by the
  call arguments (GetParam(core | voice << 1 | 0x500 = ENVX), 36 SetParam sites).
- **What the EE asks of the IOP** (`PS2X_TRACE_RPC`, boot + 35 s of play including driving, 2026-10-24): only
  CDSTREAM's three servers. 0x65686579 (sound effects) 23,901 calls in 46 functions: `0xA0A00`-`0xA0A2B` (0xA0A07,
  0xA0A09, 0xA0A2B ~950 each), `0xA0B00` / `0xA0C00` x7722 each (per-sound queries), `0xB0000` x3016, `0xB0100`
  x1908 (bank status), `0xA0D00` x3 (bank loads), `0xA0000` once. 0x65686578: 6,595 calls - `0xB00` x3022,
  `0x80E00` x3207, `0xC00` x224, `0x80700` x120, `0x80000`-`0x80221`, `0x90000`-`0x90400` a few. No PADMAN /
  MCSERV RPCs in play (pads and the card don't go through RPC here). All nine IRX modules run as IOP code.

### 9a. The sound engine, read from CDSTREAM.IRX (native since milestone 6 step 2, 2026-10-24)

How it was read: `tools/irxdis.py --decompile` (headless Ghidra on the module as a raw MIPS image, import stubs and
exports named, `tools/ghidra/DecompileAll.java`) for the logic, the plain listing for register-level detail, and the
SPU2 write traces of the emulated IOP (`PS2X_SPU2_TRACE`) as the final word. **Ghidra drops stores to hardware
registers it thinks are dead** (a write followed by another to the same address, e.g. libsd's `ATTR &= ~0x30` before
the voice reset) and reorders stores (SPDIF: the IRX writes 0x7C8, 0x7C0, 0x7C6) - the traces caught both. Offsets
below are module offsets (CDSTREAM loads at IOP 0x1D600 on the emulated IOP); "data" is module data.

- **Replies**: both servers answer with a pointer to one result word (0x8160 effects, 0x7FD0 music); the EE asks for
  64 bytes (1444 for `0xB0000`) and only the first word means anything. Commands that return nothing leave the old
  word in place (`0xA0F00`, `0xB0000`, `0xA0200`; music `0xB00`, `0xC00`, `0xD00`, `0x100`, `0x90400`, `0x90500`).
  The request's first word is the argument; `cmd & 0xFF` is a second one.
- **Effects server 0x65686579** (handler 0x57C0): `0xA0000` init(extra sounds) -> 1; `0xA0200` shutdown (key off
  all); `0xA0A00+v` voice v playing (ENVX != 0); `0xA0B00` / `0xA0C00` a sound's length in samples (bytes x 7 / 4) /
  sample rate; `0xA0D00` request bank (arg >> 8 = bank, arg & 0xFF = 0xFF to load); `0xA0F00` effects volume
  (signed byte, 0x7F); `0xB0000` the voice block; `0xB0100` bank status (1 loaded, 2 loading); `0xB0200` / `0xB0300`
  is a special sound ready / load one (arg >> 8 = sound, & 0xFF = slot type).
- **The game decides by `0xA0A00+v`** whether an effect voice is still sounding (ENVX != 0, ~150 queries a second
  while driving): an engine loop it believes stopped is keyed on again. A native port that read the wrong voice's
  envelope (`index | core << 1` for libsd's `core | index << 1`) made the bike's engine restart every frame (a short
  sample looping fast, sometimes silence at speed) and cars play rev samples while slowing (found 2026-10-24 by the
  user; 676 key-ons vs the IOP's 156 over the same ride, 91 back-to-back restarts vs 0).
- **Vehicle skid sounds: `FUN_001BA600`** (cAudioManager::ProcessVehicleSkidding; found 2026-10-24 through the float
  constants 13000.0 / 35000.0 of the pitch formula; a1 = cVehicleParams: +0 type, +8 squared distance, +0xC vehicle,
  +0x10 transmission, +0x18 speed along the vehicle's forward axis). Vehicle types 0 / 9 have four wheels (count of
  wheels on the ground +0x7FC, gas pedal +0x800, wheel states +0x804), 6 / 8 (bikes) two (+0x668 / +0x66C / +0x670);
  wheel states 0 normal, 1 spinning, 2 skidding, 3 locked. Per wheel: drive type (transmission +0x5C, 'F' / 'R' /
  '4') picks `FUN_001BA9A8` for driven wheels (spinning: (gas - 0.4) x 1.667; locked / skidding: max of that and
  |speed| / max velocity (transmission +0x50)) or `FUN_001BAB18` for the others (skidding only), both raised to
  |turn speed z| x 20 (vehicle +0x78), capped at 1. The largest x 55 is the volume before distance (40 m). Sound by
  the surface under the vehicle (+0x137 - 2, jump table 0x4A7EA0): grass / hedge sound 239 (a hiss) at
  35000 + 13000 x skid, 1/4 volume; gravel / sand sound 175 at 5000 + 3000 x skid; everything else (tarmac) **sound
  260, the screech, at 11000 + 5000 x skid, +2000 for bikes**. A bike at 120 km/h held on R1 and turned: front wheel
  skidding, rear locked, screech at volume ~36 (gas held) / ~25 (gas off), pitch 16,000-18,000, as long as the skid
  lasts (`VCS_SKID_LOG=1` logs the inputs for the player's vehicle).
- **Voices and cores**: the effect voices 0-23 are core 0, 24-43 core 1 voices 0-19 (music: core 1 voices 22 / 23); the
  game hands out voices in turn (a machine-gun burst walks 12/13, 14/15, ... - a left / right pair per shot). Core 0
  reaches the output only through core 1's external input, scaled by core 1's AVOL, which sceSdInit sets to 0x7FFF
  (BVOL, the AutoDMA input, 0). An SPU2 emulation that gets AVOL wrong silences ~half the game's sound effects at
  random (fixed 2026-10-26, PROGRESS.md).
- **Init** (0x3B10): `sceSdInit(0)`, SPDIF mode 0x800, main volumes 0 then 0x3FFF, a 128 KB IOP buffer, then every
  bank's `\AUDIO\SET<b/10>\SFX<b>_PS.SDT` read into one sound table: **12 bytes per sound** - offset in the bank's
  .RAW, bytes, sample rate - indexed from bank b's first sound (68 constants written by 0x3B10 to data 0x9FC0; last
  bank sized by the init argument: 1). ADSR of all 48 voices 0x0F0F / 0x1FC7.
- **The voice block** (`0xB0000`, 1444 bytes, sent every frame): words 3-4 key-on mask per core, 5-6 key-off mask
  per core, then eight arrays of 44 words from word 9: sound, bank, -, -, rate (Hz), pan (0-127), volume, -. Voices
  0-23 = core 0, 24-43 = core 1 voices 0-19 (core 1 voices 22 / 23 are the music). Applied by the thread 0x4B8C:
  key off; per voice: start address = sound offset + the bank's SPU2 address + 0x30 (past the VAG header) - a voice
  whose bank is not loaded is not keyed on -, pitch = rate x 4096 / 48000, volume L / R = min(2 x vol x (127 - pan) /
  127, vol) / min(2 x vol x pan / 127, vol), times the effects volume; then key on (KOFF + KON of the same mask).
- **Banks** (68; SPU2 address table in data 0x8000): 0-1 at 0x79810, 2 = specials at 0x21810, 3-0x27 "level" banks
  sharing 0xD010 (loading one unloads the others), 0x28-0x3C "building" banks in two slots at 0x21810 (the quieter
  slot is replaced; the loader prints "BUILDING BANKS NOT USED"), 0x3D-0x42 one area at 0x6F010, 0x43 specials.
  Loading (thread 0x50DC): the .RAW through the 128 KB buffer, `sceSdVoiceTrans` on core 0 in 128 KB pieces.
- **Special sounds** (speech, mission audio): sounds 0x125-0x16BA come out of bank 2's .RAW, sounds above 0x1750 out
  of bank 0x43's, one at a time, into a slot by type: 0-4 fixed (0x3A810, 0x45010, 0x4F810, 0x5A010, 0x64810), 5-7
  at 0x74010, 0xFF a ring of 5 at 0x21810 + n x 0x5000 (voices find a ring sound among the last two loaded).
- **Music server 0x65686578** (handler 0x36DC, thread 0x26E8): `0x80000` init (finds the 112 streams - names at
  data 0x6410, 40 bytes apart: radio stations, ambience, news, cutscene audio; SLES builds swap in WAVE_EU.VB) ->
  the thread id; `0x80200+n` open stream n at arg ms; `0x80700` stop; `0x80E00` state; `0x90000` a stream's length in
  ms (bytes x 7 / 256); `0x90100` position in ms; `0x90200+n` preload n held (cutscenes) / `0x90300` start it;
  `0x90400` mono; `0x90500` loop; `0xB00` volume at the next step; `0xC00` volume now (left voice gets the high
  half, right voice the low half); `0xD00+core` a core's main volume.
- **Streams** (.VB): stereo ADPCM at 32 kHz, interleaved in 8 KB chunks (L R L R ...). Two 256 KB IOP buffers read
  from disc; two 16 KB SPU2 rings at 0x5010 (left) / 0x9010 (right) played by core 1 voices 22 / 23 as loops. The
  IOP marks the ADPCM block flags in each 8 KB chunk before sending it (first block 6 = loop start or 2, last block
  of the ring 3 = jump back). The IRQ address sits at the start of the half that just started playing: the IRQ
  (every 448 ms) refills the other half - left, then right on its DMA completion, then the IRQ moves. A start
  position in ms maps to a 16 KB-aligned offset piecewise over eighths of the file (0x1524).
- **The music thread** is a state machine driven by one semaphore (max count 1) signalled by commands, DMA
  completions (`sceSdSetTransCallback`) and the SPU2 IRQ (`sceSdSetIRQCallback`): 0x80200 open -> fill both disc
  buffers -> 0x1000 / 0x7000 / 0x2000 / 0x8000 send the four ring halves -> 0x3000 IRQ armed -> 0x4000 preloaded ->
  0x5000 playing (keys on, volume, IRQ enable) -> 0x6000 stop. A stop request takes effect at the next step.
- **Timing the game relies on**: after opening a radio station the EE sends the station's volume 3 samples later;
  on the IOP the preload's four 8 KB DMAs take ~22 samples, so the volume is in before key-on. A preload done
  instantly started the radio at the old volume (0) for one refill period (found by the replay comparison).
- **libsd** (LIBSD.IRX, `src/sound/libsd.cpp`): entries are `core | voice << 1 | param << 8` (+0x80 for per-core
  volumes, core stride 0x28 instead of 0x400); the register table is data 0x4CA0. `sceSdSetCoreAttr` 2 / 4 / 6 =
  ATTR bit 7 / 6 / 14, 8 = noise clock, 10 = SPDIF. VoiceTrans mode 0 = TSA, ATTR DMA-write mode (0x20), DMA; the
  DMA interrupt clears ATTR & 0x30 and calls the channel's callback. The SPU2 IRQ handler clears the IRQ-enable bit
  of the core that hit, then calls the IRQ callback. `sceSdInit(0)` resets the hardware, writes a silent looping
  block at 0x5000 through the data port, points every voice at it, keys all on and off.

### 9b. Running without the IOP (milestone 6 step 3, 2026-10-24)

- With streaming and sound native the EE's only remaining IOP call is the stream server's fn 0 at boot (CDSTREAM
  0x0000: read queues + CD thread; the IOP's own sound code reads through its channels 2 and 3, so with the emulated
  IOP on this call must still reach it). `retireIop` (`src/game/vcs_stream.cpp`) answers it natively and switches
  the emulated IOP off: no IRX module is loaded or run (loads report success), no IOP time is emulated.
- Pads and the memory card never went through the IOP here (EE-side HLE in the runtime), nor did the EE's own
  `cdrom0:` file access. IOPRP300.IMG is never needed.
- Boot to gameplay from the rig card: 4.9-6.1 s with the IOP off, on with the native paths, or fully emulated (the
  game is the limit). IOP time per frame: 0.2 ms off, 0.3-0.4 ms emulated.

### 9c. The game's music / effects levels (2026-10-28)

How it was found: RAM dumps (rig `dump`) before and after steps of the pause menu's sliders (Audio page: Music
Volume, SFX Volume - 8 bars each; no dialogue level; then Speaker Setup and Radio Station), then a write watch
(`VCS_WATCH=4cda0c,4cda0e`, `VCS_WATCH_STACK=1`) from boot through a save load and the sliders, then the generated C++
of every writer and caller.
- **cSampleManager at 0x4CDA08**: +4 effects level, +5 music level (u8, 0..127; +6 / +7 / +8 = 0x7F, likely the fade
  levels). Its constructor FUN_0010D718 sets 0x70 / 0x50 (the defaults: 7 and 5 bars). The setters are one store each:
  FUN_0010E2B8 (+4) / FUN_0010E2C0 (+5), reached through DMAudio (0x514A90) FUN_002A6C10 / FUN_002A6C38. The sound
  code reads them (0x1C7110 effects, 0x189B54 / 0x2AE9B8 music); the menu draws its bars from them (FUN_002AE958).
  A slider step is 16; up from 112 the setter's signed-byte test turns 128 into 127.
- **The menu's prefs**: an object at `*0x48F3D0` (heap, 0x1FB5800 in the rig run) with +0x38 effects, +0x3C music (u32),
  getters FUN_002AF320 / FUN_002AF310, setters FUN_002AF328 / FUN_002AF318. Saves carry these.
- **The menu's setters FUN_002FA538 (effects) / FUN_002FA5B0 (music)** (a0 = 0x520D60, a1 = level; a negative byte
  becomes 0x7F) call DMAudio's setter, then the prefs setter. Callers: the Audio page (FUN_002AEF38: return addresses
  0x2AEF84 music, 0x2AEF9C effects), the save load FUN_003ADAE0 at its end (0x3ADD88 / 0x3ADDB0, the prefs' values
  just read from the save by FUN_003ACEF0; at boot too), and FUN_003163D8 (from FUN_003157E0), which sets the defaults
  0x50 / 0x70. The effects RPC 0xA0F00 is not used for this (no call in play): the levels act on the EE side.
- `src/game/vcs_volume.cpp` makes them the settings Audio > Music / Sound effects volume: writes both places at the
  frame kick, takes the Audio page's changes back, and gives every other setter call the player's level (a save load
  logs `[volume] the game sets the music level 80 (ra=0x3add90): the player's 32 instead`).
- **Speech** has no level of its own: it plays on effect voices from banks 2 and 0x43 (9a, special sounds) under the
  effects level, while speech in cutscenes and on the radio is part of their streams. The voice block sends a voice's
  volume only when it changes, so a new sound can start on a voice with its old volume. People near an explosion
  scream (speech sounds). A Voices volume that scaled those voices in the native driver was tried on 2026-10-28 and
  removed (DECISIONS.md).

## 10. Memory card and saves

libmc calls are HLE (`Kernel/Stubs/MemoryCard.cpp`); files live in `%LOCALAPPDATA%/VCSRecomp/mc0`
(`src/main.cpp`), one host folder per card folder.

### 10a. Card manager

- Card manager object `0x510480`, one 0x4C0-byte block per port. Status word `+0x54` reads 27 (0x1B)
  when idle / the last operation was fine, 14 (0xE) after "no entry", 1 after "no format".
- `FUN_00275068(mgr, port)` / `FUN_002760d8(mgr, port)` list the current folder:
  `sceMcGetDir(port, 0, "*", 0, 15, mgr + port*0x4C0 + 0x100)` (path string at `0x4B0148`), then
  `sceMcSync(0, ...)` - **synchronous**, waits for the result. The 15-entry table (64 bytes per
  entry, name at +0x20, attributes at +0x14, size at +0x10) is what everything else reads.
- `FUN_002788e0` is the save / load state machine (states 0..5 at `0x487730`, error at `0x487744`,
  open fd at `0x487748`); it builds paths with `sprintf` (formats at `0x4B03D8` / `0x4B03E8`) and calls
  `sceMcGetDir` with 1 or 20 entries for single files.

### 10b. Save folder and slot files

- `FUN_002778a8(mgr, slot)` (from the save menu's "save to slot", `FUN_00108128`, slot byte at
  `0x4818AC`) creates `BASLUS-21590GTA40001/` with `icon.sys` and `vcsicon.ico` if missing, then
  writes the slot file and the `BASLUS-21590GTA40001` data file (179,350 bytes). Order of creation
  on a fresh card (host creation times): `icon.sys`, `vcsicon.ico`, `BASLUS-21590GTA40001`, then the
  slot file.
- Slot files are named `"<slot> <mission name>"` (e.g. `1 In the beginning`, `1 Soldier`), 98,304
  bytes; the data starts with the block magic `"SIMP"`. Saving over an existing slot (checked 2026-10-23 with
  `VCS_TEST_SAVE` on a copy of the user's card): the game lists the folder, reads both slot-1 headers, issues two
  `sceMcDelete`s (both succeed), then opens `1 Soldier` with flags 0x203 (create | write | truncate), writes
  98,300 + 4 bytes and rewrites `icon.sys`. No new file appears; a stray older `1 ...` file (made before the
  directory-order fix) is left alone.
- `FUN_00277688(mgr, slot)` checks the card and free space (0 ok, 2 not enough space, 3 error); the
  game calls it at boot.

### 10c. How the game finds its saves - card directory order matters

`FUN_00276bf0` (loop at `0x276da0..0x2772dc`) scans the listing for **8 slots**: for slot s (1..8)
it walks **table entries 5 to 14**, and takes an entry when its name is non-empty, its attributes
have bit 0x80 (closed) set, its size is > 0x17FFF, and its first character equals `sprintf("%d", s)`
(format at `0x4B00A8`). Then it reads each slot file's first 268 bytes; with two files for slot 1
on the user's card it read both headers and then loaded the newer one (`1 Soldier`) in full.

It **skips entries 0-4**, assuming they are `.`, `..` and the three files created with the folder.
That is only true in a real card's **directory-table order** (creation order; a deleted entry's slot
is reused by the next file created). Our first `sceMcGetDir` sorted names alphabetically, which put
`1 ...` at index 2 - so saves were written but never found: no load at boot, an empty Load Game
list, and a new save to slot 1 created a second `1 ...` file next to the old one (found 2026-10-22
from the user's card: `1 In the beginning` and `1 Soldier` side by side). Fix: each host card folder
keeps its order in a hidden `.ps2x-order` file (PS2RECOMP_PATCHES.md).

### 10d. Loading

- At boot the game reads `icon.sys` (964 bytes), lists the folder, reads every slot file's header
  and then the newest slot file in full (98,300 + 4 bytes), showing "Loading data..." and "Load
  Successful." before the world loads at the save point.
- `FUN_003adae0()` (generic load) runs from world init `FUN_00255308` when a load was requested; it
  reads through `FUN_002759e8` (`sceMcRead`).
- `VCS_TEST_SAVE=<s>` (`src/game/vcs_overrides.cpp`) runs the save sequence as guest tail calls from
  `scePadRead`. A direct host call of a guest function is not safe: a scheduler checkpoint inside it
  unwinds the call and the rest of the routine never runs.

### 10e. The save / load / delete menus (driven 2026-10-23, `tools/saves.py`)

- **Save Game** is opened by scripts with `ACTIVATE_SAVE_MENU` (opcode 0x0260, no arguments; handler entry at
  `0x4BFDF0` in the opcode table) - the rig can open it anywhere. "Save the current game?" -> Save Game -> the
  8-slot list ("1 Soldier  22 Oct 2026 23:31:27", "Save File 2 Not Present" ...) with the cursor on **Cancel**;
  an empty slot asks "Are you sure you want to save this game?", an used one "Proceed with overwriting this saved
  game?" (both default to **No**), then "Save Successful. Select OK to continue."
- Saving advances the clock (12:02 -> 22:00 at Fort Baxter). Loading that save then starts the story's next
  mission intro (script `ch_jerr`, "Take Sgt. Martinez's bike") - game flow, not a load problem; the original
  Fort Baxter save loads straight into the barracks.
- **Load Game / New Game / Delete Game** are on the pause menu's *Game* tab (Map, Brief, Game, Stats, Controls,
  Audio, Display). Load lists the slots with their dates, asks "All unsaved progress in your current game will be
  lost. Proceed with loading?", and reads the slot file in full (98,300 + 4 bytes). Delete asks "Proceed with
  deleting this saved game?" and ends with "Delete Successful"; the file and its `.ps2x-order` entry go.
- With two files for slot 1 on the card (the stray `1 In the beginning` from before the directory-order fix) the
  menus show only the newer one.
- At boot the newest slot (by the header date) is loaded automatically; with slots 1 and 2 present it took slot 2.

## 11. Scripts: MAIN.SCM and the script VM

Found 2026-10-22 for the automation rig (`src/debug/rig.cpp`, `tools/rig.py`) from a RAM dump at the Fort Baxter
save (`rig.py` `dump`), a read watch on the script (`VCS_RWATCH`), and disassembly. Opcode *names* come from the
Sanny Builder Library's VCS database (`vcs.json`); every number we use was checked against the handler table
below (e.g. 0x0023 terminates, 0x0289 loads a mission, 0x0238 names a script).

### 11a. MAIN.SCM layout

`MAIN.SCM` (root of the disc, 1,876,562 bytes):
- Header: u32 main-section size (0x3CAE3), u32 largest mission size (0x96A9).
- From file offset 8 the script itself; segments are separated by `GOTO` (opcode 0x0002, int32 target):
  globals (file 0x0F..0x63F4) -> segment 2: u8 0, u32 count 1092, 1092 x u16 (a model-id table; searched by
  `FUN_00255188`) -> segment 3: u8 0, u16 0x14E2, u16 0x0419, u32 0x96A9, u32 **101 missions**, 101 x u32 mission
  start IPs -> main code from file 0x7814 (`SCRIPT_NAME "MAIN"`).
- Missions follow the main section in the file; mission n is IP `table[n]`..`table[n+1]` (file offset = IP + 8),
  loaded on demand. Names (their `SCRIPT_NAME`): 0-5 `INITPU INITCG INITGA INITOB INITPLA INITGEN` (the main
  script launches these six at start), side activities (`PARAMED VIG FIRETRK CHOPLIF TAXI` races, trials...) and the
  story chains `JER_A* PHI_A* MAR_A* LOU_A*/B* LAN_B*/C* UMB_B* BRY_B* MEN_C* REN_C* GON_C* DIA_C*` (45..100).
- **Mission names for people** (the trainer, 2026-10-26): almost every mission opens with `LOAD_MISSION_TEXT
  "<name>"` (opcode 0x033A; its own `SCRIPT_NAME` 0x0238 is missing in some, e.g. 44 `JER_A2`, 77 `MEN_C6`, 80
  `REN_C3`, 88 `LAN_C6`, and differs in others: 11 `RENC7` / `REN_C7`, 96 `TEMP1` / `DIA_C1`). The title is the main
  text table's key of that name with a two-digit number: `JER_A01` "Soldier", `REN_C07` "In The Air Tonight". 59
  story missions; 7 `JER_A1` opens the story and 11 `REN_C7` ends it, the rest run 44..100 in story order. Mission 6
  is a 24-byte stub. Side jobs: 14 `PARAMED`, 15 `VIG`, 16 `FIRETRK`, 17 `CHOPLIF` (Air Rescue), 19 `TAXI` - launched
  on foot each says "You have 39 seconds to return to your vehicle". 0x045C (VC's FAIL_CURRENT_MISSION) is something
  else in VCS (one parameter, `FUN_00266350`); no command fails a mission.
- `INITPLA` creates the player: `CREATE_PLAYER 0` at (-1710.7, -306.7, 14.86) into **global 0x2A5**, then
  `SET_CHAR_HEADING` on that same global - VCS uses one handle for the player and the player's char.

### 11b. In memory

| What | Where |
|---|---|
| ScriptSpace | `*(0x48741C)` = `0x1DE0800` = MAIN.SCM file offset 8; an IP is an offset from it |
| Model table / mission table (segments 2, 3) | `*(0x487420)` (count `0x4CD3CC`); mission IPs copied to `0x7404D0[101]` by `FUN_0025b420` |
| Mission count / largest mission size | u16 `0x4CD3EE` (101) / u32 `0x4CD3E8` |
| Mission space offset | `*(0x4CD3D8)` (where `LOAD_AND_LAUNCH_MISSION_INTERNAL` reads the mission to) |
| A mission is running | u8 `0x4CD3E7` |
| MAIN.SCM file handle | `*(0x487418)` (kept open; missions are read from the disc) |
| Script id counter | `0x48742C` |
| Active / idle script lists | `0x4CD3C4` / `0x4CD3C8` (doubly linked: +0 next, +4 prev; insert at head) |
| Script parameters (CollectParameters output) | `0x50DEF8` |
| Opcode table | `0x4BEAF0`: 8-byte GCC pointer-to-member entries {s16 delta, u16 valid, u32 handler}, 1381 opcodes, 1338 with handlers |

`CRunningScript` (0x218 bytes, pool around `0x738948`): +0 next, +4 prev, +8 id, +0x10 IP, +0x14 16-word stack
(gosub), +0x54 0x6A-word local variables (timers at locals 0x68 / 0x69), +0x1FC local frame base, +0x200 wake
time, +0x208 active, +0x20A mission script, +0x20C NOT flag of the current condition, +0x20D, +0x20F name (8
chars; `Init` writes `"id%02i"`), +0x217 "is the mission" (cleared by terminate). **The stack** (read from a running
mission's slot, 2026-10-29): a GOSUB pushes its return IP as it is, a CALL a packed word (not a plain IP: the caller's
frame goes with it, e.g. 0x0884077D); **+0x204 (u16) is the depth**, and a CALL adds its frame offset to +0x1FC.
Setting IP, depth 1, frame 0 and local 0 between frames (rig `pause on`, `poke`) puts a mission back at its state
dispatch in another state - how `tools/finale_check.py` skips Last Stand to its roof (11g). **A CALL from rig
bytecode does not come back**: the return IP of code in a slot's locals lies outside ScriptSpace (11d: it works by
32-bit wrap-around) and does not survive the packing - the subroutine's RETURN went on at 0x17CFFE, garbage, and the
game loop stopped answering. To run a main-script subroutine the host starts a script at it with a GOSUB stack of one
entry, a TERMINATE_THIS_SCRIPT of the main script (`vcs::rig::startScriptAt`).

`FUN_00255188(id)` returns the index of `id` in that model-id table (count at 0x4CD3CC, table at *0x487420) or -1, by a
linear scan; `FUN_0025A348` calls it for each entry of a list every 30 s of game time (millions of iterations: a
frame held ~14 ms by the EE clock's charge for them until it ran natively, PERFORMANCE.md 14).

Functions: `FUN_002551d0` Init, `FUN_00255950(ip)` StartNewScript (idle -> active, id, Init, IP, +0x208 = 1),
`FUN_002558f0` / `FUN_00255928` list remove / add, `FUN_002560d8` ProcessOneCommand (u16 opcode at IP, bit 15 =
NOT, dispatch through the table), `FUN_00254b90(script, &ip, n, out)` CollectParameters, `FUN_00254ff8` variable
address, `FUN_003b2208` LOAD_AND_LAUNCH_MISSION_INTERNAL (seek MAIN.SCM to `table[n] + 8`, read into the mission
space, StartNewScript, mark it the mission, clear the mission locals), `FUN_003b1d68` TERMINATE_THIS_SCRIPT.

58 scripts run at the Fort Baxter save: `storysc` (story), `pager`, `rampage`, `usj` (unique jumps), the
vehicle-mission monitors (`paramon`, `vigmon`, `firemon`, `taximon`...), `ga_*` (gang), `safehou`...

### 11c. Bytecode encoding

- Opcode: u16 little-endian; bit 15 = NOT for conditions.
- Argument = type byte + data (`FUN_00254b90`, jump table `0x4AE120`): 0 end of a variable argument list,
  1 / 2 zero (int / float), 3 / 4 / 5 float with only its top 1 / 2 / 3 bytes stored, 6 int32, 7 int8, 8 int16,
  9 float32, 10 NUL-terminated string. A byte >= 0x0B is a variable (`FUN_00254ff8`): 0x0B / 0x0C the two timers,
  0x0D-0x6C local variable (byte - 0x0D + frame base), 0x6D-0xCC local arrays, 0xCD-0xE5 global
  ((byte - 0xCD) << 8 | next byte; address ScriptSpace + 4 * index), >= 0xE6 global arrays.
- **Arrays** (read from FUN_00254ff8, 2026-10-27): a global array is 4 bytes - (byte - 0xE6) << 8 | next byte = the
  base global, then the number of the *local* holding the index, then the array's size; address ScriptSpace + 4 *
  (base + index). A local array is 3 bytes - byte - 0x6D = the base local, the index local, the size; address script +
  0x54 + 4 * (frame + base + index). An index < 0 or >= size points at a dummy word (0x50C140). A local is script +
  0x54 + 4 * (frame (+0x1FC) + byte - 0x0D); the timers (0x0B / 0x0C) are locals 0x68 / 0x69 without the frame.
- **CALL (0x037B) / CALL_NOT (0x037A)**: three raw bytes (in count, out count, the callee's local frame offset), the
  label (typed int; negative = mission-relative), then the in arguments. Labels in a mission are negative offsets from
  the mission's start; positive ones are main-script IPs (the missions call shared main-script subroutines).
  START_NEW_SCRIPT and the other "arguments" opcodes end their variable list with a type-0 byte.
- **Disassembler** (scratch, analysis only): with those rules, Sanny's VCS parameter counts and the argument types above,
  all of MAIN.SCM (main + 101 missions, ~252,000 instructions) decodes without a desync; listings under
  `build/analysis/scm/dis/` (not committed: game code).
- Example (the rig's teleport): `EA 02 01` SET_AREA_VISIBLE 0, `53 02 09 x 09 y 09 z` LOAD_SCENE,
  `44 00 CF A5 09 x 09 y 09 z` SET_CHAR_COORDINATES $PLAYER (z <= -100 finds the ground), `23 00` terminate.

### 11d. Running our own scripts (the rig's `scm` command)

A host-side copy of StartNewScript at the frame kick (between frames, never during script processing) takes an
idle script, initialises it, puts our bytecode in its own locals 0x30.. (`+0x114`, 176 bytes; locals 0..0x2F
stay free for outputs) and sets the IP to that address minus ScriptSpace (the interpreter adds them with 32-bit
wrap-around, so code outside the script space works). The game's interpreter then runs it like any script; it ends
with `TERMINATE_THIS_SCRIPT` and the rig answers when +0x208 drops to 0. Missions start the same way, with the
game's own `LOAD_AND_LAUNCH_MISSION_INTERNAL` (refuse while `0x4CD3E7` is set).

**A slot address is ours only while its IP is in the slot's own code** (2026-10-28, the Load Game hang). Once our
script has terminated its slot is at the head of the idle list, so the game's next StartNewScript takes exactly that
slot; and a save load runs `CTheScripts::Init` inside world init `FUN_00255308` (disassembly at 0x255368..0x25539C:
both list heads cleared, every pool slot `Init`ed and added to the idle list in array order), then starts the
save's scripts from the top of the pool downwards - into the slots the rig and the trainer last used. The trainer
kept its tick script's slot (god mode and the other held toggles) and, on any frame the game's clock stood still,
took a still-active script in it back out of the active list (`cancelCodeScript`, so a paused game never saves
one of ours). During "Loading..." the clock stands still, so it unlinked the script the load had just started in
that slot (`id151`, IP 0x2ADF7, at slot 0x73C1D0 in the reproduction): the load then never finished - "Loading..."
for ~45 s and the game thread returned to 0x4548435F ("_CHE", text) from ProcessOneCommand's dispatch (ra
0x256164). It needed play that left the trainer's last slot among the ones the load fills (the city after the
Fort Baxter barracks: fewer scripts run there than the save restores). `vcs::rig::scriptActive` now also checks that
the IP (+ ScriptSpace) is inside the slot's code area `+0x114..+0x1C4` and logs `[rig] script slot ... holds the
game's '<name>'` when it is not; in plain play the same mix-up stopped the trainer's tick (and cancelled a game
script on the pause menu) whenever the game reused the slot. `tools/saves.py` loads with god mode on.

### 11e. Script commands checked in the game (the trainer, 2026-10-26)

Opcode numbers from the Sanny Builder Library's VCS list (`build/analysis/vcs_sanny.json`), each run from the rig
and its effect read back: 0x024B STORE_CAR_CHAR_IS_IN_NO_SAVE gives the player's vehicle handle - **0x007B
STORE_CAR_CHAR_IS_IN answers -1 for a car made by CREATE_CAR** (MAIN.SCM uses it on cars the player took); a
vehicle command on handle -1 never ends its script. 0x004D GET_CAR_COORDINATES, 0x00D0 / 0x00D1 GET / SET_CAR_HEADING
(SET rebuilds the matrix upright: a flip), 0x03B9 SET_CAR_ROTATION, 0x02E9 SET_CAR_FORWARD_SPEED, 0x01CA
GET_CAR_SPEED, 0x027F / 0x02EE GET_OFFSET_FROM_CAR / CHAR_IN_WORLD_COORDS, 0x00CE GET_CHAR_HEADING, 0x0216
WARP_CHAR_FROM_CAR_TO_COORD, 0x0110 STORE_WANTED_LEVEL, 0x0096 STORE_SCORE, 0x005A GET_TIME_OF_DAY, 0x013C
ADD_EXPLOSION, 0x02F9 SET_CHAR_DROWNS_IN_WATER, 0x03FA SET_PLAYER_CURRENT_WEAPON_AMMO_IN_CLIP (one parameter: the
current weapon's clip). `SET_CHAR_COORDINATES` on the player while he drives moves the vehicle with him.
GIVE_WEAPON_TO_CHAR takes weapon types 0..39; 40 and up hang the script.
- **LOAD_ALL_MODELS_NOW (0x0228) can hang the game**: it loads the requested models inside the frame and does not
  return while the streaming memory cannot take them - after 28 different vehicle models were spawned in one street
  the game thread spun in it (watchdog: PCs all over the game, no frame kicks). The trainer requests and polls instead.
- **HAS_MODEL_LOADED** (0x0161, handler `FUN_0012be70`) -> `FUN_003c6738`: the model's streaming info is
  `*(*(0x489FF8) + 200) + model * 0x18`, its byte +0xC is the load state (1 = loaded). A condition's result lands in
  the script at **+0x209** (with +0x20C the NOT flag and +0x206 the AND / OR count).
- The rig's `scm` answers `ok <slot>`: the finished script's outputs (locals) are at slot + 0x54 until the game starts
  another script in that slot (reading the head of the idle list instead raced with the trainer's own scripts).

### 11f. Mission meters that count per frame (2026-10-27)

The user's report: in PHI_A2 "Boomshine Blowout" the heat bar fills much faster at 144 fps (independent timing). Every
script runs once a frame and a `WAIT 0` loop does one pass a frame, so anything a script adds a fixed amount to per pass
moves with the frame rate. On the PS2 a frame is always 1/30 s; the game's own time-based tools are the timers TIMERA /
TIMERB, GET_GAME_TIMER and the **timed opcodes 0x0031 - 0x0034** (ADD / SUB_TIMED_VAL / FLOAT_VAR: value * ms_fTimeStep),
which REN_C7, SRANGE, MAR_A5, LAN_C5 and DIA_C3 use for their meters. Some missions used the plain ones instead.

- **PHI_A2's heat** (mission 47, the subroutine at file IP 0xCACCD = mission +0x2026, called once per pass from the
  forklift-state loops at 0xCC655 / 0xCC771, both `WAIT 0`): `$G15AB += 0.015` (the heat's floor: it always rises,
  0.45 a second at 30 fps - 100, the explosion, after 222 s), `$G15AA += $G15AC` (the heat; $G15AC = 0 without a crate,
  +1 with the crate in a fire (PHI2_H5 "Keep the boomshine out of the fire!", 0xCAC5E), -1 otherwise),
  `$G15AA = max($G15AA, $G15AB)`, at 100 `$G159E = 7` (fail); the bar is `$G15A2 = (int)$G15AA`
  (DISPLAY_ONSCREEN_COUNTER_WITH_STRING "PHI2_TE"). Measured (`VCS_TIMESTEP`, per game second): floor 0.450 at 1/30,
  2.162 at 1/144 - 4.8x; heat at +1: 29 / 144 a second.
- **How the others were found**: every on-screen counter (024D / 0311) traced back to the variables that feed it
  (CSET_VAR_INT_TO_VAR_FLOAT, copies) and their arithmetic; every non-timed float add / subtract of a constant under 1
  (per-frame rates); every variable-rate float accumulator on a global; every int counter compared with 20 or more.
  Each hit read in context: who calls the subroutine (a call-graph over CALL / GOSUB labels) and whether that loop
  waits 0, whether the change is per frame or per event (a hit, a pickup), and whether it is gameplay or looks.
- **Per frame, gameplay** (scaled by `src/game/vcs_script_timing.cpp`, its table has each instruction):
  - 59 LOU_B1 "Hose the Hoes": the girls' bar `$G1513` -0.04 / -0.03 / -0.01 a frame (by the fires left, +0x6E2..);
  - 67 UMB_B2 "Balls": havoc `$G14E9` +0.005 a frame per living Cholo (+0x24CF), the mission fails at 100;
  - 97 DIA_C2 "The Exchange": the snipers' TIME bar `$G154C` -0.04 a frame from 100 (+0x1E3F; 83 s at 30 fps);
  - 80 REN_C3 "Kill Phil": the Phil bar `$G152E` -0.25 a pass in the thugs state, a pass = two `WAIT 0`s (+0x27EC);
  - 68 UMB_B3 "Papi Don't Screech": stress `$G15B3 += max(rate, damage this frame)`; the rates (-0.2 calm, 0.25 out of
    the car, 0.5 airborne / over 30 / upside down, 2) are set into local 0 at +0xE8A..0xF12 - those sets are scaled,
    the damage (an event) is not;
  - 35 FIREHEL: the bucket's water `$G1700` -1 a frame while dropping (+0x15E3; a fire inside the bucket's box goes out
    at once, so the drain alone is how much a bucket does), the helicopter's health -5 a frame per fire it touches
    (+0x1B73);
  - 77 MEN_C6 "Burning Bridges": pressure `$G1656` +1 a frame while the player is over 70 from the depot (+0x13BE;
    the +3s are per explosion, timed with GET_GAME_TIMER);
  - 18 (the driving range) and 93 GON_C2 "Home's on the Range": the aim `$G14F1` / `$G150E` +-0.2 a frame on the stick,
    back to the centre at 0.05 a frame (the power bar is timed with GET_GAME_TIMER);
  - 99 DIA_C4 "Over the Top": the searchlight targets (model -19, beams by COMMAND_0478 from the towers) step 0.3 /
    0.15 a frame along their routes (x3 alerted): `7L *= $G1587[i]` (+0x53B7) and `8L = $G1587[i]` (+0x5478);
  - 60 LOU_B2 "Robbing the Cradle": the distances the Welfare Man may get away (`$G1513..15`) shrink by 0.1 a frame
    towards 300 / 150 / 600 (+0x1353..).
- **Checked and fine**: TOUR's "Fun" (scored every 2.5 s of TIMERB), REN_C6 / LAN_C7 bars (TIMERA, GET_GAME_TIMER),
  REN_C7 cable damage (timed opcodes) and rig stress (+25 a hit), LAN_B4 cash, DIA_C3 signal, the counters of kills /
  pickups, health-derived bars (LAN_B6 / C3 / C8 Lance, damage bars), TAXI fares, E_RO cruise speed (set from the car's
  speed), position offsets (set, then +-c), the golf power bar.
- **Per frame but looks only** (not changed): text grow / scroll animations (CRASH, SRANGE), object slides and spins
  (GON_C4, MEN_C3's barrier, camera smoothing in LAN_B6), particle bursts, the shared camera-shake helper (0.63 / 0.7 /
  0.67 in many missions), debug tools in the main script (near clip, animation viewer). Minor: LAN_C3 counts frames
  while a spawn point is blocked (its fallback comes sooner).
- **The fix** (vcs_script_timing.cpp): the handlers of 0004/0005/0035/0036 (copy, 0x3B11D8), 0007 (0x3B1248), 0008/002A
  (0x3B12C0), 0009/002B (0x3B1338), 000A/002C (0x3B13B0), 000C/002E (0x3B14A0) are wrapped; ProcessOneCommand
  (FUN_002560d8) has moved the IP past the opcode and calls them through the table with the script in a0. At a listed
  instruction (mission offset = IP - 2 - `*(0x4CD3D8)`, checked against its decoded opcode and operands) the wrapper
  does the instruction with the operand scaled by ms_fTimeStep / (50/30), clamped to 0..2 (integers keep the fraction
  for the next pass), moves the IP on and returns 0, as the handler would. Only when the frame is not the PS2's
  (independent timing, or original timing at 60); original timing at 30 runs the game's handlers. Measured at 1/144:
  floor 0.4496 a second, heat 29.5. `tools/framerate_audit.py` scenario `heat` and `--sites` (every listed instruction
  found in its mission as the game decodes it).
- The mission is read to ScriptSpace + `*(0x4CD3D8)` (an IP; 0x3CAE3, right after the main section) by
  LOAD_AND_LAUNCH_MISSION_INTERNAL (0x3B2208), which starts it there; mission-relative labels resolve against it.

### 11g. The end: Last Stand and the credits (2026-10-29)

The user's report: in Last Stand, once Vic reaches the roof and the final cutscene has played, the game goes to a loading
screen and never comes out. Read from the disassembly (IPs below are MAIN.SCM IPs as the disassembler prints them; a
mission's runtime IP is 0x3CAE3 + (IP - its start)) and reproduced with the rig.

- **Last Stand** is mission 100, `DIA_C5` (text `DIA_C05`; starts at IP 0x1C291E). Local 0 is its state, 1..12, run by
  a dispatch at 0x1C6202 (one GOSUB per state): 11 (0x1C945C) the roof scene with Martinez and Mendez (`SDAC5EA`..`EK`,
  scripted, camera by `SET_FIXED_CAMERA_POSITION`), 12 (0x1C9DF1) the fight, which ends 2.5 s after both `$G16CA` /
  `$G16CB` are dead with state 0 -> the pass at 0x1CA12A: pickups removed, both deleted, `CALL 0x24137 (55)` - the main
  script's mission-cutscene helper, whose table entry 55 is cutscene `DIA_C5` (audio `\AUDIO\CUTSCENE\DIAC5B.VB`, Lance
  arriving on the roof, `MDAC501`..`522`, about 95 s) - then the mission-passed subroutine `0x2FB30 ("DIA_C05", 5000)`
  and the cleanup. The helper waits in **0x22F5E..0x22F97** (`HAS_CUTSCENE_LOADED`, `START_CUTSCENE`,
  `HAS_CUTSCENE_FINISHED`, `CLEAR_CUTSCENE`); only the pass path calls it. The cutscene ends with the screen faded out.
- **The credits** are the main-script subroutine **0x24DC3** (CALLed; locals 0..22, its callees' frames up to local
  42): `$G2AC` (on a mission) = 1, the clock to 21:00, the player hidden and frozen at (269.5, -1158.7, 10.9),
  widescreen, no HUD, ped and car density x10, `WAIT 2000`, `PLAY_END_OF_GAME_TUNE`, `START_CREDITS`, a loop of
  camera GOSUBs over traffic until `ARE_CREDITS_FINISHED` (several minutes), then everything back, the player at
  (-948.0, 1336.7, 10.1) below the Mendez building, `DO_FADE 1000 1` - the only fade in after the cutscene.
- **Who calls them**: after every mission `storysc` (0x2FC69) runs `0x2F9C9`, the story's chapter step: chapter `$G82`
  0 / 1 advance when their flags are set, and for chapter 2 with `$G296` (credits seen) 0 and the chapter flags `$G1B
  $G16 $G1A $G1D $G19` all 1 it waits 5 s (`WAIT 5000`), CALLs the credits, then sets `$G296` and `$G104` and calls
  four more story subroutines. The flags are set only by the story's own progression (0x2AA16..0x2AA52,
  0x39A70..0x39C9F). Nothing else references 0x24DC3 (a search of MAIN.SCM's bytes for the label found that one CALL).
- **The "loading screen"**: with Last Stand played out of story order - the trainer's mission launcher, the user's
  newest save being `LOU_A3` - the check fails, nothing fades in, and the game keeps running behind the faded screen
  (clock, scripts, the world: `storysc` back in its idle loop at 0x2FCD2). Each frame it draws only the copy of FBP
  140 into FBP 0, a black full-screen quad and the text **"Loading..."** (key `LOADIN2`, the frontend's string next to
  `WRONGCD` / `NOCD` / `CDERROR`) at the top right - an F12 dump of the stuck frame; the LoadingScreen function
  (FUN_0021E170) and the menu draw are not called. So it is the game's own picture, which the original would show the
  same way. With the flags set (rig `poke` of the globals) the same run rolls the credits and ends at the building.
- The fix is in the trainer (docs/TRAINER.md): a Last Stand it launched that passes (its script seen in 0x22F5E..
  0x22F97) and ends without the story's condition gets the credits 5.5 s after the end: a script `credits` started at
  0x24DC3 whose RETURN lands on the main script's TERMINATE_THIS_SCRIPT at 0x16E90 (11b); story globals are left as
  they are. `tools/finale_check.py` plays the end both ways (`--story`).
- How it was found: the mission's state from its slot (rig `peek`; the scripts list showed it waiting in 0x22F8E for
  the cutscene's 95 s), the frames still advancing and `CTimer`'s ms moving (not a hang), the active scripts after the
  end (no credits script), the main script's references to `START_CREDITS`, the raw label search, the LoadingScreen /
  menu hooks traced (not called), and the F12 draw log.

## 12. Player, areas and the world

- **Player ped**: `*(0x4E4910)` = `CWorld::Players[0].m_pPed` (`FUN_00237fb0(ped)` returns `&Players[0]` for the
  player's ped). The ped object starts with its matrix: right (+0), forward (+0x10), up (+0x20), position (+0x30),
  each row with a word after it. Found by searching RAM for vectors near the camera that moved when the player
  walked (`findvec`), then the pointers to the object (`findu32`).
- **TheCamera** `0x6F44D0`: +0x30 is the camera's own position (its matrix; a few metres behind the player in normal
  play - read as "the point it follows" until the free camera showed it equal to the camera, 2026-10-30); it also holds pointers to the player ped
  (+0xE0, +0x350, +0x7F8). Its active CCam is at +0x70 (12b).
  - **+0x7F8 = pTargetEntity** (what the camera should follow: the player's vehicle while he drives, else the ped)
    and **+0xE0 = the active camera's target** (what it does follow). Getting into a car on foot moves both to the
    car. **Warped from one vehicle straight into another** (`WARP_CHAR_FROM_CAR_TO_COORD` + `WARP_CHAR_INTO_CAR` in
    one script frame: the trainer's spawn while driving) +0x7F8 moves to the new vehicle but **+0xE0 stays on the old
    one**, and the camera keeps showing the old car while the player drives off (the user's report, 2026-10-28).
    `SET_CAMERA_BEHIND_PLAYER` (0x0221) does not fix it; `RESTORE_CAMERA_JUMPCUT` (0x01CF, handler `0x287BD8` ->
    `FUN_0037C0E8(&TheCamera)` = RestoreWithJumpCut) does: it resets the script camera flags, sets +0x60 / +0x820 /
    +0x888 to 1 and +0x7F8 from the player's state, and the next frame +0xE0 follows. Found by listing TheCamera's
    words equal to the ped / vehicle pointers after each spawn (rig, `trainer spawn`).
  - **+0x888 = m_bLookingAtPlayer**: 1 in normal play on foot and driving, 0 under a script camera
    (`SET_FIXED_CAMERA_POSITION` + `POINT_CAMERA_AT_POINT`, `POINT_CAMERA_AT_CHAR`), 1 again after `RESTORE_CAMERA`
    (0x00B6). +0x840 is 1 while a script points the camera; +0x60 / +0x820 are one-frame requests (read back 0).
- **Current area** (interior): `CGame::currArea` = `0x489F7C`, set by `SET_AREA_VISIBLE` (opcode 0x02EA, handler
  `0x1e31a8`, then `FUN_003cc0d0`). 0 = outdoors. The Fort Baxter save loads with **area 2** (the barracks), so a
  teleport outside must set area 0 first (the user's guess, confirmed by reading the global). VCS has no
  SET_CHAR_AREA_VISIBLE in the opcode database.
- Teleports are clamped to the map: about x -2178..1564, y ..1926.
- **Ped teleport**: `FUN_0020b3d8(ped, CVector *pos)` (remove from the world via `FUN_0018fa50(ped, 2)`, set the
  position `FUN_00472688`, clear movement state +0x1c8 / +0x814..+0x81c / +0x150, add back `FUN_0018f8f8`); reached
  through a vtable, every caller seen goes through `0x4127d0`. `VCS_TRACE_TELEPORT=1` logs each call.
- **The safehouse script moves the player back once**: after loading the Fort Baxter save (inside the barracks
  safehouse, area 2) and teleporting away, the *next* teleport far from Fort Baxter is followed by two teleports
  done by the script `safehou` (IP 0x20E86, then 0x20EA4): to (-1648.87, -262.50, 15.94) and (-1648.87, -261.00,
  14.50) - the barracks door. Once, whatever the destination; later teleports land. Found with a write watch on the
  ped's x (`VCS_WATCH`, pc `0x47268c` inside the teleport), then `VCS_TRACE_TELEPORT`, which hooks the interpreter's
  ProcessOneCommand to name the script that was running. First mistaken for entrance markers. The rig's
  `Game.prime()` triggers it on purpose before working. The world tour's other "relocated" points are the map-edge
  clamp.
- While the ped sits in a vehicle its own matrix is not its world position (it read (-0.4, 0.0, 21.6) in a car
  parked at (-596, 600)); use the vehicle's.
- `CREATE_CAR` (0x0048, handler `0x3d03b0`): 4 parameters (model, x, y, z; z = -100 finds the ground) plus the
  handle output (e.g. 0x1201 = vehicle pool slot 0x12). Vehicle model ids used by MAIN.SCM: 171..276 (211 most).
- `SET_CHAR_COORDINATES` with z = -100 puts the player on the ground (or a roof: (-1400, 1250) landed at z 84).
- **Pools** (`CPool`: +0 entries, +4 flag bytes (bit 0x80 = free, low 7 bits = the handle's generation), +8 size;
  lookup `FUN_00471788(pool, handle)`: slot = handle >> 8, the low byte must equal the flag byte): peds `*(0x487A94)`
  (70 entries of 0xD20 bytes from 0x1D3FF80 in a game started from the Fort Baxter card), vehicles `*(0x487A98)`
  (entries 0x8C0). A script char handle 0x1006 = ped slot 0x10, generation 6.
- **Ped fields for the trainer** (found 2026-10-26 by setting each value with a script command and searching the ped
  for it): +0x4E4 health (float), +0x4E8 armour (float), +0x480 the vehicle it is in (0 on foot; +0x450 / +0x484 hold
  it too), **+0x8C4 state** (1 on foot, 0x37 driving; +0x8A4 read 0 in these runs), +0x578 weapon slots: 10 x 0x1C
  bytes {type, state, ammo in clip, ammo total (the clip included), ...}, slot 0 unarmed, 1 melee, 2 thrown, 3
  pistols, 4 shotguns, 5 SMGs, 6 rifles, 7 heavy, 8 snipers, 9 special (camera...). Entities: +0x56 model index.
- **Vehicle** (pool entry 0x8C0 bytes): +0x30 position, +0x20 up vector (z < 0 upside down), +0x278 health (float,
  1000 new; +0x27C holds 1000 too).
- **Clock and timers**: `0x4CD148` / `0x4CD149` the clock's hours / minutes (bytes; found by setting 13:37 then 7:11
  and diffing RAM); `0x4CD104` CTimer's milliseconds - it stands still while the game is paused (the pause menu, the
  save screen; found by diffing RAM in play and in the pause menu), so it tells running frames from paused ones.
  The player's money: `0x4E49CC` (in CPlayerInfo).
- **Names**: the text (GXT) table is `**(0x48A2A0)` = {entries, count, data, size}; an entry is 12 bytes {u32 UTF-16
  text, char key[8]}, sorted by key. Vehicle models are ids 171..280 in `CModelInfo::ms_modelInfoPtrs`
  (`*(0x486518)`); a vehicle model info's game name (its text key, e.g. `SENTINL`) is at +0x158. Zones: 56-byte
  records {name[8], min xyz, max xyz, ...} around `0x1a6e3e0`; the main districts' names are text keys (`A_PORT`
  Escobar International, `ARMYB`, `BEACH1..3`, `DOCKS`, `DTOWN`, `GOLFC`, `HAITI`, `HAVANA`, `PORNI`, `STARI`, `JUNKY`).
- **Ped fields** used below: +0x48 entity flags (64-bit; bits 4..8 = status, bit 32 = bRemoveFromWorld), +0x56 model
  index, +0x1C8 ped flags (64-bit; **bit 63 = bFadeOut**), +0x6F8 near peds (10) with the count at +0x77A, +0x8A4 /
  +0x8C4 ped state (0x37 driving, 0x39 / 0x3A dying / dead), +0x8F4 created by (1 random, 2 mission).
- **Frame functions** (found tracing ped removal, 2026-10-25): FUN_003ba8d8 = CGame::Process (scripts, then the world,
  population and cars); FUN_001933c0 = CWorld::Process (each entity's ProcessControl through its vtable; entities with
  bRemoveFromWorld go to FUN_00198408, which removes and deletes them); FUN_00210780 =
  CPed::FlagToDestroyWhenNextProcessed (sets bRemoveFromWorld, gets the ped out of a vehicle); FUN_001f4bf0 =
  CPed::ProcessControl (at 0x1f4cfc: if bFadeOut, alpha -= 8 and FlagToDestroy below 0); FUN_00430148 =
  CPopulation::Update (FUN_00430290 adds peds); FUN_00433008 / FUN_00433378 = CCarCtrl::RemoveDistantCars /
  PossiblyRemoveVehicle (a removed car deletes its occupants); FUN_0014ca80 = CAutomobile::ProcessControlInputs (with
  the player's controls disabled it brakes and calls FUN_00237c30, which destroys the player's off-screen random near
  peds and makes the others flee). The script command at 0x2b0b9c (FUN_002b0200) sets bFadeOut on many peds at once
  (an area clear).
- **Mission audio slots** (main script, `AUDIMON` at 0xaf7f and the subroutines 0xa81a - 0xac40 its users CALL): 5
  slots in globals 0x606 (state bits: 1 free, 2 load requested, 4 loaded, 8 playing, 0x20 locked, 0x40 play once
  loaded), 0x60B (the line's name, a script-space string offset, e.g. "MARA1CA"), 0x610, 0x615 (the speaking char's
  handle, -99 none). 0xaa14 requests a line (opcode 0x0413 / 0x0257), 0xa9b6 finds the slot of a name and waits
  (`WAIT 0`) until bit 4 is set. AUDIMON, per slot: requested and loaded (opcode 0x0258) -> 4; **if the speaker is
  "dead" (opcode 0x009F IS_CHAR_DEAD: no ped for the handle, or state 0x39 / 0x3A) the slot is freed (1)** - and a
  mission already waiting in 0xa9b6 on that slot waits forever. Opcode 0x048F tests `(a & b) != 0`, 0x048D ORs.
- **Shakedown's shop "Loading..." hang (MAR_A1, 2026-10-25)** was that wait: entering the shop (the mission's own
  interior at (-1735, 634, 150), area 2) the mission creates the shopkeeper (model 152) and two extras, requests his
  line with him as the speaker - and he had already been deleted, by his own ProcessControl taking the bFadeOut path.
  bFadeOut was clear; bit 31 of the same 64-bit word was set, and the recompiler tested the low word in `bgez`
  (docs/PS2RECOMP_PATCHES.md). Found by: the mission script sitting in 0xa9f9 - 0xaa0b (the `scripts` / `peek` rig
  commands and a rough disassembler with parameter counts taken from each opcode handler's CollectParameters /
  StoreParameters / GetPointerToScriptVariable calls), a write watch on the slot globals (2 -> 0x42 -> 4 -> 1 in one
  AUDIMON pass), the speaker's handle (G615) and its free pool slot, `VCS_TRACE_PED_REMOVE` (who flags and deletes
  peds), a watch on every ped's +0x1C8 armed at the door (`VCS_WATCH_STRIDE`, rig `watch`: no store ever set bit 63)
  and the flag word logged at the removal (bit 63 clear, bit 31 set). It hung at every frame rate and timing mode.

### 12a. The pad and its vibration (2026-10-28)

- The game reads port 0 slot 0 once per frame (`scePadRead` at 0x449488, called from FUN_002843d8 = the pad update,
  0x2848a8) in analog mode: buttons active low, then rx, ry, lx, ly. The runtime's stub asks its pad backend for the
  report; our bindings fill it (`PSPadBackend::setReader`, src/game/vcs_input.cpp).
- **Vibration** (found reading FUN_002843d8 in the generated C++): at start-up it asks for the motors
  (`scePadInfoAct(port, 0, -1)`, 0x28470c; the stub answers 2), then aligns them with `scePadSetActAlign` (0x284770)
  from a 6-byte table at 0x514958 = {0, 1, 0xFF, 0xFF, 0xFF, 0xFF} - act 0 the small motor, act 1 the large one, the
  DualShock 2's usual layout. While the pad's shake timer (`pad + 0x94`, s16, counted down each frame) runs it calls
  `scePadSetActDirect(port, 0, 0x514950)` (0x284898) with byte 0 = 0 (the small motor is never used) and byte 1 =
  `pad + 0x99` (the large motor's level 0..255); when it reaches 0, once more with both 0 (0x284870). A second caller
  is FUN_00285258 (0x285294). A grenade's explosion 2 m from Vic gives level 128 (`tools/controls_check.py`).
  The host maps the large motor to the gamepad's low-frequency rumble and the small one to the high-frequency one,
  scaled by Gamepad > Vibration.
- **The pad's stick curve** (2026-10-29, FUN_002842e8, called for the four stick bytes in FUN_002843d8; decompiled):
  v = byte - 128; |v| <= 42 is 0, past that (|v| - 42) * 127 / 85 (integer, truncated), sign kept - **a third of the
  stick's travel is dead** on top of any gamepad deadzone. The results are CPad 0 (`0x5147A8`, 0xD4 bytes per pad,
  FUN_002852a8(n)) +2 / +4 left x / y, +6 / +8 right x / y (s16); **+0x96 = DisablePlayerControls** (the right-stick
  getters FUN_00286af0 / FUN_00286b20 return 0 while it is set; FUN_00286b20 negates y when the game's own invert flag
  `0x487A58` is set). Found when mouse pitch below about half a tilt came out a third short.
- **scePadRead runs three times per game frame** (366 reads in 122 frames, counted with the `reads=` of `padstate`).
  vcs_input.cpp works the mouse out once per `m_FrameCounter` 0x4CD124 and repeats that report for the frame's other
  reads, so whichever read the game keeps carries it (not measured which one that is).
- **Driving buttons**, measured with a car on a straight street (575, 175): Cross accelerates (forward speed 0.28 after
  2 s), R1 is the handbrake (0.12 to 0 in 0.7 s; coasting 0.28 to 0.20), Square brakes, then reverses. Vehicle +0x140
  is its velocity (units per 1/50 s), +0x10 its forward vector.

### 12b. The camera and the mouse (2026-10-29)

- **TheCamera `0x6F44D0` + 0x70 is the active CCam** (Cams[0]; Cams[1] / [2] at +0x2E0 / +0x550, 0x270 apart; still
  [0] after a lock-on and after getting out of a car). Fields (relative to the CCam): **+0 mode** (4 follow ped on
  foot, 11 locked on with R1 - with fists too -, 18 behind a vehicle; VC's numbering), +0x10 front, **+0x78 alpha
  (pitch; negative looks down, about -1.48 .. 0.79)**, **+0x7C beta (heading, 0..2 pi; the stick to the right makes it
  fall)**, +0x130 / +0x140 pitch / heading speeds, +0x134 FOV (70), +0x1A0 the target point, **+0x220 / +0x230 the
  source points** (where the camera stands). Found by diffing TheCamera while the right stick turned it, poking each
  candidate, then a write watch on alpha / beta (`watch`): the writer is **FUN_0029dab0 = the follow-ped camera**
  (decompiled with `tools/eedecomp.py`).
- How FUN_0029dab0 turns (k = pow(0.8, step), 0.8 from the table at `0x487B30` + 0x3C per outdoor / interior): the
  heading's speed = k x the last speed + (1 - k) x (the stick's term |x| x 4.9e-5 x 0.000893 x FOV + a pull toward
  where the camera stands + the swing behind a walking player), capped at 0.1 a step; beta += speed x step. The source
  points are put back around the target from beta and the pitch at the end of each update. Pitch: the speed = k x the
  stick's term (|y| x 4.9e-5 x 0.000536 x FOV, y > 0 looks up) + (1 - k) x the last one, and it **moves the source
  points**, and alpha only
  eases toward the pitch the camera stands at (limits from the table: 0.785 up, 1.4835 down). So a heading written
  alone is pulled back (by ~0.1 a frame for many frames) unless the source points turn with it, and an alpha written
  alone is undone in a few frames; the stick's pitch speed integrates exactly (the smoothing sums to 1). The stick's
  top speeds: heading 0.05, pitch 0.03 radians a step (2.5 / 1.5 rad/s).
- The follow camera ignores the stick while `0x488EB4` is set (FUN_002a2e30) and while CPad +0x96 is set; under a
  script camera TheCamera + 0x888 is 0 (section 12).
- **Mouse look** (src/game/vcs_input.cpp, Keyboard > Mouse camera): on foot (mode 4, no script camera, controls on, not
  paused: the pause menu leaves the mode at 4, `m_UserPause` 0x4CD2AC / `m_CodePause` 0x4CD11C are bytes) the
  pad read adds the mouse's turn to beta and turns +0x220 / +0x230 about the player by the same angle (exact: 300
  counts in 30 moves -> -0.750 rad, 400 counts a radian), and sends the pitch as the stick's pitch speed with the curve
  above undone, carrying what is over the stick's top speed to the next frames (90 counts -> +0.225 rad). Other
  cameras (vehicles, aiming, lock-on) get the mouse's speed as the right stick, past the dead third. Checked by
  `tools/controls_check.py` (the `mouse dx dy` control command moves the mouse in hidden runs).
- **The camera update** (2026-10-30, for the trainer's free camera; FUN_00378dd8 decompiled with `tools/eedecomp.py`):
  FUN_00378dd8 = CCamera::Process. At `0x378FC0` it calls **FUN_00294540 = CCam::Process** on the active CCam
  (`TheCamera + 0x70 + ActiveCam x 0x270`, ActiveCam = byte `TheCamera + 0x50`; the only caller), then
  **FUN_002A2ED0** (CCam::ProcessSpecialHeightRoutines: lifts the follow camera for peds near the player in modes 4,
  0x1E, 0x24) on the same CCam. CCam::Process switches on `mode - 1` (0..0x37) through the jump table at `0x4B1870`
  (`jr` at 0x2949E8); mode 4's case calls FUN_0029dab0. After them CCamera::Process builds the frame's camera from
  the CCam's **+0x20 Source**, **+0x10 Front**, **+0x60 Up** and **+0x134 FOV** (and +0x1A0, the target point, when
  `TheCamera + 0x890` is set: front = target - source), blending with the previous camera while `TheCamera + 0x8D0`
  (a byte) marks a transition. Writing those four after CCam::Process (in place of FUN_002A2ED0) moves everything: TheCamera +0x30,
  the frustum planes, culling, LODs and the world streaming (the city streamed in at full detail 640 m from the
  player), the sound listener. Found by tracing the call (generated code), reading the decompile for the fields the
  matrix is built from, then the free camera: its position appeared at TheCamera +0x30 / +0x90 / +0x250 / +0x810 /
  +0x960 / +0xA50 the next frame.
- **A cutscene waits on its camera** (2026-10-30): Soldier (JER_A1) launched with the free camera replacing
  CCam::Process sat on "Loading..." for good - the mission script at `0x22F8E` (main script: the cutscene's wait,
  inside 0x22F5E..0x22F97) and the camera in mode 17 at 240 s, where the same launch without it left the cutscene
  ~175 s in (mode 15 for its first ~35 s, then 17; on foot, mode 4, at ~190 s). With the update left running and the
  free camera written after it, the cutscene ends on time. So the cutscene's end is driven by the camera's own update
  (as in VC, where CCutsceneMgr::HasCutsceneFinished asks TheCamera for its position along the cutscene's spline).
  Found by comparing the two runs' active scripts and camera mode every 5 s.
- Teleported to (575, 175) the camera ends up at its lowest pitch (-1.483, straight down) - the game's own doing (the
  same with `VCS_INPUT_MAP=0`).

### 12c. Bones, near plane and heading - first person on foot (2026-10-31)

Found for `src/game/vcs_firstperson.cpp` (the user's port of UltimateFP's on-foot camera; since 2026-10-31 in the
CameraAim.asi mod, spartaque12/VCS-mods `plugins/CameraAim/src/firstperson.cpp` - 12o) with the rig on a copy of
the user's card (Fort Baxter): `findvec` near the player's head height, write watches on the hits, the generated code.
- **Skeleton**: a ped's anim tree (`RslTAnimTree`, as in aap's RSL notes) has **+0x4 the node count (25 for peds)**
  and **+0x28 the bone matrices**: world matrices, 0x40 bytes each (rows: X, Y, Z, position; w lanes 0). The ped
  bones are VC's: 0 root, 1 pelvis (both at the ped's position), 2-3 spine, **4 neck** (+0.52 over the ped's
  position), **5 head** (+0.654: the head joint, the top of the neck), **6 the head's end** (same place, its own
  axes), 7-11 left arm (clavicle .. fingers), 12-16 right arm, 17-20 left leg (thigh .. toe), 21-24 right leg. The
  head bone's X row points up the head and its Y row forward (ped forward (-0.35, 0.94): Y (-0.40, 0.91, -0.12)).
  The ped's clump is at **ped +0x50**; `FUN_0019b478(clump)` returns its tree (FUN_002c01f8 walks the clump with the
  callback 0x19B448).
- **The bones are built while the ped is drawn**, not in the game update: a write watch on the head matrix gave
  `FUN_002c0a40` (pc 0x2C0BA8..0x2C0BD0) <- **FUN_0024e8d0(tree)** (the tree's matrices) <- **FUN_003c3250(ped)**
  (`if (FUN_0019b320(clump)) FUN_0024e8d0(FUN_0019b478(clump))`), called at `0x200724` from the ped's render, itself
  under FUN_0021e950 (render) -> FUN_0021eef0 -> FUN_00108dc8 -> FUN_00109368 -> FUN_0035c4b8 (an entity callback
  through a function pointer). Right after it the ped's render calls **FUN_0020c310(ped)** (a getter: `ped[0x550]
  == 0`) at `0x200738` (return address 0x200740), then goes on to draw the skinned mesh - the place to change the
  bones for the draw: first person collapses bones 5 and 6 (rows X, Y, Z zeroed, the position kept) there, and the
  head is drawn as a point. The tree is noted in a before-hook on FUN_0024e8d0 when its return address is 0x3C3280
  and the caller's `s0` (FUN_003c3250 keeps the ped there) is the player.
- **Near plane**: the RW camera is at **TheCamera + 0x7F4**; its **+0x78 is the near plane** (0.3; the far plane
  2000 at +0x7C; the view window's tan / aspect before them, e.g. 0x742AC0 = (0.750, 1.429, 0.3, 2000) in the run
  above). `FUN_0018f448(cam)` reads it (`lwc1 f0, 0x78(a0)`), `FUN_0018f3b0(cam, f12)` sets it (stores +0x78, then
  `FUN_0018f440` / `FUN_001b4688` on the camera's frame). CCamera::Process (FUN_00378dd8) copies it every frame into
  **0x4CD130** (and the far plane into 0x4CD12C) at 0x37B038..0x37B058 for IsSphereVisible - after the CCam's update
  and the height routines, so a near plane written in place of those (as the free camera writes the CCam) is the one
  the frame uses. A branch before it (0x37AF94..0x37B014: from the camera's height over 55 m) can lower the near plane
  to 0.1125 x something through FUN_0018f3b0.
- **Heading**: **ped +0x8E0 = m_fRotationCur, +0x8E4 = m_fRotationDest** (radians, = atan2(-forward.x,
  forward.y): 0 faces +y). Writing Dest turns the ped (the game eases Cur to it; written alone Cur is pulled back).
  Found by searching the ped for the heading worked out from its matrix and writing each hit. **Ped +0x8C4 (state)
  is 0x10 while attacking** (Circle held with a pistol; VC's PED_ATTACK; 0x11 PED_FIGHT), 1 idle.
- **The lock-on camera (mode 11) is not the view from the player's eyes**: it stands behind his shoulder (1.5 m back,
  0.7 m up in the probe) looking at a point beside him (+0x1A0 0.55 m to his right), so its front was 0.9 rad off his
  body; `TheCamera + 0x890` (front from the target point) was 0. R1 picks its target in front of the **body**, in the
  frame R1 is read - the camera switches to mode 11 in that same frame.
- **First person** (`VCS_FIRSTPERSON=1`, the Game page, key B): in place of FUN_002A2ED0 for the active CCam, in mode 4
  (follow ped) and 11 (locked on) with `TheCamera + 0x888` set, on foot, the free camera not flying - the camera at
  the head joint + 0.09 m up + 0.075 m forward (from the last draw, carried with the ped's position), the view from the
  mouse / right stick (mode 11: the body's heading - the game turns him to the target - and the lock-on camera's tilt),
  FOV 90, near plane 0.1 (given back after). The follow camera's heading (+0x7C, = the view's + pi) and stand points
  turn with the view, so W walks where the player looks (checked: 6.2 m walked, 0.000 rad off the view). Standing
  still, attacking (state 0x10 / 0x11) or with Circle / R1 held the body is turned to the view (+0x8E0 / +0x8E4), so
  shots and R1's target search go where the player looks.

### 12d. Aiming: lock-on, the gun's pose, the shot's line - free aim (2026-10-31)

Found for `src/game/vcs_freeaim.cpp` (the user's SA-style free aim; now CameraAim.asi's `freeaim.cpp`, 12o) with the rig on a copy of the user's card (a write
watch on the player's +0x820 while R1 locked on to a spawned ped, pokes of the aim fields) and the generated code.
- **R1's lock-on**: CPlayerPed::ProcessControl (FUN_00230640) calls ProcessPlayerWeapon (FUN_00235d30) at 0x23158C;
  on R1 it calls **CPlayerPed::FindWeaponLockOnTarget (FUN_002d68c8)** at 0x236628 / 0x2366D4. Weapon types 19..35
  (`(1 << type) & 0xFFFF80000`) search with FUN_002d6a70 (angle pi, the weapon's range), the others (fists, melee)
  first with FUN_002d6c80 (pi / 2, 5 m). A target found goes through the vtable's +0x7C (FUN_0023ad28 -> FUN_001fa3d8:
  **ped +0x820 = m_pPointGunAt**, with CleanUpOldReference / RegisterReference; FUN_0023ad28 also sets +0xD14) and
  0x486F78 = 1; it returns found (v0). Returning 0 without those is "nothing found": with a gun R1 then does nothing -
  **VCS has no aim stance without a target** (state stays 1, camera mode 4, the gun stays down; checked).
- Locked on: ped state **0x16** (VC's PED_AIM_GUN), camera mode 11, TheCamera + 0x7F0 (weapon mode) 11. Moving while
  locked the player runs where the stick points (no strafing), the gun turned to the target as far as it goes. The seek
  target (+0x450) stays set after the lock is let go.
- **The gun's pose**: CPed::ProcessControl (FUN_001f4bf0) clears m_pedIK.m_flags (**ped +0x330 + 0x2C = +0x35C**) bits
  0xF8 every frame and, with **bIsAimingGun (ped +0x1C8, 64-bit flags, bit 0x100)** and no blocking animation, calls
  **CPed::AimGun (FUN_001f1438)** at 0x1F8990; with bIsRestoringGun (0x200) RestoreGunPosition (FUN_001f1610).
  AimGun: a seek target (FUN_00218990: **ped +0x450**, or the ped's task when **0x48A638** is non-zero; 0 in play) ->
  PointGunAtPosition (FUN_002ee5c8; a ped target's PED_MID through GetComponentPosition FUN_002edcd8); none ->
  **PointGunInDirection (FUN_002ee6f0)**(m_fLookDirection **+0x6B8**, the player's pitch **+0xCAC**; other peds 0),
  which points with the arm (FUN_002eea28) when IK flag **4 (AIMS_WITH_ARM)** is set. Its result is +0x1C8 bit 0x400
  (bCanPointGunAtTarget); IK flag 1 = pointed (FireInstantHit reads it). CPed::IsPlayer = FUN_0020c310.
- **CPed::SetAimFlag(heading) = FUN_001f1298**: +0x6C8 (look timer) = 0, +0x6B4 (look target) = 0 without giving up
  its reference, flags |= 0x100 and &= ~0x200, +0x6B8 = the heading, SetSeekTarget(0) (FUN_00218478, +0x450), IK flag 4
  from the weapon info's byte 0 bit 7. The attack code (FUN_001d0970) calls it when firing without a target.
  **CPed::ClearAimFlag = FUN_001f13d0**: 0x100 -> 0x200, IK flag 4 off, look timer 0, the player's +0xCAC = 0.
  **+0xCAC is down-positive** (VC's m_fFPSMoveHeading; checked: -0.62 raised the pistol, +0.62 lowered it). The weapon
  info: **FUN_00407120(type) = *(*(0x712770) + 4) + type x 0x70**, +0x8 the range.
- **References**: CEntity::ResolveReferences (FUN_0036d548) clears a registered pointer only while it still points at
  the entity, so a reference field zeroed without CleanUpOldReference (FUN_0036d4f8) is harmless (SetAimFlag does it
  with +0x6B4). RegisterReference = FUN_0036d480 (buildings skipped, no duplicates).
- **The shot's line**: CWeapon::FireInstantHit (FUN_002c3e48; a0 the CWeapon (+4 its type), a1 the shooter, a2 the
  fire source, a3 the shooter's vehicle for a drive-by with t0 the end point) ends in **CWeapon::ProcessLineOfSight
  (FUN_002d0870)**(a0 start, a1 end, a2 colpoint, a3 hit entity**, t0 the type, t1 the shooter, ...): start and end
  are FireInstantHit's own stack (sp+0x40 the source, sp+0x30 the end), and the tracer and impacts after it use them.
  Calls: 0x2C41A4 (drive-by: to *t0, the vehicle and its passengers ignored), 0x2C479C (at m_pPointGunAt: its PED_MID
  with inaccuracy), 0x2C490C (a target but the gun not pointed: (range, 0, 0) through the right hand's frame),
  0x2C4C98 (models 0x113, 0x107, 0xAD: along their forward, with spray), **0x2C4F10 (no target: the source + the
  heading x range, level)**, FUN_002c5c78 and FUN_002cd288 in between. FUN_002cd288 is VC's DoDoomAiming (end.z only;
  skipped for the player when the weapon info's flag 0x40, can aim, is set); FUN_002c5c78 destroys objects within
  1.5 degrees of the shooter's 2D heading and 200 m (counted at 0x4CD4AC - collectibles?), not aiming.
- **Weapon types** (weapon.dat's names at 0x4C3548, in CWeapon::Fire's order): 0 Unarmed, 1 BrassKnuckle, 2
  ScrewDriver, 3 GolfClub, 4 NightStick, 5 Knife, 6 BaseballBat, 7 Hammer, 8 Cleaver, 9 Machete, 10 Katana, 11 Chainsaw,
  12 Grenade, 13 DetonateGrenade, 14 LandMine, 15 SeaMine, 16 TearGas, 17 Molotov, 18 Rocket, 19 Colt45, 20 Python, 21
  Shotgun, 22 Spas12Shotgun, 23 StubbyShotgun, 24 Tec9, 25 Uzi, 26 SilencedIngram, 27 Mp5, 28 m4, 29 Ruger, 30
  SniperRifle, 31 LaserScope, 32 RocketLauncher, 33 FlameThrower, 34 M60, 35 Minigun, 36 Detonator, 37 HeliCannon, 38
  Camera, 39 Binoculars. First-person modes (TheCamera + 0x7F0, set from ProcessPlayerWeapon by FUN_00235c70 through
  FUN_0037c488): 30 / 31 -> 7, 32 -> 8, 38 -> 46, 39 -> 47; instant-hit weapons in modes 34 / 45 fire through
  FireM16_1stPerson (its line of sight returns to 0x2CB394).
- **Shotguns** (21 - 23): FireShotgun (FUN_002c9190) copies the source, takes the heading (or the angle to +0x820) and
  calls FUN_002c7c28, whose pellet loop (21: 3 pellets 4.5 degrees apart, 22: 3 x 3, 23: 5 x 4.5; no randomness) calls
  ProcessLineOfSight returning to **0x2C8278**: start a0 = s7 (the muzzle copy, shared, the tracers' start), end a1 =
  sp+0x90, the pellet's index at sp+0x170 (count sp+0x160), f22 the step and f23 half the spread (radians: pellet i =
  the middle + f23 - i f22), DoDoomAiming applied to the player too (0x2C80A8). The other call (0x2C8018) is VC PC's
  mouse-aimed shotgun (Using3rdPersonMouseCam FUN_002a2e30, needs 0x488EB4, always 0): its start, the camera line's
  point nearest the muzzle, at sp+0xB0.
- **Other weapons**: thrown 12 / 13 / 16 / 17 and the land mine 14 through FireProjectile (FUN_002c9660 ->
  AddProjectile FUN_0017f008): the heading only, the velocity from the ped's throw power (+0xC70); one spawn point for
  all, FUN_001809a0 returning to 0x1804DC (a1 shooter, a2 matrix, a3 velocity). The rocket launcher fires only in the
  first-person modes (the camera's front). The flamethrower (FireAreaEffect FUN_002ca078): half the heading, level;
  AddShot FUN_00179708 returning to 0x2CA470 (*a3 the end) and the particles FUN_002c9d70 returning to 0x2CA4BC (*a1
  the direction x 0.5). The sniper's player shot (FUN_002ca880) has no line of sight call.
- **Free aim** (Game > Free aim, `VCS_FREEAIM=1`): FindWeaponLockOnTarget returns 0 for the player with a type 19..35
  gun other than 30 / 31 (sniper rifles) and 32 (rocket launcher); with R1 held the camera hook (12c's) writes a camera
  over the right shoulder - the ped's position + 0.58 m, 1.5 m back along the view, 0.48 m right, 0.1 m up, FOV 60,
  eased in and out over 0.12 s from the game's follow camera (which keeps working ~4.2 m out; its distance - 0.2 m caps
  ours, for walls behind) - and SetAimFlag's writes every update (the view's heading, minus its pitch), ClearAimFlag's
  after. ProcessLineOfSight from FireInstantHit for the player (return addresses 0x2C47A4, 0x2C4914, 0x2C4CA0,
  0x2C4F18) gets the camera's line while the view is ours: from the point of it nearest the game's start, the weapon's
  range on. Checked in hidden runs: R1 with a ped 9 m ahead did not lock on (+0x820 0, mode 4), the camera eased over
  the shoulder (FOV 60, the game's camera 4.18 m out), the pistol came up (flags 0x503, IK 0x9D) and followed the view
  up and down; a ped 8 m out with the dot on its chest (**ped health: +0x4E4**, found by SET_CHAR_HEALTH 37) went from
  37 to 4.5 with the first shot along the camera's line and died with the second (state 0x39, then 0x3A); in first
  person the dot sat on the ped and the pistol, pointed along the view, showed at the bottom right. Shotgun pellets
  (return address 0x2C8278): each the view's line turned by its own offset (f23 - index x f22) about the vertical, its
  start in sp+0xB0 (a0 pointed there; the muzzle copy stays the tracers'); checked: one Shotgun shot, 3 pellets
  through the hook, a 37-health ped 8 m out killed.

- **Drive-bys** (SA's Manual Driveby Remake ported onto free aim): the game's own is **L2 or R2 (active cam + 0x74
  becomes 1 / 2) + Circle, SMGs only (24..27)**; FUN_002163b8 runs the ped in a vehicle (+0x354: 1 none, 6 bike
  FUN_00217188, 9 FUN_002175e8, else FUN_00216b60; anims group 0x3B, ids 0xEB..0xF8). The shots: **CWeapon::FireFromCar
  (FUN_002c1bb0) -> FireInstantHitFromCar (FUN_002cb7c0)**, its ProcessLineOfSight returning to **0x2CC850** (start
  a0 = its sp+0x40, the muzzle from the driver's hand; end a1 = sp+0x30; t1 the driver, s2 the vehicle, ignored by the
  trace). ped +0xCF8 is a permanent dummy object made by the CPlayerPed constructor (FUN_0022ff20; deleted by
  FUN_0022fbd8). **0x2C41AC** is FireInstantHit calling itself (0x2C52C0) to re-check a hit vehicle's occupants (a3 the
  hit vehicle, occupants with +0x1D8 bit 29 made hittable for that trace), from the muzzle to the first trace's end.
  Free aim in a car: holding L2 / R2 with an SMG puts a camera over the vehicle on that side (at most 3.2 m back, never
  further out than the game's look-aside camera; +-77 degrees about the side, pitch -0.6..0.5, the aim FOV, eased
  0.12 s) - in first person the in-car view - and 0x2CC850 gets its line (0x2C41AC only the start); no pose (the
  drive-by animation holds the gun). Checked: L2 looked straight left (front . right -1.00), R2 right, the mouse turned
  it, 10 / 10 / 11 rounds through the hook (left, right, first person), the dot centred, back to the game's camera on
  release.

### 12e. Vehicle cameras, in-car first person, vehicle glass, the field of view (2026-10-31)

Found for in-car first person (`src/game/vcs_firstperson.cpp`) and `src/game/vcs_carglass.cpp` (both CameraAim.asi's
now, 12o) with the rig (car 211
Sentinel, the PCJ-600) and the generated code.
- **Modes**: CamControl (FUN_00372450) asks for a mode in the halfword 0x6F43E0; CCam::Process switches on mode - 1
  (table 0x4B1870). **18** (FUN_0029faf0) behind cars, bikes, BMX, quad, helis, planes (vehicle +0x354 not 1 / 2; set
  at 0x3736D4 / 0x3736F8), **22** boats and the jetski (+0x354 1 / 2, 0x373718; the same handler), **16** the game's
  own in-car view (FUN_00295290 from 0x295BF4: the vehicle matrix x (0, seat.y + 0.08, seat.z + 0.62), the seat at
  model info +0xA0 (+0x60 boats), FOV 60; bikes the lean matrix and the rider's bone 0x11 + 0.15) when the zoom float
  TheCamera + 0x7C8 is 0. **Select** (FUN_00286220) steps the zoom down: 2 -> 1 -> 0 (mode 16) -> 5 (mode 14, cinematic)
  -> 3 -> 2 (pad config 0, CPad + 0x92).
- **Looking aside**: L2 left (FUN_00285940), R2 right (FUN_00285ab0), both behind (FUN_00285c20); CCam::Process
  (0x294FCC..0x295144) applies them in modes 18, 16, 22 and 3 - **cam + 0x74: 0 behind, 1 left, 2 right, 3 ahead**
  (TheCamera + 0x884 set on a change); helis and planes look behind only (the hovercraft 198 aside too). On foot R3
  looks behind (FUN_00285dd0). CPad: new state at +2, old at +0x32 (L1 +0xA, L2 +0xC, R1 +0xE, R2 +0x10, Start +0x22,
  Select +0x24, R3 +0x30).
- **Mode 18's field of view is stateful**: FOV += (the speed along the vehicle's forward - 0.4 (boats 0.1)) x the
  time step, then above 70 FOV = 70 + (FOV - 70) x 0.98^step (0x29FF6C..0x2A00B8) - scaling the CCam's FOV every frame
  would compound. **CCamera::Process hands the frame's FOV to CDraw::SetFOV (FUN_002653e0, `ms_fFOV` 0x487484) at
  0x37ADD4** (sp+0x104 + *(0x481CDC)); the renderer reads 0x487484 - the game's cameras' field of view settings scale it
  there (return address 0x37ADDC), on foot (mode 4) and in vehicles (18, 22).
- **The driver in a car** is drawn through the same path as on foot (FUN_003c3250 -> FUN_0024e8d0 at 0x3C3280,
  FUN_0020c310 at 0x200740; one bone build a frame); **ped +0x30 holds his world seat position**. Head joint (bone 5)
  in the Sentinel's matrix (-0.39, -0.19, +0.387), within 0.01 from 0 to 29 m/s (reversing he turns his head: (-0.32,
  -0.10)); on the PCJ-600 in its lean matrix (-0.01, 0.135, 0.838) upright.
- **Vehicle fields**: +0x354 type (0 car, 1 boat, 2 jetski, 4 heli, 5 plane, 6 bike, 8 BMX, 9 quad; model info +0x54),
  +0x56 model, +0x160 handling (+0xD0 flags: 0x01000000 bike, 0x02000000 heli, 0x04000000 plane), **+0x140 move speed
  (x 50 = m/s)**, +0x70 turn speed, +0x384 driver; bikes **+0x684 lean (radians)** and **the lean matrix at +0x3C0** (it
  rolls; the bike's own matrix stays level).
- **Near plane in vehicles**: CCamera::Process sets 0.1125 every frame (0x378F24) before the CCam's update; mode 18
  lowers it when obstructed, mode 16 through FUN_002a4d90(cam, 0.1); after the height routines only a script near plane
  (0x3790A0, TheCamera + 0x894), 0.00625 in a blocked transition (0x37A978) and helis / planes over 55 m (0x37B010)
  change it.
- **Vehicle glass** is not separate parts: the windows are meshes with one glass material (model 211: colour
  0x32C2B666, alpha 0x32) in `chassis_hi`, the windscreen and the front doors, materials shared by every vehicle of the
  model. FUN_003942b0 (cars; FUN_00394438 / 394620 / 3947c8 / 394960 the other types) gives `_hi` parts with an alpha
  material or named "windscreen" FUN_0036df88, the rest FUN_0036de58; all end in the part render FUN_0039ec18
  (FUN_0039e828 for pipeline 0x47), which hands **each mesh's colour to FUN_0039e7f0(rgba)** (alpha halved, to the VU)
  before its draw - from 0x39F89C / 0x39F9C0 (the part in s7) and 0x39E920 / 0x39EB24 (the part at 0(sp)). RslElement
  +0x04 frame, +0x18 its clump (vehicle +0x50); RslNode +0xA8 name. World draws alpha-test GREATER 8.
- **In-car first person** (First person + "First person in vehicles"): in modes 18, 22 and 16 the camera at the head
  joint of the last draw kept in the vehicle's space (the lean matrix on bikes) + 0.075 m ahead, 0.09 m up, the mouse
  / right stick looking about the vehicle's ahead (cam + 0x74 adds L2 / R2's quarter turns or behind), eased back after
  0.75 s without look input above 3 m/s (time constant 0.35 s), rolling with the vehicle, FOV of first person, near
  plane 0.1; the game's camera keeps running underneath. The windows: FUN_0039e7f0's colour gets alpha 0 for the
  player's vehicle's glass meshes (alpha < 255, or parts named windscreen*). Checked in hidden runs: the eye at
  (-0.40, -0.12, 0.48) in the Sentinel, looking ahead (front . forward 1.00), the mouse turned it 1.5 rad, 3 s driving
  brought it back (-0.008), first person off gave mode 18 back; the dashboard, wheel and hands drawn, the glass gone, and
  shown again on foot. Field of view settings: CDraw's FOV 90 on foot with 90, 85 in the car with 85.
- **Camera shake**: CCamera::Process applies VC's CamShake after the CCam's update (0x37AC5C..0x37AD5C): strength =
  TheCamera + 0x7C0 (force) - 0.00028 x (now - TheCamera + 0x7C4, the start, ms), clamped 0..2; a random offset of up to
  +-0.7 x strength per axis added to TheCamera's position (+0x30) and the pad rumbled from it. Set by CamShake
  FUN_00376988 / FUN_00376a28 (explosions FUN_002e1140, the sniper's shot, ...). In-car first person zeroes the force
  every update (the third-person cameras keep their shake) and eases the vehicle's forward / up for the view over 0.08 s
  (the body's jolts on bumps at speed stayed in a view fixed to it).

### 12f. Hook points for a physics engine - SA's Jolt Physics mod (research, 2026-10-31)

From the analysis of SA's "[SA] Jolt Physics" (an ASI with Jolt 5.6.0 statically linked: death / knockdown / active
ragdolls, ballistics, gore, foot IK, jiggle bones, gun and cash props; hooks per frame after CGame::Process, rendering,
Fx_c::TriggerGunshot, CBulletTraces::AddTrace, CExplosion::AddExplosion, CWeapon::GenerateDamageEvent, the dead-ped
money / weapon pickups, CPopulation::ManagePopulation, CEntity::GetIsOnScreen, CPhysical::ApplySpeed). VCS's
counterparts, from the generated code (not all checked at run time):
- A physics step: **FUN_00408c30**, called only at 0x3BABDC, right after CWorld::Process (0x3BABD0) in CGame::Process.
- Bones for a ragdoll: the ped's 25 world matrices of its last draw (12c), written in the FUN_0020c310 before-hook at
  0x200740.
- **CPhysical::ApplyMoveSpeed = FUN_00348098** (no direct callers: through the vtable).
- **CPed::SetDie = FUN_0020a3b8** (state 0x39), **SetDead = FUN_0020a818** (0x3A), both through SetPedState
  (FUN_00219340); the knockdown is **CPed::SetFall = FUN_002022f0** (state 0x2D), its get-up **SetGetUp =
  FUN_00203240** (0x2E): 12l. (FUN_0020b558 sets state 0x33, not the fall.)
- Bullet hits: FireInstantHit -> ProcessLineOfSight -> FUN_002c5320 (called once at 0x2C5138; likely the impact,
  unverified). **CExplosion::AddExplosion = FUN_002e1140** (from the ADD_EXPLOSION handler FUN_00182998; 22 callers).
- CPopulation::Update FUN_00430148, entity removal FUN_00198408 (corpse despawn; partial).
- The CColModel layout and the world sectors' collision lists: 12k. VU code runs with round-toward-zero, so a native
  physics step needs the host rounding mode restored around it.
- Milestone 1 (death ragdolls) is built on the step, the bones, ApplyMoveSpeed and SetDie, checked at run time: 12h;
  milestone 2 (the world's collision) on the sectors and col models: 12k.

### 12g. Weapon models, their textures, streaming, reloading - the Immersive Weapons Pack port (2026-10-31)

Found with the rig on a copy of the user's card (iwp probes: weapon info / model info / streaming info dumps, write watches
on a model's load state, a weapon's clip and state) and by reading the chunks straight from the disc.
- **CWeaponInfo** (FUN_00407120, 0x70 each): +0 flags, +4 fire type, +8 range, +0xC firing rate, **+0x10 reload time (ms)**,
  +0x14 clip size, +0x18 damage, +0x30 fire offset, **+0x40 anim group**, +0x44.. anim loop / fire frames, **+0x60 model,
  +0x64 second model** (-1 none), +0x68 slot. Models: knuckles..chainsaw 331..341, grenade 342, tear gas 343, molotov 344,
  rocket 345, **Colt45 346**, Python 347, Ruger 348, shotguns 349..351, m4 352, Tec9 353, Uzi 354, silenced Ingram 355, MP5
  356, sniper 357, laser scope 358, rocket launcher 359, flamethrower 360, M60 361 (and the heli cannon), minigun 362 (+366),
  detonator 363, camera 364, binoculars 367, land mine 368. tools/weapon_convert.py has the table (with the dictionaries).
- **Model info** (CWeaponModelInfo, 0x44 bytes, vtable 0x491938): +8 name hash, +0xC the loaded element, +0x1C refs (u16),
  **+0x1E texture dictionary slot** (u16; Colt45 293), +0x3C weapon type.
- **CStreaming** (`*0x489FF8`): +8 first texture dictionary id (7534), +0xC first collision id (8365), +0x10 first animation
  id (8392); **+200 -> the streaming infos**, 0x18 bytes per id: +0xC load state (1 loaded, 3 requested), +0x10 position and
  +0x14 size, both in sectors of GTA3PS2.IMG. Dictionary id = 7534 + the slot (Colt45: 7827). In the IMG each weapon's 'xet'
  sits just before its 'ldm' (Colt45: 0x2DBE, 2 sectors; 0x2DC0, 3 sectors); an 'anim' chunk (id 8408, 0x2DC3) follows.
- **Loading**: CStreaming::RequestModel **FUN_003C7ED8**(streaming, id, flags) allocates size x 2048 bytes (FUN_003C6478)
  and reads that many sectors (FUN_002213D0 -> FUN_00220EC8); FUN_003C7048 checks the bytes read against the size and calls
  **ConvertBufferToObject FUN_003C72A8**(streaming, id, buffer): models FUN_003C7498, dictionaries FUN_003C7918, collision
  FUN_003C79A8, animations FUN_003C7AD8, each relocating the chunk in place (FUN_00324A50), then state 1. So a bigger file
  only needs a bigger size word before the request: `src/game/vcs_stream_override.cpp` (DECISIONS.md).
- **'ldm' chunk** (Leeds relocatable chunk: ident, shrink, fileEnd, dataEnd, relocation table + count, global table,
  u16 classes, u16 functions; pointers are chunk offsets): +0x20 -> the RslElement, then the materials' pointer array.
  Material 16 bytes {texture-name pointer (the name strings follow the relocation table), colour (0xFF969696 for guns),
  2, 0}. RslElement 0x38 bytes {0x0004AA01, frame, frame link x2, 0, geometry +0x14, clump, link x2, render callback +0x24
  (the one entry of the global table, filled at load), u16 model id +0x28}. RslNode 0xB0 {0x0300AA00, parent, object
  list x2, modelling matrix +0x10, LTM +0x50, child, next, root +0x98, ..., name +0xA8}. RslGeometry {8, 0, 1, materials,
  count, 0x10, skin, 0} then the **PS2 geometry** at +0x20: bounding sphere, **(meshes << 20 | bytes to the end of the
  packets)**, 7, u16 strip vertices of all meshes, u16 header size (0x40 + 0x30 x meshes), int16 box min / max, **scale
  xyz, centre xyz** (vertex = int16 / 32768 x scale + centre); mesh headers 0x30: sphere, **uv scale xy**, a value added to
  log2(texture width) x 16 for FUN_00317F10 (0x25 on the Colt45), packet offset from the first packet, u16 triangles
  (strip vertices - 2), i16 material, int16 box. Each mesh's packet: DMA RET tag, then batches of <= 70 strip vertices
  overlapping by 2 (no restarts but degenerate triangles): UNPACK V4-32 to 0 (0, 0, n, n | 0x8000), STMASK / STROW 0 +
  **V3-16 positions** at 1, STMASK 0x50505050 / STROW (0, 0, 255, 0) + **V2-8 uv** (unsigned; 127 = 1.0 x the uv scale, which the
  render passes doubled) at 0x8D, **V3-8 normals** (length 127) at 0x47, MSCAL 6 - the rigid lit pipeline (6d).
  Per mesh the render (FUN_0039E828 loop) binds the material's texture (FUN_00408F30), the uv scale (FUN_00317D48) and
  CALLs the packet (FUN_002F7D58).
- **'xet' chunk** (a texture dictionary): +0x20 {0x00008606, 0, texture list}; textures 0x60 {raster, dictionary, link x2,
  name[32], mask[32], 1}; rasters 0x10 {0, (0x45 << 16 | row bytes) for 4-bit, (0x25 << 16 | row bytes) for 8-bit, pixels,
  **log2 w | log2 h << 6 | depth << 12 | mips << 20 | per-mip swizzle bits << 24**}; the CLUT follows the last mip (16 or 256
  RGBA, alpha 0x80 = opaque, 256 in CSM1 order). The bind (FUN_00317FB8) reads these: depth 4 -> PSMT4, 8 -> PSMT8; all
  weapon / ped textures seen are linear (swizzle 0), up to 256x256 8-bit.
- **Reloading**: a ped's CWeapon array is at ped +0x574, 0x1C each: **+4 type, +8 state (2 reloading), +0xC clip, +0x10
  total, +0x14 the reload's end time**. CWeapon::Fire (FUN_002C0F98) sets state 2 at **0x2C1998** when the clip is empty,
  end = CTimer ms (0x4CD104) + info +0x10; CWeapon::Update **FUN_002CE018** (from CPlayerPed::ProcessControl 0x231694)
  calls **CWeapon::Reload FUN_002CDFB0** (clip = min(total, clip size), 0x2CE000) and state 0 when the time is up.
- Checked: the Immersive Weapons Pack's Colt45 (SA DFF, 16.5k triangles, 9 textures at 128x128) converted by
  tools/weapon_convert.py (249 + 79 sectors) loads, draws in the hand and fires / reloads in a hidden run (build/iwp).
- **The streaming heap** is the CMemoryHeap at **0x51F420** (FUN_003C6478 allocates stream buffers from it through
  FUN_002BC730): +4 the out-of-memory callback (0x21C300), **+8 the free blocks** (a tree: +0 size, +8 / +0xC children;
  FUN_002BBB00 = the largest free block), **+0x14 bytes allocated** - 5.4 - 5.5 MB in play, with 0.1 - 0.3 MB free in
  20 - 50 blocks (largest 30 - 80 KB): a cache kept full. RequestModel calls **FUN_003CB760**(streaming, bytes) first,
  which evicts least-recently-used streamed objects (FUN_003C9F10) until the largest free block fits, so a bigger file
  costs world data, not a failure (a 500 KB Colt45 loaded). Every weapon a ped carries stays loaded (its model's refs),
  so the converted weapons were kept at 25 - 110 KB each (VCS's: 2 - 13 KB); a full inventory costs ~0.6 MB.
- **Where the streaming heap comes from** (2026-10-31, the generated code): the game's **main heap** is the CMemoryHeap
  at **0x51D6A0** (FUN_002BB658 returns it; FUN_002BB6A0 constructs it once and FUN_002BB6F8 -> **CMemoryHeap::Init
  FUN_002BB768(heap, start, size, small-block area)** gives it 0x74DF54 .. 0x1FE0000, 25.7 MB with 0x80000 of
  small-block pools; FUN_002BC730(heap, size) allocates, sizes up to 0x100 from the pools; FUN_002BD178(size) =
  allocate from the main heap). **FUN_002E5688** (called once from FUN_0021C5E8 at 0x21C8E0, guarded by heap +0x12C;
  FUN_00255308 0x2554D8 the same) takes **0x567000 bytes** (lui 0x56 / ori 0x7000 at 0x2E5698 and 0x2E56A4) from the
  main heap through FUN_002BD178 (returning to 0x2E56A4) and makes them the streaming heap 0x51F420 with Init (returning
  to 0x2E56C0): 0x1180B78 .. 0x16E77F8 in play. FUN_0021C5E8 sets both heaps' out-of-memory callbacks (FUN_002BCC50;
  0x21C300 and 0x21C3A8) and the small-block pool sizes (FUN_002BD0C8). FUN_003693A0 makes a third, 0x7D000-byte heap the
  same way. Header: +0 size, +4 callback, +8 free-block tree, +0xC first block, +0x10 end, +0x14 bytes used.
- **No RAM beyond 32 MB**: guest addresses are masked to 0x1FFFFFF (the runtime's 32 MB); the main heap ends 128 KB under
  the top (the stack). In play (Downtown, four city spots, a full inventory) **the main heap has 0.9 - 1.0 MB free**
  (one block of 0.93 - 1.0 MB): that is the only spare memory. Zero-filled runs elsewhere (0x548000 / 0x640000, in the
  0x500000 - 0x6FFFFF packet buffers; 0x80000 below the ELF) are not known to be unused and were left alone.
- **Measured headroom of the streaming heap** (hidden runs, `heaptest`: a full inventory - chainsaw, grenade, Python,
  SPAS, MP5, M4, sniper rifle, minigun, camera - then five busy spots with the camera turned round; the CStreaming infos
  counted, the override's loads from the log): 140 - 170 objects loaded; collision ~2.5 MB, models ~1.8 MB, texture
  dictionaries 0.6 - 1.0 MB, animations 0.2 - 0.3 MB; 0.1 - 0.4 MB free in 20 - 50 blocks. With the 80's VC True
  Vegetation port's files (1.1 MB) in the folder too, a weapon inventory of 0.29 MB caused no reloads, 0.58 MB 135 at one
  spot, the first conversion's 0.82 MB 180 - 1440 reloads of a vegetation dictionary in ten seconds at three of five spots
  (evicted and loaded again every frame), and SA's own texture coordinates at 4 - 6k triangles (2.7 MB) ended the game
  thread (pc 0) while the sixth weapon loaded. So the streaming heap is full: bigger weapons cost the world.
- **The weapons' batches as the native lit draw sees them** (2026-11-01, WeaponHD.asi; the refiner's `VcsLitBatch`):
  rigid, one batch per MSCAL of the converted packets (<= 70 strip vertices, 2 shared with the next), `pos` the model's
  int16 positions (V3-16, signed), **pos_scale 1/32768 and pos_offset ~1.5e-5** (the model's scale and centre from its
  geometry header are in the matrices, not here), normals of length ~127, uv the V2-8 values with **the third lane
  255** (the STROW fill; a refined batch with 0 there drew nothing), all as uploaded - so a hash of the positions
  identifies each batch of each converted model (FNV-1a over count + int32 x / y / z; 991 batches over 28 models, no
  collisions). Frame cost of drawing the full meshes instead (M4 51k, minigun ~40k triangles; hidden run, held, D3D11):
  render 0.6 ms either way, GPU 1.2 -> 1.5 ms, +52k vertices.
- **The floating M4 muzzle** was not a transform: the M4's barrel is a separate 133-triangle piece (x 0.26 .. 0.63), and
  simplifying the whole 51k-triangle model to 1.7k flattened it into a line (quadrics count a thin part's collapse as
  cheap). Each piece is now simplified on its own with a floor that grows with its length.
- **Weapon frames**: SA and VCS share the convention (x along the barrel, z up, the grip near the hand bone's origin),
  but VCS's grips sit ~6 cm further forward and ~2.5 cm higher in the hand frame (the median over the guns fitted to
  VCS's own models at the grip), and VCS's long melee weapons lean ~20 degrees forward about y (golf club 21, bat and
  katana 18, knife 12). The minigun's barrels (model 366, dictionary 7847 = slot 313) are drawn spinning about their own
  x axis, their front end at the model's origin (VCS's: x -0.456 .. 0.017). VCS's rocket (345) points along -y.
- **The hand**: a ped's right hand is bone **15** of its anim tree (12c), the weapon drawn in its frame. The tree from
  the ped: `*(*(*(ped + 0x50) + 8) - 0x1C + 0x2C)` (the clump's first atomic +0x2C; FUN_0019b478 -> FUN_0024ebb0).
- **Script cameras** (VCS opcodes, Sanny Builder Library vcs.json): SET_FIXED_CAMERA_POSITION **0x00B9** (x y z, 3
  rotations), POINT_CAMERA_AT_POINT **0x00BA** (x y z, switch style), POINT_CAMERA_AT_CHAR 0x00B5, RESTORE_CAMERA 0x00B6;
  SET_CURRENT_CHAR_WEAPON 0x010B, SET_CHAR_AMMO 0x00D5, SET_ANIM_GROUP_FOR_CHAR 0x015F.
- **Converted models** draw without back-face culling (strips of either winding came out whole), so one side of a
  double-sided SA surface is enough. Material +0xC is an extension pointer (FUN_0042C0F0 reads its +0xC flags; flag 2 =
  drawn in the second, alpha pass); 0 = none.
- Note for test runs: vcs_stream_override's folder walk fails silently on paths near MAX_PATH; a mods folder under a
  long path (the agent scratchpad) loaded nothing - use a short one.

### 12i. Animation blocks - the Immersive Weapons Pack's animations (2026-10-31)

Found by reading the 'mina' chunks from the disc (CStreaming ids 8392 + the block) and the generated code.
- **Loading**: ConvertBufferToObject -> FUN_003C7AD8 -> **FUN_003C7B28**: checks the ident 'mina' and fileEnd /
  relocation table against the buffer (size x 2048), relocates (FUN_00324A50), then **FUN_002259A8**(CAnimManager, block,
  pointer array, chunk): the block record is `*(*(manager + 0xC) + 0x10140) + block x 0x30` (+0x1C first animation, +0x20
  count, +0x24 the chunk, +0x14 loaded), and hierarchy i (0x28 bytes) is **copied** to the animation slot
  `*(... + 0x1013C) + (first + i) x 0x28`. So a replacement block keeps the anims' count, order and names.
- **Layout**: +0x20 an array of pointers to the hierarchies (as many as the block record says), then the key data
  (each track's keys word-aligned), the hierarchies, the tracks, the relocation table (the array, each hierarchy's
  tracks pointer, each track's keys pointer). **Hierarchy 0x28**: tracks pointer, name[24], u32 track count, float
  duration, u32 a size (equal to the key bytes for some anims, larger for others, the same 6780 / 9266 for every
  crouch anim of several blocks - not understood; a converted anim gets max(original, its own bytes)). **Track 12
  bytes**: u16 flags (**0x9** rotation, **0xB** rotation + translation: the root), u16 key count, keys pointer, **u16
  bone id**, u16 a hash per bone (0 df9e, 1 b88a, 2 9a64, 3 bcfc, 4 e97b, 5 6e99, 31..35 b052 2830 1e52 c7d5 a1c5,
  21..25 8935 1157 7a50 fe09 c8f4, 41..43 cdd3 ccec 2938, 51..53 fa32 f530 10e4). **Keys** are half floats: quaternion
  x y z w, **the time since the previous key** (the first 0; every track sums to the duration), then x y z for 0xB.
  Bone ids are SA's (0 root, 1 pelvis, 2 / 3 spine, 4 neck, 5 head, 21-25 right arm clavicle .. finger, 31-35 left
  arm, 41-43 / 51-53 legs); fire anims carry only the bones they move (colt45_fire: 21-24).
- **Weapon blocks**: buddy 8404 (0x2DF3, 8 sectors: buddy_crouchfire / fire / reload), colt45 8408 (0x2DC3, 4:
  colt45_cop / crouchfire / crouchreload / fire / reload), python 8459, RIFLE 8464, shotgun 8467 (fire, crouchfire),
  sniper 8469, TEC 8474, UZI 8480, M60 8444, rocket 8466, FLAME 8415; melee: 8395 bat / golf club, 8406 chainsaw, 8427
  knife, 8473 sword; 8419 throwing. tools/anim_convert.py has the table and `--dump`.
- SA's IFP (ANP3) bones carry the same ids and the same bone frames: the first frames of anims both games share
  (colt45_fire) agree within 4 - 15 degrees bone by bone, other pairs differ from anim to anim with no constant offset;
  crouching lowers the root 0.58 m in SA, 0.59 - 0.63 m in VCS.
- **SA's fire anims lean on SA's aiming IK**: unaimed they leave the elbow bent (colt45_fire's forearm 97 degrees off
  VCS's at the fire point), and their spine / neck keys (the clavicles' parents) tip the gun up - converted as they are,
  the Colt45 fired pointing at the sky. VCS's own fire anims hold the gun out themselves. So a converted fire anim keeps
  SA's arms (21-25, 31-35) and both clavicles turn, in the neck's frame, by the rotation that puts SA's gun hand
  (21 * 22 * 23 * 24) onto VCS's own anim's at the weapon's fire point; the second hand of a two-handed hold moves with
  it. **The body comes from VCS's own anim** (correction, below): only colt45_fire carries just the arms (21-24); every
  other VCS fire / crouch-fire anim carries the whole body (root, spine, neck, legs; RIFLE_fire turns the shoulders for
  the rifle stance, UZI_fire adds bone 6).
- **The aim over the anims** (2026-10-31, free aim, hidden runs with the rig: R1 held, the view turned by `mouse`
  counts, the right hand's x axis - the barrel, bone 15 - against the view's direction, held and 0.25 s into firing):
  AimGun's IK works on top of the anim pose, so with VCS's own anims the gun follows the view within 5 - 15 degrees
  (Colt45 up / down 36 degrees: hand pitch 41 / -30; M4 23 / -44; MP5 39 / -32). **CWeaponInfo byte 0 bit 0x80 = aims
  with the arm** (ped IK flag 4): set for 19 Colt45, 24 Tec9, 26 silenced Ingram only (the rest 0x40; 28 0x50, 32 0x34,
  33 0x5E). Anim group (+0x40) per type: 19 -> 14 (colt45 block). The arm IK turns the **right upper arm alone**, so it
  points the gun only when the anim holds it along a straight arm (VCS's colt45_fire): with SA's two-handed / bent-elbow
  pistol anims the gun stayed 28 - 33 degrees off the aim and the IK gave up (ped +0x1C8 bit 0x400 bCanPointGunAtTarget
  clear, IK flags 0x9E instead of 0x97) - **the pack's pistol fire anims cannot follow free aim** without moving the
  Colt45 to the torso IK (a change of that bit), so the colt45 block keeps VCS's fire / crouch-fire and takes the pack's
  reloads only. The other guns aim with the torso (PED_MID), which turns the anim's whole upper body: the arms-only
  conversion had lost VCS's body pose (RIFLE_fire's turned shoulders), so the M4 / shotgun pointed 53 degrees left of
  the aim at every pitch - the user's "the gun does not rotate to where I aim". With VCS's body under SA's aligned arms
  the errors are VCS's own: M4 13 - 16 degrees (VCS's 9 - 15), Uzi / MP5 4 - 10, Spas 9 - 15, Python 11 - 27 (its
  recoil). The Tec9 and silenced Ingram (arm IK) use none of the converted blocks (3 degrees).
- The Tec9 fires with neither the TEC (8474) nor the UZI block loaded by it in the checks (one-handed, as before the
  change): TEC is not used by the player's weapons; the Uzi, MP5 (and the silenced Ingram) use UZI.
- Checked (hidden runs, build/iwp/stageB): every converted block loads through the override (CStreaming state 1), the
  Colt45 fires two-handed, the Python, shotguns, Uzi, MP5, M4 / Ruger and sniper rifle fire and reload in the pack's
  poses, no errors in the log.

### 12h. Death ragdolls - Jolt Physics, milestone 1 (2026-10-31)

Found for `VCS-mods plugins/JoltPhysics/src/jolt.cpp` / `VCS-mods plugins/JoltPhysics/src/physics/ragdoll.cpp` with the rig on a copy of the user's card (the player's
anim tree - from first person's status - dumped standing and running; spawned peds killed) and the generated code.
- **RslTAnimTree +0x30, the node info**: 8 bytes a node - byte 0 the bone id, byte 1 its index, **byte 2 the flags (2
  push, 1 pop the parent: RenderWare HAnim's)**, byte 3 (1 on the root) - and a word (0). The ids are SA-like: 0-6 root,
  pelvis, spine, spine1, neck, head, head end; **31-35 the left arm, 21-25 the right arm, 41-43 the left leg, 51-53 the
  right leg, 0xFF the toes**. The flags give **0 <- 1 pelvis <- 2 spine <- 3 spine1 <- 4 neck <- 5 head <- 6; the
  clavicles (7, 12) hang off the neck, the thighs (17, 21) off the spine (2)**, each limb a chain (3ds Max Biped's
  layout). Another copy of the same array follows it.
- **Bone frames** (orthonormal, right-handed): bones 1-4 X up the spine, Y forward, Z left; the root (0) X forward, Y
  left, Z up; a limb's X runs along it to its child; the clavicles' X outward. **An elbow or knee bends about the Z its
  two bones share** (left on both arms, right on both legs) **by a negative angle**: knees -20 degrees standing, -80 and
  -111 running; elbows -100 and -122 (worked out from the dumped matrices).
- **Dying**: health (+0x4E4) set to 0 kills the ped in its next CPed::ProcessControl (VC's `health <= 1` -> SetDie):
  state 0x39 at once, 0x3A about a second later. **CPed::SetDie** (FUN_0020a3b8, a0 the ped; nothing when the state is
  already 0x39 / 0x3A) runs inside CWorld::Process, before FUN_00408c30. Vic's death (Wasted) too; about 10 s later the
  game puts him at the hospital (a teleport; the same ped) with his state back to 1.
- **CPhysical::ApplyMoveSpeed** (FUN_00348098): with either of the entity flags +0xE8 bits 62 / 63 it zeroes the move
  speed (FUN_00356288), else position (+0x30) += move speed (+0x140) x ms_fTimeStep.
- **A standing ped's position is ~1 m over its soles** (its toe bones at -0.98 / -0.99, its feet at -0.91): a ped spawned
  on the road at z 11.10 had its toes at 10.11; Vic, 4 m away on the pavement, stood at 11.25.
- **The ragdolls** (Game > Physics > Ragdolls, `VCS_JOLT`; DECISIONS.md): SetDie notes the ped and its move speed x 50
  (m/s); at its next draw - its tree noted where FUN_0024e8d0 returns to 0x3C3280, then FUN_0020c310 at 0x200740 before
  the skinned draw - a Jolt ragdoll is made from the bones just built: 11 bodies (hips on bone 2, chest 3, head 5, upper
  arms 8 / 13, forearms 9 / 14 with the hands, thighs 17 / 21, calves 18 / 22 with the feet), swing-twist joints at the
  waist, neck, shoulders and hips, hinges at the elbows and knees (-150 .. +3 degrees about their Z). From then on its 25
  matrices are written there at every draw: the parts' bones from the bodies, the others carried with their parents as
  at death. FUN_00408c30's before-hook steps the physics (ms_fTimeStep / 50 s) and moves the ped's x / y to its root
  bone; ApplyMoveSpeed is not run for it. The ragdoll goes when the ped's pool slot is freed or reused, its state leaves
  0x39 / 0x3A, or the game moves it by more than 2 m (Vic's respawn). Milestone 1 landed each on a ground of its own 1 m
  under the ped's position (or under its lowest bone); since milestone 2 that is only where the world has no collision
  under it (12k).
- Checked (`tools/ragdoll_check.py`, hidden): a ped killed standing still - the ragdoll made at its next draw, the
  pelvis from 11.08 down to 10.16 (the hips down, the trunk still up), then the trunk over: lying at 10.23, 13 cm over
  the road, still and asleep after ~4 s, the drawn pelvis the physics' own, the ped's position on the body; then Vic
  killed: his ragdoll, his respawn at the hospital (-884, -470), the ragdoll gone. Eight peds killed at once: the step
  0.49 ms on average while they fall (0.70 at most, 88 bodies awake), ~0.005 ms once asleep. The setting switched at
  run time: off (the default) the game's own death, on the next death a ragdoll, off again the ragdoll removed. Street
  peds of models 8, 26, 28, 43 and 64 (and the spawned 55) all have this skeleton; their corpses are deleted by the game
  once Vic goes elsewhere (the ragdolls with them). The matrices' w lanes read 0 (bones 0-5 of six trees); the game
  never writes them, so only the rows' xyz are taken or written. One ped was refused before refusals said why (a
  stricter check on all 16 floats then): not seen again.
- **The killing blow** (the user's videos: a shotgun victim only crumpled, cars drove through the bodies). **CPed::
  InflictDamage = FUN_001d7940**(ped a0, attacker a1, weapon a2, damage f12, piece a3 - VC's 0 torso, 1 mid, 2 / 3 left /
  right arm, 4 / 5 left / right leg, 6 head -, direction t0; t1 is stored and never read); VC's: it bumps the player's
  shots-hit count (CPlayerInfo +0x154, 0x190 per player) for damage over 3 and calls SetDie. Found as the function
  calling SetDie three times among SetDie's 12 callers (FUN_00203240, the other one also calling InflictDamage, is
  CPed::SetGetUp: state 0x2E, a car - not a bike - on top of the ped; 12l). **The game knocks the ped back before
  InflictDamage**: a shotgun victim had 5.6 m/s at its first pellet's call, a ped run down 5.2 - 13 m/s. A car's hit
  comes as weapon 42 or 43 with the vehicle as attacker (piece 1 or 6).
- **CColModel**: **model info +0x14**; +0x00 the bounding sphere's centre, +0x0C its radius, **+0x10 the box's min,
  +0x20 its max** (16-byte vectors), in the model's frame (found by following model info pointers to sphere-and-box
  floats in a run): the Sentinel (211) (-1.18, -3.11, -0.68) .. (1.18, 2.69, 0.75), radius 2.82; peds (-0.35, -0.35,
  -1.0) .. (0.35, 0.35, 0.9), radius 1.25 - their position 1 m over the soles again.
- **The blow's push** (DECISIONS.md): InflictDamage's arguments are kept per ped (the first of a frame's burst: a
  shotgun's later pellets come after the knock-back); when SetDie follows, the ragdoll gets, from a ped attacker, a
  push from its side on the part hit (kg m/s by weapon, after SA's mod's DeathPush; shotguns over the trunk, x 1.6 at
  point blank down to x 1 at 10 m) with the victim's own speed capped at 2 m/s (the game's knock-back left out); from a
  vehicle, its speed at the blow to the legs (lifted), less to the trunk and head. Vehicles within 15 m of a ragdoll
  are kinematic bodies: the col model's box raised 0.25 m off the ground; a car (+0x354 = 0) as its lower body to 55% of
  the height plus the cabin, set back a third of the length from the front.
- Checked (`tools/ragdoll_check.py`): a Shotgun kill at 4 m throws the body 2.3 - 2.5 m back, airborne at 0.25 s
  (before: it crumpled where it stood); Vic's Sentinel at 11.8 m/s into a ped - the body over the bonnet against the
  windscreen, legs up, for ~1 s while he keeps the throttle, then off the front as the car slows, 0.9 m ahead of the
  bumper (before: the car drove through it). Right after the Wasted respawn the game ignores the throttle for a while
  (the check runs the car before Vic's death).
- **Shots on a body already down** (the user's request: corpse reactions). **CWeapon::DoBulletImpact = FUN_002c6460**
  (weapon a0 - its type at +4 -, shooter a1, victim a2, source* a3, end* t0, **colpoint* t1**: the point at +0, the piece
  hit at +0x33, as InflictDamage's piece), called from FireInstantHit (0x2C51FC) and FUN_002cb1d0 (0x2CB4C4) only. The
  Shotgun's pellets (FUN_002c7c28) have their own: ProcessLineOfSight (start *s7, end s2, colpoint sp+0x30, the entity
  out at sp+0x150, weapon sp+0x154; the two bytes cleared after it are VC's bIncludeDeadPeds pair), then for a ped not
  dying / dead ApplyMoveForce (FUN_00347D20: the knock-back, ~6 x the line + 5 up) and InflictDamage; for one dying or
  dead (0x2C85E0 -> 0x2C8914), with the gore flag **CGame::nastyGame 0x489F80** (1), **CEntity::GetIsOnScreen =
  FUN_003c4318** (its col sphere against the view) then 8 blood particles (FUN_001E9040) and, dead, a hit-the-floor
  animation (FUN_00178828 on the clump) - no physics. **The game's own collision for a dead ped is not where its ragdoll
  lies**: Colt45 shots aimed at a lying body's hips (traced at DoBulletImpact) hit the road under them (victim a building
  entity), a Shotgun's pellets met it now and then. So bullets are cast against the ragdolls themselves: a before-hook
  on **CWeapon::ProcessLineOfSight (FUN_002d0870; start* a0, end* a1, ..., weapon t0, shooter t1)**, every bullet's line
  (FireInstantHit's, each pellet's, drive-bys'), Jolt's ray against the ragdoll parts, the part met pushed at that
  point (kg m/s per bullet by weapon, after SA's PhysicsForce x 2). Free aim's hook on the same function is installed
  after Jolt's, so it wraps it and the line seen is the camera's.
- **Blasts**: **CExplosion::AddExplosion = FUN_002e1140**(exploding entity a0, culprit a1, type a2 - 12 types through a
  jump table, VC's radius / power pairs: grenade and car 9 / 300, rocket 10 / 300, heli 6 / 300, mine 10 / 150, ... -,
  position* a3, lifetime t0) calls **CWorld::TriggerExplosion = FUN_00192760**(position* a0, culprit a1, flag a2, a3,
  **radius f12 = the explosion's +0x20, power f13 = its +0x40**), also called twice from CExplosion::Update (0x2E2494,
  0x2E3010). It runs the sector lists through FUN_001929a8 (3 calls), which pushes and damages (InflictDamage with the
  blast's weapon: a grenade's 12, else 0x31) - the push again before the damage (a grenade's victim had 11 m/s at
  SetDie). The script command **ADD_EXPLOSION is opcode 0x013C** (x, y, z, type; handler FUN_00182998, found in the
  opcode table at 0x4BEAF0 by its handler).
- Checked (`tools/ragdoll_check.py`, a second game with first person and free aim to aim down at a body): Colt45 shots
  at a lying body hit its ragdoll (2 of 3), a Shotgun blast put 3 pellets on it and shoved its pelvis 0.24 m; an
  ADD_EXPLOSION of type 0 (a grenade's) 2 m from a lying body threw it 7.3 m, and the ped 2 m on its other side died
  and was thrown by the blast's own throw (the game's 11 m/s left out).

### 12j. Model infos by name, vegetation models - the 80's VC True Vegetation port (2026-10-31)

Found with RAM dumps of a hidden run (the rig's `dump`) and the models read from the disc (`tools/veg_convert.py`).
- **Model infos start 0x24 before their vtable word** (GCC 2's vptr placement): +8 the name hash, +0x1E the texture
  dictionary slot, +0x24 the vtable (CSimpleModelInfo `0x4915B0`, 3,840 of 4,428; weapons `0x491938`), +0x28 the atomics,
  +0x2C the LOD distances, +0x38 the atomic count, +0x3A flags. The weapon offsets in 12g count from the same start.
  **CModelInfo's pointer array** is on the heap (`0x1AB4CC8` in that run): found as the array whose entry 346 points to
  the model info with dictionary slot 293 (the Colt45).
- **Names are CKeyGen::GetUppercaseKey = `FUN_00366480`**: CRC-32 (table at `0x488860`, start 0xFFFFFFFF, no final xor)
  of the upper-cased name; `FUN_00366428` is the same without upper-casing. So VC's names find VCS's models.
- **VCS keeps VC's vegetation names**: `veg_palm01` 578, `veg_palm02` 546, `veg_palm03` 547, `veg_palm04` 545,
  `veg_palmbig14` 574, `veg_palwee01` 548, `veg_palwee02` 549, `veg_tree3` 540, `veg_treea1` 541, `veg_treeb1` 542,
  `veg_treea3` 543 - CSimpleModelInfo, one atomic, flags 0x840, LOD distance 290 for the big palms; each with a texture
  dictionary of its own (slots 375-385, no other model uses them). `veg_palwee03` and the `veg_palmkb*` set exist as
  names without data (no position in GTA3PS2.IMG). The palms are VC's designs drawn larger (`veg_palm01` 33.5 x 27.4 x
  41.2 m against VC's 24 x 13.5 x 29), 76 - 602 triangles, 1 - 4 sectors, dictionaries of 6 - 7 sectors.
- **Map objects are prelit**: the same 'ldm' as the weapons (12g) but geometry flags **0xD** (weapons 7) and per batch
  V3-16 positions at 1, **V2-8 uv at 0x48**, **V4-5 colours (RGBA 5551) at 0x8F**, MSCAL 6 (the VU1 program reads the
  layout the flags give). The palms' colour is a flat `0xAD6B` (88, 88, 88 of 128).
- **Texture dictionaries ('xet')**: of the 2,748 textures in the dictionaries (ids 7534 - 8364) 2,034 are 4-bit -
  raster word +4 `0x0045 << 16 | width / 2`, flags `log2 w | log2 h << 6 | 4 << 12 | 1 << 20` (one level), pixels
  linear with the even pixel in the low nibble, then a 16-entry CT32 CLUT (alpha 0x80 = opaque), 32 x 16 to 256 x 256 -
  and 714 8-bit (`0x0025 << 16 | width`, a 256-entry CLUT in CSM1 order), 8 x 8 to 256 x 256. Read from the disc with
  the streaming infos of a RAM dump. The streaming object's +4 held 0x5B2800 (5.97 MB) in that run - likely the
  streaming memory's size, not checked.
- **A VU1 batch is a draw**: every batch of <= 70 strip vertices becomes a native draw, so a model's cost goes with its
  strip vertices. In a Little Havana view full of palms the game's own drew 1,325 native draws (GS stage 6.0 ms); the
  pack's palms (1,470 - 3,886 triangles, 3,054 - 8,088 strip vertices each) 4,631 (10.3 ms).
- **Alpha-tested texels write depth**: world draws test alpha GREATER 8 (of 128) with no second pass, so a texel at,
  say, half alpha is blended over what is already drawn and also hides everything drawn after it behind it. Foliage
  textures with broad half-transparent areas (VC PC textures box-filtered to a quarter) showed the sky through as pale
  patches; with alpha 0 / 128 only the bilinear edge band between texels is left half transparent.
- **Where each model's trunk stands (its foot)** - the VCS models' vertices decoded from the disc (every V3-16 UNPACK
  to address 1, through the geometry header's scale +0x28 and offset +0x34: `veg_convert.vcs_verts`); the foot is the
  lowest vertex's z and the middle (x / y) of everything within 0.5 m of it - the trunk's bottom ring in every model,
  VCS's and both packs' (checked by material: the lowest triangles are bark in all of them). In model space, metres:

  | model | VCS box min - max | VCS foot | VC pack foot (unscaled) | BSOR foot (unscaled) |
  |---|---|---|---|---|
  | veg_palm01 | (-28.9 -21.1 -1.14) - (4.6 6.4 40.0) | (-0.71 0.50 -1.14) | (-0.10 0.05 -0.68) | (1.87 3.10 -2.11) |
  | veg_palm02 | (-7.1 -2.6 0.14) - (13.9 23.2 41.7) | (0.14 0.00 0.14) | (0.06 0.07 -0.71) | (0.08 0.35 0.10) |
  | veg_palm03 | (-11.7 -1.3 -0.92) - (15.9 37.2 37.0) | (0.14 -0.53 -0.92) | (-0.08 -0.07 -0.73) | (0.14 -0.02 -0.85) |
  | veg_palm04 | (-15.9 -13.6 -0.67) - (14.0 13.7 36.9) | (-0.86 0.01 -0.67) | (0.00 0.10 -0.37) | (-0.57 -0.02 -0.10) |
  | veg_palmbig14 | (-9.2 -8.0 -0.83) - (8.4 9.2 18.6) | (-0.04 0.06 -0.83) | (-0.03 0.10 -0.05) | (0.07 0.11 -0.17) |
  | veg_palwee01 | (-7.4 -0.8 -0.51) - (10.1 23.5 23.4) | (0.09 -0.30 -0.51) | (-0.05 -0.05 -0.73) | (0.11 -0.05 -0.81) |
  | veg_palwee02 | (-6.0 -5.6 -0.10) - (5.5 5.9 27.8) | (-0.05 0.11 -0.10) | (0.01 0.07 -0.71) | (-0.05 0.11 0.63) |
  | veg_tree3 | (-8.4 -8.4 0.00) - (8.7 10.0 25.9) | (-0.01 0.29 0.00) | (0.11 -0.33 0.00) | (0.00 0.33 0.00) |
  | veg_treea1 | (-8.8 -8.5 0.00) - (8.3 9.9 35.3) | (-0.40 0.26 0.00) | (-0.13 -0.03 0.03) | (-0.39 0.29 0.00) |
  | veg_treea3 | (-4.6 -4.1 -0.33) - (4.4 5.7 13.4) | (-0.16 0.54 -0.33) | (-0.13 -0.03 0.03) | (-0.16 0.61 -0.41) |
  | veg_treeb1 | (-5.4 -5.7 0.00) - (6.1 6.7 17.5) | (0.22 0.19 0.00) | (-0.13 -0.03 0.03) | (0.24 0.19 0.00) |

  So the origin is not the foot: VCS's palms sink theirs 0.1 - 1.1 m (veg_palm02 0.14 m above), the packs' differ
  again, and BSOR's veg_palm01 stands 3.6 m off its origin. Scaled about the origin alone (the converter until
  2026-10-31: `vhi.z / hi.z`), the VC pack's veg_palmbig14 stood 0.76 m above its lawn - the user's report: its trunk
  on the low wall beside it - veg_palm04 0.38 m, veg_treea3 0.34 m, while veg_palm02 sank 0.96 m and veg_palwee02
  0.59 m. The converter now scales by the full height (`(vhi.z - vlo.z) / (hi.z - lo.z)`) and moves the pack model's
  foot onto VCS's (x, y and z). Checked in a hidden run at instances read from RAM dumps (the model id is a u16 0x26
  bytes after the entity's position x): veg_palmbig14 (-1154.72, -362.71, 10.17), veg_palm01 (-1463.31, -297.60,
  13.78), veg_palm02 (-1298.97, -434.27, 9.65), veg_palm03 (-1013.92, -526.19, 10.03), veg_palm04 (-1828.53, -302.97,
  11.75), veg_palwee01 (-1111.86, -459.16, 10.04), veg_palwee02 (-1303.12, -437.27, 9.20), veg_tree3 (10.15, -229.03,
  13.54), veg_treea1 (222.11, 137.01, 8.29): every trunk now meets the ground where the game's own does
  (build/veg_test/feet: off / before / after / bsor).
- **BSOR Vegetation (SA PC)** has all eleven names (RW 3.6, one atomic each, 1.7k - 6.3k triangles); its textures are
  in one dictionary, `bsor5s_txdp.txd`, which `thetxdp.ide` makes the parent of SA's vegetation dictionaries
  (`gta_tree_palm`, `tree1`, ...). Each model carries SA's night vertex colours (0x253F2F9; all alpha 255), an empty
  2dfx (0x253F2FD, count 0) and day prelighting (alpha 255); the converter uses none of them (VCS's palms are a flat
  grey). Material colours are white. Its `sjmpalm*`, `vgs_palm*`, `veg_palwee03`, `veg_palmkb*` have no VCS model with
  data and are not used.
- **Wind on the native world draws (research for SkyGfx Extended's wind, 2026-10-31)**: `vs_world` (gs_draw.hlsl)
  gets the raw V3-16 position (ITOF0) and transforms it with `nat[0..3]` (window) and `nat[11..14]` (clip test), the
  model's geometry scale folded in; the colour is RGBA 5551 (no spare bits) and the uv's z lane is the batch's STROW
  row (0xFF), so there is no free per-vertex channel in the game's prelit format. `GSNativeDraw::constants` holds 31
  float4s and VcsWorld uses 0 - 14: 15 - 30 are free. The converter's quantizer centres each model's box, so
  `(pos.z + 32768) / 65536` is a vertex's height within its model (0 = bottom).
- **Built (2026-10-31)**: the converted BSOR palms share textures between models of different sizes, so a texture
  cannot carry one model's box. tools/veg_convert.py quantizes every converted tree the same way instead - 2 mm per
  unit on all three axes (geometry scale 64), the crown (top of the trunk) at position 0 - and the wind list
  (mods/wind.txt) has one set of numbers for every name; only the leaves' (cut-out) textures are in it (2026-11-01:
  8 of the 16 named textures), so the bark never moves. **CWeather::Wind is the float at `0x4CD2A4`** (read with the rig while forcing each weather
  type, FORCE_WEATHER_NOW): 0.25 sunny, 0.7 cloudy, 1.0 rain, 0 foggy and extra sunny (types 3, 4, 6, 7), 2.0
  hurricane (5); it changes at once with the weather. game/vcs_wind.cpp drives the field from it and from
  `m_snTimeInMilliseconds` (still while paused). Checked in a hidden run (Havana, the palmbig14 view): between two
  frames 0.4 s apart only the converted palms' crowns change (16k pixels at 1080p in the calm; 1.5k with the wind
  off - water, the clock); trunks stay joined to the crowns and the game's own bushes stay still. Leaves only
  (2026-11-01, rain, a close-up of the palms by the Havana houses): the frame diff marks fronds only, the trunks
  identical in both frames, the crown seated on the trunk's top.

### 12k. The world's collision - Jolt Physics, milestone 2 (2026-10-31)

Found in the generated code - CWorld::TriggerExplosion (FUN_00192760), CWorld::ClearScanCodes (FUN_001943b8),
CWorld::ProcessLineOfSight (FUN_001908c0) with its sector (FUN_001918e8) and list (FUN_00191c00) passes,
CCollision::ProcessLineOfSight (FUN_002b7e88) and its triangle range (FUN_002b6ae0) - and read back with the rig: the
col triangle under Vic standing in the street at (-700, -500) lies 1.03 m under his position, as a ped's soles do (12h).
- **CWorld's sectors**: `*0x486464` -> 50 x 50 sectors of 80 m - x index = x / 80 + 30, y index = y / 80 + 25 (so x
  -2400..1600, y -2000..2000), clamped to 0..49 -, 0x38 bytes each (FUN_00472698(x, y) = base + (y x 50 + x) x 0x38):
  14 CPtrLists (the first node; a node is {item, prev, next}). **Buildings +0x00 / +0x04 and +0x14 / +0x18** (the
  building pass of ProcessLineOfSight takes all four), **objects +0x0C / +0x10**, vehicles +0x1C / +0x20, peds +0x24 /
  +0x28, dummies +0x30 / +0x34; +0x08 a list ProcessLineOfSight reads under a flag of its own; +0x2C holds one
  world-sized entity (model 318: one box, radius 2000) in every sector, in no collision pass. ClearScanCodes zeroes the
  u16 scan code at entity +0x54 (CWorld::ms_nCurrentScanCode, u16 at `0x486468`) in the first list of each kind.
  CPhysical::ProcessCollisionSectorList (FUN_0034FD60) walks the lists +0x00 .. +0x28 of each sector the entity is in
  (its entry info list at +0xE4: {list, node, sector +8, prev, next +0x10}).
- **CEntity**: +0x00 its matrix (rows right, forward, up, position; 16 bytes each), **+0x48 the flags** (64-bit: bits
  1-3 the type - 1 building, 2 vehicle, 3 ped, 4 object, 6 in the dummy lists -, **bit 9 uses collision**), +0x54 the
  scan code, +0x56 the model.
- **CColModel** past its bounds (12h): **+0x30 u16 boxes, +0x32 u16 triangles, +0x34 u8 spheres**, +0x35 u8 (lines? 0
  in all seen), +0x36 u8 triangle sections, +0x37 u8 (25 on the level's buildings, 0 on the others: their col store
  slot?), **+0x38 spheres** (0x20 bytes: centre, radius; the surface at +0x10), +0x3C lines, **+0x40 boxes** (0x30: min,
  max; the surface at +0x20), +0x44 sections (0x30: a box, u16 first and last triangle at +0x20 / +0x22 - with two or
  more ProcessLineOfSight tests each box before its range), **+0x48 vertices** (int16 xyz x 1/128 - VC's compressed
  vectors, the VU0 collision programs' 7-bit fixed point, 6c), **+0x4C triangles** (8 bytes: three u16 **byte offsets**
  into the vertices - 6 bytes a vertex -, the surface, a byte), +0x50 the triangle planes (made on demand and cached by
  CalculateTrianglePlanes FUN_00128db0, 10 bytes each). There is no vertex count: the highest offset gives it. **The
  front face is clockwise**: (b - a) x (c - a) points down on 305 of 333 and 654 of 659 flat triangles around two
  spots (VC's CColTrianglePlane::Set takes (c - a) x (b - a)).
- What is there: the level's buildings near Vic have their triangles (his sector: 8 buildings with collision, 906
  triangles, 33 boxes, no spheres); far buildings and LOD models keep their bounds with no primitives; small street
  furniture can be one box (model 485: 0.6 x 0.4 x 1.8 m). Objects' bounds can be huge while their primitives are not:
  a palm (model 545) has a 30 x 27 x 37 m box around its crown and one 1.4 x 1.5 x 28 m box, its trunk.
- **The ragdolls' world** (Game > Physics > Ragdolls; DECISIONS.md): each game step the buildings (static) and objects
  (kinematic, moved with the game's matrix) whose col model's bounding sphere comes within 10 m of a ragdoll's hips are
  bodies in Jolt; each col model is made into one shape (a MeshShape of its triangles, wound counter-clockwise for Jolt,
  with its boxes and spheres) kept while its counts, arrays and first vertices stay the same, dropped after 10 s
  unused. A ragdoll gets a ground of its own only when the world has no surface within 50 m under the ped (collision
  not streamed in); the ped's height follows its body (1 m over the lowest bone) once they differ by 0.5 m; a body
  60 m under where it started (nothing left under it) is frozen. Corpse shots stop at the static world in front of a
  body. `VCS_JOLT_WORLD=0`: milestone 1's grounds only.
- Checked (`tools/ragdoll_world_check.py`, Vic on the street at (-650, -440) east of a flat roof 5.2 m up whose edge
  runs at x -666.9): a ped on the roof 0.8 m from its edge, a grenade's ADD_EXPLOSION 5 m behind it - the ragdoll made
  on the world's collision (9 buildings and 9 shapes in the physics), over the edge, its pelvis at 10.15 on the street
  (9.78), the ped's height 11.10; a ped 1 m in front of the wall, the blast 3.5 m in front of it - thrown 0.75 m back
  against the wall, it stays in front of it; the step at most 0.26 ms. With a stronger throw (the blast 3.5 m behind)
  the body came to rest 3 m over the street 6.7 m out, where no building or object has collision - most likely on a
  vehicle's roof in the traffic (vehicles are boxes in the physics: 12h; not checked then). The milestone 1 check
  (`tools/ragdoll_check.py`) passes with the world in (its bodies land on the road's own triangles: ground 10.02).

### 12l. Bike falls - knockdown ragdolls (2026-10-31)

Found in the generated code (SetPedState's callers by the state they set, CPed::SetFall's callers) and checked with the
rig (`tools/ragdoll_bike_check.py`).
- **Ped states** (VCS's numbers: near VC's, but not one shift - FALL / GETUP are VC's + 3, DRIVING + 5): **0x2D
  PED_FALL, 0x2E PED_GETUP**, 0x37 PED_DRIVING (a rider on its bike too), 0x39 / 0x3A DIE / DEAD.
- **CPed::SetFall = FUN_002022f0**(ped, extra ms a1 or -1, animation a2, even out of control a3; 19 callers - blasts,
  bullet impacts, the shotgun's pellets...): state 0x2D, the fall animation, **+0x6C4 m_getUpTimer** = CTimer ms
  (`0x4CD104`) + the animation's length + the extra (+ up to a random second for peds; -1: never), a flag in +0x1D0.
  **CPed::Fall = FUN_00202808** (the state's handler) calls SetGetUp once that time is not -1 and has passed and the
  ped stands (+0x1C8 bit 0) or +0xE8 bit 40 is set. **CPed::SetGetUp = FUN_00203240** (state 0x2E; InflictDamage
  weapon RUNOVERBYCAR on a ped with a car on top of it, SetDie on one with no health) - not "a fall's landing" (12h).
- **CBike::KnockOffRider = FUN_003f0a58**(bike a0, weapon a1, direction a2, rider a3, get back on t0): the rider leaves
  the bike (its vehicle pointer +0x480 is 0 after) with the bike's speed and a throw (ApplyMoveForce, FUN_00347d20), then
  SetFall(rider, 1000, animation) - or SetDie when it has no health left - and its standing flag (+0x1C8 bit 0)
  cleared. A bike's driver is at +0x384 (state 0x37 while on it); FUN_003f3968 gives a passenger. 14 callers, among them:
  **the bike's collision damage** (`fn_00336448`, VC's CBike::VehicleDamage): damage = impulse x 800 / mass (x 0.65 for
  a bike not the player's), times a direction factor - |normal . forward| x 0.6 (up to 7.6 head on) + |normal . right|
  x 0.45 + up / down terms -; over 75 the driver and passenger get InflictDamage (weapon 42) and are thrown off with
  weapon 42; a tyre bursting at speed (FUN_00344d28, 42); **a ped's own hit by a vehicle** (FUN_001db5f8 / FUN_001dc3e8:
  weapon 47, direction 2); **CPed::InflictDamage** for a rider of a bike or boat brought to 1 health or less (health 0,
  the weapon's own number: the rider dies off the bike); jetskis turned over (FUN_001a4b20 / FUN_001a4c50, 42).
- Checked: Vic on a PCJ-600 (212) at full throttle into a wall - thrown off (weapon 42) at (-12.6, 1.4, 6.4) m/s (another
  run 16.7 m/s, high enough to land him on the terrace over the wall); a ped on a parked PCJ-600 hit head on by a
  Sentinel at 13 m/s - weapon 47, thrown at (-15.1, 2.1, 3.7) m/s; the same hit side on did not throw it (the factor
  0.45); a rider shot with a Shotgun from 4 m - thrown off and killed (SetDie from inside KnockOffRider).
- **The knockdown ragdolls** (Game > Physics > Bike falls with Ragdolls on; DECISIONS.md): KnockOffRider is hooked
  (before) for the rider; at its next draw in state 0x2D it gets a ragdoll from its pose with its speed then (the
  bike's and the throw), its bike left out of the physics while it is down (it starts astride it). While the body
  moves, m_getUpTimer is held at -1 and the ped's move speed at 0 (ApplyMoveSpeed is not run for it: gravity would pile
  up); once its bodies have slept - or its hips stayed within 3 cm (a body pressed into a wall jitters awake) - for
  0.4 s, and it has been down 2.5 s (8 s at the latest), the ped is put on the body - x / y on the root bone, z 1 m
  over the lowest bone, its heading along the body (feet first on its back, head first on its front) -, its
  m_getUpTimer set to now: CPed::Fall gets it up (0x2E, then 1). The body's last pose is drawn until the get-up starts,
  then eased into it over 0.35 s (rotations along the shortest arc). A rider that dies while down becomes a dead
  ragdoll; one killed in the throw goes through SetDie (noted although its vehicle pointer is still set then).
- Checked (`tools/ragdoll_bike_check.py`): Vic's crash - knockdown ragdoll, the body against the wall and down onto the
  street, still and up after 3.9 s (0x2E, then 1), health 98; the ped hit by the Sentinel - onto the median wall's top,
  up after 3.4 s on it; the rider shot dead - a dead ragdoll; the death (`tools/ragdoll_check.py`) and world
  (`tools/ragdoll_world_check.py`) checks pass with the parts' swept collision (Jolt's LinearCast, against tunnelling
  through single-triangle walls at bike speeds).

### 12m. Pickups - guns and cash on the ground (2026-10-31)

Found in the generated code (CPed::SetDead's callees) and with the rig (the pickup array dumped after a kill, write
watches on pickup objects' matrices).
- **CPickups' array at `0x4EA740`**: 336 pickups of 0x40 bytes (0x140 regular, the last 16 for money): **+0x00 the
  position** (collection is measured from it; a respawning pickup is made there again), **+0x20 its object** (a
  CObject, type 4, drawn with the pickup's model), +0x2C the quantity (ammo, dollars), +0x30 a time, **+0x34 u16 the
  model**, +0x36 u16 an index, **+0x38 u8 the type** - VC's: 0 none, 3 ONCE, 4 ONCE_TIMEOUT (a dead ped's gun), **8
  MONEY**, 11 and others for the map's -, +0x3C 0xFF.
- **CPickups::GenerateNewOne = FUN_001ddb38**(position* a0, model a1, type a2, quantity a3, ..., t1): the first free
  slot (type 9 and a flag take the 16 from the end); FUN_001dde40 the weapon-type version, 9 callers in all.
- **CPickups::CreateSomeMoney = FUN_001e17f0**(position* a0, amount a1): up to 4 piles (a pile per $30, at least 1)
  within 1.5 m, each GenerateNewOne(model 437, type 8, its share). **CPed::CreateDeadPedMoney = FUN_001e1700** (from
  CPed::SetDead FUN_0020a818): nothing with CGame::nastyGame (`0x489F80`) off, for models 8 - 13, 0x61, 0x62, 0x77
  (cops and the like), **for a mission ped (+0x8F4 = 2) unless +0x1D0 bit 22 (money given by the script)**, for a ped
  in a vehicle, or with **its cash (u16 +0x77E)** under $10; else CreateSomeMoney and the cash zeroed. FUN_001e1968 is
  the weapon drop beside it.
- **The pickups' look is drawn, not updated**: the render's FUN_003c35a8 calls **CPickups::DoPickUpEffects =
  FUN_001df618**(object) - the spin about z with a scale (a gun x 1.84), glow, coronas - and **CPickups::
  DoMoneyEffects = FUN_001e0e08**(object) for cash (its spin). Nothing else writes a pickup object's matrix after
  GenerateNewOne placed it (through FUN_00472688, return address 0x1DE2B8).
- **Models**: weapons 331 - 368 (12g); cash 437 (box 0.20 x 0.08 x 0.08 m, a col model of one sphere); the guns' col
  models are a generic half-metre cube without primitives, their sizes come from the geometry: the 'ldm' chunk at model
  info +0xC, its RslElement at +0x20, the element's geometry at +0x14, its PS2 part (+0x20) with **int16 bounds at
  +0x1C / +0x22, scaled by the floats at +0x28 around +0x34** - the Colt45 0.25 x 0.05 x 0.20 m, the Shotgun 1.06 x
  0.16 x 0.35, the M4 1.08 x 0.15 x 0.34: **barrels along x, thin along y**.
- **Pickups on the ground** (Game > Physics > Pickups on the ground; DECISIONS.md): both effects functions are hooked
  (before): a gun's or cash's object gets a prop the first time it is drawn - a Jolt box from those bounds, dropped
  from where the game put it with a tumble about its length (a dead ped's thrown out 0.5 - 1.5 m/s and up 1 - 2 m/s) -
  and from then on is drawn where its prop lies at unit scale, the game's spin, glow and coronas left out; the
  pickup's position follows it, 0.6 m over it (about the game's own height). A prop still for 0.5 s (or not drawn for
  3 s) leaves the physics and stays put; one whose pickup is gone (picked up, timed out) goes.
- Checked (`tools/pickups_check.py`): a ped with a Colt45 and $100 killed at (-700, -500) - the gun and four piles
  became props, came to rest on the road on a side at unit scale and stayed still, their pickup positions over them;
  walking onto the cash collected it ($50 -> $155); the map's Ruger pickup (334) at (-893.6, -717.9) dropped from 11.10
  to 10.19, on the ground.

### 12n. Hit reactions - GTA IV / Euphoria style active ragdolls (2026-10-31)

After SA's Jolt Physics mod's `[ActiveRagdoll]` (its ASI knocks peds down from the game's KO_SHOT_FRONT_0..3 /
KO_SHOT_BACK_0 / KO_SHOT_STOM animations, with "balance", "catchFall" and arm-grab behaviours; its ini: Knockdowns,
CatchFall, MuscleStrength, StanceAssist, DownRelaxation). Nothing new in the game was needed: CPed::InflictDamage
(12h) gives the ped, attacker, weapon and piece hit, the draw hooks the animated bones, and a hit that knocks a ped down
leaves it in PED_FALL (0x2D, 12l).
- **A hit reaction** (Game > Physics > Hit reactions, with Ragdolls on; DECISIONS.md): at the next draw of a ped hit and
  not killed (not in a vehicle), an active ragdoll from its animated pose - its hips kinematic, moved each step to the
  animation's hips, so the game keeps walking, running, aiming it; every joint's motor (Jolt swing-twist / hinge
  motors, position mode, 8 Hz) pulls toward the animation's pose. The blow's push (the killing push of 12h, 0.8 of it,
  from the attacker's side on the part hit - head, chest, hips, an arm, a leg) lands on that part; the muscles start
  at 0.6 and rise to 1.0. Drawn: the physics' pose for 0.2 s, then eased back into the animation by 0.9 s. Another hit
  meanwhile pushes it again; a death ends it (the death ragdoll follows from the next draw); a hit that knocks the ped
  down makes a knockdown ragdoll instead (12l's: held down, then up with the game's get-up), pushed the same way.
  Vic reacts to hits too. Drawn never more than 0.2 m off the animation, and faded out within 0.15 s once the
  animation's hips run faster than 3 m/s (a ped sprinting off once hit: its limbs' muscles cannot keep up, and the body
  trailed behind its hips - the user's report).
- **Clutching the wound** (SA's mod's "LeftArmGrab / RightArmGrab"): with the reaction, unless the ped is Vic or the hit
  is the head, a hand reaches for the wound - a point on the bone hit (VC's piece: 0 spine1 (bone 3), 1 the spine (2),
  2 / 3 the upper arms (8 / 13), 4 / 5 the thighs (17 / 21)) on the shooter's side, kept in that bone's frame so it
  follows the body: the other arm for an arm, the same side's for a leg, the nearer shoulder's for the trunk. Two-bone
  IK on the drawn pose (upper arm, forearm, hand and fingers turned about the shoulder and elbow, the elbow kept on the
  side it bends to), eased in over 0.25 s, held, eased out by 1.6 s; the reaction lasts as long. Kept when the ped runs
  off holding it (civilians sprint within ~0.2 s of a hit: none would show otherwise); none started while running.
- **Stumbling** (Euphoria's stagger): a push of 85 kg m/s or more (a shotgun's, close rifles') or a third hit within
  1.5 s moves the ped 0.45 - 1.2 m along the push (push / 110 m), eased out over 0.5 - 0.9 s, its position shifted
  each step - its state, AI and animation left alone, the reaction's hips following - and stopped short of the world
  (a ray 0.35 m ahead against the world's bodies and vehicles; a reacting ped's own kinematic hips left out of such
  rays by their user data); 1 - 3 steps drawn in turn - the stepping leg swung 0.45 rad along the push about the hip,
  its knee bent 0.7 rad, a sine over the step - with the reaction's lean of the trunk. Not for Vic.
- Checked (`tools/hit_reactions_check.py`, 3 runs): Colt45 hits on a ped with 200 health - a reaction each, its bones
  drawn up to 0.33 m off the animation, the pelvis with the ped, over within 1.8 s, the ped alive; a ped knocked down
  by a second hit is a knockdown ragdoll and gets up; a Shotgun from 2.5 m knocks down or kills as a ragdoll. With the extras (3 runs more): the hand held on the wound
  (IK exactly on it: 0.00 m), three quick pistol hits on a fresh ped stumble it 0.51 m, still on its feet. Without
  the drawn-weight the hands lag up to ~1 m behind a ped that turns to flee late in the reaction (drawn at < 0.5 weight).

### 12o. Game functions several mods hook - their order, for mods as DLLs (2026-10-31)

Found while moving the camera mods into CameraAim.asi (docs/MODDING.md), from every `replaceFunction` in `src/`: four
game functions are hooked by more than one mod, and which hook wraps which is part of what they do. A DLL mod's hooks go
in at two points of `applyVcs` for this reason (VcsModInstall, VcsModInstallLate).
| Function | Hooked by, outermost first | Why the order |
|---|---|---|
| FUN_002A2ED0 CCam::ProcessSpecialHeightRoutines | first person (mod), the free camera (exe) | the free camera, installed first, is the original first person calls while it flies |
| FUN_0024E8D0 an anim tree's bones (ra 0x3C3280) | ragdolls, first person (mod) | both only note the tree; kept in the order of the next row (first person in before the ragdolls: both VcsModInstall, CameraAim.asi before JoltPhysics.asi by name) |
| FUN_0020C310 between the bones and the ped's draw (ra 0x200740) | ragdolls, first person (mod) | the same: first person's head collapse runs on the bones the ragdoll left |
| FUN_002D0870 CWeapon::ProcessLineOfSight | free aim (mod), ragdolls | free aim puts the shot on the camera's line first, so the ragdolls' bullet test sees that line (VcsModInstallLate) |
Checked with the mod: hidden runs on a copy of the card (port 47690) - first person on foot and in car 211 (glass
hidden, `carglass` hidden = the car), free aim's shoulder camera with the crosshair drawn by the DLL into the exe's
Dear ImGui context, a pistol aimed by the mouse taking a ped from 100 to 35 health; without the DLL the rows, the hotkey
row and the `firstperson` command are gone and the game plays as v0.0.1.

### 12s. Catching falls and firing back from the ground (2026-10-31)

After SA's Jolt Physics mod's CatchFall / KnockdownGunFire. **CWeapon::Fire = FUN_002c0f98**(weapon a0 - the ped's
current one: ped +0x574 + the byte at +0x789 x 0x1C -, shooter a1, source* a2): with no source (0) the muzzle is the
shooter's position + its matrix x (0, 0, 0.6), and the shot goes along the ped's heading (its callers: the peds' fire
functions FUN_001d26c8, FUN_00216768, FUN_002168e8, FUN_00233c80 / FUN_00233ff0, each passing a hand position from
FUN_00175338 on the stack).
- **Catching the fall** (Game > Physics > Catch falls): a knockdown ragdoll's (12l) arms - the shoulders' swing-twist
  motors turning each upper arm along a direction, the elbows' hinges straight - reach toward the ground the body falls
  to (its hips' way down, forward or back as it goes, and down), until its hips are 0.35 m over the ground under them
  or 1.5 s, then go limp.
- **Firing back** (Game > Physics > Fire back from the ground): a ped knocked down by a ped's hit, a gun (types 19 - 37)
  with rounds in hand, not the player: 0.5 s after landing, a shot every 0.35 s, 4 at most, while its shooter lives.
  The shot is the game's own: in the ApplyMoveSpeed hook (the game calls it for the ped each frame; a ragdolled ped's
  is skipped anyway) a tail call to CWeapon::Fire(its weapon, it, 0) back to ApplyMoveSpeed's caller, the ped turned
  to its shooter and moved for that frame so that the muzzle (0.6 m up) is its right hand (the next step puts it back
  on its body). Ammo, tracer, sound, damage and the shooter's reaction are the game's.
- Checked (`tools/blindfire_check.py`, 3 runs): a ped with a Colt45 and 500 health shotgunned from 2.5 m - knocked down
  at the first try, its arms braced, 4 blind shots (clip 17 -> 13), Vic hit (health 100 -> 67 / 83 / 92), up again.

### 12p. Dismemberment - stumps and blood (2026-10-31)

After SA's Jolt Physics mod's [Dismemberment] (its JoltPhysics.dat: SeverChance - a lethal hit on a limb takes it
off -, SeverPower, HeadBurst - a head hit destroys the head; ExplosionChance 0.6 a limb, 2 a body at most).
- **CParticle::AddParticle = FUN_001e9040**(type a0, position* a1, direction* a2, entity a3, size f12, t0 - t3): the
  shotgun's pellet loop (FUN_002c7c28) sprays 8 of **type 7, blood** on a body down (0.3 m/s-ish directions: units per
  1/50 s). **CGame::nastyGame (`0x489F80`)** off: no gore.
- **A part taken off** (Game > Physics > Dismemberment, with Ragdolls on; DECISIONS.md): a lethal hit on a limb (VC's
  pieces 2 - 5: the arm / leg whole or its lower half at random) or the head (piece 6) by the weapon's chance (SA's
  columns mapped onto VCS's types: blades 0.35 - 1, shotguns 0.65 - 0.75 and heads 1, Python 0.35, rifles 0.2 - 0.6,
  pistols and SMGs 0.01 - 0.02), a shot on a body already down by the same chance on the part it met (Jolt's ray), a
  blast 0.6 x nearness a limb (half that the head), 2 at most. The part's bones (and those below them) are drawn
  collapsed onto the joint they hang from - rows 0, position the joint -, so the skin weighted to them shrinks into a
  stump at the joint; its ragdoll bodies become sensors (they meet nothing; Jolt keeps them on their joints). Blood: a
  burst of 14 drops (30 for a head) one a frame, then one every 45 ms for 3 s, each the game's AddParticle(blood) from
  the stump outward - a tail call from ApplyMoveSpeed as 12o's shots, the dead ped's position (+0x30) and move speed
  (+0x140) lent as the vectors for that frame (the game calls ApplyMoveSpeed for dead peds too: the drops counted).
- **Not done: the loose limb.** The ped is one skinned mesh drawn once by the game; a second copy of the part (SA's
  DetachedMesh: its own models) would need a draw of our own or new models, so a severed part is gone, not flying.
- Checked (`tools/gore_check.py`): a grenade-sized ADD_EXPLOSION 1.5 m from a ped and another 1 m from its body - 4
  parts off (both upper arms, a thigh, a calf), all 12 of their bones drawn collapsed, 98 blood drops in 2.5 s and
  still coming; with the setting off, none. Head shots by a sniper rifle were not tried (no aimed shot in the rig
  without the camera mod); hit reactions and bike falls still pass.
- **A head kept whole** (2026-11-01, JoltPhysics.asi, Game > Physics > Keep severed heads, on): the head's Jolt body
  lets go of the neck (its swing-twist constraint disabled) and is thrown up and aside. Drawing it was the work:
  - **One skinned mesh can't be cut by bone matrices**: a ped's skin weights the neck's vertices across the neck (bone 4)
    and the head (5), and the chest's across 3 / 4, so with the head 2 m away whichever bones go with it, a band of skin
    stretches from the body to it (seen: a 2 m strip). It takes a second draw of the ped: the body with the head bones
    collapsed into the stump (the stump as before, at the neck bone's end), then the head alone - every other bone's
    matrix collapsed onto the head's joint, so the mixed vertices close up its bottom.
  - **CPed::Render (FUN_00200660) only builds the bones** (FUN_003c3250, then FUN_0020c310 at 0x200740); calling it twice
    drew the ped once, with the second call's bones. The renderer calls the skinned element's render callback
    **FUN_0036eb70** (a0 the element; it returns the element) later, and what that queues is drawn at the frame's end
    through **element -> anim tree (a word of the element's first 0x40 bytes) -> its matrices (tree +0x28)** - the
    matrices' address is nowhere else in RAM (a scan of the heap and packet buffers), so a second draw needs a second
    element, tree and matrices. The tree is 0x400 bytes before its matrices in every tree seen.
  - The hook on FUN_0036eb70: for a ped with a loose part, a copy of the element pointing at a copy of the tree pointing
    at matrices of its own (the part alone), passed to the callback after the element itself through a continuation
    (0x36EB74, no entry there). The copies live in 8 slots (0xA80 bytes each) taken once from the main heap through
    **FUN_002BD178(size)** (malloc; called through a continuation at 0x36EB78) - 21 KB, never freed; more loose parts in
    one frame than slots are drawn as stumps.
  - Checked with `VCS_JOLT_HEADSHOTS=1` (every killing hit takes the head) and a Shotgun at 3 m, first person to see past
    Vic: the head flew 0.6 m up and came to rest ~2 m from the body, face and hair drawn, the body with its closed stump,
    nothing between them; gore_check and ragdoll_check pass.
- **First person on a ragdoll** (CameraAim.asi with JoltPhysics.asi, 2026-11-01): JoltPhysics.asi exports
  `JoltPhysicsPlayerRagdoll` (1 while Vic's body is a ragdoll, not a hit reaction); CameraAim keeps first person on
  through it (whatever the game's camera mode, e.g. Wasted's) with the eyes on the drawn head's axes and the view along
  the face, its up the head's (rolling), eased in over 0.2 s and out over 0.5 s to a level mouse view the way the face
  last looked; the mouse doesn't turn the view or the body meanwhile. Checked: Vic killed in first person - the eyes went
  from 0.74 m over his position to 0.77 m under it as the body fell, the view tumbling down along his legs and hands.

### 12q. Foot IK - feet on the ground on slopes and stairs (2026-10-31)

After SA's Jolt Physics mod's [FootIK] (Enabled, AdaptNpcs, NpcRange 25, MaxOffset 0.45, Smoothing 0.4, SlopeAlign,
AlignStrength 0.7). Nothing new in the game was needed: the ground is the col triangles of 12k, the bones those of 12h
(thigh 17 / 21, calf 18 / 22, foot 19 / 23, toe 20 / 24; a limb's X along it), a standing ped's soles 1 m under its
position (12h), its standing flag +0x1C8 bit 0 (12l).
- **The ground under a foot** (`VCS-mods plugins/JoltPhysics/src/footik.cpp`): in the sector under the ankle, the buildings' and objects'
  col models (lists +0x00 / +0x04 / +0x14 / +0x18 / +0x0C / +0x10, uses-collision entities) - their triangles, and
  their boxes' tops, in the world through the entity's matrix, faces with a normal over 0.35 up only, cached per entity
  (made again when its col model's counts / arrays or its position change; dropped after 10 s unused) - the highest
  face over (x, y) within 0.45 m of the animation's ground.
- **The legs**: each foot's need is its ground less the animation's (the ped's position less 1 m), at most 0.45 m
  either way; the whole pose goes down by the lower foot's need (none up), each leg's two-bone IK (law of cosines,
  the knee kept in the plane it bends in, the thigh's and then the calf's shortest turn) takes its ankle to the
  animation's ankle plus the rest - a step's lift over the ground is kept -, the foot and toe tilt 0.7 of the way to
  the face's normal; all eased (0.4 a frame at 30 fps, SA's Smoothing) and back to the animation when the ped stops
  standing on foot (states 0x2C - 0x2E, 0x37, 0x38, 0x39, 0x3A excluded, which leaves the ragdolls' poses alone).
  Written into the drawn bones in the ped render's FUN_0020c310 (return address 0x200740), before the ragdolls' and
  first person's hooks on it (installed after them, so it wraps them): a hit reaction takes the adjusted pose as its
  target; a ragdoll's pose replaces it.
- Checked (`tools/footik_check.py`, 3 runs): Vic on the stairs at (-891.8, -709.8), a 17 cm step between his feet -
  each sole as drawn within 1 mm of its ground (the animation's 2 / 17 cm off), the hips 0.17 m down; a ped near
  adjusted too; 0.011 ms a frame for both; switched off, no pose adjusted.

### 12r. Jiggle physics (2026-10-31)

After SA's Jolt Physics mod's [JigglePhysics] (its breast / glute springs need SA models with extra bones).
- **VCS's peds have no bones for it**: every ped's anim tree is the same 25 nodes (12h); the skinned draw is VU1
  microcode on prebuilt packets (6d), so moving single vertices would mean rewriting a ped's packet every frame - not
  done. What does work: **the skinned draw takes each bone's world matrix on its own** (a child's matrix is not
  derived from its parent's at draw time), so moving one bone's drawn matrix moves only the vertices weighted to it.
  Spine1 (bone 3) carries the chest, the pelvis (bone 1) the hips and buttocks.
- **The ped type is ped +0x550 (u32)**: 0 the player, 4 civilian male, 5 civilian female (VC's PEDTYPE_CIVFEMALE), 6 a
  cop (found by diffing two peds made by CREATE_CHAR with types 4 and 5; street peds read 4 and 6, a cop's model 8).
  "Female" is type 5.
- **The springs** (Game > Physics > Jiggle physics, off by default, `VCS_JIGGLE`; Jiggle intensity, 100 % = the SA
  ini's 1.8): per ped, one on spine1 (5.2 Hz, damping 0.28, at most 6 cm / 22 degrees) and one on the pelvis (3.8 Hz,
  0.30, 5.5 cm / 16 degrees), driven by the bone's world acceleration (from its drawn positions, 1/240 s steps,
  more than 80 m/s^2 = a teleport: reset), a little gravity (x 0.35), into the body at most 35 % of the max; the offset
  moves the bone's drawn matrix and tilts it about the bone. The nearest 8 eligible peds within 30 m (chosen from the
  previous frame's draws). In the ped's render, chained on FUN_0020c310 at 0x200740 with its own tree note on
  FUN_0024e8d0 at 0x3C3280, installed before jolt::install so Jolt's hook (a ragdoll's or hit reaction's pose) runs
  first and the springs ride on the drawn pose (the SA ini's RagdollJiggle). `VCS_JIGGLE_ALL=1`: every ped, Vic too.
- Checked (`tools/jiggle_check.py`, three hidden games): a female ped is jiggled, a male one and Vic not; Vic (all
  peds) running 1.5 s and stopping - chest 5.7 cm, hips 5.5 cm at most (the limits), settled to 0.3 / 0.6 cm (the
  sag) 2 s later; off - nothing stepped. No tearing seen at the joints with the neck, arms and thighs (their own
  matrices, skin blended across them).

### 12t. The first-person viewmodel - arms and gun in view (2026-10-31)

Found for CameraAim.asi's `viewmodel.cpp` (the user's request: UltimateFP SA's first person, where the player's own
arms hold the gun in view) with the rig on a copy of the user's card (the `viewmodel` command: the hand's axes and
place in the view's frame) and screenshots.
- **What first person showed before**: the game's arms. With the aim flag (free aim's R1) only the arm-IK pistols
  (19, 24, 26: weapon info bit 0x80) come up: the Colt45's hand at (0.25 right, 0.14 ahead, -0.24 up) of the eyes, the
  barrel along the view. The others keep their hip hold under the aim flag: the Uzi's hand 0.72 m under the eyes, its
  barrel straight down; the M4 / shotgun across the hips, barrel (-0.89, 0.44, 0.12) in the view; the left hand 0.47 m
  out along the barrel, palm open beside it. So no gun showed in first person without firing.
- **The hand's frame**: bone 15's rows in the view with the Colt45 pointed by the game: x (0.01, 0.99, -0.14) = **the
  barrel**, z = the gun's up, y = z x x (the palm side, left). The weapon is drawn from the tree's bone 15 matrix after
  FUN_0020c310 (0x200740): matrices changed there move the gun with the hand (checked on every class).
- **The pose** (in the hook at 0x200740, before the head is collapsed): the right hand set to a place in the view per
  class (pistols (0.15, 0.38, -0.16), SMGs (0.14, 0.36, -0.16), long guns (0.14, 0.24, -0.19) m) with its barrel on the
  crosshair 30 m out and its z up; the left hand of two-handed guns at a fore-grip point per weapon in the gun's frame
  (shotgun 0.30 m along the barrel, M4 / Ruger 0.25, MP5 0.19, ... 4.5 - 5 cm under it) with the gun's axes turned half a
  turn about the barrel (the fingers wrap the fore-end from under); both shoulders (bones 8 / 13) carried with their arm
  to (+-0.19, 0.08, -0.30) of the eyes - outside the picture - and each arm solved by two-bone IK (bones 8-10 / 13-15, the
  elbow bent down and out, the clavicles 7 / 12 and fingers 11 / 16 carried). The game's shoulders are level with the
  camera: moving the arm as one piece put the shoulder and upper arm in front of the lens (the user's complaint).
  Upper arm + forearm reach ~0.5 m, so a rifle's grip out of reach draws the gun back along its barrel (at most 12 cm).
- **Recoil** from the weapon slot's **+8, the rounds in the clip** (VC's CWeapon; ped +0x578 + slot x 0x1C): a drop is a
  shot - the gun kicked 4 cm back, 1.2 cm up, 0.1 rad muzzle up, decaying in 0.07 s. Sway: the view's turn rate (0.08 s
  smoothing) turns the gun about the eyes against it (at most 0.1 rad); bob from the ped's speed (+0x140 x 50 m/s).
- The aim flag is kept on in first person with a gun (SetAimFlag's writes, the view's yaw / pitch) so the game's own
  aim (and its shot source) follows the view; free aim's line hook still carries the shots (12d).
- **Getting in and out of vehicles**: the ped's vehicle (+0x480) is set from the first frame of the enter anim (state
  0x3D) to the end of the exit (0x3F), while the camera is still the follow camera (mode 4) - first person tested "on
  foot" as +0x480 == 0 and handed those frames to the game's third-person camera (the user's "I see third person when I
  enter a car or bike"). First person now runs in mode 4 / 11 whatever +0x480 holds (free aim's camera keeps the on-foot
  test); while the vehicle is set the eyes come from the head joint kept in the vehicle's space (a bike's lean matrix)
  plus the head's own axes (x 0.09 up the head, y 0.075 forward) - he ducks onto the seat. Checked: Sentinel and PCJ-600
  enter (car: mode 4 for 2.5 s, then 18) and exit in first person. One frame of a bike dismount still showed the back of
  his head (the head not collapsed in that draw: the hook at 0x200740 apparently not reached for it); a jump of the eyes
  over 0.35 m in one update is held for up to three updates.
- **Getting in and out, frame by frame** (the user's video: "my neck detaches", a torso blink stopping a backward run):
  per-frame captures of a Sentinel's and a PCJ-600's enter and exit found four causes. (1) The skeleton check at
  0x200740 (head within 2 m of the ped's position) failed while the ped's position lagged the anim by metres: those
  draws kept the head and the eyes went stale - now a head within 3 m of the vehicle counts while he has one. (2) The
  camera is worked out before the draw, from the last draw's head: while he ducks in the head moves fast, so the drawn
  body is moved by the difference to put the head joint at the camera (at most 0.8 m; the neck collapsed too). (3) His
  head goes into the door pillar leaning out and through the roof standing up to get out (anims do not collide): a car
  driver's head in the vehicle's space is kept softly inside - past 0.42 m from the middle and past 0.05 m over his
  seated head height (within the cabin and its door opening) it moves at 35%; the body follows. (4) The frame the
  vehicle is let go his position is set anew: a jump of the ped over 0.35 m holds the eyes for that frame. The jump
  guard from before held the eyes when the body turned in one frame at the end of a backward run (our turn to the
  view): that was the torso blink; it holds only in those two cases now. TheCamera's matrix matched the CCam's
  source on every captured frame (no mode-switch blend; first person's view is copied into the other two CCams anyway).
  Left: two frames at the start of getting in look over the roof edge as he ducks.
- **Running backwards** the game turns the body to the run (S with the view ahead: the body faces the camera's back), so
  the eyes at the head joint looked into his collar. The eyes now move out along the view's horizontal direction by 0.15 m x
  (1 - view . body forward): 0 looking ahead, 0.3 m looking back.
- Checked in hidden runs (an exe copy, a copy of the card, build/vm/*): Colt45, Uzi, M4, Shotgun standing, looking
  0.6 rad up / down, turning, walking, aimed (R1) and fired - the gun in view at the lower right, the barrel on the
  crosshair (hand x . view 0.99 - 1.00), only forearms and hands showing; free aim's shots through the dot at a
  37-health ped 6 m out: Colt45 37 -> 4.5, Uzi -> 11, M4 and Shotgun killed. Melee weapons keep the game's arms.

- **Manual reload** (2026-11-01, `reload.cpp`): CWeapon::Reload (FUN_002CDFB0) fills the clip from **weapon info +0x14,
  the clip size** (clip = min(total, size); with the slot base at ped +0x578: +0 type, +4 state, +8 clip, +0xC total,
  +0x10 the reload's end time). CWeapon::Fire's empty-clip branch (0x2C1998) only sets state 2 and the end time (CTimer
  ms 0x4CD104 + info +0x10; a quarter of it on another path for the player); the anim, sound and refill follow from the
  state. The reload key (R, Back + Square) does the same when the clip is short of its size and the total is larger,
  the slot is ready (state 0) and the player idle / attacking / aiming; guns with a clip of 1 (the shotguns 21 - 23, the
  sniper rifles, the rocket launcher) are left alone - the game reloads them every shot. Checked first person on and off:
  M4 28 / 88 -> 30 / 88 and Uzi 28 -> 30 after the reload time, Colt45 16 -> 17, a full clip refused; third person plays
  the reload anim; the viewmodel tips the gun over, low, while the slot reloads.
- **Scopes** (2026-11-01, the user's "fix first person for rocket and sniper, so mouse can work"): the game's own
  first-person aims on foot - CCam mode 7 (sniper rifle, laser scope), 8 (rocket launcher), 46 (camera), 47 (binoculars)
  - aim from the stick only; the mouse, sent to them as a right stick, did nothing (first person on or off). The camera
  hook now writes their front / up / target from the mouse / right stick (CameraAim's look, invert-Y as set; turns
  slowed by the mode's FOV / 70), turns the body with it and leaves the game its source and FOV. Shots go to the reticle
  (the sniper's shot and the rocket follow the camera's front). Checked first person on and off: the view turned 0.5 rad
  left / right and 0.375 up / down by the mouse, a 37-health ped 25 m out and 0.25 rad off killed by the sniper and the
  laser scope after aiming at it with the mouse, the rocket exploding at the reticle, and the view's direction kept when
  R1 is let go.
- **At rest unless aiming** (the user's request, 2026-11-01): the hand 6 cm lower and 3 cm back and in, the barrel 0.3 rad
  down and 0.22 rad in, raised to the crosshair only while R1 / the right mouse button aims (free aim) or locked on -
  eased 200 ms up, 180 ms down (UltimateFP's ADS ease); attacking (state 0x10 / 0x11, or a shot's recoil) raises it in
  80 ms, so hip fire shows the gun up. Checked: M4, Colt45, Uzi walking (ads 0), R1 held (ads 1, barrel . view 1.00),
  hip fire (ads 1).
- **Follow-up (the user's video 23-23)**: the eye-jump guard held the old eye behind him when a backwards run stopped
  (our code turns the body to the view in one frame) - now only while the ped has a vehicle. Getting in / out his
  position (+0x30) lags the anim by metres, so the bone hook's "within 2 m of the ped" test skipped those draws (head
  drawn, eyes stale): within 3 m of the vehicle is accepted too. The drawn body is moved by the one-frame gap so the
  head joint is at the camera (neck collapsed then), a car driver's head is kept softly within 0.42 m of the middle,
  and TheCamera's matrix is set to first person's view at CDraw::SetFOV (0x37ADD4: after CCamera::Process's mode blend
  and shake). Still open: 1 - 3 near-black frames at the start of a car exit and when the door shuts after entering
  (the eye at the seated head; not the blend - cause not found), and one frame of the back of his head on a bike
  dismount.

### 12u. VR - what a headset needs from a frame (VR.asi, docs/VR_PLAN.md M0, 2026-11-01)

- **A frame's own `had3d` alternates in play.** VCS draws the 3D into one buffer and copies the finished frame into the
  displayed one at the start of the next frame (the HUD rides along, `hudOnDraw`), so roughly every other composed
  `Frame` (`frames.back()` in the executor) has `had3d = 0` while the window shows 3D. The stable answer is decideShape's
  `Frame::shown` (3D in >= 4 of the last 32 frames, reset by a menu frame): `GSHwLayers.has3d` /
  `VcsPresentFrame.has_3d` use it. Found by VR.asi's cinema-reason counters (`vr` command: `no3d` counted on every
  other headset frame, the headset flipping between the head-tracked picture and the cinema screen).
- **The HUD alone.** The native HUD layer (gs_hw.cpp `HudLayer`) is drawn with the game's GS blends; drawn once over
  black (B) and once over white (W) it gives coverage a = 1 - (W - B) and premultiplied colour B - exact for blends
  linear in the destination (all the HUD's), close for additive glow. `splitLayers` in `composeDisplay` does it at the
  display's output size, before the HUD goes onto the picture.
- **Which head pose a shown frame was rendered with.** `PSPadBackend::lastInputNs()` is the main thread's input
  snapshot (`platform::inputSnapshotNs`, taken by `pumpEvents` at the host frame's start or in the frame lead); each
  `Frame` carries it (`inputNs`) and `gsHwShownInputNs()` names the shown one. A pose handed to the game before that
  snapshot is the one the frame's camera used: VR.asi keeps its poses by send time and submits the picture with the
  last one sent before `VcsPresentFrame.input_ns`, so the runtime reprojects it to where the head is now.
- **The camera's roll.** CCam's up vector (+0x60, written by CameraAim) is honoured by the game's view matrix: a head
  roll of 8 degrees sent as `up = up0 cos r + right sin r` rolls the picture by 8 degrees (hidden run, window shot).
- **Order in a host frame** (ps2_runtime.cpp main loop): pumpEvents -> (game frame starts: `ps2HostTick`, unless the
  frame lead started it) -> `UploadFrame` (the executor runs the ready frames: render hooks, `composeDisplay`) ->
  Dear ImGui -> `present::drawWindow` -> `present::present()` (the mods' present hook, then the swapchain) ->
  `waitNextFrame` (frame lead). An OpenXR mod's xrEndFrame + xrWaitFrame + xrBeginFrame in the present hook paces the
  whole loop to the headset; the next game frame then reads the new head pose.

### 12v. Head shots - how CPed::InflictDamage decides a critical hit (PedSkills.asi, 2026-11-01)

Found for VCS-mods `plugins/PedSkills` from the generated code of **CPed::InflictDamage (FUN_001D7940**; ped a0 -> s1,
attacker a1 -> s5, weapon a2 -> s6, damage f12 -> f21, piece a3 -> s3, direction t0 -> s2; 12h) and its jump tables in
the ELF (build/elf: by weapon at 0x4A9BB0, 48 entries; by piece at 0x4A9C70, 7), checked in hidden runs. It is VC's rule
("critical hits"); VCS has no sniper-only test.
- **Weapon cases** (the table at 0x1D7D48): 0 / 1 -> 0x1D7D60 (fists), 2 - 11 -> 0x1D7DD4 (melee), 12 / 15 / 18 / 32 / 44
  -> 0x1D8024 (blasts: random limbs off by FUN_001D8C20 when the damage kills and `nastyGame`), 17 -> 0x1D813C (the
  Molotov), 33 -> 0x1D8008 (fire), **19, 21 - 31, 34, 35, 45 -> 0x1D7E3C (bullets)**, 20 (Python), 37 and 13 / 14 / 16 /
  36 / 38 - 41 -> 0x1D83D8 (no hit logic: the damage only), 42 / 43 (vehicles) -> 0x1D8158, 46 / 47 their own. The cases are skipped (s0 = 0) when the victim is falling or
  getting up (state 0x2D / 0x2E, 0x1D7C6C - 0x1D7D34) - a shotgun's knock-back puts its victim there before a pellet's
  damage.
- **The bullet case** (0x1D7E3C): entity flags +0x48 bit 26 (bullet proof) -> no damage. Then, **unless the victim
  IsPlayer (FUN_0020C310 = ped type +0x550 == 0; called at 0x1D7E50, ra 0x1D7E58) or has ped +0x1D0 bit 9** (VC's
  bNoCriticalHits; missions set it), the **per-piece branch** is taken: always for types 28 - 31 (M4, Ruger, sniper
  rifles) and 34 (M60), else when **rand() (FUN_00408058) & 15 == 0** (ra 0x1D7EB4), shotguns **& 7** (21, ra
  0x1D7EA4); otherwise a generic hit animation (s4 0x10; the shotguns by the direction, 0x1C - 0x1F).
- **The per-piece branch** (the table at 0x1D7F30; VC's pieces): 0 / 1 torso / mid -> s4 0x10, 2 - 5 an arm / leg ->
  FUN_001D8C20 on it (nothing unless it kills, see below) and s4 0x16 - 0x19, **6 head -> 0x1D7F48: FUN_001D8C20(ped, 2,
  direction) = CPed::RemoveBodyPart(head)** (with `nastyGame` 0x489F80 and the ped on screen: the head hidden and blood
  - the head pop), **s4 = 0x14 (the face-hit death) and s7 = 1, fp = 1** (VC's headShot / bodyPartHit).
- **s7 kills**: after the armour (+0x4E8 takes the damage first, except weapons 46 / 47) the health (+0x4E4) - damage
  is stored only when it stays over 1 **and s7 is 0** (0x1D85C8); with s7 the ped dies (SetDie FUN_0020A3B8 with s4,
  CDarkel / stats with fp = head shot) whatever its health or armour. So a sniper's head shot kills because the sniper
  always takes the branch; a pistol's does 1 time in 16.
- **The mod** (Game > Ped skills, `pedskills.headshots` on, `pedskills.everyone` off): a before-hook on rand() answers 0
  at ra 0x1D7EA4 / 0x1D7EB4 when s3 (the piece) is 6 and the shooter (s5) is the player (`*(0x4E4910 + 0x190 x
  byte 0x4CD128)`, FindPlayerPed FUN_0024A430) or anyone with "everyone" - the game's own head-shot branch then runs;
  a before-hook on IsPlayer answers 0 at ra 0x1D7E58 for a head hit by a bullet weapon with "everyone" (Vic one-shot);
  a before-hook on InflictDamage raises the damage to health + armour + 100 for a head hit that never reaches the
  bullet case - the Python's, and any bullet weapon's on a victim in state 0x2D / 0x2E - under the same rules (no head
  pop there: the normal death). bNoCriticalHits peds, bullet-proof peds, the checks before the weapon cases (invulnerable,
  "only damaged by the player", dying / dead) stay the game's. Melee, blasts, fire never reach these paths.
- Checked (hidden, exe copy, free aim in first person, a fresh ped 4 m away with its back turned and 500 health per
  shot; `VCS_PEDSKILLS_LOG=1` logs every hit of the player's and every head shot made): one head shot killed with the
  Colt45 (rand forced), Uzi (rand forced), M4 (the game's own branch), Shotgun (the pellet's victim knocked down first:
  the damage path) and Python (the damage path), each a Jolt ragdoll; a Colt45 chest shot did 25 damage (100 -> 67.5,
  piece 0); setting off: head hits did 25, now and then one killed (the game's own 1 in 16). Aim: the head piece is the
  sphere around ped z + 0.65 - 0.8 (z + 0.62 at 4 m hit the shoulder / arm, piece 3, with the Uzi's lower eye).
  "Everyone" (an NPC's head shot on Vic) was not run.

## 13. Open questions / next research targets

- Main loop, frame limiter, CTimer (section 4) - milestone 4 (60 fps).
- Vehicle structure, "in vehicle" / "in water" ped flags.
- After dying (hospital respawn, clock jumps to ~01:25) the world around the hospital was not drawn for ~40 s,
  only lights (autodrive soak 2026-10-23) - streaming or rendering, to find out (milestone 2).
- Mission-passed flags (storyline globals) - for reaching late-game states.
- Cheat handlers (weapons, health, vehicles, weather) - the script commands cover these for now.
- Collision: VU0 program 0 (section 6c), collision streaming - the fall-through bug.
- HUD / font / sprite call sites (CHud, CFont, CSprite2d, CSprite) - milestone 3 (2D at the RW level).
- Sound driver command protocol in full (section 9) - milestone 6.
- Threads and their priorities.
