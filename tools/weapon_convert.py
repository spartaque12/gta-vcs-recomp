"""GTA SA weapon (DFF + TXD) -> VCS PS2 weapon model ('ldm' Rsl chunk) + its texture dictionary ('xet' chunk), written
as streamed-file overrides (src/game/vcs_stream_override.h: <mods>/stream/<id>.ldm / .xet).

    python tools/weapon_convert.py --pack "<...>/modloader/Immersive Weapons Pack" [--only 19,20] [--mods DIR]
        every weapon of the Immersive Weapons Pack that VCS has (PACK below), with its settings
    python tools/weapon_convert.py --weapon 19 --dff colt45.dff --txd colt45.txd [--tris 3000] [--offset x,y,z]
                                   [--rotate z:180] [--skip bullet] [--prefix c45_] [--mods build/mods] [--iso ISO]
    (or --vcs-mdl / --vcs-xet / --model-id / --out-mdl / --out-xet with files of your own)

The model is one RslElement (rigid, lit: VU1 stage table 0x19 + 0x4ff), as VCS's own weapons: per material a mesh whose
DMA packet (RET) holds batches of <= 70 strip vertices (V3-16 positions, V2-8 uv, V3-8 normals; MSCAL 6). Every part
of the SA model (its atomics) is merged at its frame's place (hidden parts - the rounds inside a magazine - left out),
welded, simplified to a triangle budget (tools/mesh_simplify.py: SA's guns are 6k - 60k triangles, VCS's 80 - 800,
and every carried weapon stays in the game's streaming memory), given smooth normals within a crease angle and turned
into strips. SA and VCS share the weapon frame (the grip near the origin, x along the barrel, z up); per weapon an
offset fits the gun into VCS's hand. The texture dictionary keeps the VCS model's own textures (the HUD icon) and adds
the new ones (T8, linear, CLUT in CSM1 order), 32 - 128 px by how much of the model each covers.
Layouts: docs/game-internals.md 12g."""
import argparse, math, os, struct, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rw_dff as rwdff, rw_txd as rwtxd, mesh_simplify

def u32(d, o): return struct.unpack_from("<I", d, o)[0]

# VCS's weapon models (read in the game, 2026-10-31; docs/game-internals.md 12g): weapon type -> (name, model id, model
# position and size in GTA3PS2.IMG sectors, texture dictionary id, its position and size). Ids are CStreaming ids.
WEAPONS = {
    1: ('BrassKnuckle', 331, 0x2d62, 1, 7812, 0x2d60, 2), 2: ('ScrewDriver', 332, 0x2d65, 2, 7813, 0x2d63, 2),
    3: ('GolfClub', 333, 0x2d74, 1, 7814, 0x2d71, 3), 4: ('NightStick', 334, 0x2d7e, 2, 7815, 0x2d7c, 2),
    5: ('Knife', 335, 0x2d83, 2, 7816, 0x2d80, 3), 6: ('BaseballBat', 336, 0x2d88, 1, 7817, 0x2d85, 3),
    7: ('Hammer', 337, 0x2d8b, 2, 7818, 0x2d89, 2), 8: ('Cleaver', 338, 0x2d90, 2, 7819, 0x2d8d, 3),
    9: ('Machete', 339, 0x2d95, 1, 7820, 0x2d92, 3), 10: ('Katana', 340, 0x2d99, 1, 7821, 0x2d96, 3),
    11: ('Chainsaw', 341, 0x2d9d, 3, 7822, 0x2d9a, 3), 12: ('Grenade', 342, 0x2daa, 2, 7823, 0x2da8, 2),
    14: ('LandMine', 368, 0x2fc6, 2, 7849, 0x2fc4, 2), 16: ('TearGas', 343, 0x2db5, 2, 7824, 0x2db2, 3),
    17: ('Molotov', 344, 0x2dba, 2, 7825, 0x2db7, 3), 18: ('Rocket', 345, 0x2dbd, 1, 7826, 0x2dbc, 1),
    19: ('Colt45', 346, 0x2dc0, 3, 7827, 0x2dbe, 2), 20: ('Python', 347, 0x2dc9, 4, 7828, 0x2dc7, 2),
    21: ('Shotgun', 349, 0x2de6, 3, 7830, 0x2de3, 3), 22: ('Spas12Shotgun', 350, 0x2df0, 3, 7831, 0x2dee, 2),
    23: ('StubbyShotgun', 351, 0x2dfd, 2, 7832, 0x2dfb, 2), 24: ('Tec9', 353, 0x2e06, 4, 7834, 0x2e04, 2),
    25: ('Uzi', 354, 0x2e15, 3, 7835, 0x2e13, 2), 26: ('SilencedIngram', 355, 0x2e1a, 3, 7836, 0x2e18, 2),
    27: ('Mp5', 356, 0x2e1f, 4, 7837, 0x2e1d, 2), 28: ('m4', 352, 0x2e01, 3, 7833, 0x2dff, 2),
    29: ('Ruger', 348, 0x2dd5, 4, 7829, 0x2dd3, 2), 30: ('SniperRifle', 357, 0x2e25, 4, 7838, 0x2e23, 2),
    31: ('LaserScope', 358, 0x2e2f, 5, 7839, 0x2e2c, 3), 32: ('RocketLauncher', 359, 0x2e36, 3, 7840, 0x2e34, 2),
    33: ('FlameThrower', 360, 0x2e3e, 6, 7841, 0x2e3c, 2), 34: ('M60', 361, 0x2e48, 5, 7842, 0x2e46, 2),
    35: ('Minigun', 362, 0x2e53, 4, 7843, 0x2e50, 3), 36: ('Detonator', 363, 0x2e59, 2, 7844, 0x2e57, 2),
    38: ('Camera', 364, 0x2e5e, 3, 7845, 0x2e5b, 3), 39: ('Binoculars', 367, 0x2fc1, 3, 7848, 0x2fbd, 4),
    # the minigun's spinning barrels: CWeaponInfo +0x64 of type 35 (model info +0x1E: dictionary slot 313)
    135: ('MinigunBarrels', 366, 0x2fbb, 2, 7847, 0x2fb8, 3),
}

# The Immersive Weapons Pack (2.5.1) -> VCS weapon types: (DFF, TXD, options) relative to its modloader folder. Only
# weapons VCS has; the pack's Silenced, Cuntgun, pool cue, shovel and the rest have no VCS counterpart. Options: tris
# (the triangle budget), offset (x, y, z m: after the SA model is put in VCS's frame), skip (frame names left out),
# keep (only these frames), local (parts in their own frames), rotate (degrees about the model's axes), atlas (the baked
# texture's size). Placements were fitted against VCS's own models (side views, a chamfer fit of the grip region for
# guns and of the whole shape with a rotation for the rest) and checked in the game (docs/game-internals.md 12g).
_A, _M, _T, _I = "I - Base/Animated Weapons/", "I - Base/Melee Weapons/", "I - Base/Misc Weapons/", \
    "II - Pickups and Misc (Ezekiel)/Gameplay  weapons - items/"
