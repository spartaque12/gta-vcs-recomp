#!/usr/bin/env python3
"""Foot IK check (`VCS-mods plugins/JoltPhysics/src/footik.cpp`; docs/game-internals.md 12q): on a slope or a step the feet stand on the ground
under them.

    python tools/footik_check.py [OUT] [--port 47750]

Loads the Fort Baxter rig save (a copy, hidden) at noon and looks, in the buildings' col triangles around a few spots
(read from the game as tools/ragdoll_world_check.py does), for a place where the ground under a standing ped's two
feet (0.13 m either side of it) differs by 8 - 35 cm. Vic is put there across the slope, Foot IK switched on
(`setting physics.footik 1`): both feet find their ground, each foot's sole as drawn within 5 cm of the ground under
it (the animation's own soles are off by more on one side), the hips lowered no more than 0.45 m; a ped spawned
near is adjusted too; the cost per frame. Then switched off: no pose is adjusted any more. Results: OUT/summary.txt,
OUT/*.png. Default OUT: build/footik/<date-time>. VCS_EXE=<a copy of vcs.exe> runs that one (build\\vcs.exe stays free).
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
MODEL_INFOS, SECTORS = 0x486518, 0x486464
LISTS = (0x00, 0x04, 0x14, 0x18)
SPOTS = ((-893.0, -712.0), (-700.0, -500.0), (-650.0, -440.0), (-760.0, -560.0), (-620.0, -470.0))
FEET = 0.13


class Check:
    def __init__(self, out, port):
        self.out = os.path.abspath(out)
        self.port = port
        self.results = []
        self.g = None
        self.triangles = []

    def ok(self, name, cond, detail=""):
        self.results.append((name, bool(cond), detail))
        print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail), flush=True)
        return cond

    def status(self):
        return dict(kv.split("=", 1) for kv in self.g.cmd("footik").split() if "=" in kv)

    def big(self, addr, n):
        return b"".join(self.g.peek(addr + o, min(4096, n - o)) for o in range(0, n, 4096))

    def load_triangles(self, cx, cy, reach):
        g = self.g
        table, sectors = g.u32(MODEL_INFOS), g.u32(SECTORS)
        entities = []
        for sy in range(int((cy - reach) / 80 + 25), int((cy + reach) / 80 + 25) + 1):
            for sx in range(int((cx - reach) / 80 + 30), int((cx + reach) / 80 + 30) + 1):
                heads = struct.unpack("<14I", g.peek(sectors + (sy * 50 + sx) * 0x38, 0x38))
                for off in LISTS:
                    node = heads[off // 4]
                    while node:
                        item, _, node = struct.unpack("<3I", g.peek(node, 12))
                        entities.append(item)
        tris = []
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
            vertices, tri_p = struct.unpack_from("<2I", head, 0x48)
            if not count or not vertices or not tri_p:
                continue
            traw = self.big(tri_p, count * 8)
            offsets = [struct.unpack_from("<3H", traw, i * 8) for i in range(count)]
            vraw = self.big(vertices, max(max(o) for o in offsets) + 6)
            for o in offsets:
                c = []
                for k in o:
                    v = [q / 128.0 for q in struct.unpack_from("<3h", vraw, k)]
                    c.append(tuple(m[12 + j] + m[j] * v[0] + m[4 + j] * v[1] + m[8 + j] * v[2] for j in range(3)))
                tris.append(c)
        self.triangles = tris

    def top(self, x, y, below=1e9):
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
            if z < below and (best is None or z > best):
                best = z
        return best

    def find_slope(self, cx, cy):
        """A place and heading where the feet's grounds differ by 8 - 35 cm, the middle between them."""
        for r in range(0, 24):
            for a in range(0, 360, 30 if r else 360):
                x, y = cx + r * 0.5 * math.cos(math.radians(a)), cy + r * 0.5 * math.sin(math.radians(a))
                zc = self.top(x, y)
                if zc is None:
                    continue
                for h in range(0, 180, 30):
                    rx, ry = math.cos(math.radians(h)), math.sin(math.radians(h))
                    zl = self.top(x - rx * FEET, y - ry * FEET, zc + 0.5)
                    zr = self.top(x + rx * FEET, y + ry * FEET, zc + 0.5)
                    if zl is None or zr is None:
                        continue
                    if 0.08 <= abs(zl - zr) <= 0.35 and min(zl, zr) - 0.05 <= zc <= max(zl, zr) + 0.05:
                        return x, y, h, zl, zr
        return None

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        g = self.g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name="footik_check",
                                    seconds=400, port=self.port)
        try:
            g.wait_ingame()
            g.prime()
            g.set_time(12)
            found = None
            for cx, cy in SPOTS:
                g.teleport(cx, cy, -100.0)
                time.sleep(2.5)
                self.load_triangles(cx, cy, 14.0)
                found = self.find_slope(cx, cy)
                print("spot (%.0f, %.0f): %d triangles, %s" % (cx, cy, len(self.triangles), found), flush=True)
                if found:
                    break
            if not self.ok("a slope or step under the feet", found, "%s" % (found,)):
                return self.finish()
            x, y, h, zl, zr = found
            g.teleport(x, y, -100.0, heading=float(h))
            time.sleep(2.5)
            g.cmd("setting physics.footik 1")
            time.sleep(1.5)
            st = self.status()
            print(st, flush=True)
            g.cmd("screenshot " + os.path.join(self.out, "slope.png"))
            ground = [float(v) for v in st["ground"].split(",")]
            sole = [float(v) for v in st["sole"].split(",")]
            anim = [float(v) for v in st["animsole"].split(",")]
            both = st["found"] == "1,1" and st["vic"] == "1"
            self.ok("Vic's feet find their ground", both, "found %s, ground %s (the triangles: %.2f / %.2f)" % (
                st["found"], st["ground"], zl, zr))
            if both:
                errs = [abs(sole[k] - ground[k]) for k in range(2)]
                before = [abs(anim[k] - ground[k]) for k in range(2)]
                self.ok("each sole on its ground", max(errs) < 0.05,
                        "sole - ground %.3f / %.3f m (the animation's %.3f / %.3f)" % (errs[0], errs[1], before[0], before[1]))
                self.ok("the slope mattered", max(before) > 0.04, "the animation's soles off by up to %.3f m" % max(before))
                self.ok("the hips lowered within 0.45 m", -0.45 <= float(st["pelvis"]) <= 0.0, "pelvis %s" % st["pelvis"])
            # a ped near: adjusted too
            me = g.player()[0]
            g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                  S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(x + 2.5), S.f(y + 1.0), S.f(-100.0), S.LOCAL0))
            time.sleep(2.0)
            st = self.status()
            self.ok("a ped near is adjusted too", int(st["peds"]) >= 2, "%s poses adjusted in a frame" % st["peds"])
            self.ok("it is cheap", float(st["ms"]) < 1.0, "%s ms a frame" % st["ms"])
            g.cmd("setting physics.footik 0")
            time.sleep(0.5)
            a0 = int(self.status()["adjusted"])
            time.sleep(1.0)
            a1 = int(self.status()["adjusted"])
            self.ok("off: no pose adjusted", a1 == a0 and self.status()["enabled"] == "0", "adjusted %d -> %d" % (a0, a1))
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
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "footik", time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--port", type=int, default=47750)
    a = ap.parse_args()
    sys.exit(0 if Check(a.out, a.port).run() else 1)


if __name__ == "__main__":
    main()
