#!/usr/bin/env python3
"""Catch fall and fire back from the ground check (Jolt: `VCS-mods plugins/JoltPhysics/src/jolt.cpp` catchFall / applyMoveSpeed;
docs/game-internals.md 12n): an armed ped shot down puts its hands out as it falls, then fires blind shots back at its
shooter from the ground (the game's own CWeapon::Fire), and gets up.

    VCS_EXE=<a copy of vcs.exe> python tools/blindfire_check.py [OUT]

Loads the Fort Baxter rig save (a copy, hidden) with VCS_JOLT=1 at (-700, -500), noon. Up to four times: a ped with a
Colt45 and 500 health spawned 2.5 m ahead, Vic with a Shotgun locked on (R1) fires until it is knocked down (the
game's call: a ped may die or stand). Checked on the knockdown: its arms braced, blind shots fired (the counter and
its clip), and it got up again. Results: OUT/summary.txt, OUT/down_*.png. Default OUT: build/hits/blindfire-<time>.
"""
import math, os, sys, time
ROOT = r"F:\games\VCS-Recomp-0.0.1-windows"
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rig
S = rig.Scm
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "hits", time.strftime("blindfire-%Y%m%d-%H%M%S")))
os.makedirs(OUT, exist_ok=True)
g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name="blindfire_check", seconds=400,
                   env={"VCS_JOLT": "1"}, port=47683)


def jolt():
    return dict(kv.split("=", 1) for kv in g.cmd("jolt").split() if "=" in kv)


try:
    g.wait_ingame(); g.prime(); g.set_time(12)
    g.teleport(-700.0, -500.0, -100.0); time.sleep(3.0)
    me, (x, y, z), _ = g.player()
    fx, fy = g.peekf(me + 0x10, 2); h = math.hypot(fx, fy); fx, fy = fx / h, fy / h
    g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.REQUEST_MODEL, S.i(346)) + S.op(S.REQUEST_MODEL, S.i(349)) +
          S.op(S.LOAD_ALL_MODELS_NOW) + S.op(S.GIVE_WEAPON_TO_CHAR, S.PLAYER, S.i(21), S.i(50)))
    time.sleep(1.0)
    results = []
    for attempt in range(4):
        me, (x, y, z), _ = g.player()
        g.scm(S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(x + fx * 2.5), S.f(y + fy * 2.5), S.f(-100.0), S.LOCAL0) +
              S.op(S.GIVE_WEAPON_TO_CHAR, S.LOCAL0, S.i(19), S.i(60)))
        time.sleep(0.4)
        pool = g.u32(0x487A94); base, flags, size = g.u32(pool), g.u32(pool + 4), g.u32(pool + 8)
        used = g.peek(flags, size)
        peds = [base + i * 0xD20 for i in range(size) if not used[i] & 0x80 and base + i * 0xD20 != me]
        ped = min(peds, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (x + fx * 2.5, y + fy * 2.5)))
        g.cmd("pokef 0x%x 500" % (ped + 0x4E4))
        st0 = jolt()
        hp0 = g.peekf(me + 0x4E4, 1)[0]
        g.cmd("key E down"); time.sleep(0.4)
        t0, fired, down_seen = time.time(), 0, False
        while time.time() - t0 < 8.0:
            state = g.u32(ped + 0x8C4)
            if state == 0x2D:
                down_seen = True
            if fired < 3 and not down_seen and state not in (0x39, 0x3A) and time.time() - t0 >= fired * 1.2:
                g.cmd("key Ctrl down"); time.sleep(0.12); g.cmd("key Ctrl up"); fired += 1
            if down_seen and 1.0 < time.time() - t0 < 1.1:
                g.cmd("screenshot " + os.path.join(OUT, "down_%d.png" % attempt))
            time.sleep(0.08)
        g.cmd("key E up")
        st = jolt()
        slot = g.peek(ped + 0x789, 1)[0]
        clip = g.u32(ped + 0x574 + slot * 0x1C + 0xC)
        r = dict(attempt=attempt, down=down_seen, shotdown=int(st["shotdown"]) - int(st0["shotdown"]),
                 braced=int(st["braced"]) - int(st0["braced"]), blind=int(st["blindshots"]) - int(st0["blindshots"]),
                 clip=clip, slot=slot, vic_hp=(hp0, g.peekf(me + 0x4E4, 1)[0]), state=hex(g.u32(ped + 0x8C4)))
        print(r, flush=True)
        results.append(r)
        if r["blind"]:
            break
        g.teleport(x + 20, y, -100.0); time.sleep(1.5)
finally:
    g.quit()
knocked = [r for r in results if r["shotdown"] > 0]
checks = []
if knocked:
    r = knocked[-1]
    checks = [("a shot knocks an armed ped down", True, "attempt %d" % r["attempt"]),
              ("its arms reach for the ground as it falls", r["braced"] >= 1, "braced %d" % r["braced"]),
              ("it fires back from the ground", r["blind"] >= 1 and r["clip"] < 60, "%d blind shots, clip now %d, Vic's health %.0f -> %.0f" % (
                  r["blind"], r["clip"], r["vic_hp"][0], r["vic_hp"][1])),
              ("and gets up", r["state"] not in ("0x2d", "0x2e", "0x39", "0x3a"), "state %s" % r["state"])]
else:
    checks = [("a shot knocks an armed ped down", False, "in %d attempts: killed or still standing" % len(results))]
with open(os.path.join(OUT, "summary.txt"), "w") as f:
    for name, good, detail in checks:
        line = "%-4s %s %s" % ("ok" if good else "FAIL", name, detail)
        print(line); f.write(line + chr(10))
passed = all(c[1] for c in checks)
print("%s - %s" % ("PASS" if passed else "FAIL", os.path.join(OUT, "summary.txt")))
sys.exit(0 if passed else 1)