_G = (0.06, 0.0, 0.025)  # SA's grip -> VCS's: the median of the guns fitted at the grip (game-internals.md 12g)
PACK = {
    1: (_I + "brassknuckle.dff", _I + "brassknuckle.txd", dict(tris=600, offset=(0.040, 0.009, 0.012), atlas=(128, 64))),
    3: (_M + "Golfclub/golfclub.dff", _M + "Golfclub/golfclub.txd", dict(tris=700, rotate="y:21.4", offset=(0.001, 0, -0.046))),
    4: (_M + "Nitestick/nitestick.dff", _M + "Nitestick/nitestick.txd", dict(tris=500, rotate="y:-3", offset=(0.032, 0, 0.144),
                                                                          atlas=(128, 64))),
    5: (_M + "Knifecur/knifecur.dff", _M + "Knifecur/knifecur.txd", dict(tris=700, rotate="y:11.6", offset=(0.040, 0, 0.046))),
    6: (_M + "Bat/bat.dff", _M + "Bat/bat.txd", dict(tris=600, rotate="y:18.4", offset=(0.050, 0, 0.109))),
    10: (_M + "Katana/katana.dff", _M + "Katana/katana.txd", dict(tris=900, rotate="y:18.4", offset=(0.048, 0, 0.064))),
    11: (_M + "Chnsaw/chnsaw.dff", _M + "Chnsaw/chnsaw.txd", dict(tris=1500, rotate="y:9.8", offset=(0.022, 0, 0.075),
                                                                  atlas=(256, 128))),
    12: (_T + "Grenade/grenade.dff", _T + "Grenade/grenade.txd", dict(tris=600, rotate="y:-30.6", offset=(0.068, 0, 0.003),
                                                                      atlas=(128, 64))),
    16: (_T + "Tear Gas/teargas.dff", _T + "Tear Gas/teargas.txd", dict(tris=600, rotate="y:2.1", offset=(0.054, 0, 0.020),
                                                                        atlas=(128, 64))),
    17: (_T + "Molotov/molotov.dff", _T + "Molotov/molotov.txd", dict(tris=500, rotate="y:6.8", offset=(0.072, 0, 0.154),
                                                                      atlas=(128, 64))),
    18: (_I + "missile.dff", _I + "missile.txd", dict(tris=600, rotate="z:180", offset=(-0.003, -0.026, -0.002), atlas=(128, 64))),
    19: (_A + "Colt45/colt45.dff", _A + "Colt45/colt45.txd", dict(tris=1300, prefix="c45_", offset=(0.059, 0, 0.021), atlas=(256, 128))),
    20: (_A + "Desert Eagle/desert_eagle.dff", _A + "Desert Eagle/desert_eagle.txd", dict(tris=1300, prefix="deg_", offset=_G, atlas=(256, 128))),
    21: (_A + "Chromegun/chromegun.dff", _A + "Chromegun/chromegun.txd", dict(tris=1500, prefix="chg_", offset=(0.088, 0, 0.009),
                                                                              atlas=(256, 128))),
    22: (_A + "Shotgspa/shotgspa.dff", _A + "Shotgspa/shotgspa.txd", dict(tris=1500, prefix="spa_", offset=_G, atlas=(256, 128))),
    23: (_A + "Sawned Off/sawnoff.dff", _A + "Sawned Off/sawnoff.txd", dict(tris=1300, prefix="saw_", offset=(0.109, 0, 0.034),
                                                                          atlas=(256, 128))),
    24: (_A + "Tec9/tec9.dff", _A + "Tec9/tec9.txd", dict(tris=1300, prefix="tec_", offset=(0.064, 0, 0.043), atlas=(256, 128))),
    25: (_A + "Micro Uzi/micro_uzi.dff", _A + "Micro Uzi/micro_uzi.txd", dict(tris=1300, prefix="uzi_", offset=(0.043, 0, 0.029), atlas=(256, 128))),
    27: (_A + "MP5/mp5lng.dff", _A + "MP5/mp5lng.txd", dict(tris=1500, prefix="mp5_", offset=(0.044, 0, 0.024), atlas=(256, 128))),
    28: (_A + "M4/m4.dff", _A + "M4/m4.txd", dict(tris=1700, prefix="m4_", offset=(0.022, 0, -0.017), atlas=(256, 128))),
    29: (_A + "AK-47/ak47.dff", _A + "AK-47/ak47.txd", dict(tris=1700, prefix="ak_", offset=(0.065, 0, 0.025), atlas=(256, 128))),
    30: (_A + "Sniper/sniper.dff", _A + "Sniper/sniper.txd", dict(tris=1700, prefix="snp_", offset=(0.030, 0, 0.030),
                                                                  atlas=(256, 128))),
    32: (_A + "Rocket Launcher/rocketla.dff", _A + "Rocket Launcher/rocketla.txd", dict(tris=1400, prefix="rpg_", offset=_G,
                                                                                      atlas=(256, 128))),
    33: (_I + "flame.dff", _I + "flame.txd", dict(tris=1400, rotate="y:19.5", offset=(0.066, 0, 0.137), atlas=(256, 128))),
    35: (_I + "minigun.dff", _I + "minigun.txd", dict(tris=1400, keep="minigun", rotate="y:30.2", offset=(0.040, 0, 0.183),
                                                      atlas=(256, 128))),
    # the barrels spin about their own x axis at a place the game's code gives: in their own frame, the front end at
    # VCS's (its model: x -0.456 .. 0.017, the axis through the origin)
    135: (_I + "minigun.dff", _I + "minigun.txd", dict(tris=500, keep="minigun2", prefix="iwp2_", local=True,
                                                       offset=(-0.298, 0.005, 0.005), atlas=(128, 64))),
    36: (_I + "bomb.dff", _I + "bomb.txd", dict(tris=600, rotate="z:42.8", offset=(0.085, -0.004, 0.038), atlas=(128, 64))),
    38: (_I + "camera.dff", _I + "camera.txd", dict(tris=800, rotate="y:-12.6", offset=(0.044, 0, 0.011))),
}

def read_img(iso_path, pos, sectors):
    """sectors of GTA3PS2.IMG from the disc image"""
    import vcs_disc
    iso = vcs_disc.IsoImage(iso_path)
    rec = iso.find("GTA3PS2.IMG")
    return iso.read_sectors(rec["lba"] + pos, sectors)

