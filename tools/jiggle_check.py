#!/usr/bin/env python3
"""Jiggle physics check (`VCS-mods plugins/JoltPhysics/src/jiggle.cpp`; docs/game-internals.md 12r): the chest and hips springs of the nearest
female peds follow their movement within their limits and settle; off, nothing is touched.

    python tools/jiggle_check.py [OUT]

Three hidden games of the Fort Baxter rig save (copies), at (-700, -500), noon:
- VCS_JIGGLE=1 (female peds only, the default): a female (ped type 5) and a male (type 4) civilian spawned beside Vic:
  only the female is jiggled (the status' ped).
- VCS_JIGGLE=1 VCS_JIGGLE_ALL=1 (Vic too): Vic runs forward 1.5 s and stops - the chest / hips offsets rise above
  2 cm / 1 cm, never past their max (6 / 5.5 cm), and settle (under 2 cm: the gravity sag and the idle animation's sway) 2 s after he stops.
- VCS_JIGGLE=0: no ped is stepped.
Results: OUT/summary.txt, OUT/*.png. Default OUT: build/jiggle/<date-time>. VCS_EXE=<a copy of vcs.exe> runs that one.
"""
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = rig.Scm
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "jiggle", time.strftime("%Y%m%d-%H%M%S")))
results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail), flush=True)


def game(name, env, port):
    g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name=name, seconds=300, env=env, port=port)
    g.wait_ingame()
    g.prime()
    g.set_time(12)
    g.teleport(-700.0, -500.0, -100.0)
    time.sleep(3.0)
    return g


def status(g, ped=0):
    return dict(kv.split("=", 1) for kv in g.cmd("jiggle %x" % ped if ped else "jiggle").split() if "=" in kv)


def peds(g):
    pool = g.u32(0x487A94)
    base, flags, size = g.u32(pool), g.u32(pool + 4), g.u32(pool + 8)
    used = g.peek(flags, size)
    return [base + i * 0xD20 for i in range(size) if not used[i] & 0x80]


def spawn(g, kind, x, y):
    before = set(peds(g))
    g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.LOAD_ALL_MODELS_NOW) +
          S.op(S.CREATE_CHAR, S.i(kind), S.i(55), S.f(x), S.f(y), S.f(-100.0), S.LOCAL0))
    time.sleep(0.8)
    new = [p for p in peds(g) if p not in before]
    return min(new, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (x, y))) if new else 0


os.makedirs(OUT, exist_ok=True)
g = game("jiggle_female", {"VCS_JIGGLE": "1"}, 47761)
try:
    me, (x, y, z), _ = g.player()
    fx, fy = g.peekf(me + 0x10, 2)
    h = math.hypot(fx, fy) or 1.0
    fx, fy = fx / h, fy / h
    female = spawn(g, 5, x + fx * 3 + fy, y + fy * 3 - fx)
    male = spawn(g, 4, x + fx * 3 - fy, y + fy * 3 + fx)
    seen = set()
    for _ in range(20):
        st = status(g)
        seen.add(int(st["ped"], 16))
        time.sleep(0.1)
    g.cmd("screenshot " + os.path.join(OUT, "female.png"))
    ok("a female ped is jiggled", female in seen, "female %08X, jiggled %s" % (female, ["%08X" % p for p in seen]))
    ok("a male ped and Vic are not", male not in seen and me not in seen, "male %08X, Vic %08X" % (male, me))
finally:
    g.quit()

g = game("jiggle_all", {"VCS_JIGGLE": "1", "VCS_JIGGLE_ALL": "1"}, 47762)
try:
    me = g.player()[0]
    status(g)
    g.cmd("key W down")
    peak = [0.0, 0.0]
    t0 = time.time()
    while time.time() - t0 < 1.5:
        st = status(g, me)
        peak = [max(peak[0], float(st["chestmax"])), max(peak[1], float(st["hipsmax"]))]
        time.sleep(0.05)
    g.cmd("key W up")
    t0 = time.time()
    while time.time() - t0 < 0.8:
        st = status(g, me)
        peak = [max(peak[0], float(st["chestmax"])), max(peak[1], float(st["hipsmax"]))]
        if 0.1 < time.time() - t0 < 0.16:
            g.cmd("screenshot " + os.path.join(OUT, "stop.png"))
        time.sleep(0.05)
    time.sleep(2.0)
    rest = [], []
    for _ in range(10):
        st = status(g, me)
        rest[0].append(float(st["chest"]))
        rest[1].append(float(st["hips"]))
        time.sleep(0.05)
    ok("running and stopping move the chest and hips", peak[0] > 0.02 and peak[1] > 0.01,
       "peaks chest %.3f m, hips %.3f m" % tuple(peak))
    ok("within their limits", peak[0] <= 0.0601 and peak[1] <= 0.0551, "max 0.060 / 0.055")
    ok("they settle standing still", max(rest[0]) < 0.02 and max(rest[1]) < 0.02,
       "chest %.3f, hips %.3f m after 2 s" % (max(rest[0]), max(rest[1])))
finally:
    g.quit()

g = game("jiggle_off", {"VCS_JIGGLE": "0"}, 47763)
try:
    me, (x, y, z), _ = g.player()
    spawn(g, 5, x + 3, y)
    time.sleep(1.0)
    st = status(g)
    ok("off: nothing is jiggled", int(st["steps"]) == 0 and st["enabled"] == "0", "steps %s" % st["steps"])
finally:
    g.quit()

with open(os.path.join(OUT, "summary.txt"), "w") as f:
    for name, good, detail in results:
        f.write("%-4s %s %s\n" % ("ok" if good else "FAIL", name, detail))
passed = bool(results) and all(good for _, good, _ in results)
print("%s - %s" % ("PASS" if passed else "FAIL", os.path.join(OUT, "summary.txt")))
sys.exit(0 if passed else 1)
