#!/usr/bin/env python3
"""Death ragdolls check (`VCS-mods plugins/JoltPhysics/src/jolt.cpp`, `VCS-mods plugins/JoltPhysics/src/physics/ragdoll.cpp`; docs/game-internals.md 12h): a ped is spawned
in front of Vic and killed, and its ragdoll is followed as it falls and settles.

    python tools/ragdoll_check.py [OUT] [--port 47673]

Loads the Fort Baxter rig save (a copy, hidden) with VCS_JOLT=1, goes to open flat ground at noon, spawns a ped 4 m
ahead and sets its health (+0x4E4) to 0 - the game's own CPed::ProcessControl then calls SetDie. Ten times a second
for 6 s it logs the ped's pelvis bone as written into its anim tree (the matrix the skinned draw uses) next to the
physics' own (the control channel's "jolt"), and checks: the ragdoll was made for that ped, the pelvis fell from
about standing height to the ground and stays above it, it ended lying (the spine not upright), settled (still, its
bodies asleep), the drawn bones are the physics' pose, the ped's position followed the body. A shotgun kill at 4 m
(R1, Circle) throws the body back 1 - 5 m. Then Vic is killed the same way: his ragdoll, then the game's respawn - the
ragdoll goes and he is where the game put him (its teleport is not pulled back to the body). Last, Vic drives a
Sentinel into a ped at full throttle: the body folds onto the bonnet and is not left inside the car. And the game is
still running. A second game (first person and free aim on, to aim at a body on the ground): Colt45 shots at a lying
body hit its ragdoll, a Shotgun blast shoves it, a grenade-sized ADD_EXPLOSION throws a body lying in its reach and the
ped it kills. Screenshots of the body falling, on the ground, the shotgun's victim in the air, the car's on the
bonnet, a shotgunned corpse, the blast. Results: OUT/summary.txt, OUT/pelvis.csv, OUT/*.png. Default OUT:
build/ragdoll/<date-time>. VCS_EXE=<a copy of vcs.exe> runs that one (build\vcs.exe stays free).
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
PED_STATE, PED_HEALTH = 0x8C4, 0x4E4
DYING, DEAD = 0x39, 0x3A
SPOT = (-700.0, -500.0)  # open flat ground (tools/ragdoll_check.py and the free aim probes)
WARP_CHAR_FROM_CAR_TO_COORD = 0x0216  # char, x, y, z (the trainer's)


class Check:
    def __init__(self, out, port):
        self.out = os.path.abspath(out)  # the game saves screenshots from its own folder
        self.port = port
        self.results = []
        self.g = None

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

    def jolt(self):
        st = dict(kv.split("=", 1) for kv in self.g.cmd("jolt").split() if "=" in kv)
        st["pelvis"] = [float(v) for v in st["pelvis"].split(",")]
        return st

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        g = self.g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name="ragdoll_check",
                                    seconds=600, env={"VCS_JOLT": "1"}, port=self.port)
        csv = open(os.path.join(self.out, "pelvis.csv"), "w")
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
            tx, ty = x + fx * 4.0 + fy * 1.8, y + fy * 4.0 - fx * 1.8  # ahead and to the right: not behind Vic
            before = set(self.peds())
            g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                  S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(tx), S.f(ty), S.f(-100.0), S.LOCAL0))
            time.sleep(1.5)
            new = [p for p in self.peds() if p not in before and p != me]
            if not self.ok("a ped was spawned", new, "%d new" % len(new)):
                return False
            ped = new[0]
            px, py, pz = g.peekf(ped + 0x30, 3)
            ground = pz - 1.0
            print("ped %08X at (%.2f, %.2f, %.2f), state 0x%x; the player at (%.2f, %.2f, %.2f)" % (
                ped, px, py, pz, g.u32(ped + PED_STATE), x, y, z), flush=True)
            g.cmd("pokef 0x%x 0" % (ped + PED_HEALTH))
            csv.write("t,state,dolls,awake,pelvis_x,pelvis_y,pelvis_z,spine_x,spine_y,spine_z,drawn_z,ped_x,ped_y,"
                      "bodies,active,stepms\n")
            rows, start, falling = [], time.time(), False
            while time.time() - start < 6.0:
                if not falling and time.time() - start > 0.6:
                    g.cmd("screenshot " + os.path.join(self.out, "falling.png"))
                    falling = True
                st = self.jolt()
                state = g.u32(ped + PED_STATE)
                drawn = None
                if int(st["tree"], 16):
                    matrices = g.u32(int(st["tree"], 16) + 0x28)
                    drawn = g.peekf(matrices + 0x40, 16) if matrices else None
                ped_xy = g.peekf(ped + 0x30, 2)
                p = st["pelvis"]
                row = (time.time() - start, state, int(st["dolls"]), int(st["awake"]), p[12], p[13], p[14], p[0], p[1],
                       p[2], drawn[14] if drawn else float("nan"), ped_xy[0], ped_xy[1], int(st["bodies"]),
                       int(st["active"]), float(st["stepms"]))
                rows.append((row, st, drawn))
                csv.write(",".join("%.4f" % v if isinstance(v, float) else str(v) for v in row) + "\n")
                time.sleep(0.1)
            g.cmd("screenshot " + os.path.join(self.out, "ragdoll.png"))
            st = self.jolt()
            shot = self.shotgun(me)
            car = self.run_down()  # before Vic's death: right after his respawn the game ignores the throttle a while
            g.scm(S.op(WARP_CHAR_FROM_CAR_TO_COORD, S.PLAYER, S.f(SPOT[0]), S.f(SPOT[1]), S.f(-100.0)))
            time.sleep(3.0)
            player = self.player_death(me)
            alive = g.alive()
        finally:
            csv.close()
            g.quit()
        later = self.corpse_and_blast()

        print("pelvis z (ground %.2f): %s" % (ground, " ".join("%.2f" % r[0][6] for r in rows[::5])), flush=True)
        made = [r for r in rows if int(r[1]["ped"], 16) == ped and r[0][2] > 0]
        self.ok("the ped died", rows[-1][0][1] in (DYING, DEAD), "state 0x%x" % rows[-1][0][1])
        if not self.ok("a ragdoll was made for it", made, "created=%s ped=%s" % (st["created"], st["ped"])):
            return self.finish()
        first, last = made[0][0], made[-1][0]
        self.ok("the pelvis fell", last[6] < first[6] - 0.4, "z %.2f -> %.2f" % (first[6], last[6]))
        lowest = min(r[0][6] for r in made)
        self.ok("it stayed above the ground", lowest > ground - 0.05, "lowest %.2f, ground %.2f" % (lowest, ground))
        self.ok("it ended lying", abs(last[9]) < 0.7, "spine axis z %.2f" % last[9])
        tail = [r[0] for r in made if r[0][0] > last[0] - 1.0]
        drift = max(math.dist(r[4:7], last[4:7]) for r in tail)
        self.ok("it settled", drift < 0.02 and not last[3], "moved %.3f m in its last second, awake %d" % (drift, last[3]))
        same = [r for r in made if r[2] and math.dist(r[2][12:15], r[1]["pelvis"][12:15]) < 0.01]
        self.ok("the drawn bones are the ragdoll's", len(same) >= len(made) // 2, "%d / %d samples" % (len(same), len(made)))
        self.ok("the ped's position follows the body", math.dist(last[11:13], last[4:6]) < 0.3,
                "ped (%.2f, %.2f), pelvis (%.2f, %.2f)" % (last[11], last[12], last[4], last[5]))
        self.ok("the step is cheap", max(r[0][15] for r in made) < 2.0, "max %.3f ms" % max(r[0][15] for r in made))
        made, away, moved = shot
        self.ok("a shotgun kill throws the body back", made and 1.0 < away < 5.0,
                "%.2f m away from Vic (%.2f m in all)" % (away, moved) if made else "no ragdoll for the shot ped")
        died_at, ragdolled, removed, respawn = player
        self.ok("Vic's death gets a ragdoll", ragdolled, "at (%.1f, %.1f)" % died_at[:2])
        self.ok("it goes when he respawns", removed)
        self.ok("he respawns where the game puts him", respawn and math.dist(respawn[:2], died_at[:2]) > 20.0,
                "at %s" % (respawn and "(%.1f, %.1f, %.1f)" % respawn))
        made, speed, rode, end = car
        self.ok("a car's kill folds the body onto the bonnet", made and rode >= 3,
                "hit at %.1f m/s, %d samples on the bonnet" % (speed, rode) if made else "no ragdoll for the ped run down")
        self.ok("and does not leave it inside the car", made and end and (end[0] > 2.4 or abs(end[1]) > 1.2 or end[2] > 0.3),
                "it ends %.2f m ahead of the car's middle, %.2f beside, %.2f over it" % end if end else "")
        self.ok("the game is still running", alive)
        pistol, pellets, shoved, thrown, moved, victim = later
        self.ok("pistol shots at a lying body hit its ragdoll", pistol >= 1, "%d of 3" % pistol)
        self.ok("a shotgun blast shoves it", pellets >= 1 and shoved > 0.05,
                "%d pellets on it, the pelvis %.2f m" % (pellets, shoved))
        self.ok("a blast throws a body lying in its reach", thrown >= 1 and moved > 0.5,
                "%d thrown, %.2f m" % (thrown, moved))
        self.ok("and the ped it kills is thrown by it", victim, victim or "no ragdoll for the ped beside the blast")
        return self.finish()

    def corpse_and_blast(self):
        """A second game, first person and free aim on (to aim at a body on the ground): a ped killed 3.5 m ahead, three
        Colt45 shots at its pelvis, then a Shotgun blast; then ADD_EXPLOSION (a grenade's: radius 9, power 300) 2 m from a
        body and 2 m from a living ped. (pistol shots on the ragdoll, shotgun pellets on it, how far that blast shoved
        its pelvis, ragdolls the explosion threw, metres it threw the body, the killed ped's ragdoll line or None)"""
        g = self.g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name="ragdoll_check2",
                                    seconds=600, env={"VCS_JOLT": "1", "VCS_FIRSTPERSON": "1", "VCS_FREEAIM": "1"},
                                    port=self.port)
        result, victim = [0, 0, 0.0, 0, 0.0, None], 0
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
            ped = self.spawn(x + fx * 3.5, y + fy * 3.5)
            g.cmd("pokef 0x%x 0" % (ped + PED_HEALTH))
            time.sleep(4.0)
            body = self.jolt()["pelvis"][12:15]
            g.scm(S.op(S.REQUEST_MODEL, S.i(346)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                  S.op(S.GIVE_WEAPON_TO_CHAR, S.PLAYER, S.i(19), S.i(100)))
            time.sleep(0.8)
            g.cmd("key E down")
            time.sleep(0.4)
            self.aim_at(me, body)
            hits = int(self.jolt()["corpsehits"])
            for _ in range(3):
                g.cmd("key Ctrl down")
                time.sleep(0.12)
                g.cmd("key Ctrl up")
                time.sleep(0.5)
            result[0] = int(self.jolt()["corpsehits"]) - hits
            g.cmd("key E up")
            g.scm(S.op(S.REQUEST_MODEL, S.i(349)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                  S.op(S.GIVE_WEAPON_TO_CHAR, S.PLAYER, S.i(21), S.i(100)))
            time.sleep(0.8)
            g.cmd("key E down")
            time.sleep(0.4)
            st = self.jolt()
            before, hits = st["pelvis"][12:15], int(st["corpsehits"])
            self.aim_at(me, before)
            g.cmd("key Ctrl down")
            time.sleep(0.12)
            g.cmd("key Ctrl up")
            time.sleep(0.2)
            g.cmd("screenshot " + os.path.join(self.out, "corpse_shotgun.png"))
            time.sleep(1.3)
            st = self.jolt()
            result[1], result[2] = int(st["corpsehits"]) - hits, math.dist(before, st["pelvis"][12:15])
            g.cmd("key E up")
            # ADD_EXPLOSION (x, y, z, type): its opcode from the handler table (the entry naming FUN_00182998)
            table = b"".join(g.peek(0x4BEAF0 + off, min(4096, 1381 * 8 - off)) for off in range(0, 1381 * 8, 4096))
            explode = next(i for i in range(1381) if struct.unpack_from("<I", table, i * 8 + 4)[0] == 0x182998)
            g.teleport(SPOT[0] + 50.0, SPOT[1], -100.0)
            time.sleep(3.0)
            me, (x, y, z), _ = g.player()
            cx, cy = x + fx * 8.0, y + fy * 8.0
            corpse = self.spawn(cx + 2.0, cy)
            g.cmd("pokef 0x%x 0" % (corpse + PED_HEALTH))
            time.sleep(3.5)
            lay = g.peekf(corpse + 0x30, 2)  # the ped follows its body
            victim = self.spawn(cx - 2.0, cy)
            gz = g.peekf(victim + 0x30, 3)[2] - 0.5
            before = int(self.jolt()["blasted"])
            g.scm(S.op(explode, S.f(cx), S.f(cy), S.f(gz), S.i(0)))
            time.sleep(0.35)
            g.cmd("screenshot " + os.path.join(self.out, "blast.png"))
            time.sleep(3.0)
            st = self.jolt()
            result[3], result[4] = int(st["blasted"]) - before, math.dist(lay, g.peekf(corpse + 0x30, 2))
        finally:
            g.quit()
        for line in open(os.path.join(ROOT, "build", "run", "ragdoll_check2.log"), encoding="utf-8", errors="replace"):
            if line.startswith("[jolt] ped %08X" % victim) and "blasts 1" in line:
                result[5] = line.split(":", 1)[1].strip()[:120]
        return result

    def aim_at(self, me, target):
        """First person's view turned onto `target` with the mouse (400 counts a radian; +dx turns right, +dy down)."""
        g = self.g
        for _ in range(2):
            fp = dict(kv.split("=", 1) for kv in g.cmd("firstperson").split() if "=" in kv)
            pos = g.peekf(me + 0x30, 3)
            eye = [pos[k] + float(v) for k, v in enumerate(fp["eye"].split(","))]
            yaw = math.atan2(target[1] - eye[1], target[0] - eye[0])
            pitch = math.atan2(target[2] - eye[2], math.dist(target[:2], eye[:2]))
            g.cmd("mouse %d %d" % (int(-math.remainder(yaw - float(fp["yaw"]), 2 * math.pi) * 400),
                                   int(-(pitch - float(fp["pitch"])) * 400)))
            time.sleep(0.4)

    def spawn(self, x, y):
        """A ped (model 55) at (x, y) on the ground: its address, 0 when none came."""
        g = self.g
        before = set(self.peds())
        g.scm(S.op(S.REQUEST_MODEL, S.i(55)) + S.op(S.LOAD_ALL_MODELS_NOW) +
              S.op(S.CREATE_CHAR, S.i(4), S.i(55), S.f(x), S.f(y), S.f(-100.0), S.LOCAL0))
        time.sleep(1.0)
        new = [p for p in self.peds() if p not in before]
        return min(new, key=lambda p: math.dist(g.peekf(p + 0x30, 2), (x, y))) if new else 0

    def shotgun(self, me):
        """A shotgun (type 21, model 349) fired at a ped 4 m ahead, locked on with R1: its ragdoll thrown back.
        (a ragdoll was made for it, metres the pelvis went away from Vic along the shot, metres in all)"""
        g = self.g
        _, (x, y, z), _ = g.player()
        g.scm(S.op(S.REQUEST_MODEL, S.i(349)) + S.op(S.LOAD_ALL_MODELS_NOW) +
              S.op(S.GIVE_WEAPON_TO_CHAR, S.PLAYER, S.i(21), S.i(100)))
        time.sleep(1.0)
        fx, fy = g.peekf(me + 0x10, 2)
        h = math.hypot(fx, fy) or 1.0
        fx, fy = fx / h, fy / h
        ped = self.spawn(x + fx * 4.0, y + fy * 4.0)
        if not ped:
            return False, 0.0, 0.0
        start = g.peekf(ped + 0x30, 2)
        g.cmd("key E down")
        time.sleep(0.6)
        g.cmd("key Ctrl down")
        time.sleep(0.15)
        g.cmd("key Ctrl up")
        made, last, t0 = None, None, time.time()
        while time.time() - t0 < 3.0:
            st = self.jolt()
            if int(st["ped"], 16) == ped:
                made = made or time.time()
                last = st["pelvis"][12:14]
                if made and 0.2 < time.time() - made < 0.3:
                    g.cmd("screenshot " + os.path.join(self.out, "shotgun.png"))
            time.sleep(0.05)
        g.cmd("key E up")
        if not made:
            return False, 0.0, 0.0
        return True, (last[0] - start[0]) * fx + (last[1] - start[1]) * fy, math.dist(last, start)

    def run_down(self):
        """Vic in a Sentinel (211) on the beach at (575, 175), a ped 18 m ahead: full throttle into it, a second more,
        then rolling to a stop, looking at the car's left side (L2). (a ragdoll was made for the ped, the car's speed
        then, how many samples the pelvis was over the car's middle and up at the bonnet, where it ends in the car's
        frame: ahead, beside, over)"""
        g = self.g
        g.teleport(575.0, 175.0, -100.0)
        time.sleep(3.0)
        g.spawn_car(211, ahead=0.0)
        time.sleep(2.0)
        me, at, _ = g.player()
        car = g.u32(me + 0x480)
        if not car:
            print("run down: Vic (%08X at %s, state 0x%x) is in no car" % (me, ["%.1f" % v for v in at],
                                                                          g.u32(me + PED_STATE)), flush=True)
            return False, 0.0, 0, None
        cx, cy, _ = g.peekf(car + 0x30, 3)
        fx, fy = g.peekf(car + 0x10, 2)
        h = math.hypot(fx, fy) or 1.0
        ped = self.spawn(cx + fx / h * 18.0, cy + fy / h * 18.0)
        if not ped:
            print("run down: no ped came at (%.1f, %.1f)" % (cx + fx / h * 18.0, cy + fy / h * 18.0), flush=True)
            return False, 0.0, 0, None
        g.cmd("key W down")
        speed, made, rode, end, t0 = 0.0, None, 0, None, time.time()
        while time.time() - t0 < 9.0:
            st = self.jolt()
            if int(st["ped"], 16) == ped:
                if not made:
                    made = time.time()
                    v = g.peekf(car + 0x140, 3)
                    speed = math.hypot(v[0], v[1]) * 50.0
                    g.cmd("key z down")
                elif time.time() - made > 1.0:
                    g.cmd("key W up")
                p = st["pelvis"][12:15]
                c = g.peekf(car + 0x30, 3)
                f, u = g.peekf(car + 0x10, 3), g.peekf(car + 0x20, 3)
                d = [p[k] - c[k] for k in range(3)]
                r = (f[1] * u[2] - f[2] * u[1], f[2] * u[0] - f[0] * u[2], f[0] * u[1] - f[1] * u[0])
                end = (sum(d[k] * f[k] for k in range(3)), sum(d[k] * r[k] for k in range(3)), sum(d[k] * u[k] for k in range(3)))
                rode += 0.5 < end[0] < 2.7 and abs(end[1]) < 1.0 and end[2] > 0.05
                if 0.5 < time.time() - made < 0.6:
                    g.cmd("screenshot " + os.path.join(self.out, "car.png"))
                if time.time() - made > 3.5:
                    break
            elif time.time() - t0 > 6.0:
                break
            time.sleep(0.05)
        g.cmd("key W up")
        g.cmd("key z up")
        v = g.peekf(car + 0x140, 3)
        print("run down: car %08X, ped %08X state 0x%x health %.0f, %.2f m from the car; car at %.1f m/s now, %s" % (
            car, ped, g.u32(ped + PED_STATE), g.peekf(ped + PED_HEALTH, 1)[0],
            math.dist(g.peekf(ped + 0x30, 2), g.peekf(car + 0x30, 2)), math.hypot(v[0], v[1]) * 50.0,
            "a ragdoll" if made else "no ragdoll"), flush=True)
        return bool(made), speed, rode, end

    def player_death(self, me):
        """Vic killed: his ragdoll, then the game's respawn (a teleport while dead: the ragdoll must let him go).
        (where he died, a ragdoll was made for him, it was removed, where he is once up again)"""
        g = self.g
        died_at = g.player()[1]
        created = int(self.jolt()["created"])
        g.cmd("pokef 0x%x 0" % (me + PED_HEALTH))
        ragdolled = removed = False
        respawn = None
        start = time.time()
        while time.time() - start < 40.0:
            st = self.jolt()
            ragdolled = ragdolled or (int(st["created"]) > created and int(st["ped"], 16) == me)
            state = g.u32(me + PED_STATE)
            if ragdolled and int(st["ped"], 16) != me:  # the newest ragdoll's ped: none once his is gone
                removed = True
            if ragdolled and state not in (DYING, DEAD) and time.time() - start > 2.0:
                time.sleep(3.0)  # up again: where the game put him, a little later
                respawn = g.player()[1]
                removed = removed or int(self.jolt()["ped"], 16) != me
                break
            time.sleep(0.25)
        return died_at, ragdolled, removed, respawn

    def finish(self):
        with open(os.path.join(self.out, "summary.txt"), "w") as f:
            for name, good, detail in self.results:
                f.write("%-4s %s %s\n" % ("ok" if good else "FAIL", name, detail))
        passed = all(good for _, good, _ in self.results)
        print("%s - %s" % ("PASS" if passed else "FAIL", os.path.join(self.out, "summary.txt")), flush=True)
        return passed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "ragdoll", time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--port", type=int, default=rig.gamectl.DEFAULT_PORT)
    a = ap.parse_args()
    sys.exit(0 if Check(a.out, a.port).run() else 1)


if __name__ == "__main__":
    main()
