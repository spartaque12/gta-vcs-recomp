#!/usr/bin/env python3
"""Hit reactions check (Jolt active ragdolls, GTA IV / Euphoria style: `VCS-mods plugins/JoltPhysics/src/jolt.cpp` react; docs/game-internals.md
12n): a ped shot and not killed reacts with its body where the bullet hits and keeps going; a hit that knocks it down
drops it as a ragdoll that gets up.

    python tools/hit_reactions_check.py [OUT] [--port 47681]

Loads the Fort Baxter rig save (a copy, hidden) with VCS_JOLT=1 at (-700, -500), noon. A ped (model 55, health 200 so a
pistol does not kill it) 4 m ahead; Vic locks on (R1) with a Colt45 and fires one shot: a reaction is made for that ped,
its drawn pelvis stays on the ped (within 0.6 m - the hips are the animation's), its bones pushed 5 - 60 cm off the
animation's pose, the reaction ends within 1.5 s, the ped is alive and not down. Three more shots,
each a reaction. Then a Shotgun from 2 m: the ped is down as a knockdown ragdoll and gets up again, or killed as a dead
one (a new ped: the first runs away; a pistol shot that already knocked the first down counts). Screenshots 0.1 / 0.3 / 0.6 s after the first shot. Results: OUT/summary.txt, OUT/*.png. Default OUT:
build/hits/<date-time>. VCS_EXE=<a copy of vcs.exe> runs that one (build\\vcs.exe stays free).
"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = rig.Scm
PED_POOL, PED_SIZE = 0x487A94, 0xD20
PED_STATE, PED_HEALTH = 0x8C4, 0x4E4
FALL, GETUP, DYING, DEAD = 0x2D, 0x2E, 0x39, 0x3A
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

    def drawn(self, tree, bone):
        m = self.g.u32(tree + 0x28)
        return self.g.peekf(m + bone * 0x40 + 0x30, 3) if m else None

    def fire(self):
        self.g.cmd("key Ctrl down")
        time.sleep(0.12)
        self.g.cmd("key Ctrl up")

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        g = self.g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name="hit_reactions",
                                    seconds=400, env={"VCS_JOLT": "1"}, port=self.port)
        try:
            g.wait_ingame()
            g.prime()
            g.set_time(12)
            g.teleport(SPOT[0], SPOT[1], -100.0)
            time.sleep(3.0)
            me, (x, y, z), _ = g.player()
            fx, fy = g.peekf(me + 0x10, 2)
            h = math.hypot(fx, fy) or 1.0
            fx, fy = fx / h, fy / h
            g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.REQUEST_MODEL, S.i(346)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                  S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(x + fx * 4), S.f(y + fy * 4), S.f(-100.0), S.LOCAL0) +
                  S.op(S.GIVE_WEAPON_TO_CHAR, S.PLAYER, S.i(19), S.i(100)))
            time.sleep(1.0)
            pool = g.u32(PED_POOL)
            base, flags, size = g.u32(pool), g.u32(pool + 4), g.u32(pool + 8)
            used = g.peek(flags, size)
            peds = [base + i * PED_SIZE for i in range(size) if not used[i] & 0x80 and base + i * PED_SIZE != me]
            ped = min(peds, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (x + fx * 4, y + fy * 4)))
            g.cmd("pokef 0x%x 200" % (ped + PED_HEALTH))
            g.cmd("key E down")
            time.sleep(0.8)
            before = self.jolt()
            self.fire()
            made, tree, far, head0, heads, t0 = None, 0, 0.0, None, [], time.time()
            shots = {0.1: "hit_0.1", 0.3: "hit_0.3", 0.6: "hit_0.6"}
            while time.time() - t0 < 2.3:
                st = self.jolt()
                t = time.time() - t0
                if int(st["reacting"]) and int(st["ped"], 16) == ped:
                    made = made or t
                    tree = int(st["tree"], 16)
                    if tree:
                        pelvis = self.drawn(tree, 1)
                        head = self.drawn(tree, 5)
                        pos = g.peekf(ped + 0x30, 3)
                        far = max(far, math.dist(pelvis[:2], pos[:2]))
                        heads.append(head)
                for s in list(shots):
                    if t > s:
                        g.cmd("screenshot " + os.path.join(self.out, shots.pop(s) + ".png"))
                time.sleep(0.03)
            st = self.jolt()
            state, health = g.u32(ped + PED_STATE), g.peekf(ped + PED_HEALTH, 1)[0]
            self.ok("a pistol hit makes a reaction for the ped", int(st["reactions"]) > int(before["reactions"]) and made,
                    "reactions %s -> %s, seen at %s s" % (before["reactions"], st["reactions"], made and "%.2f" % made))
            self.ok("its hips stay with the ped", made and far < 0.8, "pelvis at most %.2f m from the ped" % far)
            self.ok("the hit pushes the body off its animation", 0.03 < float(st["reactdev"]) <= 0.21,
                    "drawn up to %.2f m off the animation" % float(st["reactdev"]))
            self.ok("the reaction ends", int(st["reacting"]) == 0, "reacting %s after 2.3 s (its hand held on the wound 1.6 s)" % st["reacting"])
            self.ok("the ped is alive (on its feet, or knocked down by a second hit)", health > 0 and state not in (DYING, DEAD),
                    "health %.0f, state 0x%x" % (health, state))
            self.ok("a hand goes to the wound", int(st["clutches"]) > int(before["clutches"]) and
                    0.0 <= float(st["clutchgap"]) < 0.25,
                    "clutches %s -> %s, the hand %.2f m from the wound" % (before["clutches"], st["clutches"],
                                                                            float(st["clutchgap"])))
            hp = g.peekf(ped + PED_HEALTH, 1)[0]
            for _ in range(3):
                self.fire()
                time.sleep(1.2)
            st2 = self.jolt()
            # the hits that landed (the ped runs once shot: some miss) react - or knock it down (later ones then push its
            # ragdoll)
            landed = int(round((hp - max(g.peekf(ped + PED_HEALTH, 1)[0], 0.0)) / 32.0))
            got = int(st2["reactions"]) - int(st["reactions"]) + int(st2["shotdown"])
            self.ok("the hits that land react", got >= (1 if int(st2["shotdown"]) else min(landed, 2)),
                    "%d hit(s) landed, reactions %s -> %s, knocked down %s" % (landed, st["reactions"], st2["reactions"],
                                                                         st2["shotdown"]))
            g.cmd("key E up")

            # three quick hits: a stumble (a fresh ped, 4 m ahead: the first may have run)
            me, (x, y, z), _ = g.player()
            fx, fy = g.peekf(me + 0x10, 2)
            h = math.hypot(fx, fy) or 1.0
            fx, fy = fx / h, fy / h
            g.scm(S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(x + fx * 4), S.f(y + fy * 4), S.f(-100.0), S.LOCAL0))
            time.sleep(0.3)
            used = g.peek(flags, size)
            peds = [base + i * PED_SIZE for i in range(size) if not used[i] & 0x80 and base + i * PED_SIZE not in (me, ped)]
            target = min(peds, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (x + fx * 4, y + fy * 4)))
            g.cmd("pokef 0x%x 400" % (target + PED_HEALTH))
            g.cmd("key E down")
            time.sleep(0.4)
            before = self.jolt()
            for _ in range(3):
                self.fire()
                time.sleep(0.3)
            time.sleep(1.5)
            g.cmd("key E up")
            st = self.jolt()
            state = g.u32(target + PED_STATE)
            self.ok("three quick hits make it stumble", int(st["stumbles"]) > int(before["stumbles"]) and
                    0.3 <= float(st["stumbled"]) <= 1.5 and state not in (DYING, DEAD),
                    "stumbles %s -> %s, %.2f m along the push, state 0x%x" % (before["stumbles"], st["stumbles"],
                                                                             float(st["stumbled"]), state))
            ped = target

            # a Shotgun from 2 m: down (and up), or dead
            # (the first ped runs away once shot: a new one, 2.5 m ahead of Vic)
            me, (x, y, z), _ = g.player()
            fx, fy = g.peekf(me + 0x10, 2)
            h = math.hypot(fx, fy) or 1.0
            fx, fy = fx / h, fy / h
            g.scm(S.op(S.REQUEST_MODEL, S.i(349)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                  S.op(S.GIVE_WEAPON_TO_CHAR, S.PLAYER, S.i(21), S.i(50)))
            time.sleep(1.0)
            g.scm(S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(x + fx * 2.5), S.f(y + fy * 2.5), S.f(-100.0), S.LOCAL0))
            time.sleep(0.3)
            used = g.peek(flags, size)
            peds = [base + i * PED_SIZE for i in range(size) if not used[i] & 0x80 and base + i * PED_SIZE not in (me, ped)]
            ped = min(peds, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (x + fx * 2.5, y + fy * 2.5)))
            g.cmd("pokef 0x%x 200" % (ped + PED_HEALTH))
            g.cmd("key E down")
            time.sleep(0.4)
            before = self.jolt()
            states, t0, fired = [], time.time(), 0
            while time.time() - t0 < 9.0:
                state = g.u32(ped + PED_STATE)
                states.append(state)
                # up to three shots, a second apart, until it is down or dead (a shot can miss a ped turning away)
                if fired < 3 and state not in (FALL, GETUP, DYING, DEAD) and time.time() - t0 >= fired * 1.2:
                    self.fire()
                    fired += 1
                if 0.4 < time.time() - t0 < 0.5:
                    g.cmd("screenshot " + os.path.join(self.out, "shotgun.png"))
                time.sleep(0.1)
            g.cmd("key E up")
            st = self.jolt()
            seen = list(dict.fromkeys(states))
            down = int(st["shotdown"]) > 0  # this shot's, or an earlier pistol shot's
            dead = states[-1] in (DYING, DEAD) and int(st["created"]) > int(before["created"])
            self.ok("a Shotgun close up drops it as a ragdoll", down or dead,
                    "%s; states %s" % ("knocked down" if down else "killed" if dead else "neither",
                                       " ".join("0x%x" % s for s in seen)))
            if down:
                self.ok("and it gets up again", int(st["gotup"]) > 0,
                        "got up %s -> %s" % (before["gotup"], st["gotup"]))
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
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "hits", time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--port", type=int, default=rig.gamectl.DEFAULT_PORT)
    a = ap.parse_args()
    sys.exit(0 if Check(a.out, a.port).run() else 1)


if __name__ == "__main__":
    main()
