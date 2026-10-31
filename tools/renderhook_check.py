#!/usr/bin/env python3
"""RenderHook.asi's ambient occlusion in a hidden run: off / normal / strong / occlusion-only shots, and checks.

    python tools/renderhook_check.py [OUT] --asi PATH\\RenderHook.asi [--exe DIR\\vcs.exe] [--small] [ENV=VALUE ...]

Copies the mod into the exe's scripts\\ folder (--exe: a private copy, tools/exe_copy.py; default build\\vcs.exe),
starts the game hidden from the card copy in build\\rig\\saves\\user (else fortbaxter), noon and sunny, and at Fort
Baxter's barracks door and a Downtown street (-675, 1425) takes the four pictures (OUT, default build/renderhook/check),
reading the mod's status (`renderhook`) and the renderer's frame-hook log. 16:9 1920x1080 with the exe's own MSAA by
default; --small: 4:3 640x448 without MSAA. Fails when the mod did not load, the hook skipped frames or missed any, or
the camera it was handed is not plausible (docs/RENDERHOOK_PLAN.md, NATIVE_RENDERER.md "Frame hook for render mods").
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
SPOTS = [("fortbaxter", None, None, None), ("street", -675.0, 1425.0, 90.0)]


def status_fields(line):
    out = {}
    words = line.split()
    for i, w in enumerate(words[:-1]):
        if w in ("ao", "frames", "skipped", "camera", "depth", "hooked"):
            out[w] = words[i + 1]
    m = re.search(r" f ([\d.]+) ([\d.]+) c ([\d.]+) ([\d.]+)", line)
    if m:
        out["lens"] = tuple(float(v) for v in m.groups())
    m = re.search(r" size (\d+)x(\d+)", line)
    if m:
        out["size"] = (int(m.group(1)), int(m.group(2)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=os.path.join(ROOT, "build", "renderhook", "check"))
    ap.add_argument("--asi", required=True, help="the built RenderHook.asi (VCS-mods)")
    ap.add_argument("--exe", help="the vcs.exe to run (default: build\\vcs.exe)")
    ap.add_argument("--small", action="store_true", help="4:3 640x448 without MSAA")
    ap.add_argument("env", nargs="*", help="ENV=VALUE for the game")
    a = ap.parse_args()
    a.out = os.path.abspath(a.out)  # the game writes the pictures from its own working folder (build\run)
    exe = os.path.abspath(a.exe) if a.exe else tc.VCS_EXE
    os.environ["VCS_EXE"] = exe
    import rig  # after VCS_EXE: tools/run.py reads it

    scripts = os.path.join(os.path.dirname(exe), "scripts")
    os.makedirs(scripts, exist_ok=True)
    shutil.copy2(a.asi, scripts)
    os.makedirs(a.out, exist_ok=True)
    env = {"PS2X_HW_FRAME_HOOK_LOG": "1", "PS2X_GPU_TIMING": "1"}
    if a.small:
        env.update({"VCS_ASPECT": "43", "PS2X_HW_SCALE": "1", "PS2X_HW_MSAA": "1", "PS2X_CAPTURE_SIZE": "960x672"})
    else:
        env.update({"VCS_ASPECT": "169", "PS2X_HW_FRAME": "1920x1080", "PS2X_HW_OUTPUT": "1920x1080",
                    "PS2X_CAPTURE_SIZE": "1920x1080"})
    env.update(dict(p.split("=", 1) for p in a.env if "=" in p))
    saves = os.path.join(ROOT, "build", "rig", "saves")
    save = os.path.join(saves, "user") if os.path.isdir(os.path.join(saves, "user", "mc0")) else os.path.join(saves, "fortbaxter")
    g = rig.Game.start(save=save, name="renderhook_check", port=47673,
                       data_dir=os.path.join(ROOT, "build", "renderhook", "data"), env=env)
    problems, statuses = [], []
    try:
        g.wait_ingame()
        g.set_time(12)
        g.weather(0)
        g.invincible()
        g.prime()
        for spot, x, y, heading in SPOTS:
            if x is not None:
                g.teleport(x, y, -100.0, heading=heading)
                time.sleep(3.0)
                g.cmd("key W down")  # a few steps: the camera swings in behind the player
                time.sleep(1.2)
                g.cmd("key W up")
            time.sleep(4.0)
            g.set_time(12)
            for label, cmds in (("off", ["setting renderhook.ao 0", "renderhook view 0"]), ("normal", ["setting renderhook.ao 2"]),
                                ("strong", ["setting renderhook.ao 3"]), ("view", ["setting renderhook.ao 2", "renderhook view 1"])):
                for c in cmds:
                    g.cmd(c)
                time.sleep(0.6)
                g.cmd("screenshot " + os.path.join(a.out, "%s_%s.png" % (spot, label)))
            g.cmd("renderhook view 0")
            line = g.cmd("renderhook")
            statuses.append((spot, line))
            print("[renderhook_check] %s: %s" % (spot, line))
            st = status_fields(line)
            if st.get("hooked") != "1" or int(st.get("frames", "0")) == 0:
                problems.append("%s: the hook did not run" % spot)
            if st.get("skipped", "0") != "0":
                problems.append("%s: frames skipped (%s)" % (spot, st.get("skipped")))
            lens, size = st.get("lens"), st.get("size")
            if not lens or not size or st.get("camera") != "1":
                problems.append("%s: no camera" % spot)
            else:
                fx, fy, cx, cy = lens
                w, h = size
                if not (0.2 * w < fx < 4.0 * w and 0.2 * h < fy < 4.0 * h and abs(cx - w / 2) < 0.01 * w + 2 and abs(cy - h / 2) < 0.01 * h + 2):
                    problems.append("%s: implausible camera f %.1f %.1f c %.1f %.1f for %dx%d" % (spot, fx, fy, cx, cy, w, h))
        time.sleep(6.0)  # a GPU timing report with the occlusion on
    except Exception as e:  # noqa: BLE001 - reported as a failure
        problems.append("run: %s" % e)
    finally:
        g.quit()
    log = open(g.log_path, encoding="utf-8", errors="replace").read()
    if "[mods] RenderHook loaded" not in log:
        problems.append("RenderHook.asi did not load (see %s)" % g.log_path)
    missed = re.findall(r"frame hook: \d+ run, (\d+) frames missed", log)
    if missed and missed[-1] != "0":
        problems.append("%s frames without the hook" % missed[-1])
    gpu = re.findall(r"\[gpu-timing\]\s+([\d.]+) ms\s+([\d.]+) spans\s+renderhook ao", log)
    if gpu:
        ms = [float(t) / max(float(s), 1e-6) for t, s in gpu]
        print("[renderhook_check] GPU per frame with ambient occlusion: %.3f - %.3f ms" % (min(ms), max(ms)))
    print("[renderhook_check] pictures in %s; log %s" % (a.out, g.log_path))
    for p in problems:
        print("[renderhook_check] FAIL " + p)
    print("[renderhook_check] %s" % ("ok" if not problems else "%d problem(s)" % len(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