class Chunk:
    """A Leeds relocatable chunk under construction: data from 0x20, pointers recorded for the relocation table."""
    def __init__(self):
        self.b = bytearray(0x20)
        self.relocs = []
    def align(self, n):
        while len(self.b) % n:
            self.b.append(0)
        return len(self.b)
    def alloc(self, size, align=4):
        o = self.align(align)
        self.b += bytes(size)
        return o
    def w32(self, o, v): struct.pack_into("<I", self.b, o, v & 0xFFFFFFFF)
    def ptr(self, o, target):
        self.w32(o, target)
        self.relocs.append(o)
    def finish(self, ident, funcs=()):
        data_end = self.align(4)
        glob = data_end
        for f in funcs:  # function-pointer slots the loader fills (the global table)
            self.relocs.insert(0, len(self.b))
            self.b += struct.pack("<I", f)
        reloc = len(self.b)
        for r in self.relocs:
            self.b += struct.pack("<I", r)
        return glob, data_end, reloc

# ---- textures ------------------------------------------------------------------------------------------------------
def quantize(rgba, n=256):
    keys = Counter()
    px = []
    for i in range(0, len(rgba), 4):
        k = (rgba[i] >> 3, rgba[i + 1] >> 3, rgba[i + 2] >> 3, rgba[i + 3] >> 5)
        px.append(k)
        keys[k] += 1
    def stats(bx):
        rng = [max(c[0][j] for c in bx) - min(c[0][j] for c in bx) for j in range(4)]
        ch = max(range(4), key=lambda j: rng[j])
        return rng[ch] * sum(c[1] for c in bx) if len(bx) > 1 else -1, ch
    boxes = [(list(keys.items()),) + stats(list(keys.items()))]
    while len(boxes) < n:
        i = max(range(len(boxes)), key=lambda k: boxes[k][1])
        bx, score, ch = boxes[i]
        if score <= 0:
            break
        bx = sorted(bx, key=lambda c: c[0][ch])
        tot, acc, cut = sum(c[1] for c in bx), 0, 1
        for j, c in enumerate(bx):
            acc += c[1]
            if acc * 2 >= tot:
                cut = max(1, min(len(bx) - 1, j + 1))
                break
        a, b = bx[:cut], bx[cut:]
        boxes[i:i + 1] = [(a,) + stats(a), (b,) + stats(b)]
    pal, lut = [], {}
    for bx, _, _ in boxes:
        tot = sum(c[1] for c in bx)
        col = [sum(c[0][j] * c[1] for c in bx) / tot for j in range(4)]
        for c in bx:
            lut[c[0]] = len(pal)
        pal.append((round(col[0] * 255 / 31), round(col[1] * 255 / 31), round(col[2] * 255 / 31), round(col[3] * 255 / 7)))
    while len(pal) < 256:
        pal.append((0, 0, 0, 255))
    return pal, bytes(lut[k] for k in px)

def csm1(i):
    return (i & 0xE7) | ((i & 0x08) << 1) | ((i & 0x10) >> 1)

