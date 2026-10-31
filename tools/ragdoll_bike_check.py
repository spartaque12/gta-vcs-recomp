#!/usr/bin/env python3
"""Bike falls check (Jolt Physics: `VCS-mods plugins/JoltPhysics/src/jolt.cpp` knockOff / getUp; docs/game-internals.md 12l): riders thrown off
bikes tumble as ragdolls and get up where their bodies come to rest.

    python tools/ragdoll_bike_check.py [OUT] [--port 47677]

Loads the Fort Baxter rig save (a copy, hidden) with VCS_JOLT=1 on the street at (-635, -437.5), east of a building's
wall at x -666.6. Vic's crash: a PCJ-600 (212) facing the wall, full throttle - the game throws him off
(CBike::KnockOffRider), his knockdown ragdoll flies on with the bike's speed, lands, settles and he gets up (the
game's get-up: state 0x2E, then on his feet), alive, his body's pose drawn while he was down. A ped thrown off: a ped
on a PCJ-600 parked facing east, Vic in a Sentinel 20 m east driving into it head on - the same for the ped. A rider
shot dead: a ped on a parked PCJ-600, Vic 4 m away with a Shotgun locked on (R1) - its ragdoll is a dead one. Then the
game is still running. Screenshots of each fall, its body at rest and the ped standing again. Results:
OUT/summary.txt, OUT/*.png. Default OUT: build/ragdoll/bike-<date-time>. VCS_EXE=<a copy of vcs.exe> runs that one.
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
SET_CAR_HEADING = 0x00D1                  # car, degrees (the trainer's)
WARP_CHAR_FROM_CAR_TO_COORD = 0x0216      # char, x, y, z
PED_STATE, PED_HEALTH, PED_VEHICLE = 0x8C4, 0x4E4, 0x480
FALL, GETUP, DYING, DEAD, DRIVING = 0x2D, 0x2E, 0x39, 0x3A, 0x37
VEHICLE_POOL, VEHICLE_SIZE, VEHICLE_DRIVER = 0x487A98, 0x8C0, 0x384
PCJ600, SENTINEL, PED_MODEL, SHOTGUN, SHOTGUN_MODEL = 212, 211, 55, 21, 349
WALL_X, LANE_Y = -666.6, -437.5


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

    def jolt(self):
        st = dict(kv.split("=", 1) for kv in self.g.cmd("jolt").split() if "=" in kv)
        st["pelvis"] = [float(v) for v in st["pelvis"].split(",")]
        return st

    def bike_with_rider(self, x, y, heading):
        """A PCJ-600 at (x, y) facing `heading` (degrees) with a ped on it, held still: (bike, rider)."""
        g = self.g
        g.scm(S.op(S.REQUEST_MODEL, S.i(PCJ600)) + S.op(S.REQUEST_MODEL, S.i(PED_MODEL)) + S.op(S.LOAD_ALL_MODELS_NOW) +
              S.op(S.CREATE_CAR, S.i(PCJ600), S.f(x), S.f(y), S.f(-100.0), S.LOCAL0) +
              S.op(SET_CAR_HEADING, S.LOCAL0, S.f(heading)) +
              S.op(S.CREATE_CHAR_INSIDE_CAR, S.LOCAL0, S.i(4), S.i(PED_MODEL), b"\x0e") +
              S.op(S.SET_CAR_CRUISE_SPEED, S.LOCAL0, S.f(0.0)))
        time.sleep(1.5)
        pool = g.u32(VEHICLE_POOL)
        base, flags, size = g.u32(pool), g.u32(pool + 4), g.u32(pool + 8)
        used = g.peek(flags, size)
        bikes = [base + i * VEHICLE_SIZE for i in range(size) if not used[i] & 0x80 and
                 struct.unpack("<h", g.peek(base + i * VEHICLE_SIZE + 0x56, 2))[0] == PCJ600 and
                 g.u32(base + i * VEHICLE_SIZE + VEHICLE_DRIVER)]
        bikes.sort(key=lambda b: math.dist(g.peekf(b + 0x30, 2), (x, y)))
        return (bikes[0], g.u32(bikes[0] + VEHICLE_DRIVER)) if bikes else (0, 0)

    def down(self, ped, name, seconds=9.0):
        """A rider just thrown off: its knockdown ragdoll followed until it is up again. (made - the ragdoll's ped,
        a knockdown -, where its pelvis went from and to, the drawn pelvis matched the ragdoll's, it was released
        (gotup), the states seen after, seconds down)"""
        g = self.g
        st0 = self.jolt()
        made, start, end, drawn, released, states, t_up = False, None, None, 0, False, [], None
        shot_rest = False
        t0 = time.time()
        while time.time() - t0 < seconds:
            st = self.jolt()
            state = g.u32(ped + PED_STATE)
            if int(st["ped"], 16) == ped and int(st["dolls"]) > 0 and not released:
                if not made:
                    made = int(st["down"]) == 1
                    start = st["pelvis"][12:15]
                end = st["pelvis"][12:15]
                tree = int(st["tree"], 16)
                if tree:
                    matrices = g.u32(tree + 0x28)
                    pelvis = g.peekf(matrices + 0x40, 16) if matrices else None
                    drawn += bool(pelvis) and math.dist(pelvis[12:15], end) < 0.15  # (a frame apart while it flies)
                if int(st["awake"]) == 0 and not shot_rest:
                    g.cmd("screenshot " + os.path.join(self.out, name + "_rest.png"))
                    shot_rest = True
            if int(st["gotup"]) > int(st0["gotup"]) and not released:
                released, t_up = True, time.time() - t0
                time.sleep(0.15)
                g.cmd("screenshot " + os.path.join(self.out, name + "_getup.png"))
            if released:
                states.append(state)
                if state not in (FALL, GETUP) and len(states) > 3:
                    break
            if 0.3 < time.time() - t0 < 0.42:
                g.cmd("screenshot " + os.path.join(self.out, name + "_air.png"))
            time.sleep(0.08)
        g.cmd("screenshot " + os.path.join(self.out, name + "_up.png"))
        return made, start, end, drawn, released, states, t_up

    def report(self, who, result, ped):
        g = self.g
        made, start, end, drawn, released, states, t_up = result
        self.ok("%s: a knockdown ragdoll" % who, made)
        if not made:
            return
        self.ok("%s: the body flies on" % who, math.dist(start[:2], end[:2]) > 1.0,  # sampled from its first poll, already in flight
                "pelvis from (%.2f, %.2f, %.2f) to (%.2f, %.2f, %.2f)" % (tuple(start) + tuple(end)))
        self.ok("%s: its drawn pose is the ragdoll's" % who, drawn >= 5, "%d samples" % drawn)
        self.ok("%s: it gets up once still" % who, released and states and states[-1] not in (FALL, GETUP, DYING, DEAD),
                "released after %s s, states then %s" % (t_up and "%.1f" % t_up,
                                                         " ".join("0x%x" % s for s in dict.fromkeys(states))))
        self.ok("%s: alive" % who, g.peekf(ped + PED_HEALTH, 1)[0] > 0.0, "health %.0f" % g.peekf(ped + PED_HEALTH, 1)[0])

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        g = self.g = rig.Game.start(save=os.path.join(ROOT, "build", "rig", "saves", "user"), name="ragdoll_bike",
                                    seconds=600, env={"VCS_JOLT": "1"}, port=self.port)
        try:
            g.wait_ingame()
            g.prime()
            g.set_time(12)
            # Vic's crash: a PCJ-600 at full throttle into the wall 30 m west
            g.teleport(-635.0, LANE_Y, -100.0, heading=90.0)
            time.sleep(3.0)
            me, (x, y, z), _ = g.player()
            g.scm(S.op(S.REQUEST_MODEL, S.i(PCJ600)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                  S.op(S.CREATE_CAR, S.i(PCJ600), S.f(x), S.f(y), S.f(-100.0), S.LOCAL0) +
                  S.op(SET_CAR_HEADING, S.LOCAL0, S.f(90.0)) + S.op(S.WARP_CHAR_INTO_CAR, S.PLAYER, S.LOCAL0))
            time.sleep(2.0)
            if self.ok("Vic rides a PCJ-600", g.u32(me + PED_VEHICLE), "vehicle %08X" % g.u32(me + PED_VEHICLE)):
                g.cmd("key W down")
                t0 = time.time()
                while time.time() - t0 < 6.0 and g.u32(me + PED_VEHICLE):
                    time.sleep(0.03)
                g.cmd("key W up")
                thrown = not g.u32(me + PED_VEHICLE)
                if self.ok("the crash throws him off", thrown, "after %.1f s" % (time.time() - t0)):
                    self.report("Vic", self.down(me, "vic"), me)

            # a ped thrown off: its PCJ-600 parked facing east, Vic's Sentinel 20 m east driving into it head on
            g.scm(S.op(WARP_CHAR_FROM_CAR_TO_COORD, S.PLAYER, S.f(-628.0), S.f(LANE_Y), S.f(-100.0)))
            g.teleport(-628.0, LANE_Y, -100.0)
            time.sleep(3.0)
            bike, rider = self.bike_with_rider(-652.0, LANE_Y, 270.0)
            if self.ok("a ped rides a parked PCJ-600", rider and g.u32(rider + PED_STATE) == DRIVING,
                       "bike %08X, rider %08X" % (bike, rider)):
                bx, by, _ = g.peekf(bike + 0x30, 3)
                g.scm(S.op(S.REQUEST_MODEL, S.i(SENTINEL)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                      S.op(S.CREATE_CAR, S.i(SENTINEL), S.f(bx + 20.0), S.f(by), S.f(-100.0), S.LOCAL0) +
                      S.op(SET_CAR_HEADING, S.LOCAL0, S.f(90.0)) + S.op(S.WARP_CHAR_INTO_CAR, S.PLAYER, S.LOCAL0))
                time.sleep(2.0)
                g.cmd("key W down")
                t0, tapped = time.time(), False
                while time.time() - t0 < 6.0 and g.u32(rider + PED_VEHICLE):
                    car = g.u32(me + PED_VEHICLE)
                    v = g.peekf(car + 0x140, 3) if car else (0.0, 0.0, 0.0)
                    # the game now and then ignores a throttle held from a warp into the car: press it again
                    if not tapped and time.time() - t0 > 1.5 and math.hypot(v[0], v[1]) * 50.0 < 1.0:
                        g.cmd("key W up")
                        time.sleep(0.3)
                        g.cmd("key W down")
                        tapped = True
                    time.sleep(0.03)
                car = g.u32(me + PED_VEHICLE)
                v = g.peekf(car + 0x140, 3) if car else (0.0, 0.0, 0.0)
                g.cmd("key W up")
                g.cmd("key z down")
                if self.ok("the car's hit throws it off", not g.u32(rider + PED_VEHICLE),
                           "the car at %.1f m/s" % (math.hypot(v[0], v[1]) * 50.0)):
                    self.report("the ped", self.down(rider, "ped"), rider)
                g.cmd("key z up")

            # a rider shot dead: a Shotgun locked on from 4 m
            g.scm(S.op(WARP_CHAR_FROM_CAR_TO_COORD, S.PLAYER, S.f(-640.0), S.f(LANE_Y + 6.0), S.f(-100.0)))
            g.teleport(-640.0, LANE_Y + 4.0, -100.0, heading=180.0)  # facing south, at the bike
            time.sleep(3.0)
            bike, rider = self.bike_with_rider(-640.0, LANE_Y, 90.0)
            if self.ok("a ped rides a second PCJ-600", rider, "bike %08X, rider %08X" % (bike, rider)):
                g.scm(S.op(S.REQUEST_MODEL, S.i(SHOTGUN_MODEL)) + S.op(S.LOAD_ALL_MODELS_NOW) +
                      S.op(S.GIVE_WEAPON_TO_CHAR, S.PLAYER, S.i(SHOTGUN), S.i(50)))
                time.sleep(1.0)
                created = int(self.jolt()["created"])
                g.cmd("key E down")
                time.sleep(0.6)
                for _ in range(3):
                    if g.u32(rider + PED_STATE) in (DYING, DEAD) or not g.u32(rider + PED_VEHICLE):
                        break
                    g.cmd("key Ctrl down")
                    time.sleep(0.15)
                    g.cmd("key Ctrl up")
                    time.sleep(1.2)
                g.cmd("key E up")
                time.sleep(1.0)
                st = self.jolt()
                dead = g.u32(rider + PED_STATE) in (DYING, DEAD)
                g.cmd("screenshot " + os.path.join(self.out, "shot.png"))
                # its death's ragdoll in the log ("killed by"; a later hit reaction elsewhere is the status' newest)
                log = open(os.path.join(ROOT, "build", "run", "ragdoll_bike.log"), encoding="utf-8", errors="replace").read()
                ragdoll = int(st["created"]) > created and ("[jolt] ped %08X (model" % rider) in log and \
                    any(l.startswith("[jolt] ped %08X (model" % rider) and "killed by" in l for l in log.splitlines())
                self.ok("a rider shot dead falls off as a dead ragdoll", dead and ragdoll,
                        "state 0x%x, ragdoll %s, off the bike %s" % (
                            g.u32(rider + PED_STATE), ragdoll, not g.u32(rider + PED_VEHICLE)))
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
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "ragdoll", time.strftime("bike-%Y%m%d-%H%M%S")))
    ap.add_argument("--port", type=int, default=rig.gamectl.DEFAULT_PORT)
    a = ap.parse_args()
    sys.exit(0 if Check(a.out, a.port).run() else 1)


if __name__ == "__main__":
    main()
