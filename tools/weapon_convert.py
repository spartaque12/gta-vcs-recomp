"""GTA SA weapon (DFF + TXD) -> VCS PS2 weapon model ('ldm' Rsl chunk) + its texture dictionary ('xet' chunk), written
as streamed-file overrides (src/game/vcs_stream_override.h: <mods>/stream/<id>.ldm / .xet).

    python tools/weapon_convert.py --weapon 19 --dff colt45.dff --txd colt45.txd [--mods build/mods] [--iso ISO]
                                   [--tex 128] [--skip bullet] [--prefix c45_] [--offset x,y,z]
    (or --vcs-mdl / --vcs-xet / --model-id / --out-mdl / --out-xet with files of your own)

The model is one RslElement (rigid, lit: VU1 stage table 0x19 + 0x4ff), as VCS's own weapons: per material a mesh whose
DMA packet (RET) holds batches of <= 70 strip vertices (V3-16 positions, V2-8 uv, V3-8 normals; MSCAL 6). Every part
of the SA model (its atomics) is merged at its frame's place; it is moved so its box centre is the VCS model's.
The texture dictionary keeps the VCS model's own textures and adds the new ones (T8, linear, CLUT in CSM1 order).
Layouts: docs/game-internals.md 12g."""
import argparse, math, os, struct, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rw_dff as rwdff, rw_txd as rwtxd

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

