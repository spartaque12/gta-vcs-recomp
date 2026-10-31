#!/usr/bin/env python3
"""Ragdolls on the world's collision check (Jolt milestone 2: `VCS-mods plugins/JoltPhysics/src/jolt.cpp` world(), `VCS-mods plugins/JoltPhysics/src/physics/ragdoll.cpp`;
docs/game-internals.md 12k): a body blown off a roof lands on the street below, one blown into a wall stays in front of
it.

    python tools/ragdoll_world_check.py [OUT] [--port 47675]

Loads the Fort Baxter rig save (a copy, hidden) with VCS_JOLT=1 and puts Vic on the street at (-650, -440) looking
west, at a flat roof 5 m up whose edge runs north-south around x -666.5 (found in the buildings' col triangles, read
from the game: the highest surface along two east-west lines, y -440 and -435). Ledge: a ped spawned on the roof 0.8 m
from its edge, a grenade-sized ADD_EXPLOSION 3.5 m behind it on the roof - the ragdoll must be made on the world's
collision (not a ground of its own: the log's "(the world's)"), go over the edge and end on the street (its pelvis
under the roof's height, not under the street's), the ped's height following it down. Wall: a ped on the street 1 m in
front of the building's wall, the blast 3.5 m in front of it - thrown at the wall, the body must stay in front of it
(the highest surface under its pelvis the street's). Also: the world's bodies and shapes in the physics, the step's
cost. Screenshots of both falls. Results: OUT/summary.txt, OUT/*.png. Default OUT: build/ragdoll/world-<date-time>.
VCS_EXE=<a copy of vcs.exe> runs that one (build\\vcs.exe stays free).
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
PED_POOL, PED_SIZE = 0x487A94, 0xD20
VEHICLE_POOL, VEHICLE_SIZE = 0x487A98, 0x8C0
PED_STATE, PED_HEALTH = 0x8C4, 0x4E4
DYING, DEAD = 0x39, 0x3A
MODEL_INFOS, SECTORS = 0x486518, 0x486464
BUILDING_LISTS = (0x00, 0x04, 0x14, 0x18)
STAND = (-650.0, -440.0)        # Vic, on the street east of the roof
LINES = (-440.0, -435.0)        # the ledge's line, the wall's
ADD_EXPLOSION_HANDLER = 0x182998


class Check:
    def __init__(self, out, port):
        self.out = os.path.abspath(out)  # the game saves screenshots from its own folder
        self.port = port
        self.results = []
        self.g = None
        self.triangles = []

    def ok(self, name, cond, detail=""):
        self.results.append((name, bool(cond), detail))
        print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail), flush=True)
        return cond

    def peds(self):
        g = self.g
        pool = g.u32(PED_POOL)
        base, flags, size = g.u32(pool), g.u32(pool + 4), g.u32(pool + 8)
        used = g.peek(flags, size)
        return [base + i * PED_SIZE for i in range(size) if not used[i] & 0x80]

    def vehicle_under(self, p):
        """A vehicle whose middle is within 3 m of p across and under it (a body can land on its roof): its model and
        position, or None."""
        g = self.g
        pool = g.u32(VEHICLE_POOL)
        base, flags, size = g.u32(pool), g.u32(pool + 4), g.u32(pool + 8)
        used = g.peek(flags, size)
        for i in range(size):
            if used[i] & 0x80:
                continue
            v = base + i * VEHICLE_SIZE
            at = g.peekf(v + 0x30, 3)
            if math.dist(at[:2], p[:2]) < 3.0 and at[2] < p[2]:
                return struct.unpack("<h", g.peek(v + 0x56, 2))[0], at
        return None

    def jolt(self):
        st = dict(kv.split("=", 1) for kv in self.g.cmd("jolt").split() if "=" in kv)
        st["pelvis"] = [float(v) for v in st["pelvis"].split(",")]
        return st

    def big(self, addr, n):
        return b"".join(self.g.peek(addr + o, min(4096, n - o)) for o in range(0, n, 4096))

    def load_triangles(self, cx, cy, reach):
        """The world triangles of the buildings around (cx, cy) whose col models have them, from the game's memory:
        each as its three corners (game-internals.md 12k)."""
        g = self.g
        table, sectors = g.u32(MODEL_INFOS), g.u32(SECTORS)
        entities = []
        for sy in range(int((cy - reach) / 80 + 25), int((cy + reach) / 80 + 25) + 1):
            for sx in range(int((cx - reach) / 80 + 30), int((cx + reach) / 80 + 30) + 1):
                heads = struct.unpack("<14I", g.peek(sectors + (sy * 50 + sx) * 0x38, 0x38))
                for list_offset in BUILDING_LISTS:
                    node = heads[list_offset // 4]
                    while node:
                        item, _, node = struct.unpack("<3I", g.peek(node, 12))
                        entities.append(item)
        triangles = []
        for e in dict.fromkeys(entities):
            raw = g.peek(e, 0x60)
            m = struct.unpack_from("<16f", raw, 0)
            flags, model = struct.unpack_from("<I", raw, 0x48)[0], struct.unpack_from("<h", raw, 0x56)[0]
            if not flags & 0x200 or model < 0:
                continue
            col = g.u32(g.u32(table + model * 4) + 0x14)
            if not col:
                continue
            head = g.peek(col, 0x58)
            count = struct.unpack_from("<H", head, 0x32)[0]
            vertices, tris = struct.unpack_from("<2I", head, 0x48)
            if not count or not vertices or not tris:
                continue
            traw = self.big(tris, count * 8)
            offsets = [struct.unpack_from("<3H", traw, i * 8) for i in range(count)]
            vraw = self.big(vertices, max(max(o) for o in offsets) + 6)
            for o in offsets:
                corners = []
                for k in o:
                    v = [c / 128.0 for c in struct.unpack_from("<3h", vraw, k)]
                    corners.append(tuple(m[12 + j] + m[j] * v[0] + m[4 + j] * v[1] + m[8 + j] * v[2] for j in range(3)))
                triangles.append(corners)
        self.triangles = triangles

    def top(self, x, y):
        """The highest triangle over (x, y), or None."""
        best = None
        for (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) in self.triangles:
            if x < min(x1, x2, x3) or x > max(x1, x2, x3) or y < min(y1, y2, y3) or y > max(y1, y2, y3):
                continue
            d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if abs(d) < 1e-9:
                continue
            l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
            l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
            if min(l1, l2, 1 - l1 - l2) < -1e-6:
                continue
            z = l1 * z1 + l2 * z2 + (1 - l1 - l2) * z3
            best = z if best is None or z > best else best
        return best

    def edge(self, y, street):
        """Along y, from x -672 east: where a roof 3+ m up drops to the street (`street`: about its height) - the roof's
        height, the street's and the x where one meets the other."""
        samples = [(x / 4.0, self.top(x / 4.0, y)) for x in range(-672 * 4, -658 * 4)]
        for (xa, za), (xb, zb) in zip(samples, samples[1:]):
            if za is not None and zb is not None and za - zb > 3.0 and abs(zb - street) < 1.0:
                high = [z for x, z in samples if z is not None and xa - 1.5 < x <= xa]
                low = [z for x, z in samples if z is not None and xb <= x < xb + 1.5]
                return min(high), max(low), (xa + xb) / 2.0
        return None

    def spawn(self, x, y):
        """A ped (model 55) at (x, y) on the highest ground there: its address, 0 when none came."""
        g = self.g
        before = set(self.peds())
        g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.LOAD_ALL_MODELS_NOW) +
              S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(x), S.f(y), S.f(-100.0), S.LOCAL0))
        time.sleep(1.0)
        new = [p for p in self.peds() if p not in before]
        return min(new, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (x, y))) if new else 0

    def blow(self, explode, ped, at, name):
        """ADD_EXPLOSION (a grenade's) at `at` near `ped`: its ragdoll followed for 5 s. (made, where the pelvis
        started, where it ended, the ped's position then, the slowest step)"""
        g = self.g
        created = int(self.jolt()["created"])
        start = g.peekf(ped + 0x30, 3)
        g.scm(S.op(explode, S.f(at[0]), S.f(at[1]), S.f(at[2]), S.i(0)))
        made, end, slowest, t0 = False, None, 0.0, time.time()
        while time.time() - t0 < 5.0:
            st = self.jolt()
            if int(st["created"]) > created and int(st["ped"], 16) == ped:
                made = True
                end = st["pelvis"][12:15]
                slowest = max(slowest, float(st["stepms"]))
            if 0.45 < time.time() - t0 < 0.55:
                g.cmd("screenshot " + os.path.join(self.out, name + "_air.png"))
            time.sleep(0.05)
        g.cmd("screenshot " + os.path.join(self.out, name + ".png"))
        return made, start, end, g.peekf(ped + 0x30, 3), slowest

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        g = self.g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name="ragdoll_world",
                                    seconds=400, env={"VCS_JOLT": "1"}, port=self.port)
        try:
            g.wait_ingame()
            g.prime()
            g.set_time(12)
            g.teleport(STAND[0], STAND[1], -100.0, heading=90.0)  # looking west, at the roof
            time.sleep(3.0)
            self.load_triangles(-665.0, -438.0, 15.0)
            feet = g.player()[1][2] - 1.0  # the street Vic stands on
            ledge, wall = self.edge(LINES[0], feet), self.edge(LINES[1], feet)
            print("%d triangles; ledge %s, wall %s" % (len(self.triangles), ledge, wall), flush=True)
            if not self.ok("the roof's edge is in the col triangles", ledge and wall,
                           "ledge %s, wall %s (roof z, street z, edge x)" % (ledge, wall)):
                return self.finish()
            table = b"".join(g.peek(0x4BEAF0 + off, min(4096, 1381 * 8 - off)) for off in range(0, 1381 * 8, 4096))
            explode = next(i for i in range(1381) if struct.unpack_from("<I", table, i * 8 + 4)[0] == ADD_EXPLOSION_HANDLER)

            # off the roof: the ped 0.8 m from the edge, the blast 5 m behind it (a throw of a few metres: onto the
            # pavement under the wall, not into the traffic)
            roof, street, x = ledge
            ped = self.spawn(x - 0.8, LINES[0])
            stood = g.peekf(ped + 0x30, 3) if ped else None
            if not self.ok("a ped stands on the roof", ped and abs(stood[2] - 1.0 - roof) < 0.6,
                           "at %s, the roof at %.2f" % (stood and "(%.2f, %.2f, %.2f)" % tuple(stood), roof)):
                return self.finish()
            made, start, end, at, slowest = self.blow(explode, ped, (x - 5.8, LINES[0], roof + 0.3), "ledge")
            st = self.jolt()
            print("ledge: ped %08X from %s to pelvis %s, ped at %s; world=%s shapes=%s bodies=%s" % (
                ped, ["%.2f" % v for v in start], end and ["%.2f" % v for v in end], ["%.2f" % v for v in at],
                st["world"], st["shapes"], st["bodies"]), flush=True)
            self.ok("the blast's victim on the roof gets a ragdoll", made)
            line = self.log_line(ped)
            self.ok("on the world's collision", line and "(the world's)" in line, line or "no log line")
            self.ok("the world's buildings are in the physics", int(st["world"]) > 0 and int(st["shapes"]) > 0,
                    "%s bodies, %s shapes" % (st["world"], st["shapes"]))
            if made and end:
                self.ok("it goes over the edge", end[0] > x + 0.2 and end[2] < roof - 2.0,
                        "pelvis x %.2f (edge %.2f), z %.2f (roof %.2f)" % (end[0], x, end[2], roof))
                # the street's traffic is in the physics too: a body on a vehicle's roof is where it should be
                vehicle = self.vehicle_under(end) if end[2] > street + 0.8 else None
                self.ok("and lands on the street (or a vehicle in it)", street - 0.3 < end[2] < street + 0.8 or vehicle,
                        "pelvis z %.2f, street %.2f%s" % (end[2], street, vehicle and ", on vehicle %d at %s" % (
                            vehicle[0], ["%.1f" % v for v in vehicle[1]]) or ""))
                self.ok("the ped's height follows it down", abs(at[2] - (end[2] + 0.85)) < 0.8,
                        "ped z %.2f, pelvis %.2f" % (at[2], end[2]))
            ledge_step = slowest

            # into the wall: a ped 1 m in front of it, the blast 3.5 m in front of the ped
            roof, street, x = wall
            ped = self.spawn(x + 1.0, LINES[1])
            stood = g.peekf(ped + 0x30, 3) if ped else None
            if not self.ok("a ped stands in front of the wall", ped and abs(stood[2] - 1.0 - street) < 0.6,
                           "at %s, the street at %.2f" % (stood and "(%.2f, %.2f, %.2f)" % tuple(stood), street)):
                return self.finish()
            made, start, end, at, slowest = self.blow(explode, ped, (x + 4.5, LINES[1], street + 0.3), "wall")
            print("wall: ped %08X from %s to pelvis %s" % (ped, ["%.2f" % v for v in start],
                                                          end and ["%.2f" % v for v in end]), flush=True)
            self.ok("the blast's victim by the wall gets a ragdoll", made)
            if made and end:
                under = self.top(end[0], end[1])
                self.ok("it is thrown at the wall", end[0] < start[0] - 0.2,
                        "pelvis x %.2f, started %.2f, wall %.2f" % (end[0], start[0], x))
                self.ok("and stays in front of it", end[0] > x - 0.3 and under is not None and abs(under - street) < 0.8
                        and street - 0.3 < end[2] < street + 1.5,
                        "pelvis (%.2f, %.2f), wall x %.2f, the surface under it %s, street %.2f" % (
                            end[0], end[2], x, under and "%.2f" % under, street))
            self.ok("the step stays cheap", max(ledge_step, slowest) < 3.0, "slowest %.3f ms" % max(ledge_step, slowest))
            self.ok("the game is still running", g.alive())
        finally:
            g.quit()
        return self.finish()

    def log_line(self, ped):
        for line in open(os.path.join(ROOT, "build", "run", "ragdoll_world.log"), encoding="utf-8", errors="replace"):
            if line.startswith("[jolt] ped %08X (model" % ped):
                return line.split(":", 1)[1].strip()[:160]
        return None

    def finish(self):
        with open(os.path.join(self.out, "summary.txt"), "w") as f:
            for name, good, detail in self.results:
                f.write("%-4s %s %s\n" % ("ok" if good else "FAIL", name, detail))
        passed = bool(self.results) and all(good for _, good, _ in self.results)
        print("%s - %s" % ("PASS" if passed else "FAIL", os.path.join(self.out, "summary.txt")), flush=True)
        return passed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "ragdoll", time.strftime("world-%Y%m%d-%H%M%S")))
    ap.add_argument("--port", type=int, default=rig.gamectl.DEFAULT_PORT)
    a = ap.parse_args()
    sys.exit(0 if Check(a.out, a.port).run() else 1)


if __name__ == "__main__":
    main()
