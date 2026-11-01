#!/usr/bin/env python3
"""The converted weapons' full-resolution textures as a PCSX2 texture-replacement pack (docs/TEXTURE_PACKS.md).

    python tools/weapon_textures.py name MODS [--pack build/textures/SLUS-21590] [--port 47675]
    python tools/weapon_textures.py check [OUT] [--pack build/textures/SLUS-21590] [--mods MODS] [--port 47675]

tools/weapon_convert.py bakes each weapon's atlas at four times its in-game size (<mods>/fullres/<id>.png) and records
the in-game texture's shape and palette hash (<mods>/fullres/manifest.json). A replacement is named after the texture
as the game uploads it ("<pixel hash>-<palette hash>-<bits>.png", XXH3 over the GS blocks), which only the game knows:
`name` starts a hidden run with the replacements on and VCS_TEXTURE_TRACE=1 (a placeholder file per shape makes the
renderer hash textures of those shapes), gives the player every weapon (aimed and fired, so the rocket and the
minigun's barrels draw too), reads the lookups from the log, finds each weapon's by its palette hash (each atlas has a
CLUT of its own) and copies the PNGs to <pack>/replacements/weapons/. `check` runs again with the pack and reports
the files matched and loaded, with screenshots aimed over the shoulder and in first person.
Test runs: a copy of the user's card (build/rig/saves/user), hidden, VCS_EXE honoured (a copy of vcs.exe)."""
import argparse
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig  # noqa: E402
import weapon_convert as wc  # noqa: E402

ROOT = rig.ROOT
SAVE = os.path.join(ROOT, "build", "rig", "saves", "user")
GIVE_WEAPON, CURRENT_WEAPON = rig.Scm.GIVE_WEAPON_TO_CHAR, 0x010B
# what to hold: the weapon types whose models draw the textures (13: the satchel, then its detonator; 32 fires the rocket)
TYPES = [1, 3, 4, 5, 6, 10, 11, 12, 16, 17, 19, 20, 21, 22, 23, 24, 25, 27, 28, 29, 30, 32, 33, 35, 13, 38]


def start(name, pack, mods, port, env=None):
    e = {"VCS_TEXTURE_REPLACEMENTS": "1", "VCS_TEXTURE_PACK": pack, "VCS_MODS_DIR": mods, "VCS_FREEAIM": "1",
         "VCS_FIRSTPERSON": "0"}
    e.update(env or {})
    g = rig.Game.start(save=SAVE, name=name, port=port, seconds=900, env=e)
    g.wait_ingame()
    g.prime()
    g.set_time(12)
    g.weather(0)
    for tog in ("god", "wanted", "hidehud"):
        g.cmd("trainer toggle %s 1" % tog)
    g.teleport(-700.0, -500.0, -100.0, heading=0.0)
    time.sleep(2.0)
    g.invincible(True)
    return g


def hold(g, t, shots=None, fire=True):
    g.scm(rig.Scm.op(GIVE_WEAPON, rig.Scm.PLAYER, rig.Scm.i(t), rig.Scm.i(50)) +
          rig.Scm.op(CURRENT_WEAPON, rig.Scm.PLAYER, rig.Scm.i(t)))
    time.sleep(1.5)
    g.cmd("key E down")
    time.sleep(0.8)
    if shots:
        g.cmd("mouse 0 40")
        time.sleep(0.6)
        g.cmd("screenshot " + shots)
    if fire:
        g.cmd("key Ctrl down")
        time.sleep(0.3 if t not in (33, 35) else 0.8)
        g.cmd("key Ctrl up")
    time.sleep(0.4)
    g.cmd("key E up")
    if t == 13:  # the satchel thrown: the detonator in the hand
        time.sleep(1.2)
    time.sleep(0.3)


def log_lines(g, key):
    return [l.rstrip() for l in open(g.log_path, encoding="utf-8", errors="replace") if key in l]


