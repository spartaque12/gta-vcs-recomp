#!/usr/bin/env python3
"""Pickups on the ground check (Jolt Physics props: `VCS-mods plugins/JoltPhysics/src/jolt.cpp` pickupEffects / makeProp; docs/game-internals.md
12m): weapon and cash pickups fall with the physics and lie on the ground at their real size, without spin or glow, and
can still be picked up.

    python tools/pickups_check.py [OUT] [--port 47679]

Loads the Fort Baxter rig save (a copy, hidden) with VCS_JOLT_PICKUPS=1 at noon on the street at (-700, -500). A ped
(model 55) with a Colt45 and $100 (+0x77E; its money-given-by-script flag set, so a mission ped drops it) is killed 3 m
ahead: its gun (type 4) and four piles of cash (type 8) become props - they fall, come to rest on the road (the pickup
objects' matrices no longer spinning: unchanged over a second, unit scale - the game draws a gun 1.84 x -, the up row
of the gun not vertical: on its side), their pickup positions over them; Vic walked onto the cash collects it (the
slots empty). Then a weapon pickup the map places (the nearest in the array) is visited: it lies on the ground too.
Screenshots of the drop and the props at rest. Results: OUT/summary.txt, OUT/*.png. Default OUT:
build/pickups/<date-time>. VCS_EXE=<a copy of vcs.exe> runs that one (build\\vcs.exe stays free).
"""
import argparse
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = rig.Scm
PICKUPS, PICKUP_SIZE, PICKUP_COUNT = 0x4EA740, 0x40, 336
PED_POOL, PED_SIZE = 0x487A94, 0xD20
SPOT = (-700.0, -500.0)


