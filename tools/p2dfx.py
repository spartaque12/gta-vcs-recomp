#!/usr/bin/env python3
"""The Project2DFX light table for "Distant lights" (game/vcs_project2dfx.h): imported from your copy of the plugin.

    python tools/p2dfx.py import PATH    PATH: GTAVCS.PCSX2F.Project2DFX.zip, its .elf, or the plugin source's Lights.hpp
    python tools/p2dfx.py check          what the game will load (count, checksum)

The table (4,423 lamps: position, size, the game's own corona range, colour, blink mode) comes from ThirteenAG's
Project2DFX for the PCSX2 fork (MIT, github.com/ThirteenAG/III.VC.SA.IV.Project2DFX); its positions were taken from the
game's map, so it is game data and never part of this repository. `import` writes it to p2dfx/lights.bin in the build
folder, next to vcs.exe (VCS_P2DFX_LIGHTS=<file> points a run elsewhere). Records are kept as the plugin stores them
(32 bytes: x, y, z, size, native range, orientation as floats; r, g, b, a, blink, no-distance as bytes; 2 pad).
"""
import argparse
import hashlib
import math
import os
import re
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toolchain as tc  # noqa: E402

SYMBOL = "_ZN5vcsfx6lightsE"  # vcsfx::lights (the LCS plugin's table has another name)
RECORD = struct.Struct("<6f6B2x")
MAGIC = b"VCSP2DFX"
VERSION = 1
OUT = os.path.join(tc.BUILD, "p2dfx", "lights.bin")


def table_from_elf(data):
    """The bytes of vcsfx::lights in the plugin's relocatable MIPS object (ELF32, little-endian)."""
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        tc.fail("not a 32-bit little-endian ELF: is this the PCSX2F plugin's .elf?")
    shoff, = struct.unpack_from("<I", data, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", data, 0x2E)
    sections = [struct.unpack_from("<10I", data, shoff + i * shentsize) for i in range(shnum)]

    def name_at(strtab, offset):
        start = sections[strtab][4] + offset
        return data[start:data.index(b"\0", start)].decode("ascii", "replace")

    for sh in sections:
        if sh[1] != 2:  # SHT_SYMTAB
            continue
        strtab = sh[6]
        for i in range(sh[5] // 16):
            st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from("<IIIBBH", data, sh[4] + i * 16)
            if st_name and name_at(strtab, st_name) == SYMBOL:
                target = sections[st_shndx]
                if target[1] != 1:  # SHT_PROGBITS
                    tc.fail("%s is not initialised data in this file" % SYMBOL)
                for rel in sections:  # the table must be plain data: nothing relocated into it
                    if rel[1] in (4, 9) and rel[7] == st_shndx:
                        tc.fail("%s has relocations: not the table this tool knows" % SYMBOL)
                return data[target[4] + st_value:target[4] + st_value + st_size]
    tc.fail("no %s in this ELF: it must be the GTA: Vice City Stories plugin (GTAVCS.PCSX2F.Project2DFX.elf)" % SYMBOL)


NUMBER = r"\s*(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)f?\s*"
LINE = re.compile(r"\{\{" + ",".join([NUMBER] * 3) + r"\}," + ",".join([NUMBER] * 3) + r",\s*\{" +
                  ",".join([r"\s*(\d+)\s*"] * 4) + r"\},\s*(\d+)\s*,\s*(\d+)\s*\}")


def table_from_header(text):
    """The records of the plugin source's Lights.hpp (`inline constexpr console::LightData lights[] = {...}`)."""
    if "vcsfx" not in text or "LightData lights[]" not in text:
        tc.fail("not the VCS plugin's Lights.hpp (source/console/GTAVCS.PCSX2F.Project2DFX/Lights.hpp)")
    out = bytearray()
    for m in LINE.finditer(text):
        g = m.groups()
        out += RECORD.pack(*(float(v) for v in g[:6]), *(int(v) for v in g[6:]))
    return bytes(out)


def load(path):
    if not os.path.isfile(path):
        tc.fail("%s not found" % path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".elf") and "gtavcs" in os.path.basename(n).lower()]
            if not names:
                tc.fail("no GTAVCS ... .elf in %s" % path)
            return table_from_elf(z.read(names[0]))
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] == b"\x7fELF":
        return table_from_elf(data)
    return table_from_header(data.decode("utf-8", "replace"))


def validate(table):
    if not table or len(table) % RECORD.size:
        tc.fail("the table is %d bytes: not a whole number of %d-byte lights" % (len(table), RECORD.size))
    count = len(table) // RECORD.size
    if count >= 65535:
        tc.fail("%d lights: more than the game's index holds" % count)
    for i in range(count):
        r = RECORD.unpack_from(table, i * RECORD.size)
        if not all(math.isfinite(v) for v in r[:6]) or not all(abs(v) < 10000 for v in r[:3]):
            tc.fail("light %d is not a sane record %r: wrong file?" % (i, r))
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="read the table from the plugin (zip / elf / Lights.hpp)")
    imp.add_argument("path")
    imp.add_argument("--out", default=OUT)
    chk = sub.add_parser("check", help="the table the game will load")
    chk.add_argument("--file", default=os.environ.get("VCS_P2DFX_LIGHTS") or OUT)
    a = ap.parse_args()

    if a.cmd == "import":
        table = load(os.path.abspath(a.path))
        count = validate(table)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "wb") as f:
            f.write(MAGIC + struct.pack("<II", VERSION, count) + table)
        print("%d lights -> %s (sha256 %s)" % (count, a.out, hashlib.sha256(table).hexdigest()[:16]))
        return
    if not os.path.isfile(a.file):
        tc.fail("no light table at %s: python tools/p2dfx.py import <GTAVCS.PCSX2F.Project2DFX.zip>" % a.file)
    with open(a.file, "rb") as f:
        data = f.read()
    if data[:8] != MAGIC or struct.unpack_from("<I", data, 8)[0] != VERSION:
        tc.fail("%s is not a light table of this version: import it again" % a.file)
    count = struct.unpack_from("<I", data, 12)[0]
    table = data[16:]
    if validate(table) != count:
        tc.fail("%s is cut short: import it again" % a.file)
    print("%d lights in %s (sha256 %s)" % (count, a.file, hashlib.sha256(table).hexdigest()[:16]))


if __name__ == "__main__":
    main()