def t8_raster(w, h, rgba):
    pal, idx = quantize(rgba)
    clut = bytearray(1024)
    for i, (r, g, b, a) in enumerate(pal):
        clut[csm1(i) * 4:csm1(i) * 4 + 4] = bytes((r, g, b, (a * 128 + 127) // 255))
    flags = int(math.log2(w)) | int(math.log2(h)) << 6 | 8 << 12 | 1 << 20
    return {"w4": 0x00250000 | w, "flags": flags, "data": idx + bytes(clut)}

def downscale(w, h, rgba, size):
    """box filter down to at most size x size"""
    w2, h2 = w, h
    while max(w2, h2) > size:
        w2, h2 = max(1, w2 // 2), max(1, h2 // 2)
    if (w2, h2) == (w, h):
        return w, h, rgba
    fx, fy = w // w2, h // h2
    out = bytearray(w2 * h2 * 4)
    n = fx * fy
    for y in range(h2):
        for x in range(w2):
            for c in range(4):
                out[(y * w2 + x) * 4 + c] = sum(rgba[((y * fy + j) * w + x * fx + i) * 4 + c] for j in range(fy) for i in range(fx)) // n
    return w2, h2, bytes(out)

def read_xet(d):
    """The textures of a VCS 'xet' chunk: [(name, w4, flags, pixels + CLUT)]"""
    out = []
    head = 0x28
    p = u32(d, head)
    while p != head:
        t = p - 8
        r = u32(d, t)
        name = d[t + 0x10:t + 0x30].split(b"\0")[0]
        w4, dp, fl = u32(d, r + 4), u32(d, r + 8), u32(d, r + 12)
        depth, lw, lh, mips = (fl >> 12) & 0x3F, fl & 0x3F, (fl >> 6) & 0x3F, (fl >> 20) & 0xF
        size = sum(((depth << lw) >> 3 << lh) >> (2 * m) for m in range(mips)) + (64 if depth == 4 else 1024)
        out.append((name, w4, fl, d[dp:dp + size]))
        p = u32(d, p)
    return out

def build_xet(textures):
    c = Chunk()
    dic = c.alloc(16, 16)
    c.w32(dic, 0x00008606)
    c.alloc(16, 16)
    data_at = []
    for name, w4, fl, data in textures:
        data_at.append(c.alloc(len(data), 16))
        c.b[data_at[-1]:data_at[-1] + len(data)] = data
    texs = [c.alloc(0x60, 16) for _ in textures]
    rasters = [c.alloc(0x10, 16) for _ in textures]
    n = len(textures)
    for i, (name, w4, fl, data) in enumerate(textures):
        t, r = texs[i], rasters[i]
        c.ptr(t, r)
        c.ptr(t + 4, dic)
        c.ptr(t + 8, texs[i + 1] + 8 if i + 1 < n else dic + 8)   # link next
        c.ptr(t + 12, texs[i - 1] + 8 if i > 0 else dic + 8)      # link prev
        c.b[t + 0x10:t + 0x10 + len(name)] = name
        c.w32(t + 0x50, 1)
        c.w32(r + 4, w4)
        c.ptr(r + 8, data_at[i])
        c.w32(r + 12, fl)
    c.ptr(dic + 8, texs[0] + 8)
    c.ptr(dic + 12, texs[-1] + 8)
    glob, data_end, reloc = c.finish(b"xet\0")
    hdr = struct.pack("<4sIIIIIIHH", b"xet\0", 0, len(c.b), data_end, reloc, len(c.relocs), 0, 0, 0)
    c.b[0:0x20] = hdr
    return bytes(c.b)

# ---- geometry ------------------------------------------------------------------------------------------------------
def stripify(tris):
    edges = defaultdict(list)
    for t, (a, b, c) in enumerate(tris):
        for x, y in ((a, b), (b, c), (c, a)):
            edges[(x, y) if x < y else (y, x)].append(t)
    used = [False] * len(tris)
    def free_on(x, y):
        for t in edges[(x, y) if x < y else (y, x)]:
            if not used[t]:
                return t
        return None
    # start from triangles with few neighbours (strip ends)
    order = sorted(range(len(tris)), key=lambda t: sum(len(edges[(x, y) if x < y else (y, x)]) for x, y in
                                                       ((tris[t][0], tris[t][1]), (tris[t][1], tris[t][2]), (tris[t][2], tris[t][0]))))
    strips = []
    for s in order:
        if used[s]:
            continue
        used[s] = True
        a, b, c = tris[s]
        strip = [a, b, c]
        for rot in ((a, b, c), (b, c, a), (c, a, b)):
            if free_on(rot[1], rot[2]) is not None:
                strip = list(rot)
                break
        while True:
            t = free_on(strip[-2], strip[-1])
            if t is None:
                break
            z = [v for v in tris[t] if v != strip[-2] and v != strip[-1]]
            used[t] = True
            if len(z) != 1:
                continue
            strip.append(z[0])
        strips.append(strip)
    seq = []
    for s in strips:
        if seq:
            seq += [seq[-1], s[0]]
        seq += s
    return seq, len(strips)

def stripify2(tris):
    """Greedy strips with swaps: from the last triangle (x, y, z) a strip goes on across (y, z) with one vertex, or
    across (x, z) with two (x again: the triangle drawn twice - weapons are opaque and not culled - then the new one);
    a new strip costs four (two to close the old one with degenerate triangles, two to open). Starts and choices
    prefer triangles with few free neighbours, so none are left alone. -> (sequence, strip count)"""
    edges = defaultdict(list)
    for t, (a, b, c) in enumerate(tris):
        for x, y in ((a, b), (b, c), (c, a)):
            edges[(x, y) if x < y else (y, x)].append(t)
    used = [False] * len(tris)
    def nbrs(t):
        a, b, c = tris[t]
        return [u for x, y in ((a, b), (b, c), (c, a)) for u in edges[(x, y) if x < y else (y, x)] if u != t]
    def free_count(t):
        return sum(1 for u in nbrs(t) if not used[u])
    def best_on(x, y):
        best = None
        for t in edges[(x, y) if x < y else (y, x)]:
            if not used[t]:
                f = free_count(t)
                if best is None or f < best[0]:
                    best = (f, t)
        return best[1] if best else None
    def third(t, x, y):
        for v in tris[t]:
            if v != x and v != y:
                return v
        return None
    buckets = defaultdict(set)
    for t in range(len(tris)):
        buckets[free_count(t)].add(t)
    seq, nstrips, left = [], 0, len(tris)
    while left:
        start = None
        for k in sorted(buckets):
            while buckets[k]:
                t = buckets[k].pop()
                if not used[t]:
                    start = t
                    break
            if start is not None:
                break
        if start is None:
            break
        a, b, c = tris[start]
        strip = [a, b, c]
        for r in ((a, b, c), (b, c, a), (c, a, b)):
            if best_on(r[1], r[2]) is not None:
                strip = list(r)
                break
        used[start] = True
        left -= 1
        touched = set(nbrs(start))
        while True:
            x, y, z = strip[-3], strip[-2], strip[-1]
            t = best_on(y, z)
            if t is not None:
                strip.append(third(t, y, z))
            else:
                t = best_on(x, z)
                if t is None:
                    break
                strip += [x, third(t, x, z)]
            used[t] = True
            left -= 1
            touched.update(nbrs(t))
        for u in touched:  # their free-neighbour counts dropped
            if not used[u]:
                buckets[free_count(u)].add(u)
        if seq:
            seq += [seq[-1], strip[0]]
        seq += strip
        nstrips += 1
    return seq, nstrips

def pow2_at_least(x):
    p = 1.0 / 1024
    while p < x:
        p *= 2
    return p

def vcs_box(d):
    """The original model's vertex box from its geometry header: (min, max)"""
    el = u32(d, 0x20)
    g = u32(d, el + 0x14) + 0x20
    bb = struct.unpack_from("<6h", d, g + 0x1C)
    sc = struct.unpack_from("<3f", d, g + 0x28)
    po = struct.unpack_from("<3f", d, g + 0x34)
    return [po[i] + sc[i] * bb[i] / 32768 for i in range(3)], [po[i] + sc[i] * bb[3 + i] / 32768 for i in range(3)]

def batch_packet(verts):
    """VIF data of one batch (as VCS's weapons): header, positions, uv, normals, MSCAL 6"""
    n = len(verts)
    out = bytearray()
    out += struct.pack("<I4I", 0x6C018000, 0, 0, n, n | 0x8000)
    out += struct.pack("<II", 0x20000000, 0x40404040)
    out += struct.pack("<I4I", 0x30000000, 0, 0, 0, 0)
    out += struct.pack("<I", 0x79008001 | n << 16)
    pos = b"".join(struct.pack("<3h", *v[0]) for v in verts)
    out += pos + bytes(-len(pos) & 3)
    out += struct.pack("<II", 0x20000000, 0x50505050)
    out += struct.pack("<I4I", 0x30000000, 0, 0, 0xFF, 0)
    out += struct.pack("<I", 0x7600C08D | n << 16)
    uv = b"".join(struct.pack("<2B", *v[1]) for v in verts)
    out += uv + bytes(-len(uv) & 3)
    out += struct.pack("<I", 0x6A008047 | n << 16)
    nr = b"".join(struct.pack("<3b", *v[2]) for v in verts)
    out += nr + bytes(-len(nr) & 3)
    out += struct.pack("<I", 0x14000006)
    return out

def quantizer(allp):
    lo = [min(p[i] for p in allp) for i in range(3)]
    hi = [max(p[i] for p in allp) for i in range(3)]
    centre = [(lo[i] + hi[i]) / 2 for i in range(3)]
    scale = [pow2_at_least((hi[i] - lo[i]) / 2 * 1.0001) for i in range(3)]
    def q(p):
        return tuple(max(-32768, min(32767, round((p[i] - centre[i]) / scale[i] * 32768))) for i in range(3))
    return centre, scale, q

def uv_params(uvs):
    us = [u for u, v in uvs]; vs = [v for u, v in uvs]
    su, sv = math.floor(min(us)), math.floor(min(vs))
    return su, sv, max(max(us) - su, 1e-3) / 2, max(max(vs) - sv, 1e-3) / 2

def uv8(uv, prm):
    su, sv, ku, kv = prm
    return (min(255, max(0, round((uv[0] - su) / ku * 127.5))), min(255, max(0, round((uv[1] - sv) / kv * 127.5))))

def build_mdl(groups, model_id, colour, mesh_w, packet=None, geo_flags=7):
    """groups: [(texture name, [(pos xyz float, uv, normal)] strip sequence, uv params)]. packet / geo_flags: another
    vertex layout (tools/veg_convert.py: prelit map objects, the third element a 16-bit colour, flags 0xD)"""
    packet = packet or batch_packet
    allp = [v[0] for _, seq, _ in groups for v in seq]
    centre, scale, q = quantizer(allp)
    def sphere(ps):
        l = [min(p[i] for p in ps) for i in range(3)]; h = [max(p[i] for p in ps) for i in range(3)]
        c = [(l[i] + h[i]) / 2 for i in range(3)]
        return c + [max(math.dist(c, p) for p in ps)]
    c = Chunk()
    root = c.alloc(4)
    mats = c.alloc(4 * len(groups))
    matrec = [c.alloc(16) for _ in groups]
    el = c.alloc(0x38, 16)
    fr = c.alloc(0xB0, 16)
    geo = c.alloc(0x20, 16)
    ps2 = c.alloc(0x40 + 0x30 * len(groups), 16)
    names = []
    c.ptr(root, el)
    for i, (tex, seq, _) in enumerate(groups):
        c.ptr(mats + 4 * i, matrec[i])
        names.append((matrec[i], tex))
        c.w32(matrec[i] + 4, colour)
        c.w32(matrec[i] + 8, 2)
    c.w32(el, 0x0004AA01)
    c.ptr(el + 4, fr)
    c.ptr(el + 8, fr + 8)
    c.ptr(el + 12, fr + 8)
    c.ptr(el + 0x14, geo)
    struct.pack_into("<H", c.b, el + 0x28, model_id)
    c.w32(fr, 0x0300AA00)
    c.ptr(fr + 8, el + 8)
    c.ptr(fr + 12, el + 8)
    for m in (fr + 0x10, fr + 0x50):
        struct.pack_into("<16f", c.b, m, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
        c.w32(m + 0x3C, 1)
    c.ptr(fr + 0x98, fr)
    c.w32(fr + 0x9C, 0xAAAAAAAA)
    c.w32(fr + 0xA0, 0xFFFFFFFF)
    c.w32(geo, 8)
    c.w32(geo + 8, 1)
    c.ptr(geo + 0x0C, mats)
    c.w32(geo + 0x10, len(groups))
    c.w32(geo + 0x14, max(0x10, len(groups)))
    first_packet = c.align(16)
    total = 0
    qall = []
    for i, (tex, seq, prm) in enumerate(groups):
        mh = ps2 + 0x40 + 0x30 * i
        qs = [q(v[0]) for v in seq]
        qall += qs
        su, sv, ku, kv = prm
        verts = [(qs[k], uv8(v[1], prm), v[2]) for k, v in enumerate(seq)]
        pkt = bytearray()
        start = 0
        while start < len(verts) - 2:
            pkt += packet(verts[start:start + 70])
            start += 68
        pkt += bytes(-(len(pkt)) & 15)
        tag = c.alloc(16, 16)
        c.w32(tag, 0x60000000 | len(pkt) // 16)
        at = c.alloc(len(pkt), 16)
        c.b[at:at + len(pkt)] = pkt
        struct.pack_into("<4f", c.b, mh, *sphere([v[0] for v in seq]))
        struct.pack_into("<2f", c.b, mh + 0x10, ku, kv)
        c.w32(mh + 0x18, mesh_w)
        c.w32(mh + 0x1C, tag - first_packet)
        struct.pack_into("<Hh", c.b, mh + 0x20, len(seq) - 2, i)
        struct.pack_into("<6h", c.b, mh + 0x24, *[min(p[j] for p in qs) for j in range(3)], *[max(p[j] for p in qs) for j in range(3)])
        total += len(seq)
    end = c.align(16)
    struct.pack_into("<4f", c.b, ps2, *sphere(allp))
    c.w32(ps2 + 0x10, len(groups) << 20 | (end - ps2))
    c.w32(ps2 + 0x14, geo_flags)
    struct.pack_into("<HH", c.b, ps2 + 0x18, total, 0x40 + 0x30 * len(groups))
    struct.pack_into("<6h", c.b, ps2 + 0x1C, *[min(p[j] for p in qall) for j in range(3)], *[max(p[j] for p in qall) for j in range(3)])
    struct.pack_into("<3f", c.b, ps2 + 0x28, *scale)
    struct.pack_into("<3f", c.b, ps2 + 0x34, *centre)
    c.relocs += [at for at, _ in names]  # the materials' texture-name pointers
    glob, data_end, reloc = c.finish(b"ldm\0", funcs=[el + 0x24])
    for at, tex in names:  # texture names after the relocation table, as in the game's models
        o = len(c.b)
        c.b += tex.encode("latin1") + b"\0"
        c.w32(at, o)
    c.b[0:0x20] = struct.pack("<4sIIIIIIHH", b"ldm\0", 0, len(c.b), data_end, reloc, len(c.relocs), glob, 0, 1)
    return bytes(c.b), total, end - first_packet

# ---- the SA model: parts, welding, simplification, normals -------------------------------------------------------
def rotation(spec):
    """'z:180,x:90' -> 3x3 matrix (rows), applied as p' = p R (row vectors, as RW)"""
    m = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for item in filter(None, (s.strip() for s in (spec or "").split(","))):
        ax, deg = item.split(":")
        a = math.radians(float(deg))
        c, s = math.cos(a), math.sin(a)
        r = {"x": [[1, 0, 0], [0, c, s], [0, -s, c]], "y": [[c, 0, -s], [0, 1, 0], [s, 0, c]],
             "z": [[c, s, 0], [-s, c, 0], [0, 0, 1]]}[ax.lower()]
        m = [[sum(m[i][k] * r[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return m

def load_parts(path, skip=(), keep=(), log=print, local=False):
    """the SA model's triangles in its root frame (local: each part in its own frame): [(texture, (p0, p1, p2),
    (uv0, uv1, uv2))]"""
    frames, geoms, atomics = rwdff.parse_dff(path)
    out, seen = [], set()
    for at in atomics:
        fname = frames[at["frame"]]["name"].strip("\0 \t").lower()
        g = geoms[at["geometry"]]
        if (keep and fname not in keep) or fname in skip:
            log("  part %-16s %6d tris - left out" % (fname, len(g.tris)))
            continue
        m = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]] if local else rwdff.ltm(frames, at["frame"])
        key = (at["geometry"], tuple(round(x, 4) for row in m for x in row))
        if key in seen:
            log("  part %-16s %6d tris - a duplicate, left out" % (fname, len(g.tris)))
            continue
        seen.add(key)
        n = 0
        for (v0, v1, v2, mi) in g.tris:
            if v0 == v1 or v1 == v2 or v0 == v2:
                continue
            tex = (g.materials[mi]["texture"] or "none").lower()
            ps, uvs = [], []
            for v in (v0, v1, v2):
                p = g.pos[v]
                ps.append(tuple(p[0] * m[0][c] + p[1] * m[1][c] + p[2] * m[2][c] + m[3][c] for c in range(3)))
                uvs.append(tuple(g.uv[v]) if g.uv else (0.0, 0.0))
            out.append((tex, tuple(ps), tuple(uvs)))
            n += 1
        log("  part %-16s %6d tris" % (fname, n))
    return out

def weld(tris, eps=1e-5):
    """positions welded within eps, wedges = (position, u, v, texture); exact duplicate triangles dropped"""
    pidx, P, widx, W, T, seen = {}, [], {}, [], [], set()
    for tex, ps, uvs in tris:
        t = []
        for p, uv in zip(ps, uvs):
            pk = (round(p[0] / eps), round(p[1] / eps), round(p[2] / eps))
            pi = pidx.get(pk)
            if pi is None:
                pi = pidx[pk] = len(P)
                P.append(p)
            wk = (pi, round(uv[0] * 65536), round(uv[1] * 65536), tex)
            wi = widx.get(wk)
            if wi is None:
                wi = widx[wk] = len(W)
                W.append((pi, uv[0], uv[1], tex))
            t.append(wi)
        if len({W[w][0] for w in t}) < 3:
            continue
        k = min((t[0], t[1], t[2]), (t[1], t[2], t[0]), (t[2], t[0], t[1]))
        if k in seen:
            continue
        seen.add(k)
        T.append(t)
    return P, W, T

def corner_normals(P, W, T, crease=50.0):
    """smooth normals per triangle corner: the area-weighted normals of the triangles around the corner's position
    within `crease` degrees of this triangle's"""
    fn, unit = [], []
    for t in T:
        a, b, c = (P[W[w][0]] for w in t)
        e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2]); e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        l = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1e-20
        fn.append(n); unit.append((n[0] / l, n[1] / l, n[2] / l))
    around = defaultdict(list)
    for i, t in enumerate(T):
        for w in t:
            around[W[w][0]].append(i)
    cc = math.cos(math.radians(crease))
    out = []
    for i, t in enumerate(T):
        ni = unit[i]
        res = []
        for w in t:
            s = [0.0, 0.0, 0.0]
            for j in around[W[w][0]]:
                u = unit[j]
                if ni[0] * u[0] + ni[1] * u[1] + ni[2] * u[2] >= cc:
                    n = fn[j]
                    s[0] += n[0]; s[1] += n[1]; s[2] += n[2]
            l = math.sqrt(s[0] * s[0] + s[1] * s[1] + s[2] * s[2]) or 1.0
            res.append(tuple(max(-127, min(127, round(x / l * 127))) for x in s))
        out.append(res)
    return out

def tri_area(a, b, c):
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2]); e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
    return math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) / 2

def grouped_normals(P, T, crease=50.0):
    """normals per triangle corner: at each position the triangles are grouped by facing (within `crease` degrees of a
    group's first), each group gets one area-weighted normal - corners of a group share it, so strips share them"""
    fn = []
    for t in T:
        a, b, c = P[t[0]], P[t[1]], P[t[2]]
        e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2]); e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        fn.append((e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]))
    def unit(n):
        l = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1e-20
        return (n[0] / l, n[1] / l, n[2] / l)
    around = defaultdict(list)
    for i, t in enumerate(T):
        for k, v in enumerate(t):
            around[v].append((i, k))
    cc = math.cos(math.radians(crease))
    out = [[None, None, None] for _ in T]
    for v, corners in around.items():
        groups = []  # [seed unit normal, summed normal, corners]
        for i, k in corners:
            u = unit(fn[i])
            for g in groups:
                if g[0][0] * u[0] + g[0][1] * u[1] + g[0][2] * u[2] >= cc:
                    g[1] = [g[1][0] + fn[i][0], g[1][1] + fn[i][1], g[1][2] + fn[i][2]]
                    g[2].append((i, k))
                    break
            else:
                groups.append([u, list(fn[i]), [(i, k)]])
        for _, s, cs in groups:
            n = unit(s)
            n8 = tuple(max(-127, min(127, round(x * 127))) for x in n)
            for i, k in cs:
                out[i][k] = n8
    return out

