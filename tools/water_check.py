#!/usr/bin/env python3
"""RenderHook.asi's water in a hidden run: original / new shots of the sea and a shore at noon, 17:00 and night, debug views,
and checks.

    python tools/water_check.py [OUT] --asi PATH\\RenderHook.asi [--exe DIR\\vcs.exe] [--times 12,17,23] [ENV=VALUE ...]

Copies the mod into the exe's scripts\\ folder (--exe: a private copy, tools/exe_copy.py), starts the game hidden from the
card copy in build\\rig\\saves\\user (else fortbaxter), 1280x720, sunny, puts the player in the water off Downtown's quay
(-675, -75) and swims a little each way: towards the quay ("shore") and out to sea ("sea"). Per time: original
(renderhook.water 0) and new (2); at noon also the debug views (rhwater view 1 mask / depth, 2 normals, 3 reflection
hits). Fails when the mod did not load, the water points did not run or drew nothing. GPU time per frame from
PS2X_GPU_TIMING's "renderhook water" marker. docs/RENDERHOOK_PLAN.md "Water".
"""
import argparse
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain as tc  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPOTS = [("shore", -675.0, -75.0, 90.0), ("sea", -675.0, -75.0, 270.0)]


def fields(line):
    out = {}
    words = line.split()
    for i, w in enumerate(words[:-1]):
        if w in ("frames", "before", "skipped", "hooked"):
            out[w] = words[i + 1]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "water", "check"))
    ap.add_argument("--asi", required=True, help="the built RenderHook.asi (VCS-mods)")
    ap.add_argument("--exe", help="the vcs.exe to run (default: build\\vcs.exe)")
    ap.add_argument("--times", default="12,17,23", help="hours to shoot (default 12,17,23)")
    ap.add_argument("--port", type=int, default=47731)
    ap.add_argument("env", nargs="*", help="ENV=VALUE for the game")
    a = ap.parse_args()
    a.out = os.path.abspath(a.out)
    exe = os.path.abspath(a.exe) if a.exe else tc.VCS_EXE
    os.environ["VCS_EXE"] = exe
    import rig  # after VCS_EXE: tools/run.py reads it

    scripts = os.path.join(os.path.dirname(exe), "scripts")
    os.makedirs(scripts, exist_ok=True)
    shutil.copy2(a.asi, scripts)
    os.makedirs(a.out, exist_ok=True)
    env = {"PS2X_GPU_TIMING": "1", "VCS_ASPECT": "169", "PS2X_HW_FRAME": "1280x720", "PS2X_HW_OUTPUT": "1280x720",
           "PS2X_CAPTURE_SIZE": "1280x720"}
    env.update(dict(p.split("=", 1) for p in a.env if "=" in p))
    saves = os.path.join(ROOT, "build", "rig", "saves")
    save = os.path.join(saves, "user") if os.path.isdir(os.path.join(saves, "user", "mc0")) else os.path.join(saves, "fortbaxter")
    g = rig.Game.start(save=save, name="water_check", port=a.port, data_dir=os.path.join(ROOT, "build", "water", "data"), env=env)
    problems = []
    hours = [int(h) for h in a.times.split(",") if h.strip()]
    try:
        g.wait_ingame()
        g.weather(0)
        g.invincible()
        g.prime()
        for spot, x, y, heading in SPOTS:
            g.teleport(x, y, 30.0, heading=heading)
            time.sleep(4.0)
            g.cmd("key W down")  # a few strokes: the camera swings in behind the swimmer
            time.sleep(1.5)
            g.cmd("key W up")
            time.sleep(1.5)
            for hour in hours:
                g.set_time(hour)
                time.sleep(2.0)
                shots = [("original", ["setting renderhook.water 0", "rhwater view 0"]), ("new", ["setting renderhook.water 2"])]
                if hour == hours[0]:
                    shots += [("view%d" % v, ["rhwater view %d" % v]) for v in (1, 2, 3)]
                for label, cmds in shots:
                    for c in cmds:
                        g.cmd(c)
                    time.sleep(0.8)
                    g.cmd("screenshot " + os.path.join(a.out, "%s_%02d_%s.png" % (spot, hour, label)))
                g.cmd("rhwater view 0")
            line = g.cmd("rhwater")
            print("[water_check] %s: %s" % (spot, line))
            st = fields(line)
            if st.get("hooked") != "1" or int(st.get("frames", "0")) == 0:
                problems.append("%s: the water was not drawn (%s)" % (spot, line))
        g.cmd("setting renderhook.water 2")
        time.sleep(6.0)  # a GPU timing report with the water on
    except Exception as e:  # noqa: BLE001 - reported as a failure
        problems.append("run: %s" % e)
    finally:
        g.quit()
    log = open(g.log_path, encoding="utf-8", errors="replace").read()
    if "[mods] RenderHook loaded" not in log:
        problems.append("RenderHook.asi did not load (see %s)" % g.log_path)
    for m in re.findall(r"\[renderhook\] water off: .*", log):
        problems.append(m)
    gpu = re.findall(r"\[gpu-timing\]\s+([\d.]+) ms\s+([\d.]+) spans\s+renderhook water\s*$", log, re.M)
    if gpu:
        ms = [float(t) / max(float(s), 1e-6) for t, s in gpu]
        print("[water_check] GPU per water pass: %.3f - %.3f ms" % (min(ms), max(ms)))
    print("[water_check] pictures in %s; log %s" % (a.out, g.log_path))
    for p in problems:
        print("[water_check] FAIL " + p)
    print("[water_check] %s" % ("ok" if not problems else "%d problem(s)" % len(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