class Check:
    def __init__(self, out, port):
        self.out = os.path.abspath(out)
        self.port = port
        self.results = []
        self.g = None

    def ok(self, name, cond, detail=""):
        self.results.append((name, bool(cond), detail))
        print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail), flush=True)
        return cond

    def jolt(self):
        return dict(kv.split("=", 1) for kv in self.g.cmd("jolt").split() if "=" in kv)

    def pickups(self):
        g = self.g
        raw = b"".join(g.peek(PICKUPS + o, min(4096, PICKUP_COUNT * PICKUP_SIZE - o))
                       for o in range(0, PICKUP_COUNT * PICKUP_SIZE, 4096))
        out = {}
        for i in range(PICKUP_COUNT):
            e = raw[i * PICKUP_SIZE:(i + 1) * PICKUP_SIZE]
            if e[0x38]:
                out[i] = dict(pos=struct.unpack_from("<3f", e, 0), obj=struct.unpack_from("<I", e, 0x20)[0],
                              model=struct.unpack_from("<h", e, 0x34)[0], type=e[0x38])
        return out

    def matrix(self, obj):
        return self.g.peekf(obj, 16)

    def ground(self, x, y):
        """The ped-standing ground under (x, y): where a ped spawned there stands, 1 m over its soles."""
        return None

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        g = self.g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name="pickups_check",
                                    seconds=400, env={"VCS_JOLT_PICKUPS": "1"}, port=self.port)
        try:
            g.wait_ingame()
            g.prime()
            g.set_time(12)
            g.teleport(SPOT[0], SPOT[1], -100.0)
            time.sleep(3.0)
            me, (x, y, z), _ = g.player()
            feet = z - 1.0
            fx, fy = g.peekf(me + 0x10, 2)
            h = math.hypot(fx, fy) or 1.0
            fx, fy = fx / h, fy / h
            before = self.pickups()
            g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.REQUEST_MODEL, S.i(346)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                  S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(x + fx * 3), S.f(y + fy * 3), S.f(-100.0), S.LOCAL0) +
                  S.op(S.GIVE_WEAPON_TO_CHAR, S.LOCAL0, S.i(19), S.i(60)))
            time.sleep(1.0)
            pool = g.u32(PED_POOL)
            base, flags, size = g.u32(pool), g.u32(pool + 4), g.u32(pool + 8)
            used = g.peek(flags, size)
            peds = [base + i * PED_SIZE for i in range(size) if not used[i] & 0x80 and base + i * PED_SIZE != me]
            ped = min(peds, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (x + fx * 3, y + fy * 3)))
            g.cmd("poke 0x%x 6400" % (ped + 0x77E))                                   # $100
            g.cmd("poke 0x%x %02x" % (ped + 0x1D2, g.peek(ped + 0x1D2, 1)[0] | 0x40))  # money given by the script
            g.cmd("pokef 0x%x 0" % (ped + 0x4E4))
            time.sleep(1.3)
            g.cmd("screenshot " + os.path.join(self.out, "drop.png"))
            time.sleep(3.5)
            g.cmd("screenshot " + os.path.join(self.out, "rest.png"))
            st = self.jolt()
            new = {i: p for i, p in self.pickups().items() if i not in before or before[i]["obj"] != p["obj"]}
            guns = {i: p for i, p in new.items() if p["type"] == 4}
            cash = {i: p for i, p in new.items() if p["type"] == 8}
            print("new pickups: %s; jolt props=%s moving=%s made=%s" % (
                ["%d:%d/%d" % (i, p["model"], p["type"]) for i, p in new.items()], st["props"], st["propsmoving"],
                st["propsmade"]), flush=True)
            self.ok("the dead ped drops a gun and cash", guns and cash, "%d gun(s), %d pile(s)" % (len(guns), len(cash)))
            self.ok("they are props in the physics", int(st["propsmade"]) >= len(new) and len(new) > 0,
                    "%s made, %s moving now" % (st["propsmade"], st["propsmoving"]))
            first = {i: self.matrix(p["obj"]) for i, p in new.items()}
            time.sleep(1.0)
            for i, p in new.items():
                m = self.matrix(p["obj"])
                kind = "gun" if p["type"] == 4 else "cash"
                scale = [math.sqrt(sum(v * v for v in m[r * 4:r * 4 + 3])) for r in range(3)]
                still = max(abs(a - b) for a, b in zip(first[i][:15], m[:15])) < 1e-4
                self.ok("%s %d lies still at its real size" % (kind, i), still and all(abs(s - 1.0) < 0.02 for s in scale),
                        "scale %s, moved %s" % (["%.2f" % s for s in scale], not still))
                self.ok("%s %d is on the ground" % (kind, i), feet - 0.4 < m[14] < feet + 0.35,
                        "object z %.2f, the road %.2f" % (m[14], feet))
                if kind == "gun":
                    self.ok("the gun lies on its side", abs(m[10]) < 0.5, "its up row's z %.2f" % m[10])
                pos = g.peekf(PICKUPS + i * PICKUP_SIZE, 3)
                self.ok("%s %d's pickup position is over it" % (kind, i), math.dist(pos[:2], m[12:14]) < 0.05,
                        "pickup (%.2f, %.2f, %.2f), object (%.2f, %.2f, %.2f)" % (tuple(pos) + tuple(m[12:15])))
            for i, p in cash.items():
                m = self.matrix(p["obj"])
                g.teleport(m[12], m[13], -100.0)
                time.sleep(1.0)
            left = [i for i in cash if PICKUPS and self.pickups().get(i, {}).get("obj") == cash[i]["obj"]]
            self.ok("walking onto the cash picks it up", not left, "%d of %d piles left" % (len(left), len(cash)))

            # a weapon pickup the map places: the nearest
            g.teleport(SPOT[0], SPOT[1], -100.0)
            time.sleep(1.0)
            placed = [(i, p) for i, p in self.pickups().items() if 331 <= p["model"] <= 368 and p["type"] not in (4, 8)]
            placed.sort(key=lambda ip: math.dist(ip[1]["pos"][:2], SPOT))
            if self.ok("the map has weapon pickups", placed, "%d" % len(placed)):
                i, p = placed[0]
                px, py, pz = p["pos"]
                g.teleport(px + 4.0, py, -100.0)
                time.sleep(4.0)
                q = self.pickups().get(i)
                m = self.matrix(q["obj"]) if q else None
                g.cmd("screenshot " + os.path.join(self.out, "placed.png"))
                feet2 = g.player()[1][2] - 1.0
                self.ok("a placed weapon pickup lies on the ground", m and feet2 - 0.6 < m[14] < feet2 + 0.4 and abs(m[10]) < 0.5,
                        "model %d at (%.1f, %.1f): object z %s, Vic's soles %.2f, up row z %s" % (
                            p["model"], px, py, m and "%.2f" % m[14], feet2, m and "%.2f" % m[10]))
            self.ok("the game is still running", g.alive())
        finally:
            g.quit()
        return self.finish()

    def finish(self):
        with open(os.path.join(self.out, "summary.txt"), "w") as f:
            for name, good, detail in self.results:
                f.write("%-4s %s %s\n" % ("ok" if good else "FAIL", name, detail))
        passed = bool(self.results) and all(good for _, good, _ in self.results)
        print("%s - %s" % ("PASS" if passed else "FAIL", os.path.join(self.out, "summary.txt")), flush=True)
        return passed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "pickups", time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--port", type=int, default=rig.gamectl.DEFAULT_PORT)
    a = ap.parse_args()
    sys.exit(0 if Check(a.out, a.port).run() else 1)


if __name__ == "__main__":
    main()
