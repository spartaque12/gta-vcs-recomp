#!/usr/bin/env python3
"""Link a private copy of vcs.exe while build\\vcs.exe is in use (the user playing, another test running).

    python tools/exe_copy.py DIR        -> DIR\\vcs.exe (+ the DLLs and vcs.ini from build\\ when DIR has none)

Builds every input of the game's link edge with ninja (objects and the libraries it links), writes the link's response
file from build.ninja (ninja writes it only while it runs the link, which would try to replace the locked
build\\vcs.exe), then runs the same link with /out: /pdb: /implib: in DIR and without the post-build copy. build\\vcs.exe
is not touched; the next normal build relinks it as usual. Test from the copy with VCS_EXE=DIR\\vcs.exe (tools/run.py
and everything on top of it, docs/MODS.md "Testing and building alongside play"); its mods go in DIR\\scripts.
Windows (clang-cl / lld-link through CMake's vs_link_exe); the build tree must exist (python tools/build.py once).
"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain as tc  # noqa: E402


def split_paths(s):
    """A ninja path list: spaces separate, '$ ' '$:' '$$' are escapes."""
    out, cur, i = [], "", 0
    while i < len(s):
        c = s[i]
        if c == "$" and i + 1 < len(s):
            cur += s[i + 1] if s[i + 1] in "$: " else s[i:i + 2]
            i += 2
            continue
        if c == " ":
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    if cur:
        out.append(cur)
    return out


def unescape(s):
    return re.sub(r"\$(.)", lambda m: m.group(1) if m.group(1) in "$: " else m.group(0), s)


def main():
    if len(sys.argv) != 2 or not tc.IS_WINDOWS:
        print(__doc__)
        return 2
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    env = tc.build_env()
    ninja = tc.program("ninja", env)
    bd = tc.BUILD_DIR
    if not os.path.isfile(os.path.join(bd, "build.ninja")):
        tc.fail("no build tree yet: python tools/build.py first")
    commands = subprocess.run([ninja, "-t", "commands", "ps2EntryRunner"], capture_output=True, text=True, env=env,
                              cwd=bd).stdout.strip().splitlines()
    link = commands[-1] if commands else ""
    m = re.search(r"/out:(\S+)", link, re.I)
    if not m:
        tc.fail("the game's link command was not found")
    exe = m.group(1)
    # the link edge (continuation lines joined): explicit inputs, implicit ones (the libraries), its variables
    text = open(os.path.join(bd, "build.ninja"), encoding="utf-8").read().replace("$\n", "")
    key = "build " + exe.replace(":", "$:") + ":"
    start = text.find(key)
    if start < 0:
        tc.fail("the link edge of %s was not found in build.ninja" % exe)
    lines = text[start:].split("\n")
    explicit, _, implicit = lines[0][len(key):].strip().split(" || ")[0].partition(" | ")
    inputs = split_paths(explicit)[1:]  # [0] is the rule
    libraries = [p for p in split_paths(implicit) if p.lower().endswith(".lib") and not os.path.isabs(p)]
    variables = {}
    for line in lines[1:]:
        if not line.startswith("  "):
            break
        k, _, v = line.strip().partition(" = ")
        variables[k] = unescape(v)
    needed = inputs + libraries
    print("[exe_copy] building %d inputs of %s" % (len(needed), os.path.basename(exe)))
    for i in range(0, len(needed), 40):  # the command line's length limit
        if subprocess.run([ninja] + needed[i:i + 40], env=env, cwd=bd).returncode:
            tc.fail("the game's objects did not build")
    rsp = os.path.join(bd, variables.get("RSP_FILE", "CMakeFiles\\ps2EntryRunner.rsp"))
    with open(rsp, "w", encoding="utf-8") as f:
        f.write("\n".join(inputs) + " " + variables.get("LINK_PATH", "") + " " + variables.get("LINK_LIBRARIES", ""))
    target = os.path.join(out, "vcs.exe")
    cmd = " && ".join(link.split(" && ")[0:2])  # cmd.exe /C "cd . && <vs_link_exe ... lld-link ...>: the copy step dropped
    cmd = re.sub(r"/out:\S+", lambda _: "/out:" + target, cmd, flags=re.I)
    cmd = re.sub(r"/pdb:\S+", lambda _: "/pdb:" + os.path.join(out, "vcs.pdb"), cmd, flags=re.I)
    cmd = re.sub(r"/implib:\S+", lambda _: "/implib:" + os.path.join(out, "vcs.lib"), cmd, flags=re.I)
    if cmd.count('"') % 2:
        cmd += '"'
    print("[exe_copy] linking " + target)
    code = subprocess.run(cmd, env=env, cwd=bd).returncode  # as ninja runs it: the line starts with cmd.exe /C
    os.remove(rsp)
    if code:
        tc.fail("the link failed")
    for f in os.listdir(tc.BUILD):
        if f.lower().endswith(".dll") and not os.path.exists(os.path.join(out, f)):
            shutil.copy2(os.path.join(tc.BUILD, f), out)
    ini = os.path.join(tc.BUILD, "vcs.ini")
    if os.path.isfile(ini) and not os.path.exists(os.path.join(out, "vcs.ini")):
        shutil.copy2(ini, out)
    print("[exe_copy] done: %s (VCS_EXE=%s)" % (target, target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
