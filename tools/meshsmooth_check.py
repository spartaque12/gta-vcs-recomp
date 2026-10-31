#!/usr/bin/env python3
"""MeshSmooth.asi's check (VCS-mods plugins/MeshSmooth, docs/MODS.md): hidden run from a card copy, Vic on foot, then in a car
(camera behind it); at each, pictures and perf lines with the smoothing off and on (and on with
level 2), the mod's counters (batches refined per kind, cache, build time), and a drive afterwards (models streaming in:
build time per new batch, frame times).

    python tools/meshsmooth_check.py [OUT] --asi VCS-mods\\build\\...\\MeshSmooth.asi [--exe DIR\\vcs.exe]

Pictures: OUT/<spot>_<off|on|level2>.png (1920x1080). Exit code 0 when the mod loaded and refined batches of all
three kinds.
"""
import argparse
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain as tc  # noqa: E402

ROOT = tc.ROOT
# (name, x, y, heading, car model)
SPOTS = [("onfoot", 1325.0, -325.0, 90.0, None), ("car", None, None, 0.0, 211)]  # car: Vic put into one (camera behind it)


def fields(line):
    return dict(re.findall(r"(\w+)=([^\s]+)", line))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "meshsmooth", "check"))
    ap.add_argument("--asi", required=True)
    ap.add_argument("--exe", help="the vcs.exe to run (default: build\\vcs.exe)")
    ap.add_argument("--port", type=int, default=47699)
    a = ap.parse_args()
    a.out = os.path.abspath(a.out)
    exe = os.path.abspath(a.exe) if a.exe else tc.VCS_EXE
    os.environ["VCS_EXE"] = exe
    import rig  # after VCS_EXE

    scripts = os.path.join(os.path.dirname(exe), "scripts")
    os.makedirs(scripts, exist_ok=True)
    shutil.copy2(a.asi, scripts)
    os.makedirs(a.out, exist_ok=True)
    env = {"VCS_ASPECT": "169", "PS2X_HW_FRAME": "1920x1080", "PS2X_HW_OUTPUT": "1920x1080",
           "PS2X_CAPTURE_SIZE": "1920x1080"}
    saves = os.path.join(ROOT, "build", "rig", "saves")
    save = os.path.join(saves, "user") if os.path.isdir(os.path.join(saves, "user", "mc0")) else os.path.join(saves, "fortbaxter")
    g = rig.Game.start(save=save, name="meshsmooth_check", port=a.port,
                       data_dir=os.path.join(ROOT, "build", "meshsmooth", "data"), env=env)
    problems, kinds = [], [0, 0, 0]
    S = rig.Scm
    try:
        g.wait_ingame()
        g.set_time(12)
        g.weather(0)
        g.invincible()
        for spot, x, y, heading, model in SPOTS:
            if x is not None:
                g.teleport(x, y, -100.0, heading=heading)
                time.sleep(8.0)
            if model:
                g.spawn_car(model=model)
            time.sleep(4.0)
            g.set_time(12)
            for label, cmds in (("off", ["setting meshsmooth.enabled 0"]),
                                ("on", ["setting meshsmooth.enabled 1", "setting meshsmooth.level 1"]),
                                ("level2", ["setting meshsmooth.level 2"]),
                                ("vehonly", ["setting meshsmooth.level 1", "setting meshsmooth.others 0"]),
                                ("othersonly", ["setting meshsmooth.others 1", "setting meshsmooth.vehicles 0"]),
                                ("flat", ["setting meshsmooth.vehicles 1", "setting meshsmooth.strength 0"])):
                for c in cmds:
                    g.cmd(c)
                time.sleep(1.5)  # three sightings, then cached
                g.cmd("meshsmooth reset")
                g.cmd("perf")
                time.sleep(2.0)
                perf = g.cmd("perf")
                g.cmd("screenshot " + os.path.join(a.out, "%s_%s.png" % (spot, label)))
                st = g.cmd("meshsmooth")
                print("[meshsmooth_check] %s %s: %s | %s" % (spot, label, perf, st))
                if label != "off":
                    f = fields(st)
                    for k, v in enumerate(f.get("refined", "0/0/0").split("/")):
                        kinds[k] += int(v)
            g.cmd("setting meshsmooth.level 1")
            g.cmd("setting meshsmooth.vehicles 1")
            g.cmd("setting meshsmooth.strength 100")
        # a drive: new models stream in (build time per batch, frame times)
        g.cmd("meshsmooth reset")
        g.autodrive(speed=40.0)
        for i in range(4):
            time.sleep(5.0)
            print("[meshsmooth_check] drive %ds: %s | %s" % (5 * (i + 1), g.cmd("perf"), g.cmd("meshsmooth")))
        g.cmd("setting meshsmooth.enabled 0")
        time.sleep(5.0)
        print("[meshsmooth_check] drive off: %s" % g.cmd("perf"))
    except Exception as e:  # noqa: BLE001 - reported as a failure
        problems.append("run: %s" % e)
    finally:
        g.quit()
    log = open(g.log_path, encoding="utf-8", errors="replace").read()
    if "[mods] MeshSmooth loaded" not in log:
        problems.append("MeshSmooth.asi did not load (see %s)" % g.log_path)
    for k, name in enumerate(("skinned", "rigid", "env")):
        if kinds[k] == 0:
            problems.append("no %s batches refined" % name)
    print("[meshsmooth_check] pictures in %s; log %s" % (a.out, g.log_path))
    for p in problems:
        print("[meshsmooth_check] FAIL " + p)
    print("[meshsmooth_check] %s" % ("ok" if not problems else "%d problem(s)" % len(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