def name(a):
    manifest = json.load(open(os.path.join(a.mods, "fullres", "manifest.json")))
    stage = os.path.join(ROOT, "build", "weapon_textures", "trace")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.join(stage, "replacements"))
    tiny = os.path.join(stage, "tiny.png")
    wc.write_png(tiny, 1, 1, b"\0\0\0\x80")
    for shape in sorted({m["shape"] for m in manifest.values()}):  # a placeholder per shape: those textures get hashed
        shutil.copy(tiny, os.path.join(stage, "replacements", "0-0-%08x.png" % int(shape, 16)))
    g = start("wtex_name", stage, a.mods, a.port, {"VCS_TEXTURE_TRACE": "1"})
    try:
        for t in TYPES:
            hold(g, t)
    finally:
        g.quit()
    found = {}
    for l in log_lines(g, "[textures] lookup "):
        m = re.search(r"lookup ([0-9a-f]+)-([0-9a-f]+)-([0-9a-f]{8})", l)
        if m:
            found.setdefault((m.group(2), int(m.group(3), 16) & 0x3FFF), m.group(0)[7:])
    out = os.path.join(a.pack, "replacements", "weapons")
    os.makedirs(out, exist_ok=True)
    named, missing = 0, []
    for tid, m in sorted(manifest.items(), key=lambda kv: int(kv[0])):
        key = (m["palette_hash"], int(m["shape"], 16))
        if key not in found:
            missing.append(tid)
            continue
        for old in os.listdir(out):  # an earlier name of this weapon's texture
            if old.endswith(".png") and old.split("-")[1:2] == [m["palette_hash"]]:
                os.remove(os.path.join(out, old))
        dst = os.path.join(out, found[key] + ".png")
        shutil.copy(m["png"], dst)
        named += 1
        print("%s %-16s -> %s" % (tid, m["texture"], os.path.basename(dst)))
    print("%d named, not seen in the run: %s" % (named, ", ".join(missing) or "none"))
    return 0 if named else 1


def check(a):
    out = os.path.abspath(a.out or os.path.join(ROOT, "build", "weapon_textures", "check"))
    os.makedirs(out, exist_ok=True)
    res = {}
    for fp in ("0", "1"):
        g = start("wtex_check_fp%s" % fp, a.pack, a.mods, a.port, {"VCS_FIRSTPERSON": fp})
        try:
            for t in TYPES:
                hold(g, t, os.path.join(out, "%s_%02d.png" % ("fp" if fp == "1" else "aim", t)), fire=t in (13, 32, 35))
        finally:
            g.quit()
        res["fp" if fp == "1" else "aim"] = {
            "matched": [l.split("matched ")[1].split(" ")[0] for l in log_lines(g, "[textures] matched ")],
            "loaded": [l.split("loaded ")[1].split(" ")[0] for l in log_lines(g, "[textures] loaded ")],
            "failed": log_lines(g, "[textures] failed"),
            "summary": log_lines(g, "[textures] summary")}
    ours = set(os.listdir(os.path.join(a.pack, "replacements", "weapons")))
    for k, r in res.items():
        m = sorted(set(r["matched"]) & ours)
        print("%s: %d / %d weapon textures matched, %d loaded, failures %d; %s" % (
            k, len(m), len(ours), len(set(r["loaded"]) & ours), len(r["failed"]), r["summary"][-1:] if r["summary"] else ""))
    json.dump(res, open(os.path.join(out, "result.json"), "w"), indent=1)
    print("screenshots:", out)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("name")
    p.add_argument("mods")
    p.add_argument("--pack", default=os.path.join(ROOT, "build", "textures", "SLUS-21590"))
    p.add_argument("--port", type=int, default=47675)
    p = sub.add_parser("check")
    p.add_argument("out", nargs="?")
    p.add_argument("--pack", default=os.path.join(ROOT, "build", "textures", "SLUS-21590"))
    p.add_argument("--mods", default=os.path.join(ROOT, "build", "mods"))
    p.add_argument("--port", type=int, default=47675)
    a = ap.parse_args()
    return name(a) if a.cmd == "name" else check(a)


if __name__ == "__main__":
    sys.exit(main())
