#!/usr/bin/env python3
"""Dismemberment check (Jolt: `VCS-mods plugins/JoltPhysics/src/jolt.cpp` sever / stumped / bleed; docs/game-internals.md 12p): a blast takes
limbs (or a head) off a body, the stump is drawn collapsed and bleeds the game's own blood; with the setting off nothing
is taken off.

    VCS_EXE=<a copy of vcs.exe> python tools/gore_check.py [OUT] [--port 47740]

Loads the Fort Baxter rig save (a copy, hidden) at (-700, -500), noon, with VCS_JOLT=1 and VCS_JOLT_GORE=1: a ped 1.5 m
from a grenade-sized ADD_EXPLOSION (opcode 0x013C, type 0) - it dies, and its ragdoll loses parts by the blast's
chance (0.6 x nearness a limb, half that the head, 2 at most); then a second blast 1 m from the body. Checked: parts
taken off (the counter, the log lines naming the bones), those bones drawn collapsed (their rows 0) in the ped's anim
tree, blood drops spawned (AddParticle through ApplyMoveSpeed's tail call) and still coming a second later. A second
game with VCS_JOLT_GORE=0 and the same blast: nothing taken off. Screenshots of the body. Results: OUT/summary.txt,
OUT/*.png. Default OUT: build/gore/<date-time>.
"""
import argparse
import math
import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = rig.Scm
ADD_EXPLOSION = 0x013C
SPOT = (-700.0, -500.0)


class Check:
    def __init__(self, out, port):
        self.out = os.path.abspath(out)
        self.port = port
        self.results = []

    def ok(self, name, cond, detail=""):
        self.results.append((name, bool(cond), detail))
        print("%-4s %s %s" % ("ok" if cond else "FAIL", name, detail), flush=True)
        return cond

    def game(self, gore, name):
        g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name=name, seconds=300,
                           env={"VCS_JOLT": "1", "VCS_JOLT_GORE": "1" if gore else "0"}, port=self.port)
        g.wait_ingame()
        g.prime()
        g.set_time(12)
        g.teleport(SPOT[0], SPOT[1], -100.0)
        time.sleep(3.0)
        return g

    @staticmethod
    def jolt(g):
        return dict(kv.split("=", 1) for kv in g.cmd("jolt").split() if "=" in kv)

    def blast_victim(self, g):
        """A ped 9 m ahead of Vic and a blast 1.5 m from it: (the ped, the blast's place)."""
        me, (x, y, z), _ = g.player()
        fx, fy = g.peekf(me + 0x10, 2)
        h = math.hypot(fx, fy) or 1.0
        fx, fy = fx / h, fy / h
        px, py = x + fx * 9.0, y + fy * 9.0
        g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.LOAD_ALL_MODELS_NOW) +
              S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(px), S.f(py), S.f(-100.0), S.LOCAL0))
        time.sleep(1.0)
        pool = g.u32(0x487A94)
        base, flags, size = g.u32(pool), g.u32(pool + 4), g.u32(pool + 8)
        used = g.peek(flags, size)
        peds = [base + i * 0xD20 for i in range(size) if not used[i] & 0x80 and base + i * 0xD20 != me]
        ped = min(peds, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (px, py)))
        pz = g.peekf(ped + 0x30, 3)[2]
        return ped, (px - fy * 1.5, py + fx * 1.5, pz - 0.6)

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        g = self.game(True, "gore_check")
        try:
            ped, at = self.blast_victim(g)
            st0 = self.jolt(g)
            g.scm(S.op(ADD_EXPLOSION, S.f(at[0]), S.f(at[1]), S.f(at[2]), S.i(0)))
            time.sleep(2.5)
            st1 = self.jolt(g)
            body = g.peekf(ped + 0x30, 3)
            g.scm(S.op(ADD_EXPLOSION, S.f(body[0] + 1.0), S.f(body[1]), S.f(body[2] - 0.8), S.i(0)))
            time.sleep(0.6)
            g.cmd("screenshot " + os.path.join(self.out, "blast.png"))
            time.sleep(1.4)
            st2 = self.jolt(g)
            tree = int(st2["tree"], 16) if int(st2["ped"], 16) == ped else 0
            matrices = g.u32(tree + 0x28) if tree else 0
            bones = [g.peekf(matrices + i * 0x40, 12) for i in range(25)] if matrices else []
            time.sleep(1.0)
            st3 = self.jolt(g)
            g.cmd("screenshot " + os.path.join(self.out, "body.png"))
        finally:
            g.quit()
        log = open(os.path.join(ROOT, "build", "run", "gore_check.log"), encoding="utf-8", errors="replace").read()
        taken = [int(b) for b in re.findall(r"\[jolt\] ped %08X: \w+ \(bone (\d+)\) taken off" % ped, log)]
        self.ok("the blasts take parts off the body", int(st2["severed"]) > int(st0["severed"]) and taken,
                "%s -> %s; bones %s" % (st0["severed"], st2["severed"], taken))
        kids = {5: [5, 6], 8: [8, 9, 10, 11], 9: [9, 10, 11], 13: [13, 14, 15, 16], 14: [14, 15, 16], 17: [17, 18, 19, 20],
                18: [18, 19, 20], 21: [21, 22, 23, 24], 22: [22, 23, 24]}
        collapsed = [i for r in taken for i in kids.get(r, []) if bones and max(abs(v) for v in bones[i]) < 1e-6]
        expected = sorted({i for r in taken for i in kids.get(r, [])})
        self.ok("their bones are drawn collapsed into the stump", bones and expected and set(expected) <= set(collapsed),
                "collapsed %s of %s" % (sorted(set(collapsed)), expected))
        self.ok("the stumps bleed (the game's blood particles)", int(st2["blood"]) > int(st0["blood"]),
                "drops %s -> %s" % (st0["blood"], st2["blood"]))
        self.ok("and go on bleeding", int(st3["blood"]) > int(st2["blood"]), "drops %s -> %s a second later" % (st2["blood"], st3["blood"]))
        g = self.game(False, "gore_off")
        try:
            ped, at = self.blast_victim(g)
            st0 = self.jolt(g)
            g.scm(S.op(ADD_EXPLOSION, S.f(at[0]), S.f(at[1]), S.f(at[2]), S.i(0)))
            time.sleep(2.5)
            st1 = self.jolt(g)
        finally:
            g.quit()
        self.ok("with Dismemberment off nothing is taken off", int(st1["severed"]) == 0 and int(st1["created"]) > int(st0["created"]),
                "severed %s, ragdolls %s -> %s" % (st1["severed"], st0["created"], st1["created"]))
        with open(os.path.join(self.out, "summary.txt"), "w") as f:
            for name, good, detail in self.results:
                f.write("%-4s %s %s\n" % ("ok" if good else "FAIL", name, detail))
        passed = all(good for _, good, _ in self.results)
        print("%s - %s" % ("PASS" if passed else "FAIL", os.path.join(self.out, "summary.txt")), flush=True)
        return passed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "gore", time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--port", type=int, default=47740)
    a = ap.parse_args()
    sys.exit(0 if Check(a.out, a.port).run() else 1)


if __name__ == "__main__":
    main()