def drop_back_faces(P, T):
    """Double-sided faces - a back layer lying on the front, facing the other way, often triangulated on its own and
    meeting it along shared edges - make those edges non-manifold and stop the simplifier, and cost twice. A triangle
    with an opposite-facing triangle in its plane over it (the other's centroid inside it, or its inside the other)
    is half of such a pair; of each pair the one facing the model's centre goes (weapons are drawn without culling)."""
    import mesh_bake
    def unit(t):
        a, b, c = P[t[0]], P[t[1]], P[t[2]]
        e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2]); e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        l = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1e-20
        return (n[0] / l, n[1] / l, n[2] / l)
    un = [unit(t) for t in T]
    tp = [tuple(P[v] for v in t) for t in T]
    cen = [tuple(sum(p[k] for p in ps) / 3 for k in range(3)) for ps in tp]
    lo = [min(p[k] for p in P) for k in range(3)]; hi = [max(p[k] for p in P) for k in range(3)]
    ctr = [(lo[k] + hi[k]) / 2 for k in range(3)]
    ext = max(hi[k] - lo[k] for k in range(3))
    eps = 2e-4 * ext
    grid = mesh_bake.Grid(tp, ext / 128)

    def inside(c, i):
        """c in triangle i's plane and within it"""
        a, b, d = tp[i]
        n = un[i]
        if abs((c[0] - a[0]) * n[0] + (c[1] - a[1]) * n[1] + (c[2] - a[2]) * n[2]) > eps:
            return False
        _, w = mesh_bake.closest_on_triangle(c, a, b, d)
        q = tuple(a[k] * w[0] + b[k] * w[1] + d[k] * w[2] for k in range(3))
        return math.dist(q, c) <= eps

    drop = set()
    for i in range(len(T)):
        c = cen[i]
        for j in grid.box([x - eps for x in c], [x + eps for x in c]):
            if j == i or j in drop or i in drop:
                continue
            if un[i][0] * un[j][0] + un[i][1] * un[j][1] + un[i][2] * un[j][2] > -0.9:
                continue
            if not (inside(c, j) or inside(cen[j], i)):
                continue
            for k in (i, j):
                d = [cen[k][m] - ctr[m] for m in range(3)]
                if d[0] * un[k][0] + d[1] * un[k][1] + d[2] * un[k][2] < 0:
                    drop.add(k)
    return [t for i, t in enumerate(T) if i not in drop], len(drop)