def build_mdl(groups, model_id, colour, mesh_w):
    """groups: [(texture name, [(pos xyz float, uv, normal)] strip sequence, uv params)]"""
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
            pkt += batch_packet(verts[start:start + 70])
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
        if su or sv:
            print("  mesh %d (%s): uv shifted by (%d, %d) - needs repeat addressing" % (i, tex, -su, -sv))
    end = c.align(16)
    struct.pack_into("<4f", c.b, ps2, *sphere(allp))
    c.w32(ps2 + 0x10, len(groups) << 20 | (end - ps2))
    c.w32(ps2 + 0x14, 7)
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dff", required=True); ap.add_argument("--txd", required=True)
    ap.add_argument("--weapon", type=int, help="VCS weapon type (WEAPONS): originals from the disc, output to --mods")
    ap.add_argument("--iso", help="the disc image (default: the one tools/toolchain.py finds)")
    ap.add_argument("--mods", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build", "mods"),
                    help="the mods folder (vcs.exe reads <mods>/stream; VCS_MODS_DIR, default build/mods)")
    ap.add_argument("--vcs-mdl"); ap.add_argument("--vcs-xet")
    ap.add_argument("--model-id", type=int)
    ap.add_argument("--out-mdl"); ap.add_argument("--out-xet")
    ap.add_argument("--tex", type=int, default=128)
    ap.add_argument("--skip", default="bullet")
    ap.add_argument("--prefix", default="iwp_")
    ap.add_argument("--offset", default="", help="x,y,z added after the box alignment")
    a = ap.parse_args()
    vd = xd = None
    if a.weapon:
        name, mid, mpos, msz, tid, tpos, tsz = WEAPONS[a.weapon]
        if not a.iso:
            import toolchain
            a.iso = toolchain.find_iso()
        vd, xd = read_img(a.iso, mpos, msz), read_img(a.iso, tpos, tsz)
        a.model_id = mid
        os.makedirs(os.path.join(a.mods, "stream"), exist_ok=True)
        a.out_mdl = a.out_mdl or os.path.join(a.mods, "stream", "%d.ldm" % mid)
        a.out_xet = a.out_xet or os.path.join(a.mods, "stream", "%d.xet" % tid)
        print("%s: model %d, textures %d" % (name, mid, tid))
    else:
        if not (a.vcs_mdl and a.vcs_xet and a.model_id is not None and a.out_mdl and a.out_xet):
            ap.error("--weapon, or all of --vcs-mdl --vcs-xet --model-id --out-mdl --out-xet")
        vd, xd = open(a.vcs_mdl, "rb").read(), open(a.vcs_xet, "rb").read()
    frames, geoms, atomics = rwdff.parse_dff(a.dff)
    skip = {s.strip().lower() for s in a.skip.split(",") if s.strip()}
    groups = defaultdict(lambda: ([], []))  # texture -> (vertices, triangles)
    for at in atomics:
        fname = frames[at["frame"]]["name"].strip("\0 \t").lower()
        if fname in skip:
            continue
        g = geoms[at["geometry"]]
        m = rwdff.ltm(frames, at["frame"])
        cache = {}
        for (v0, v1, v2, mi) in g.tris:
            if v0 == v1 or v1 == v2 or v0 == v2:
                continue
            tex = (g.materials[mi]["texture"] or "none").lower()
            verts, tris = groups[tex]
            ids = []
            for v in (v0, v1, v2):
                key = (tex, v)
                if key not in cache:
                    p = g.pos[v]
                    wp = tuple(p[0] * m[0][c] + p[1] * m[1][c] + p[2] * m[2][c] + m[3][c] for c in range(3))
                    n = g.nrm[v] if g.nrm else (0.0, 0.0, 1.0)
                    wn = [n[0] * m[0][c] + n[1] * m[1][c] + n[2] * m[2][c] for c in range(3)]
                    ln = math.sqrt(sum(x * x for x in wn)) or 1.0
                    cache[key] = len(verts)
                    verts.append((wp, g.uv[v] if g.uv else (0.0, 0.0), tuple(max(-127, min(127, round(x / ln * 127))) for x in wn)))
                ids.append(cache[key])
            tris.append(tuple(ids))
    vlo, vhi = vcs_box(vd)
    allp = [v[0] for verts, _ in groups.values() for v in verts]
    lo = [min(p[i] for p in allp) for i in range(3)]; hi = [max(p[i] for p in allp) for i in range(3)]
    off = [(vlo[i] + vhi[i]) / 2 - (lo[i] + hi[i]) / 2 for i in range(3)]
    if a.offset:
        off = [o + float(x) for o, x in zip(off, a.offset.split(","))]
    print("SA box %s..%s, VCS box %s..%s, offset %s" % (["%.3f" % x for x in lo], ["%.3f" % x for x in hi],
          ["%.3f" % x for x in vlo], ["%.3f" % x for x in vhi], ["%.3f" % x for x in off]))
    out_groups = []
    tris_total = 0
    _, _, q = quantizer([tuple(p[c] + off[c] for c in range(3)) for p in allp])
    for tex, (verts, tris) in sorted(groups.items()):
        verts = [(tuple(v[0][c] + off[c] for c in range(3)), v[1], v[2]) for v in verts]
        prm = uv_params([v[1] for v in verts])
        # weld vertices equal in what the game keeps (int16 position, 8-bit uv and normal): longer strips
        weld, rep, remap = {}, [], []
        for v in verts:
            k = (q(v[0]), uv8(v[1], prm), v[2])
            if k not in weld:
                weld[k] = len(rep)
                rep.append(v)
            remap.append(weld[k])
        wt = [(remap[x], remap[y], remap[z]) for x, y, z in tris]
        wt = [t for t in wt if len(set(t)) == 3]
        seq_idx, nstrips = stripify(wt)
        seq = [rep[i] for i in seq_idx]
        name = (a.prefix + tex)[:31]
        out_groups.append((name, seq, prm))
        tris_total += len(wt)
        print("  %-12s %5d tris %5d verts (%5d welded) -> %4d strips, %6d strip verts (%.2f / tri)" % (tex, len(wt), len(verts),
              len(rep), nstrips, len(seq), len(seq) / max(1, len(wt))))
    el = u32(vd, 0x20); geo = u32(vd, el + 0x14); mat0 = u32(vd, u32(vd, geo + 0x0C))
    colour = u32(vd, mat0 + 4)
    mesh_w = u32(vd, geo + 0x20 + 0x40 + 0x18)
    mdl, total, pk = build_mdl(out_groups, a.model_id, colour, mesh_w)
    open(a.out_mdl, "wb").write(mdl)
    print("model: %d tris, %d strip verts, packets %d bytes, chunk %d bytes (%d sectors)" % (tris_total, total, pk, len(mdl),
          (len(mdl) + 2047) // 2048))
    texs = read_xet(xd)
    src = rwtxd.read_txd(a.txd, a.tex)
    for tex, _ in sorted(groups.items()):
        if tex not in src:
            print("  texture %s missing in the TXD" % tex)
            continue
        w, h, rgba = src[tex]
        w2, h2 = w, h
        while max(w2, h2) > a.tex:
            w2, h2 = w2 // 2, h2 // 2
        if (w2, h2) != (w, h):  # box-filter down (DXT levels usually spare this)
            f = w // w2
            out = bytearray(w2 * h2 * 4)
            for y in range(h2):
                for x in range(w2):
                    for c in range(4):
                        out[(y * w2 + x) * 4 + c] = sum(rgba[((y * f + j) * w + x * f + i) * 4 + c] for j in range(f) for i in range(f)) // (f * f)
            w, h, rgba = w2, h2, bytes(out)
        r = t8_raster(w, h, rgba)
        texs.append(((a.prefix + tex)[:31].encode("latin1"), r["w4"], r["flags"], r["data"]))
        print("  texture %-24s %dx%d T8" % ((a.prefix + tex)[:31], w, h))
    xet = build_xet(texs)
    open(a.out_xet, "wb").write(xet)
    print("textures: %d, chunk %d bytes (%d sectors)" % (len(texs), len(xet), (len(xet) + 2047) // 2048))

if __name__ == "__main__":
    main()