def components(T, npos):
    """connected pieces (through shared positions): the triangle lists"""
    parent = list(range(npos))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, c in T:
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[find(rc)] = ra
    out = defaultdict(list)
    for i, t in enumerate(T):
        out[find(t[0])].append(i)
    return list(out.values())

def convert_baked(parts, txd, vd, xd, model_id, out_mdl, out_xet, tris, prefix, atlas, crease, min_part, log):
    """the simplified mesh with an atlas of its own, the detailed model's textures baked onto it (tools/mesh_bake.py)"""
    import mesh_bake
    pidx, P, T, seen = {}, [], [], set()
    for tex, ps, uvs in parts:
        t = []
        for p in ps:
            k = (round(p[0] * 1e5), round(p[1] * 1e5), round(p[2] * 1e5))
            if k not in pidx:
                pidx[k] = len(P)
                P.append(p)
            t.append(pidx[k])
        if len(set(t)) == 3:
            key = frozenset(t)  # a duplicate, or the back of a double-sided face: weapons are drawn without culling
            if key not in seen:
                seen.add(key)
                T.append(t)
    ext = max(max(p[k] for p in P) - min(p[k] for p in P) for k in range(3))
    T, backs = drop_back_faces(P, T)
    if backs:
        log("  %d back faces of double-sided surfaces left out" % backs)
    # small separate pieces (screws, pins) only in the texture: the bake paints them where they sat
    keepT, dropped = [], 0
    for comp in components(T, len(P)):
        ps = [P[v] for i in comp for v in T[i]]
        diag = math.dist([min(p[k] for p in ps) for k in range(3)], [max(p[k] for p in ps) for k in range(3)])
        if diag < min_part * ext:
            dropped += len(comp)
        else:
            keepT += [T[i] for i in comp]
    log("  welded: %d positions, %d triangles (%d in small pieces, left to the texture)" % (len(P), len(T), dropped))
    T = keepT
    if tris and len(T) > tris:
        m = mesh_simplify.Mesh(P, [(i, 0.0, 0.0, "") for i in range(len(P))], T, free_corners=True)
        m.simplify(tris)
        P2, W2, T = m.compact()
        P = P2
        T = [[W2[w][0] for w in t] for t in T]
        log("  simplified to %d triangles (budget %d)" % (len(T), tris))
    charts = mesh_bake.make_charts(P, T)
    aw, ah = atlas
    s, place = mesh_bake.pack(charts, P, T, aw, ah)
    log("  %d charts in a %dx%d atlas, %.0f texels per metre" % (len(charts), aw, ah, s))
    textures = rwtxd.read_txd(txd, 512)
    rgba, _ = mesh_bake.bake(P, T, charts, place, s, aw, ah, parts, textures, reach=0.012 * ext, log=log)
    N = grouped_normals(P, T, crease)
    weldv, rep, tl = {}, [], []
    for cid, (label, members) in enumerate(charts):
        for i in members:
            t = []
            for k, v in enumerate(T[i]):
                x, y = mesh_bake.chart_uv(P[v], label, place[cid], s)
                key = (v, cid, N[i][k])
                if key not in weldv:
                    weldv[key] = len(rep)
                    rep.append((P[v], (x / aw, y / ah), N[i][k]))
                t.append(weldv[key])
            tl.append(tuple(t))
    prm = (0, 0, max(v[1][0] for v in rep) / 2, max(v[1][1] for v in rep) / 2)
    seq_idx, nstrips = stripify2(tl)
    name = (prefix + "atlas")[:31]
    log("  %d tris %d verts -> %d strips, %d strip verts (%.2f / tri)" % (len(tl), len(rep), nstrips, len(seq_idx),
                                                                         len(seq_idx) / max(1, len(tl))))
    el = u32(vd, 0x20); geo = u32(vd, el + 0x14); mat0 = u32(vd, u32(vd, geo + 0x0C))
    mdl, total, pk = build_mdl([(name, [rep[i] for i in seq_idx], prm)], model_id, u32(vd, mat0 + 4),
                               u32(vd, geo + 0x20 + 0x40 + 0x18))
    with open(out_mdl, "wb") as f:
        f.write(mdl)
    r = t8_raster(aw, ah, rgba)
    xet = build_xet(read_xet(xd) + [(name.encode("latin1"), r["w4"], r["flags"], r["data"])])
    with open(out_xet, "wb") as f:
        f.write(xet)
    log("  model: %d tris, %d strip verts, %d bytes (%d sectors); textures: %d bytes (%d sectors)" % (
        len(tl), total, len(mdl), (len(mdl) + 2047) // 2048, len(xet), (len(xet) + 2047) // 2048))
    return {"tris": len(tl), "strip_verts": total, "mdl": len(mdl), "xet": len(xet), "rgba": rgba}

def convert(dff, txd, vd, xd, model_id, out_mdl, out_xet, tris=3000, offset=(0.0, 0.0, 0.0), rotate="", skip=("bullet",),
            keep=(), prefix="iwp_", tex_max=128, crease=50.0, opaque=True, bake=True, atlas=(128, 128), min_part=0.02,
            local=False, log=print):
    parts = load_parts(dff, skip, keep, log, local)
    rot = rotation(rotate)
    parts = [(tex, tuple(tuple(sum(p[k] * rot[k][c] for k in range(3)) + offset[c] for c in range(3)) for p in ps), uvs)
             for tex, ps, uvs in parts]
    if bake:
        return convert_baked(parts, txd, vd, xd, model_id, out_mdl, out_xet, tris, prefix, atlas, crease, min_part, log)
    P, W, T = weld(parts)
    log("  welded: %d positions, %d wedges, %d triangles" % (len(P), len(W), len(T)))
    if tris and len(T) > tris:
        m = mesh_simplify.Mesh(P, W, T)
        m.simplify(tris)
        P, W, T = m.compact()
        log("  simplified to %d triangles (budget %d)" % (len(T), tris))
    N = corner_normals(P, W, T, crease)
    lo = [min(p[i] for p in P) for i in range(3)]; hi = [max(p[i] for p in P) for i in range(3)]
    vlo, vhi = vcs_box(vd)
    log("  box %s..%s (VCS's %s..%s)" % (["%.3f" % x for x in lo], ["%.3f" % x for x in hi],
                                         ["%.3f" % x for x in vlo], ["%.3f" % x for x in vhi]))
    _, _, q = quantizer(P)
    bytex = defaultdict(list)
    area = Counter()
    for i, t in enumerate(T):
        tex = W[t[0]][3]
        bytex[tex].append(i)
        area[tex] += tri_area(*(P[W[w][0]] for w in t))
    out_groups, total_tris = [], 0
    for tex in sorted(bytex):
        ids = bytex[tex]
        prm = uv_params([(W[w][1], W[w][2]) for i in ids for w in T[i]])
        weldv, rep, tl = {}, [], []
        for i in ids:
            t = []
            for k, w in enumerate(T[i]):
                p, uv, n = P[W[w][0]], (W[w][1], W[w][2]), N[i][k]
                key = (q(p), uv8(uv, prm), n)
                if key not in weldv:
                    weldv[key] = len(rep)
                    rep.append((p, uv, n))
                t.append(weldv[key])
            if len(set(t)) == 3:
                tl.append(tuple(t))
        seq_idx, nstrips = stripify(tl)
        out_groups.append(((prefix + tex)[:31], [rep[i] for i in seq_idx], prm))
        total_tris += len(tl)
        log("  %-26s %5d tris %5d verts -> %4d strips, %6d strip verts (%.2f / tri)%s" % (
            tex, len(tl), len(rep), nstrips, len(seq_idx), len(seq_idx) / max(1, len(tl)),
            "  uv from (%d, %d): repeats" % (prm[0], prm[1]) if prm[0] or prm[1] else ""))
    el = u32(vd, 0x20); geo = u32(vd, el + 0x14); mat0 = u32(vd, u32(vd, geo + 0x0C))
    colour = u32(vd, mat0 + 4)
    mesh_w = u32(vd, geo + 0x20 + 0x40 + 0x18)
    mdl, total, pk = build_mdl(out_groups, model_id, colour, mesh_w)
    with open(out_mdl, "wb") as f:
        f.write(mdl)
    # textures: the VCS dictionary's own (the HUD icon), then the new ones at 32..tex_max px by their share of the area
    texs = read_xet(xd)
    src = rwtxd.read_txd(txd, tex_max)
    whole = sum(area.values()) or 1.0
    tex_bytes = 0
    for tex in sorted(bytex):
        if tex not in src:
            log("  texture %s missing in the TXD" % tex)
            continue
        size = max(32, min(tex_max, 1 << max(5, math.ceil(math.log2(max(1e-9, math.sqrt(area[tex] / whole)) * 256)))))
        w, h, rgba = downscale(*src[tex], size)
        if opaque:
            rgba = bytes(b if i % 4 != 3 else 255 for i, b in enumerate(rgba))
        r = t8_raster(w, h, rgba)
        texs.append(((prefix + tex)[:31].encode("latin1"), r["w4"], r["flags"], r["data"]))
        tex_bytes += len(r["data"])
        log("  texture %-26s %3dx%-3d (%2.0f%% of the area)" % ((prefix + tex)[:31], w, h, 100 * area[tex] / whole))
    xet = build_xet(texs)
    with open(out_xet, "wb") as f:
        f.write(xet)
    log("  model: %d tris, %d strip verts, %d bytes (%d sectors); textures: %d bytes (%d sectors)" % (
        total_tris, total, len(mdl), (len(mdl) + 2047) // 2048, len(xet), (len(xet) + 2047) // 2048))
    return {"tris": total_tris, "strip_verts": total, "mdl": len(mdl), "xet": len(xet)}

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", help="the Immersive Weapons Pack's modloader folder: convert every weapon in PACK")
    ap.add_argument("--only", help="with --pack: these weapon types (comma-separated)")
    ap.add_argument("--dff"); ap.add_argument("--txd")
    ap.add_argument("--weapon", type=int, help="VCS weapon type (WEAPONS): originals from the disc, output to --mods")
    ap.add_argument("--iso", help="the disc image (default: the one tools/toolchain.py finds)")
    ap.add_argument("--mods", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "mods"),
                    help="the mods folder (vcs.exe reads <mods>/stream; VCS_MODS_DIR, default build/mods)")
    ap.add_argument("--vcs-mdl"); ap.add_argument("--vcs-xet")
    ap.add_argument("--model-id", type=int)
    ap.add_argument("--out-mdl"); ap.add_argument("--out-xet")
    ap.add_argument("--tex", type=int, default=128, help="largest texture size (px)")
    ap.add_argument("--tris", type=int, help="triangle budget (0: no simplification)")
    ap.add_argument("--skip", help="frame names left out (default: bullet)")
    ap.add_argument("--keep", help="only these frame names")
    ap.add_argument("--prefix")
    ap.add_argument("--offset", help="x,y,z (m) added after the rotation")
    ap.add_argument("--rotate", help="e.g. z:180 (degrees about the model's axes, applied in order)")
    ap.add_argument("--crease", type=float, default=50.0, help="smoothing angle for the normals (degrees)")
    ap.add_argument("--atlas", help="baked texture size, e.g. 256x128")
    ap.add_argument("--no-bake", action="store_true",
                    help="keep the SA texture coordinates and textures (no atlas; simplification stops early)")
    a = ap.parse_args()
    if a.pack or a.weapon:
        if not a.iso:
            import toolchain
            a.iso = toolchain.find_iso()
        os.makedirs(os.path.join(a.mods, "stream"), exist_ok=True)
    jobs = []
    if a.pack:
        only = {int(x) for x in a.only.split(",")} if a.only else None
        for t, (dff, txd, opt) in sorted(PACK.items()):
            if only and t not in only:
                continue
            jobs.append((t, os.path.join(a.pack, dff), os.path.join(a.pack, txd), dict(opt)))
    elif a.weapon:
        if not (a.dff and a.txd):
            ap.error("--weapon needs --dff and --txd")
        jobs.append((a.weapon, a.dff, a.txd, dict(PACK.get(a.weapon, ("", "", {}))[2])))
    else:
        if not (a.dff and a.txd and a.vcs_mdl and a.vcs_xet and a.model_id is not None and a.out_mdl and a.out_xet):
            ap.error("--pack, --weapon, or all of --dff --txd --vcs-mdl --vcs-xet --model-id --out-mdl --out-xet")
        jobs.append((None, a.dff, a.txd, {}))
    for t, dff, txd, opt in jobs:
        if a.tris is not None: opt["tris"] = a.tris
        if a.skip is not None: opt["skip"] = a.skip
        if a.keep is not None: opt["keep"] = a.keep
        if a.prefix is not None: opt["prefix"] = a.prefix
        if a.offset is not None: opt["offset"] = a.offset
        if a.rotate is not None: opt["rotate"] = a.rotate
        if a.atlas: opt["atlas"] = tuple(int(x) for x in a.atlas.lower().split("x"))
        if a.no_bake: opt["bake"] = False
        for k in ("skip", "keep"):
            if isinstance(opt.get(k), str):
                opt[k] = tuple(s.strip().lower() for s in opt[k].split(",") if s.strip())
        if isinstance(opt.get("offset"), str):
            opt["offset"] = tuple(float(x) for x in opt["offset"].split(","))
        if t is not None:
            name, mid, mpos, msz, tid, tpos, tsz = WEAPONS[t]
            vd, xd = read_img(a.iso, mpos, msz), read_img(a.iso, tpos, tsz)
            out_mdl = a.out_mdl if len(jobs) == 1 and a.out_mdl else os.path.join(a.mods, "stream", "%d.ldm" % mid)
            out_xet = a.out_xet if len(jobs) == 1 and a.out_xet else os.path.join(a.mods, "stream", "%d.xet" % tid)
            print("%s (type %d): %s -> model %d, textures %d" % (name, t, os.path.basename(dff), mid, tid), flush=True)
        else:
            vd, xd, mid = open(a.vcs_mdl, "rb").read(), open(a.vcs_xet, "rb").read(), a.model_id
            out_mdl, out_xet = a.out_mdl, a.out_xet
        convert(dff, txd, vd, xd, mid, out_mdl, out_xet, tex_max=a.tex, crease=a.crease, **opt)

if __name__ == "__main__":
    main()
